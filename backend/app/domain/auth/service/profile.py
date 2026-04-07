from app.domain.auth.repository.user_repository import UserRepository
from app.domain.auth.dto.profile import ProfileData
from app.database.session import UnitOfWork


class ProfileService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow


    async def get_my_profile(self, user_id: str) -> ProfileData:
        """유저 프로필 전체 정보 조회"""
        async with self.uow as session:
            user_repo = UserRepository(session)

            user = await user_repo.find_by_id_with_profile(user_id)
            if user is None:
                raise ValueError("존재하지 않는 유저입니다.")
            if user.detail is None:
                raise ValueError("2차 회원가입이 완료되지 않은 유저입니다.")

            return ProfileData(
                user_id=user.user_id,
                auth_provider=user.auth_provider,
                status=user.status,
                email=user.detail.email,
                user_name=user.detail.user_name,
                phone_number=user.detail.phone_number,
                age=user.detail.age,
                gender=user.detail.gender,
                nationality=user.detail.nationality,
                travel_styles=[s.style for s in user.travel_styles],
            )
