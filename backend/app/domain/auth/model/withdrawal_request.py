from pydantic import Field
from datetime import datetime, timezone, timedelta
from beanie import Document, Indexed


WITHDRAWAL_GRACE_PERIOD_DAYS = 30


def default_purge_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=WITHDRAWAL_GRACE_PERIOD_DAYS)


class WithdrawalRequest(Document):
    """회원 탈퇴 요청 — 30일 유예 후 영구 삭제 대상.

    유저가 탈퇴를 누르면 RDB `users.status = INACTIVE` 전환과 함께 이 컬렉션에 기록되고,
    `scheduled_purge_at` 도달 시 새벽 4시(KST) 스케줄러가 실제 hard-delete 를 수행한다.
    유예 기간 동안 같은 OAuth 계정으로 다시 로그인하면 `SignupStatus.WITHDRAWAL_PENDING`
    이 반환되며, 미들웨어는 419 로 보호 경로 진입을 차단한다.

    한 유저당 1건 — `user_id` unique 인덱스로 중복 요청 방지.
    """

    user_id: Indexed(str, unique=True) = Field(..., description="탈퇴 요청한 유저 ID")  # type: ignore
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="탈퇴 요청 시각",
    )
    scheduled_purge_at: Indexed(datetime) = Field(  # type: ignore
        default_factory=default_purge_at,
        description="영구 삭제 예정 시각 (요청 시각 + 30일)",
    )

    class Settings:
        name = "withdrawal_request"
