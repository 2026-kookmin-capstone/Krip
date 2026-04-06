from app.domain.auth.repository.user_repository import UserRepository
from app.domain.auth.repository.user_detail_inform import UserDetailInformRepository
from app.domain.auth.model.user import User
from app.domain.auth.dto.signup import SignupStatus, SignupResult
from app.database.session import UnitOfWork


class SignupService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow


    async def check_and_register(self, auth_provider: str, auth_provider_id: str) -> SignupResult:
        """
        OAuth 콜백 후 회원가입 상태를 확인하고, 미가입 시 1차 가입을 수행한다.

        1. users 테이블에서 provider 정보로 조회
           - 없으면 → 신규 유저 생성 (1차 가입) → NEW
           - 있으면 → 2단계 확인
        2. user_detail_inform 테이블에서 user_id로 조회
           - 없으면 → IN_PROGRESS (2차 가입 필요)
           - 있으면 → COMPLETE
        """
        async with self.uow as session:
            user_repo = UserRepository(session)
            detail_repo = UserDetailInformRepository(session)

            user = await user_repo.find_by_provider(auth_provider, auth_provider_id)

            if user is None:
                user = User(
                    auth_provider=auth_provider,
                    auth_provider_id=auth_provider_id,
                )
                await user_repo.save(user)
                return SignupResult(user_id=user.user_id, status=SignupStatus.NEW)

            detail = await detail_repo.find_by_user_id(user.user_id)

            if detail is None:
                return SignupResult(user_id=user.user_id, status=SignupStatus.IN_PROGRESS)

            return SignupResult(user_id=user.user_id, status=SignupStatus.COMPLETE)
