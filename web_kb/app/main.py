import os
import logging
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.web.routes import router as web_router
from app.media import ensure_media_dir
from app.middleware import SecurityHeadersMiddleware, AppErrorMiddleware

LOG_FILE = "app.log"

root = logging.getLogger()
root.setLevel(logging.INFO)

fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
file_handler.setFormatter(fmt)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(fmt)
console_handler.setLevel(logging.INFO)

if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
    root.addHandler(file_handler)
if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root.handlers):
    root.addHandler(console_handler)

log = logging.getLogger("kb_admin")

# root_path allows hosting behind a reverse proxy at /smarttherm/webkb
app = FastAPI(title="SmartTherm - База знаний", root_path=settings.root_path or "")

app.add_middleware(AppErrorMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

ensure_media_dir()

app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

app.include_router(web_router)


@app.on_event("startup")
def warmup_embedding_model():
    try:
        from app.embeddings import encode_question_embedding
        _ = encode_question_embedding("ping")
        log.info("Embedding model warmed up successfully.")
    except Exception:
        log.exception("Embedding model warmup failed (app will still work, but first request may be slow).")