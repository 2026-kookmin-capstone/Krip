from dataclasses import dataclass
from enum import Enum


class SignupStatus(str, Enum):
    NEW = "new"                                  # 최초 방문 → 1차 회원가입 생성
    IN_PROGRESS = "in_progress"                  # 1차 완료, 2차 미완료
    COMPLETE = "complete"                        # 2차 회원가입까지 완료
    WITHDRAWAL_PENDING = "withdrawal_pending"    # 탈퇴 요청 후 30일 유예 중 — 로그인 차단


@dataclass
class SignupResult:
    user_id: str
    status: SignupStatus
