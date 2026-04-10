from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from dependency_injector import containers, providers

from app.domain.auth.service.signup import SignupService
from app.domain.auth.service.register import RegisterService
from app.domain.auth.service.profile import ProfileService
from app.domain.tripmate.service.tripmate_post import TripmatePostService
from app.domain.tripmate.service.tripmate_post_like import TripmatePostLikeService
from app.domain.tripmate.service.tripmate_post_draft import TripmatePostDraftService
from app.domain.tripmate.service.tripmate_search_history import TripmateSearchHistoryService
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
    tripmate_post_draft_service = providers.Factory(TripmatePostDraftService)
    tripmate_post_service = providers.Factory(TripmatePostService, uow=uow, draft_service=tripmate_post_draft_service)
    tripmate_post_like_service = providers.Factory(TripmatePostLikeService, uow=uow)
    tripmate_search_history_service = providers.Factory(TripmateSearchHistoryService)
