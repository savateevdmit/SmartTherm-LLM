import os
from dataclasses import dataclass
from typing import Optional

import boto3


def _get(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


@dataclass(frozen=True)
class S3Config:
    endpoint_url: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    prefix: str  # e.g. "smarttherm-media/media"


def s3_config() -> S3Config:
    return S3Config(
        endpoint_url=_get("S3_ENDPOINT_URL"),
        region=_get("S3_REGION", "us-east-1"),
        bucket=_get("S3_BUCKET"),
        access_key_id=_get("S3_ACCESS_KEY_ID"),
        secret_access_key=_get("S3_SECRET_ACCESS_KEY"),
        prefix=_get("S3_PREFIX", "smarttherm-media/media").strip("/"),
    )


def s3_client():
    cfg = s3_config()
    return boto3.client(
        "s3",
        endpoint_url=cfg.endpoint_url or None,
        region_name=cfg.region or None,
        aws_access_key_id=cfg.access_key_id or None,
        aws_secret_access_key=cfg.secret_access_key or None,
    )


def ensure_bucket_exists() -> None:
    cfg = s3_config()
    client = s3_client()
    try:
        client.head_bucket(Bucket=cfg.bucket)
        return
    except Exception:
        pass

    try:
        client.create_bucket(Bucket=cfg.bucket)
    except Exception:
        # already exists / no permissions
        pass


def s3_key_for_media_id(media_id: int) -> str:
    cfg = s3_config()
    return f"{cfg.prefix}/{int(media_id)}.jpg"


def upload_jpg(media_id: int, content: bytes) -> None:
    cfg = s3_config()
    client = s3_client()
    key = s3_key_for_media_id(media_id)
    client.put_object(
        Bucket=cfg.bucket,
        Key=key,
        Body=content,
        ContentType="image/jpeg",
        CacheControl="no-cache",
    )


def delete_media(media_id: int) -> None:
    cfg = s3_config()
    client = s3_client()
    key = s3_key_for_media_id(media_id)
    client.delete_object(Bucket=cfg.bucket, Key=key)


def get_media_bytes(media_id: int) -> Optional[bytes]:
    cfg = s3_config()
    client = s3_client()
    key = s3_key_for_media_id(media_id)

    try:
        resp = client.get_object(Bucket=cfg.bucket, Key=key)
        return resp["Body"].read()
    except Exception:
        return None


def next_media_id(counter_start: int = 50000) -> int:
    ensure_bucket_exists()
    cfg = s3_config()
    client = s3_client()
    counter_key = f"{cfg.prefix}/media_counter.txt"

    n = counter_start
    try:
        resp = client.get_object(Bucket=cfg.bucket, Key=counter_key)
        raw = resp["Body"].read().decode("utf-8", errors="ignore").strip()
        if raw:
            n = int(raw)
    except Exception:
        n = counter_start

    # increment (first write will become counter_start+1)
    n = n + 1 if n >= counter_start else counter_start

    client.put_object(
        Bucket=cfg.bucket,
        Key=counter_key,
        Body=str(n).encode("utf-8"),
        ContentType="text/plain",
        CacheControl="no-cache",
    )

    return n