import os
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.web.routes import router as web_router
from app.api.routes import router as api_router
from app.middleware import SecurityHeadersMiddleware, AppErrorMiddleware
from app.infrastructure.logging_setup import setup_logging
from app.media_storage_s3 import get_media_bytes, ensure_bucket_exists
from app.db_init import check_schema_or_raise

setup_logging()

check_schema_or_raise()

app = FastAPI(title="SmartTherm - Backend", root_path=settings.root_path or "")

app.add_middleware(AppErrorMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


def _storage_mode() -> str:
    return (os.getenv("MEDIA_STORAGE", "local") or "local").strip().lower()


if _storage_mode() == "s3":
    ensure_bucket_exists()

    @app.get("/media/{media_id}.jpg")
    def media_get(media_id: int):
        content = get_media_bytes(media_id)
        if content is None:
            return Response(status_code=404)
        return Response(content=content, media_type="image/jpeg")
else:
    app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

app.include_router(web_router)
app.include_router(api_router)