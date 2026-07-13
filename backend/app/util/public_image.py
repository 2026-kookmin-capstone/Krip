"""공개 Object Storage 업로드 전 이미지 바이트 정규화."""
import io
import threading
import warnings
from dataclasses import dataclass
from typing import BinaryIO, Final

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES: Final[int] = 10 * 1024 * 1024
MAX_IMAGE_PIXELS: Final[int] = 30_000_000

_FORMATS: Final[dict[str, tuple[str, str]]] = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
    "GIF": ("image/png", "png"),
}
_PROCESSING_SLOTS = threading.BoundedSemaphore(2)


class _EncodedImageTooLarge(Exception):
    pass


class _CappedBuffer(io.BytesIO):
    def write(self, data) -> int:
        if max(len(self.getbuffer()), self.tell() + len(data)) > MAX_IMAGE_BYTES:
            raise _EncodedImageTooLarge
        return super().write(data)


@dataclass(frozen=True)
class ProcessedPublicImage:
    data: bytes
    content_type: str
    file_ext: str


def process_public_image(file: BinaryIO | bytes) -> ProcessedPublicImage:
    """실제 바이트를 디코딩하고 정적 허용 포맷으로 재인코딩한다."""
    data = bytes(file) if isinstance(file, (bytes, bytearray)) else file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("이미지 파일 크기가 10MB를 초과합니다.")

    with _PROCESSING_SLOTS:
        return _decode_and_encode(data)


def _decode_and_encode(data: bytes) -> ProcessedPublicImage:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                source_format = image.format
                if source_format not in _FORMATS:
                    raise ValueError("지원하지 않는 이미지 포맷입니다.")
                if getattr(image, "is_animated", False):
                    raise ValueError("애니메이션 이미지는 업로드할 수 없습니다.")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("이미지 해상도가 너무 큽니다.")

                image.load()
                normalized = ImageOps.exif_transpose(image)
                processed = _encode(normalized, source_format)
                if len(processed.data) > MAX_IMAGE_BYTES:
                    raise ValueError("재인코딩된 이미지 파일 크기가 10MB를 초과합니다.")
                return processed
    except Image.DecompressionBombError as error:
        raise ValueError("이미지 해상도가 너무 큽니다.") from error
    except _EncodedImageTooLarge as error:
        raise ValueError("재인코딩된 이미지 파일 크기가 10MB를 초과합니다.") from error
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("이미지를 처리할 수 없습니다.") from error


def _encode(image: Image.Image, source_format: str) -> ProcessedPublicImage:
    output = _CappedBuffer()
    if source_format == "JPEG":
        image = _flatten_to_rgb(image)
        image.save(output, format="JPEG", quality=85, optimize=False)
    elif source_format == "PNG" or source_format == "GIF":
        image.save(output, format="PNG", optimize=True)
    else:
        image.save(output, format="WEBP", quality=85, method=4)

    content_type, file_ext = _FORMATS[source_format]
    return ProcessedPublicImage(output.getvalue(), content_type, file_ext)


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        return background
    if image.mode == "P" and "transparency" in image.info:
        return _flatten_to_rgb(image.convert("RGBA"))
    return image.convert("RGB")
