import io
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request, UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.domain.tripmate.router.tripmate_image import upload_images


def _png_upload() -> UploadFile:
    data = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(data, format="PNG")
    data.seek(0)
    return UploadFile(
        file=data,
        filename="image.png",
        headers=Headers({"content-type": "image/png"}),
    )


@pytest.mark.unit
async def test_upload_images_returns_400_when_image_bytes_are_invalid():
    image_service = AsyncMock()
    image_service.upload_images.side_effect = ValueError("이미지를 처리할 수 없습니다.")
    request = Request({"type": "http"})
    request.state.user_id = "USER_a"

    with pytest.raises(HTTPException) as error:
        await upload_images(
            request=request,
            files=[_png_upload()],
            image_service=image_service,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "이미지를 처리할 수 없습니다."
