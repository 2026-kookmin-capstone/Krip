from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from dependency_injector import containers, providers

from app.domain.auth.service.signup import SignupService
from app.domain.auth.service.register import RegisterService
from app.domain.auth.service.profile import ProfileService
from app.domain.auth.service.withdraw import WithdrawService
from app.domain.tripmate.service.tripmate_post import TripmatePostService
from app.domain.tripmate.service.tripmate_post_like import TripmatePostLikeService
from app.domain.tripmate.service.tripmate_post_draft import TripmatePostDraftService
from app.domain.tripmate.service.tripmate_search_history import TripmateSearchHistoryService
from app.domain.tripmate.service.tripmate_image import TripmateImageService
from app.domain.menu_ai.service.menu_ocr import MenuOcrService
from app.domain.tour.service.place import PlaceService
from app.domain.tour.service.favorite_place import FavoritePlaceService
from app.domain.tour.service.tour_search_history import TourSearchHistoryService
from app.domain.friend.service.friendship import FriendshipService
from app.domain.friend.service.user_block import UserBlockService
from app.domain.friend.service.friend_detail import FriendDetailService
from app.domain.chat.service.chat_service import ChatService
from app.domain.chat.service.fanout_service import FanoutService
from app.domain.chat.service.message_history_service import MessageHistoryService
from app.domain.chat.service.room_service import RoomService
from app.domain.chat.service.session_service import SessionService
from app.database.session import UnitOfWork
from app.config.setting import settings



class Container(containers.DeclarativeContainer):
    """DI Container — 의존성 선언"""

    engine = providers.Singleton(
        create_async_engine,
        settings.POSTGRES_URL,
        echo=False,
        future=True,
    )

    session_factory = providers.Singleton(
        async_sessionmaker,
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    uow = providers.Factory(UnitOfWork, session=session_factory)

    # 서비스 계층 주입
    signup_service = providers.Factory(SignupService, uow=uow)
    register_service = providers.Factory(RegisterService, uow=uow)
    profile_service = providers.Factory(ProfileService, uow=uow)
    withdraw_service = providers.Factory(WithdrawService, uow=uow)
    tripmate_post_draft_service = providers.Factory(TripmatePostDraftService)
    tripmate_post_service = providers.Factory(TripmatePostService, uow=uow, draft_service=tripmate_post_draft_service)
    tripmate_post_like_service = providers.Factory(TripmatePostLikeService, uow=uow)
    tripmate_search_history_service = providers.Factory(TripmateSearchHistoryService)
    tripmate_image_service = providers.Factory(TripmateImageService, uow=uow)

    # 메뉴 AI
    menu_ocr_service = providers.Factory(MenuOcrService)

    # 관광
    place_service = providers.Factory(PlaceService, uow=uow)
    favorite_place_service = providers.Factory(FavoritePlaceService, uow=uow)
    tour_search_history_service = providers.Factory(TourSearchHistoryService)

    # 친구
    friendship_service = providers.Factory(FriendshipService, uow=uow)
    user_block_service = providers.Factory(UserBlockService, uow=uow)
    friend_detail_service = providers.Factory(FriendDetailService, uow=uow)

    # 채팅 — 인프라 (Singleton: 프로세스 내 전역 상태 유지)
    fanout_service = providers.Singleton(FanoutService)
    session_service = providers.Singleton(SessionService, fanout_service=fanout_service)

    # 채팅 — 비즈 (Factory: 호출마다 UoW 새로 바인딩)
    room_service = providers.Factory(RoomService, uow=uow, fanout_service=fanout_service)
    chat_service = providers.Factory(ChatService, uow=uow, fanout_service=fanout_service)
    message_history_service = providers.Factory(MessageHistoryService, uow=uow)
