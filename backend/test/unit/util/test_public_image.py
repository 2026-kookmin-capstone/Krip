import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image, PngImagePlugin

from app.util import public_image


def _save_image(fmt: str, *, metadata=None, save_all=False, append_images=None) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (2, 2), "red")
    image.save(
        output,
        format=fmt,
        pnginfo=metadata,
        save_all=save_all,
        append_images=append_images or [],
    )
    return output.getvalue()


@pytest.mark.unit
def test_process_public_image_rejects_animated_image():
    second = Image.new("RGB", (2, 2), "blue")
    payload = _save_image("GIF", save_all=True, append_images=[second])

    with pytest.raises(ValueError, match="애니메이션"):
        public_image.process_public_image(payload)


@pytest.mark.unit
def test_process_public_image_checks_pixels_before_decode(monkeypatch):
    monkeypatch.setattr(public_image, "MAX_IMAGE_PIXELS", 3)

    with pytest.raises(ValueError, match="해상도"):
        public_image.process_public_image(_save_image("PNG"))


@pytest.mark.unit
def test_process_public_image_reencodes_and_strips_png_metadata():
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Comment", "untrusted")

    processed = public_image.process_public_image(_save_image("PNG", metadata=metadata))

    with Image.open(io.BytesIO(processed.data)) as image:
        assert image.format == "PNG"
        assert "Comment" not in image.info
    assert processed.content_type == "image/png"
    assert processed.file_ext == "png"


@pytest.mark.unit
def test_process_public_image_rejects_bytes_over_shared_limit(monkeypatch):
    monkeypatch.setattr(public_image, "MAX_IMAGE_BYTES", 3)

    with pytest.raises(ValueError, match="10MB"):
        public_image.process_public_image(b"1234")


@pytest.mark.unit
def test_process_public_image_rejects_reencoded_output_over_shared_limit(monkeypatch):
    monkeypatch.setattr(public_image, "MAX_IMAGE_BYTES", 100)
    monkeypatch.setattr(
        public_image,
        "_encode",
        lambda *_args: public_image.ProcessedPublicImage(b"x" * 101, "image/png", "png"),
    )

    with pytest.raises(ValueError, match="10MB"):
        public_image.process_public_image(_save_image("PNG"))


@pytest.mark.unit
def test_process_public_image_bounds_concurrent_decodes(monkeypatch):
    active = 0
    max_active = 0
    lock = threading.Lock()
    release = threading.Event()

    def blocked_encode(*_args):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        release.wait(timeout=1)
        with lock:
            active -= 1
        return public_image.ProcessedPublicImage(b"x", "image/png", "png")

    monkeypatch.setattr(public_image, "_encode", blocked_encode)
    payload = _save_image("PNG")
    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(public_image.process_public_image, payload) for _ in range(3)]
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                with lock:
                    if active >= 2:
                        break
                time.sleep(0.01)
            time.sleep(0.05)
            with lock:
                assert max_active <= 2
            release.set()
            for future in futures:
                future.result(timeout=1)
    finally:
        release.set()


@pytest.mark.unit
def test_process_public_image_stops_encoder_before_output_exceeds_limit(monkeypatch):
    payload = _save_image("PNG")
    observed_size = 0

    def oversized_save(_self, output, **_kwargs):
        nonlocal observed_size
        try:
            output.write(b"x" * 60)
            output.write(b"x" * 60)
        finally:
            observed_size = len(output.getvalue())

    monkeypatch.setattr(public_image, "MAX_IMAGE_BYTES", 100)
    monkeypatch.setattr(Image.Image, "save", oversized_save)

    with pytest.raises(ValueError, match="10MB"):
        public_image.process_public_image(payload)

    assert observed_size <= 100
