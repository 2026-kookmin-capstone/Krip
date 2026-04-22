"""smoke test 용 유저 2명 DB 시드.

OAuth 플로우를 거치지 않고 User + UserDetailInform 레코드를 직접 만든다 — JWT 는
`smoke_test.py` 에서 USER_LOGIN_JWT_SECRET_KEY 로 직접 서명해 사용.

실행:
    POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=5432 ... python scripts/chat/seed_users.py
    (.env.smoke 는 run_smoke.sh 가 export 해준다)
"""
import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# 모델 매퍼 전 등록
import app.database.model  # noqa: F401
from app.config.oauth import OAuthProvider
from app.config.setting import settings
from app.domain.auth.model.user import User, UserStatus
from app.domain.auth.model.user_detail_inform import Gender, UserDetailInform


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
]


async def main() -> None:
    engine = create_async_engine(settings.POSTGRES_URL, echo=False, future=True)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        # 이미 있으면 skip
        for u in USERS:
            existing = await session.get(User, u["user_id"])
            if existing is not None:
                print(f"[skip] {u['user_id']} 이미 존재")
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
            print(f"[add]  {u['user_id']} ({u['user_name']})")

        await session.commit()

    await engine.dispose()
    print("seed 완료")


if __name__ == "__main__":
    asyncio.run(main())
