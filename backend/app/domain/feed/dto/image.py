from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessedVariant:
    """단일 변형 처리 결과 — 그대로 S3 에 업로드 가능한 bytes + 메타."""
    data: bytes
    content_type: str
    file_ext: str   # 키 suffix 결정용 (예: "jpg" → ".../small.jpg")


@dataclass(frozen=True)
class ProcessedFeedImage:
    """피드 이미지 1장의 다해상도 변형 결과 — 호출측이 3건 모두 S3 에 업로드."""
    original: ProcessedVariant
    small: ProcessedVariant     # 240×240 JPEG
    medium: ProcessedVariant    # 720×720 JPEG
