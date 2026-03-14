import os
from typing import List, Optional, Tuple, Union
import io

from fastapi import UploadFile
from PIL import Image

from app.config import settings
from app.media_storage_s3 import (
    ensure_bucket_exists,
    upload_jpg,
    delete_media,
    next_media_id,
)

ALLOWED_MIME = {"image/png", "image/jpeg"}


def _storage_mode() -> str:
    return (os.getenv("MEDIA_STORAGE", "local") or "local").strip().lower()


def io_bytes(content: bytes):
    return io.BytesIO(content)


def validate_image_upload(file: UploadFile, content: bytes) -> Tuple[bool, str]:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        return False, f"Файл слишком большой по весу (>{settings.max_upload_mb} МБ)."

    if (file.content_type or "").lower() not in ALLOWED_MIME:
        return False, "Разрешены только PNG/JPG."

    try:
        with Image.open(io_bytes(content)) as _:
            pass
    except Exception:
        return False, "Файл не является корректным изображением."

    return True, ""


def _image_to_jpg_bytes(content: bytes) -> bytes:
    with Image.open(io_bytes(content)) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGBA")
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88, optimize=True, progressive=True)
        return out.getvalue()


async def save_images(files: List[UploadFile]) -> List[int]:
    """
    Save uploaded images to S3 (MinIO) if MEDIA_STORAGE=s3.
    Return list of numeric media ids (ints).
    """
    mode = _storage_mode()
    if mode != "s3":
        raise RuntimeError("MEDIA_STORAGE must be 's3' (local media storage is disabled).")

    ensure_bucket_exists()

    saved: List[int] = []
    for f in files or []:
        if not f or not f.filename:
            continue

        content = await f.read()
        ok, err = validate_image_upload(f, content)
        if not ok:
            raise ValueError(err)

        jpg_bytes = _image_to_jpg_bytes(content)
        num = next_media_id()
        upload_jpg(num, jpg_bytes)
        saved.append(num)

    return saved


def delete_media_files(names: Optional[List[Union[int, str]]]) -> None:
    """
    Delete media objects from S3 (MinIO) if MEDIA_STORAGE=s3.
    """
    if not names:
        return

    mode = _storage_mode()
    if mode != "s3":
        return

    ensure_bucket_exists()

    for n in names:
        if n is None:
            continue
        try:
            num = int(n)
        except Exception:
            continue
        try:
            delete_media(num)
        except Exception:
            pass