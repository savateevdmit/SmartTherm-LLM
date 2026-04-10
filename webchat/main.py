import os
import logging
import time
import hashlib

import requests
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("webchat")

WEBKB_INTERNAL_URL = os.getenv("WEBKB_INTERNAL_BASE_URL", "http://webkb:8052").rstrip("/")
ROOT_PATH = os.getenv("ROOT_PATH", "").rstrip("/")
TURNSTILE_SECRET = os.getenv("TURNSTILE_SECRET", "").strip()
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "").strip()

_rate: dict[str, list[float]] = {}
RATE_LIMIT = int(os.getenv("WEBCHAT_RATE_LIMIT", "5"))
RATE_WINDOW = int(os.getenv("WEBCHAT_RATE_WINDOW", "60"))


def _is_rate_limited(ip: str) -> bool:
    now = time.time()
    hits = _rate.setdefault(ip, [])
    hits[:] = [t for t in hits if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        return True
    hits.append(now)
    return False


def _verify_turnstile(token: str, ip: str) -> bool:
    if not TURNSTILE_SECRET:
        return True

    try:
        resp = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": TURNSTILE_SECRET, "response": token, "remoteip": ip},
            timeout=10,
        )
        data = resp.json()
        return data.get("success", False)
    except Exception:
        log.exception("Turnstile verification failed")
        return False


app = FastAPI(title="SmartTherm WebChat")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    text: str
    tg_username: Optional[str] = None
    cf_token: str = ""


class PollRequest(BaseModel):
    task_id: str


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(STATIC_DIR, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    inject = f'<script>window.__TURNSTILE_SITE_KEY="{TURNSTILE_SITE_KEY}";</script>'
    html = html.replace("</head>", f"{inject}\n</head>")
    return HTMLResponse(content=html)


@app.post("/chat/ask")
def chat_ask(body: ChatRequest, request: Request):
    ip = request.client.host if request.client else "unknown"

    if TURNSTILE_SECRET:
        if not body.cf_token:
            return JSONResponse({"error": "captcha_required"}, status_code=400)
        if not _verify_turnstile(body.cf_token, ip):
            return JSONResponse({"error": "captcha_failed"}, status_code=403)

    if _is_rate_limited(ip):
        return JSONResponse({"error": "rate_limited"}, status_code=429)

    text = (body.text or "").strip()
    if not text or len(text) > 2000:
        return JSONResponse({"error": "invalid_text"}, status_code=400)

    tg_username = (body.tg_username or "").strip().lstrip("@")[:64]

    user_id_hash = int(hashlib.md5(ip.encode()).hexdigest()[:8], 16)

    if tg_username:
        log_username = f"web|@{tg_username}"
    else:
        log_username = "web|anonymous"

    try:
        api_url = f"{WEBKB_INTERNAL_URL}{ROOT_PATH}/api/ask"
        resp = requests.post(
            api_url,
            json={
                "user_id": user_id_hash,
                "username": log_username,
                "text": text,
                "source": "web",
                "tg_username": tg_username,
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        log.exception("Failed to proxy /api/ask")
        return JSONResponse({"error": "backend_error"}, status_code=502)


@app.get("/chat/media/{media_id}")
def chat_media(media_id: int):
    try:
        api_url = f"{WEBKB_INTERNAL_URL}{ROOT_PATH}/media/{media_id}.jpg"
        resp = requests.get(api_url, timeout=30)
        if resp.status_code != 200:
            return JSONResponse({"error": "not_found"}, status_code=404)
        from fastapi.responses import Response
        return Response(content=resp.content, media_type="image/jpeg")
    except Exception:
        return JSONResponse({"error": "media_error"}, status_code=502)


@app.post("/chat/poll")
def chat_poll(body: PollRequest):
    task_id = (body.task_id or "").strip()
    if not task_id:
        return JSONResponse({"error": "missing_task_id"}, status_code=400)

    try:
        api_url = f"{WEBKB_INTERNAL_URL}{ROOT_PATH}/api/result/{task_id}"
        resp = requests.get(api_url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        log.exception("Failed to proxy /api/result")
        return JSONResponse({"error": "backend_error"}, status_code=502)