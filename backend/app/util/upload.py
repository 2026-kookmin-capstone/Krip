"""업로드 파일 크기 안전 처리 유틸.

`await file.read()` 로 전체 본문을 한 번에 올리면 거대 업로드가 OOM 을 유발하므로,
청크로 읽으며 상한 초과 즉시 중단해 메모리를 상한+청크 크기로 제한한다.
"""
from fastapi import UploadFile, HTTPException


_CHUNK_SIZE = 64 * 1024


async def read_upload_capped(file: UploadFile, max_bytes: int) -> bytes:
    """UploadFile 을 청크로 읽어 bytes 반환. 누적 크기가 max_bytes 를 넘으면 413.

    상한 초과 시 나머지를 읽지 않고 즉시 중단하므로 메모리 사용이 max_bytes 로 제한된다.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"파일 크기가 {max_bytes // (1024 * 1024)}MB 를 초과합니다.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def enforce_upload_size(file: UploadFile, max_bytes: int) -> None:
    """파일 객체를 그대로 넘겨야 하는 경로용 — 크기만 검증하고 offset 을 0 으로 되돌린다."""
    await read_upload_capped(file, max_bytes)
    await file.seek(0)
