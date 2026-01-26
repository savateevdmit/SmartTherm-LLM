import os
from typing import List, Optional, Tuple, Union

from fastapi import UploadFile
from PIL import Image

from app.config import settings

ALLOWED_MIME = {"image/png", "image/jpeg"}

_COUNTER_START = 50000


def ensure_media_dir():
    os.makedirs(settings.media_dir, exist_ok=True)


def io_bytes(content: bytes):
    import io
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


def _save_as_jpg(content: bytes, out_path: str) -> None:
    with Image.open(io_bytes(content)) as img:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGBA")
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")

        img.save(out_path, format="JPEG", quality=88, optimize=True, progressive=True)


def _counter_file_path() -> str:
    ensure_media_dir()
    return os.path.join(settings.media_dir, "media_counter.txt")


def _next_media_number() -> int:
    path = _counter_file_path()
    n = None

    if os.path.exists(path):
        try:
            raw = open(path, "r", encoding="utf-8").read().strip()
            if raw:
                n = int(raw)
        except Exception:
            n = None

    if n is None:
        n = _COUNTER_START
    else:
        n += 1

    with open(path, "w", encoding="utf-8") as f:
        f.write(str(n))

    return n


async def save_images(files: List[UploadFile]) -> List[int]:
    """
    Save uploaded images into MEDIA_DIR as <number>.jpg where number starts at 50000.
    Return list of numbers (ints). DB visual_path will be [50000], not ["50000"].
    """
    ensure_media_dir()
    saved: List[int] = []

    for f in files or []:
        if not f or not f.filename:
            continue

        content = await f.read()
        ok, err = validate_image_upload(f, content)
        if not ok:
            raise ValueError(err)

        num = _next_media_number()
        path = os.path.join(settings.media_dir, f"{num}.jpg")
        _save_as_jpg(content, path)
        saved.append(num)

    return saved


def delete_media_files(names: Optional[List[Union[int, str]]]) -> None:
    """
    names are numbers (preferred) or strings; delete MEDIA_DIR/<name>.jpg
    """
    if not names:
        return
    for n in names:
        if n is None:
            continue
        try:
            num = int(n)
        except Exception:
            continue
        path = os.path.join(settings.media_dir, f"{num}.jpg")
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass