from contextvars import ContextVar
from functools import wraps

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.core.context import db_route_var
from app.core.instrumentation import db_transaction_inc


# 트랜잭션 전파용 — `@transactional` 이 nested 호출 시 같은 session 재사용 여부 판정.
_current_session: ContextVar = ContextVar('_current_session', default=None)


class UnitOfWork:
    def __init__(self, session: async_sessionmaker):
        self.session_factory = session

    async def __aenter__(self):
        self.session = self.session_factory()
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        # commit 자체가 실패할 수 있어 try/except 로 'other' 라벨을 분리.
        route = db_route_var.get()
        try:
            if exc:
                await self.session.rollback()
                db_transaction_inc(route, "rollback")
            else:
                try:
                    await self.session.commit()
                    db_transaction_inc(route, "commit")
                except Exception:
                    db_transaction_inc(route, "other")
                    raise
        finally:
            await self.session.close()


def transactional(fn):
    """nested 호출은 기존 트랜잭션에 참여, 최상위 호출만 새 UoW 를 연다.

    세션을 인스턴스 상태(self._session)에 보관하므로, 한 인스턴스를 여러 task 에서 동시
    실행하면 세션이 덮어써진다 → 동시 실행 경로는 task 마다 새 인스턴스를 써야 한다.
    """
    @wraps(fn)
    async def wrapper(self, *args, **kwargs):
        existing = _current_session.get()
        if existing is not None:
            self._session = existing
            return await fn(self, *args, **kwargs)

        async with self.uow as session:
            token = _current_session.set(session)
            self._session = session
            try:
                return await fn(self, *args, **kwargs)
            finally:
                _current_session.reset(token)
                self._session = None
    return wrapper


Base = declarative_base()


from typing import Optional

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config.setting import settings
from app.domain.auth.model.withdrawal_request import WithdrawalRequest
from app.domain.chat.model.chat_message import create_indexes as create_chat_message_indexes
from app.domain.friend.model.search_history import FriendSearchHistory
from app.domain.notification.model.inbox import InboxItem
from app.domain.tour.model.place import Place
from app.domain.tour.model.tour_search_history import TourSearchHistory
from app.domain.tripmate.model.tripmate_image import TripmateImage
from app.domain.tripmate.model.tripmate_post_draft import TripmatePostDraft
from app.domain.tripmate.model.tripmate_search_history import TripmateSearchHistory


# Motor 기본값의 무한 socket 대기와 30초 server selection 대기를 제한한다.
# 장기 query는 호출처의 maxTimeMS로 별도 제어한다.
_MONGO_SERVER_SELECTION_TIMEOUT_MS = 5000
_MONGO_CONNECT_TIMEOUT_MS = 5000
_MONGO_SOCKET_TIMEOUT_MS = 10000


class MongoDB:
    def __init__(self):
        self.client: Optional[AsyncIOMotorClient] = None # type: ignore
        self.database: Optional[AsyncIOMotorDatabase] = None # type: ignore

    async def connect(self):
        self.client = AsyncIOMotorClient(
            settings.MONGODB_URL,
            maxPoolSize=100,
            minPoolSize=10,
            tz_aware=True,
            serverSelectionTimeoutMS=_MONGO_SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=_MONGO_CONNECT_TIMEOUT_MS,
            socketTimeoutMS=_MONGO_SOCKET_TIMEOUT_MS,
        )
        self.database = self.client[settings.MONGODB_NAME]

        await init_beanie(
            database=self.database,
            document_models=[
                WithdrawalRequest,
                TripmatePostDraft,
                TripmateSearchHistory,
                TripmateImage,
                Place,
                TourSearchHistory,
                FriendSearchHistory,
                InboxItem,
            ]
        )

        # 채팅 메시지는 Motor native라 인덱스만 초기화한다.
        await create_chat_message_indexes(self.database)

        await _ensure_search_history_unique_indexes()

    async def disconnect(self):
        if self.client:
            self.client.close()


_SEARCH_HISTORY_UNIQUE_INDEX = "uq_user_search_name"


async def _ensure_search_history_unique_indexes() -> None:
    """검색기록 컬렉션에 `(user_id, search_name)` unique 인덱스 보장.

    모델에 인덱스를 선언하지 않고 여기서 만든다 — init_beanie 가 unique 인덱스를 먼저
    만들면 기존 중복 데이터로 startup 이 크래시하기 때문. 인덱스 생성 전에 중복을 먼저
    정리(dedup: 그룹당 최신 1건 유지)해 안전하게 유니크화한다.

    dedup 은 unique 인덱스가 아직 없는 컬렉션(=최초 부팅)에 대해서만 실행한다. 인덱스가
    이미 있으면($sort+$group 전체 스캔은 컬렉션이 커질수록 100MB in-memory 한계 초과나
    socketTimeoutMS 초과로 connect() 크래시·배포 crash-loop 유발) aggregate 를 통째로
    건너뛰어 부팅을 저렴하게 유지한다. 정상 상태(steady state)에서 idempotent.
    """
    for model in (FriendSearchHistory, TourSearchHistory, TripmateSearchHistory):
        collection = model.get_motor_collection()

        existing = await collection.index_information()
        if _SEARCH_HISTORY_UNIQUE_INDEX in existing:
            continue

        pipeline = [
            {"$sort": {"created_at": -1}},
            {"$group": {
                "_id": {"user_id": "$user_id", "search_name": "$search_name"},
                "ids": {"$push": "$_id"},
            }},
            {"$match": {"ids.1": {"$exists": True}}},
        ]
        # 최초 dedup이 Mongo의 in-memory 한계를 넘을 수 있다.
        async for group in collection.aggregate(pipeline, allowDiskUse=True):
            await collection.delete_many({"_id": {"$in": group["ids"][1:]}})
        await collection.create_index(
            [("user_id", 1), ("search_name", 1)],
            unique=True,
            name=_SEARCH_HISTORY_UNIQUE_INDEX,
        )


mongodb = MongoDB()


async def init_mongodb():
    await mongodb.connect()


async def close_mongodb():
    await mongodb.disconnect()
