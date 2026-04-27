"""Auth 도메인 전용 커스텀 예외.

Router 가 HTTPException 으로 매핑 (§에러 처리 컨벤션):
    ValueError                       → 400
    PermissionError                  → 403
    ProfileNotRegisteredError        → 400 (defensive; middleware 가 통상 먼저 차단)
    ProfileImageAlreadyExistsError   → 409
    ProfileImageNotFoundError        → 404
"""


class ProfileNotRegisteredError(ValueError):
    """2차 회원가입이 완료되지 않은 유저 — Router 에서 400 으로 매핑.

    middleware 가 통상 먼저 403 으로 차단하지만, service 레벨에서도 방어.
    """


class ProfileImageAlreadyExistsError(ValueError):
    """프로필 이미지가 이미 존재 (POST 시) — Router 에서 409 로 매핑.

    수정은 PUT 으로 유도.
    """


class ProfileImageNotFoundError(ValueError):
    """프로필 이미지가 존재하지 않음 (PUT/DELETE 시) — Router 에서 404 로 매핑."""
