"""Auth 도메인 전용 커스텀 예외.

Router 가 HTTPException 으로 매핑 (§에러 처리 컨벤션):
    ValueError                       → 400
    PermissionError                  → 403
    ProfileNotRegisteredError        → 400 (defensive; middleware 가 통상 먼저 차단)
    ProfileImageAlreadyExistsError   → 409
    ProfileImageNotFoundError        → 404
    WithdrawalAlreadyRequestedError  → 409
    WithdrawalNotPendingError        → 409
"""

from app.core.exception import ConflictError, DomainError, NotFoundError


class ProfileNotRegisteredError(DomainError, ValueError):
    """2차 회원가입이 완료되지 않은 유저 — Router 에서 400 으로 매핑.

    middleware 가 통상 먼저 403 으로 차단하지만, service 레벨에서도 방어.
    """


class ProfileImageAlreadyExistsError(ConflictError, ValueError):
    """프로필 이미지가 이미 존재 (POST 시) — Router 에서 409 로 매핑.

    수정은 PUT 으로 유도.
    """


class ProfileImageNotFoundError(NotFoundError, ValueError):
    """프로필 이미지가 존재하지 않음 (PUT/DELETE 시) — Router 에서 404 로 매핑."""


class WithdrawalAlreadyRequestedError(ConflictError, ValueError):
    """이미 탈퇴 요청이 진행 중인 유저 — Router 에서 409 로 매핑.

    유예 기간(30일) 내에 같은 유저가 탈퇴를 다시 요청하면 발생.
    """


class WithdrawalNotPendingError(ConflictError, ValueError):
    """탈퇴 요청 상태가 아닌 유저가 cancel 시도 — Router 에서 409 로 매핑.

    `cancel_withdraw` 는 status==INACTIVE 만 처리. 이미 ACTIVE / SUSPENDED 인 유저가
    호출하면 발생.
    """
