from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import unquote

import boto3

from app.core.config import get_settings


class ObjectStorage:
    def __init__(self) -> None:
        self.settings = get_settings()

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        if self.settings.s3_endpoint_url and self.settings.s3_access_key_id:
            client = boto3.client(
                "s3",
                endpoint_url=self.settings.s3_endpoint_url,
                aws_access_key_id=self.settings.s3_access_key_id,
                aws_secret_access_key=self.settings.s3_secret_access_key,
            )
            try:
                try:
                    client.create_bucket(Bucket=self.settings.s3_bucket)
                except Exception:
                    pass
                client.put_object(
                    Bucket=self.settings.s3_bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
                base = self.settings.s3_public_base_url or ""
                return f"{base.rstrip('/')}/{key}"
            except Exception:
                if self.settings.app_env != "local":
                    raise

        upload_dir = Path(self.settings.local_upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        path = upload_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"{self.settings.public_upload_base_url.rstrip('/')}/{key}"

    def get_bytes_for_url(self, url: str) -> tuple[bytes, str]:
        s3_base = (self.settings.s3_public_base_url or "").rstrip("/")
        if s3_base and url.startswith(f"{s3_base}/"):
            key = unquote(url[len(s3_base) + 1 :])
            client = boto3.client(
                "s3",
                endpoint_url=self.settings.s3_endpoint_url,
                aws_access_key_id=self.settings.s3_access_key_id,
                aws_secret_access_key=self.settings.s3_secret_access_key,
            )
            response = client.get_object(Bucket=self.settings.s3_bucket, Key=key)
            return response["Body"].read(), response.get("ContentType") or _content_type_for_key(key)

        upload_base = self.settings.public_upload_base_url.rstrip("/")
        if url.startswith(f"{upload_base}/"):
            key = unquote(url[len(upload_base) + 1 :])
            path = Path(self.settings.local_upload_dir) / key
            return path.read_bytes(), _content_type_for_key(key)

        raise ValueError("Unsupported asset URL")


def stable_asset_key(prefix: str, content: bytes, extension: str) -> str:
    digest = hashlib.sha256(content).hexdigest()[:16]
    return f"{prefix}/{digest}.{extension.lstrip('.')}"


def _content_type_for_key(key: str) -> str:
    suffix = Path(key).suffix.lower()
    return {
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
