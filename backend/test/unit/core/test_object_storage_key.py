"""ObjectStorage._sanitize_ext / _make_key 확장자 정규화 단위 테스트.

핵심 회귀 검증 (S3 key·URL 에 클라 파일명 확장자가 그대로 박히던 문제 수정):
    - 정상 확장자(jpg/png/webp 등)는 그대로 유지
    - `x.jpg/../../evil.html` 같은 경로 주입은 세그먼트가 새지 않음 (/ · . 제거)
    - 비정상적으로 긴 확장자는 길이 상한으로 잘림 (500자 *_url 컬럼 보호)
    - 제어문자·비ASCII 제거, 확장자 없으면 UUID 만
"""
import re

import pytest

from app.core.object_storage import ObjectStorage


@pytest.mark.parametrize(
    "file_name, expected",
    [
        ("photo.jpg", "jpg"),
        ("IMG.PNG", "png"),
        ("a.webp", "webp"),
        ("a.jpeg", "jpeg"),
        # 경로 주입: 마지막 . 뒤 세그먼트에서 / 등 비영숫자 제거 → 경로 주입 무력화
        ("x.jpg/../../evil.html", "html"),
        # . 뒤에 슬래시가 섞인 경우도 영숫자만 남는다
        ("x.jpg/../../evil", "evil"),
        # 과도하게 긴 확장자는 10자로 절단
        ("a." + "x" * 300, "x" * 10),
        # 제어문자·특수문자 제거
        ("a.j\np\tg", "jpg"),
        ("a.jp@g!", "jpg"),
        # 비ASCII 제거
        ("a.한글", ""),
        # 확장자 없음
        ("noext", ""),
        # 점으로 끝남 → 빈 확장자
        ("file.", ""),
    ],
)
def test_sanitize_ext(file_name, expected):
    assert ObjectStorage._sanitize_ext(file_name) == expected


@pytest.mark.parametrize(
    "file_name",
    [
        "x.jpg/../../evil.html",
        "a." + "x" * 300,
        "a.j\np\tg",
        "photo.jpg",
        "noext",
    ],
)
def test_make_key_no_path_injection_or_overflow(file_name):
    key = ObjectStorage._make_key(object.__new__(ObjectStorage), file_name, "uploads/tmp")
    # UUID 뒤에 추가 경로 세그먼트가 새지 않아야 한다 (prefix 슬래시 2개 그대로).
    assert key.count("/") == 2
    assert ".." not in key
    # UUID + 선택적 .확장자 형태. 확장자는 영숫자 10자 이내.
    assert re.fullmatch(r"uploads/tmp/[0-9a-f-]{36}(\.[a-z0-9]{1,10})?", key)
