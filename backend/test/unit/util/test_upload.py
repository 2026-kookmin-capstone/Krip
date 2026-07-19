"""업로드 크기 검증 유틸(app.util.upload) 단위 테스트.

- read_upload_capped: 청크 누적 / 상한 경계(정확히 max 허용·+1 거부) / 초과 시 조기 중단(전량 미소비)
- enforce_upload_size: 검증 후 offset 0 복원 (실제 업로드가 처음부터 읽도록)
- 빈 파일 안전
"""
import pytest
from fastapi import HTTPException

from app.util.upload import enforce_upload_size, read_upload_capped


class _FakeUploadFile:
    """UploadFile 최소 흉내 — 청크 read / seek 만. offset·read 호출수 추적."""

    def __init__(self, data: bytes):
        self._data = data
        self.pos = 0
        self.read_calls = 0

    async def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        chunk = self._data[self.pos:] if size < 0 else self._data[self.pos:self.pos + size]
        self.pos += len(chunk)
        return chunk

    async def seek(self, pos: int) -> None:
        self.pos = pos


@pytest.mark.unit
class TestReadUploadCapped:
    async def test_returns_full_bytes_under_limit(self):
        f = _FakeUploadFile(b"hello world")
        assert await read_upload_capped(f, max_bytes=1024) == b"hello world"

    async def test_allows_exactly_max_bytes(self):
        data = b"x" * 100
        assert await read_upload_capped(_FakeUploadFile(data), max_bytes=100) == data

    async def test_rejects_one_byte_over_max(self):
        with pytest.raises(HTTPException) as exc:
            await read_upload_capped(_FakeUploadFile(b"x" * 101), max_bytes=100)
        assert exc.value.status_code == 413

    async def test_aborts_early_without_reading_whole_file(self):
        # 1MB 데이터 / 10B 상한 — 첫 청크에서 초과를 감지하고 나머지를 읽지 않는다(메모리 상한 보장).
        data = b"x" * (1024 * 1024)
        f = _FakeUploadFile(data)
        with pytest.raises(HTTPException) as exc:
            await read_upload_capped(f, max_bytes=10)
        assert exc.value.status_code == 413
        assert f.pos < len(data)

    async def test_empty_file_returns_empty_bytes(self):
        assert await read_upload_capped(_FakeUploadFile(b""), max_bytes=100) == b""


@pytest.mark.unit
class TestEnforceUploadSize:
    async def test_resets_offset_to_zero_after_validation(self):
        f = _FakeUploadFile(b"payload")
        result = await enforce_upload_size(f, max_bytes=1024)
        assert result is None
        assert f.pos == 0  # 이후 실제 업로드가 처음부터 읽도록 되감김

    async def test_rejects_over_limit(self):
        with pytest.raises(HTTPException) as exc:
            await enforce_upload_size(_FakeUploadFile(b"x" * 200), max_bytes=100)
        assert exc.value.status_code == 413
