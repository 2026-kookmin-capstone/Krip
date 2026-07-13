"""ObjectStorage key 정규화와 공개 이미지 업로드 경계 단위 테스트.

핵심 회귀 검증 (S3 key·URL 에 클라 파일명 확장자가 그대로 박히던 문제 수정):
    - 정상 확장자(jpg/png/webp 등)는 그대로 유지
    - `x.jpg/../../evil.html` 같은 경로 주입은 세그먼트가 새지 않음 (/ · . 제거)
    - 비정상적으로 긴 확장자는 길이 상한으로 잘림 (500자 *_url 컬럼 보호)
    - 제어문자·비ASCII 제거, 확장자 없으면 UUID 만
"""
import io
import re
from unittest.mock import MagicMock

import pytest
from PIL import Image

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
        ("x.jpg/../../evil", "evil"),
        ("a." + "x" * 300, "x" * 10),
        ("a.j\np\tg", "jpg"),
        ("a.jp@g!", "jpg"),
        ("a.한글", ""),
        ("noext", ""),
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
    assert key.count("/") == 2
    assert ".." not in key
    assert re.fullmatch(r"uploads/tmp/[0-9a-f-]{36}(\.[a-z0-9]{1,10})?", key)


def _storage() -> ObjectStorage:
    storage = object.__new__(ObjectStorage)
    storage.bucket = "bucket"
    storage.endpoint = "https://storage.example.com"
    storage._client = MagicMock()
    return storage


def _image_bytes(fmt: str = "PNG") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format=fmt)
    return output.getvalue()


@pytest.mark.unit
async def test_upload_perm_rejects_non_image_bytes_before_public_upload():
    storage = _storage()

    with pytest.raises(ValueError, match="이미지"):
        await storage.upload_perm(
            io.BytesIO(b"not-an-image"),
            "payload.jpg",
            "image/jpeg",
            prefix="profile/USER_a",
        )

    storage._client.upload_fileobj.assert_not_called()


@pytest.mark.unit
async def test_upload_perm_uses_decoded_format_and_safe_response_metadata():
    storage = _storage()

    url = await storage.upload_perm(
        io.BytesIO(_image_bytes("PNG")),
        "spoofed.jpg",
        "image/jpeg",
        prefix="profile/USER_a",
    )

    uploaded_file, bucket, key = storage._client.upload_fileobj.call_args.args
    extra_args = storage._client.upload_fileobj.call_args.kwargs["ExtraArgs"]
    assert Image.open(uploaded_file).format == "PNG"
    assert bucket == "bucket"
    assert key.endswith(".png")
    assert url.endswith(".png")
    assert extra_args == {
        "ContentType": "image/png",
        "ContentDisposition": 'inline; filename="image.png"',
        "ACL": "public-read",
    }
