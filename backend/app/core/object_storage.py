"""NCloud S3-compatible storage.

Temporary keys expire after 24 hours; permanent key prefixes are owned by callers.
"""
import asyncio
import io
import uuid
from typing import BinaryIO, List

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config.setting import settings
from app.core.logger import get_logger
from app.util.public_image import process_public_image


logger = get_logger("object_storage")

_PREFIX_TMP = "uploads/tmp"
_PREFIX_PERM = "uploads/perm"


class ObjectStorage:
    """Naver Cloud S3 호환 Object Storage 클라이언트"""

    _instance: "ObjectStorage | None" = None

    def __init__(self):
        self.bucket = settings.S3_BUCKET_NAME
        self.endpoint = settings.S3_ENDPOINT_URL

        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(
                region_name=settings.S3_REGION,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    @classmethod
    def get_instance(cls) -> "ObjectStorage":
        """싱글톤 인스턴스 반환 (최초 호출 시 초기화)"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def upload_temp(self, file: BinaryIO, file_name: str, content_type: str) -> str:
        """임시 경로에 업로드 → URL 반환"""
        key = self._make_key(file_name, _PREFIX_TMP)
        return await asyncio.to_thread(self._upload, file, key, content_type)

    async def upload_perm(self, file: BinaryIO, file_name: str, content_type: str, *, prefix: str) -> str:
        """검증·재인코딩한 정적 이미지를 영구 경로에 업로드 → URL 반환."""
        return await asyncio.to_thread(self._upload_public_image, file, prefix)

    async def upload_to_key(
        self,
        file: "BinaryIO | bytes",
        *,
        prefix: str,
        filename: str,
        content_type: str,
    ) -> str:
        """결정적 키 (`{_PREFIX_PERM}/{prefix}/{filename}`) 로 업로드 → URL 반환.

        `upload_perm` 과 달리 자동 UUID 생성 없이 호출자가 지정한 filename 을 그대로 사용한다.
        피드 다해상도 변형 (`small.jpg` / `medium.jpg` / `original.{ext}`) 처럼 같은 디렉터리
        하위에 결정적 이름으로 묶어야 하는 케이스 전용.
        """
        key = f"{_PREFIX_PERM}/{prefix}/{filename}"
        if isinstance(file, (bytes, bytearray)):
            import io
            file = io.BytesIO(file)
        return await asyncio.to_thread(self._upload, file, key, content_type)

    async def move_to_perm(self, temp_url: str, *, prefix: str) -> str:
        """임시 파일 1개를 영구 경로로 이동 → 새 URL 반환"""
        src_key = self._url_to_key(temp_url)
        filename = src_key.rsplit("/", 1)[-1]
        dst_key = f"{_PREFIX_PERM}/{prefix}/{filename}"

        await asyncio.to_thread(self._copy, src_key, dst_key)
        await asyncio.to_thread(self._delete, src_key)

        logger.bind(operation="move").info("Object storage operation completed")
        return self._key_to_url(dst_key)

    async def move_many_to_perm(self, temp_urls: List[str], *, prefix: str) -> List[str]:
        """임시 파일 여러 개를 영구 경로로 이동 → 새 URL 목록 반환"""
        return list(await asyncio.gather(
            *(self.move_to_perm(url, prefix=prefix) for url in temp_urls)
        ))

    async def delete(self, file_url: str) -> None:
        """URL로 파일 삭제"""
        key = self._url_to_key(file_url)
        await asyncio.to_thread(self._delete, key)
        logger.bind(operation="delete").info("Object storage operation completed")

    async def delete_many(self, file_urls: List[str]) -> None:
        """URL 목록으로 파일 일괄 삭제"""
        if not file_urls:
            return

        objects = [{"Key": self._url_to_key(url)} for url in file_urls]
        try:
            await asyncio.to_thread(
                self._client.delete_objects, Bucket=self.bucket, Delete={"Objects": objects},
            )
            logger.bind(operation="delete_many", object_count=len(objects)).info(
                "Object storage operation completed"
            )
        except ClientError as e:
            logger.bind(operation="delete_many", error=e).error(
                "Object storage operation failed"
            )
            raise

    async def delete_by_prefix(self, prefix: str) -> int:
        """특정 경로(prefix) 하위 파일 전체 삭제 → 삭제 건수 반환"""
        full_prefix = f"{_PREFIX_PERM}/{prefix}"
        deleted = await asyncio.to_thread(self._delete_by_prefix_sync, full_prefix)
        logger.bind(operation="delete_prefix", object_count=deleted).info(
            "Object storage operation completed"
        )
        return deleted

    def get_url(self, file_key: str) -> str:
        """파일 키 → URL"""
        return self._key_to_url(file_key)

    def _make_key(self, file_name: str, prefix: str) -> str:
        ext = self._sanitize_ext(file_name)
        unique = uuid.uuid4()
        return f"{prefix}/{unique}.{ext}" if ext else f"{prefix}/{unique}"

    @staticmethod
    def _sanitize_ext(file_name: str) -> str:
        """클라이언트가 준 파일명의 확장자를 안전하게 정규화한다."""
        if "." not in file_name:
            return ""
        raw = file_name.rsplit(".", 1)[-1]
        # /, ., 제어문자 등을 모두 제거하고 영숫자만 남긴다.
        cleaned = "".join(ch for ch in raw if ch.isalnum() and ch.isascii()).lower()
        return cleaned[:10]

    def _key_to_url(self, key: str) -> str:
        return f"{self.endpoint}/{self.bucket}/{key}"

    def _url_to_key(self, url: str) -> str:
        base = f"{self.endpoint}/{self.bucket}/"
        if not url.startswith(base):
            raise ValueError(f"올바르지 않은 Object Storage URL: {url}")
        return url[len(base):]

    def _upload(self, file: BinaryIO, key: str, content_type: str) -> str:
        try:
            ext = self._sanitize_ext(key)
            disposition = f'inline; filename="image.{ext}"' if ext else "inline"
            self._client.upload_fileobj(
                file, self.bucket, key,
                ExtraArgs={
                    "ContentType": content_type,
                    "ContentDisposition": disposition,
                    "ACL": "public-read",
                },
            )
        except ClientError as e:
            logger.bind(operation="upload", error=e).error(
                "Object storage operation failed"
            )
            raise
        logger.bind(operation="upload").info("Object storage operation completed")
        return self._key_to_url(key)

    def _upload_public_image(self, file: BinaryIO, prefix: str) -> str:
        processed = process_public_image(file)
        key = self._make_key(
            f"image.{processed.file_ext}",
            f"{_PREFIX_PERM}/{prefix}",
        )
        return self._upload(
            io.BytesIO(processed.data),
            key,
            processed.content_type,
        )

    def _copy(self, src_key: str, dst_key: str) -> None:
        try:
            self._client.copy_object(
                Bucket=self.bucket,
                CopySource={"Bucket": self.bucket, "Key": src_key},
                Key=dst_key,
                ACL="public-read",
            )
        except ClientError as e:
            logger.bind(operation="copy", error=e).error(
                "Object storage operation failed"
            )
            raise

    def _delete_by_prefix_sync(self, full_prefix: str) -> int:
        paginator = self._client.get_paginator("list_objects_v2")
        deleted = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if not objects:
                continue
            response = self._client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": objects},
            )
            errors = response.get("Errors", [])
            if errors:
                raise RuntimeError(f"Object Storage 일괄 삭제 부분 실패: {len(errors)}건")
            deleted += len(response.get("Deleted", []))
        return deleted

    def _delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            logger.bind(operation="delete", error=e).error(
                "Object storage operation failed"
            )
            raise


def get_object_storage() -> ObjectStorage:
    """ObjectStorage 싱글톤 인스턴스 반환"""
    return ObjectStorage.get_instance()
