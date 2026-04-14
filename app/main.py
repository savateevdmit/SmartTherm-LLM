import os
import logging

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.web.routes import router as web_router
from app.api.routes import router as api_router
from app.middleware import SecurityHeadersMiddleware, AppErrorMiddleware
from app.infrastructure.logging_setup import setup_logging
from app.media_storage_s3 import get_media_bytes, ensure_bucket_exists

setup_logging()

log = logging.getLogger("kb_admin")

log.info("[startup] Initializing database...")
from app.db import init_db
init_db()

log.info("[startup] Checking DB schema...")
from app.db_init import check_schema_or_raise
check_schema_or_raise()

log.info("[startup] Checking Redis...")
from app.infrastructure.redis_queue import ping_redis
if ping_redis():
    log.info("[startup] Redis OK.")
else:
    log.warning("[startup] Redis unavailable — queue features may not work.")

log.info("[startup] Loading embedding model...")
try:
    from app.embeddings import load_model_on_startup
    load_model_on_startup()
except Exception as e:
    log.error("[startup] Embedding model preload failed: %s — will load lazily.", e)

log.info("[startup] Initialization complete.")


def _storage_mode() -> str:
    return (os.getenv("MEDIA_STORAGE", "local") or "local").strip().lower()


def create_app() -> FastAPI:
    inner = FastAPI(title="SmartTherm - Backend")

    inner.add_middleware(AppErrorMiddleware)
    inner.add_middleware(SecurityHeadersMiddleware)

    if _storage_mode() == "s3":
        ensure_bucket_exists()

        @inner.get("/media/{media_id}.jpg")
        def media_get(media_id: int):
            content = get_media_bytes(media_id)
            if content is None:
                return Response(status_code=404)
            return Response(content=content, media_type="image/jpeg")
    else:
        inner.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

    inner.include_router(web_router)
    inner.include_router(api_router)
    return inner


outer = FastAPI(title="SmartTherm - Backend")

root_path = (settings.root_path or "").rstrip("/")
inner_app = create_app()

if root_path:
    outer.mount(root_path, inner_app)
else:
    outer = inner_app

app = outer