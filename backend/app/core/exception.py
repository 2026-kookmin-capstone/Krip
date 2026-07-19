"""도메인 공통 예외 베이스 — 전역 핸들러가 HTTP status 로 일괄 매핑한다."""


class DomainError(Exception):
    status_code = 400


class NotFoundError(DomainError):
    status_code = 404


class ForbiddenError(DomainError):
    status_code = 403


class ConflictError(DomainError):
    status_code = 409
