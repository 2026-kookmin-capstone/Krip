"""smoke test 용 유저 3명 + 친구관계 DB 시드.

OAuth 플로우를 거치지 않고 User + UserDetailInform + Friendship 레코드를 직접 만든다.
JWT 는 `smoke_test.py` 에서 `USER_LOGIN_JWT_SECRET_KEY` 로 직접 서명해 사용.

그룹 방 초대는 "친구만" 정책이 기본이라 A-B, A-C 친구관계도 ACCEPTED 로 세팅해야
smoke 의 그룹 시나리오([4/6] ~ [5/6]) 가 돌아간다.

실행:
    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5532 ... python scripts/chat/seed_users.py
    (.env.smoke 는 run_smoke.sh 가 export 해준다)
"""
import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 모델 매퍼 전 등록
import app.database.model  # noqa: F401
from app.config.oauth import OAuthProvider
from app.config.setting import settings
from app.domain.auth.model.user import User, UserStatus
from app.domain.auth.model.user_detail_inform import Gender, UserDetailInform
from app.domain.friend.model.friendship import Friendship, FriendshipStatus
from app.domain.friend.repository.friendship import FriendshipRepository


USERS = [
    {
        "user_id": "USER_SMOKE_A",
        "user_name": "앨리스",
        "email": "smoke_a@example.com",
    },
    {
        "user_id": "USER_SMOKE_B",
        "user_name": "밥",
        "email": "smoke_b@example.com",
    },
    {
        "user_id": "USER_SMOKE_C",
        "user_name": "카일",
        "email": "smoke_c@example.com",
    },
]

# 그룹 방 초대 시 "친구만" 정책 — A 가 B, C 를 초대하려면 A-B / A-C 친구관계 필요
FRIENDSHIPS = [
    ("USER_SMOKE_A", "USER_SMOKE_B"),
    ("USER_SMOKE_A", "USER_SMOKE_C"),
]


async def main() -> None:
    engine = create_async_engine(settings.POSTGRES_URL, echo=False, future=True)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        for u in USERS:
            existing = await session.get(User, u["user_id"])
            if existing is not None:
                print(f"[skip] user {u['user_id']} 이미 존재")
                continue

            session.add(
                User(
                    user_id=u["user_id"],
                    auth_provider=OAuthProvider.GOOGLE,
                    auth_provider_id=u["email"],
                    status=UserStatus.ACTIVE,
                )
            )
            session.add(
                UserDetailInform(
                    user_id=u["user_id"],
                    email=u["email"],
                    user_name=u["user_name"],
                    age=25,
                    gender=Gender.MALE,
                    nationality="KR",
                )
            )
            print(f"[add]  user {u['user_id']} ({u['user_name']})")

        await session.flush()  # 유저 insert 확정 후 friendship FK 참조 가능

        friendship_repo = FriendshipRepository(session)
        for a, b in FRIENDSHIPS:
            existing = await friendship_repo.find_between(a, b)
            if existing is not None:
                print(f"[skip] friendship {a} ↔ {b} 이미 존재")
                continue
            session.add(Friendship(
                requester_id=a,
                addressee_id=b,
                status=FriendshipStatus.ACCEPTED,
            ))
            print(f"[add]  friendship {a} ↔ {b} (accepted)")

        await session.commit()

    await engine.dispose()
    print("seed 완료")


if __name__ == "__main__":
    asyncio.run(main())
