import os
import asyncio
import logging
from typing import Optional, List
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile, InputMediaPhoto

from app.infrastructure.telegram_html import sanitize_telegram_html

log = logging.getLogger("kb_admin")


def _enabled() -> bool:
    return (os.getenv("TG_LOG_ENABLED", "0") or "0").strip() in ("1", "true", "True", "yes", "on")


def _token() -> str:
    return (os.getenv("TG_BOT_TOKEN", "") or "").strip()


def _channel_id() -> str:
    return (os.getenv("TG_LOG_CHANNEL_ID", "") or "").strip()


def _internal_webkb_base() -> str:
    return (os.getenv("WEBKB_INTERNAL_BASE_URL", "http://webkb:8052") or "").rstrip("/")


def _root_path() -> str:
    return (os.getenv("ROOT_PATH", "") or "").rstrip("/")


def _media_path(media_id: int) -> str:
    rp = _root_path()
    if rp:
        return f"{rp}/media/{media_id}.jpg"
    return f"/media/{media_id}.jpg"


def _vps_proxy() -> Optional[str]:
    p = (os.getenv("VPS_PROXY", "") or "").strip()
    return p or None


def _should_use_proxy(url: str) -> bool:
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
    except Exception:
        return False

    # internal docker service should never go through proxy
    if host in ("webkb", "localhost", "127.0.0.1"):
        return False

    return True


async def _fetch_media_bytes(url: str) -> bytes:
    proxy = _vps_proxy()
    if not proxy or not _should_use_proxy(url):
        proxy = None

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, timeout=timeout, proxy=proxy) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to fetch media: {resp.status}")
            return await resp.read()


async def _build_media_group(media_ids: List[int]) -> list[InputMediaPhoto]:
    media_group: list[InputMediaPhoto] = []
    base = _internal_webkb_base()

    for mid in (media_ids or [])[:3]:
        try:
            mid_int = int(mid)
        except Exception:
            continue

        try:
            url = f"{base}{_media_path(mid_int)}"
            content = await _fetch_media_bytes(url)
            f = BufferedInputFile(content, filename=f"{mid_int}.jpg")
            media_group.append(InputMediaPhoto(media=f))
        except Exception as e:
            log.warning("TG log: failed to fetch media %s: %s", mid_int, e)
            continue

    return media_group


async def send_log_message(text: str, media_ids: Optional[List[int]] = None) -> None:
    if not _enabled():
        return

    token = _token()
    chat_id = _channel_id()
    if not token or not chat_id:
        return

    proxy = _vps_proxy()
    if proxy:
        session = AiohttpSession(proxy=proxy)
        bot = Bot(token=token, session=session)
    else:
        bot = Bot(token=token)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=sanitize_telegram_html(text),
            parse_mode=ParseMode.HTML,
        )

        if media_ids:
            await bot.send_message(chat_id=chat_id, text="Медиа:", parse_mode=ParseMode.HTML)
            media_group = await _build_media_group(media_ids)
            if media_group:
                await bot.send_media_group(chat_id=chat_id, media=media_group)

    finally:
        await bot.session.close()


def send_log_message_sync(text: str, media_ids: Optional[List[int]] = None) -> None:
    asyncio.run(send_log_message(text, media_ids))