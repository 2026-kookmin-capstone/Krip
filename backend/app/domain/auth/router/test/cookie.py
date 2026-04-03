from fastapi import APIRouter, Request, Response

router = APIRouter(prefix="/cookie-test", tags=["test 쿠키"])


@router.get("/set-cookie")
def set_test_cookie(response: Response):
    """테스트용 쿠키 발급 - 모든 도메인/경로 허용"""
    response.set_cookie(
        key="test_token",
        value="test-cookie-value",
        httponly=False,
        secure=False,
        samesite="none",
        path="/",
        domain=None,
        max_age=60 * 60, 
    )
    return {"message": "테스트 쿠키가 발급되었습니다", "cookie_name": "test_token"}


@router.get("/read-cookie")
def read_test_cookie(request: Request):
    """발급된 테스트 쿠키 읽기"""
    test_token = request.cookies.get("test_token")
    if test_token is None:
        return {"message": "쿠키가 없습니다", "test_token": None}
    return {"message": "쿠키를 읽었습니다", "test_token": test_token}
