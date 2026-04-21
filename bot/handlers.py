import os
import asyncio
import logging
from urllib.parse import urlparse

import aiohttp
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.types import Message, InputMediaPhoto
from aiogram.types.input_file import BufferedInputFile

from app.infrastructure.redis_queue import enqueue, wait_result, queue_length
from app.infrastructure.telegram_html import sanitize_telegram_html

log = logging.getLogger("kb_admin")
router = Router()


def _root_path() -> str:
    return (os.getenv("ROOT_PATH", "") or "").rstrip("/")


def _internal_webkb_base() -> str:
    return (os.getenv("WEBKB_INTERNAL_BASE_URL", "http://webkb:8052") or "").rstrip("/")


def _media_path(media_id: int) -> str:
    root_path = (os.getenv("ROOT_PATH", "") or "").rstrip("/")
    if root_path:
        return f"{root_path}/media/{media_id}.jpg"
    return f"/media/{media_id}.jpg"


def _vps_proxy() -> str:
    return (os.getenv("VPS_PROXY", "") or "").strip()


def _should_use_proxy(url: str) -> bool:
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
    except Exception:
        return False
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


def _format_eta(seconds: int) -> str:
    if seconds <= 60:
        return f"{seconds} сек"
    minutes = int((seconds + 59) // 60)
    return f"{minutes} мин"


async def _build_media_group_as_bytes(media_ids: list, internal_base: str) -> list[InputMediaPhoto]:
    media_group: list[InputMediaPhoto] = []

    for mid in (media_ids or [])[:3]:
        try:
            mid_int = int(mid)
        except Exception:
            continue

        try:
            internal_url = f"{internal_base}{_media_path(mid_int)}"
            content = await _fetch_media_bytes(internal_url)
            f = BufferedInputFile(content, filename=f"{mid_int}.jpg")
            media_group.append(InputMediaPhoto(media=f))
        except Exception as e:
            log.warning("Failed to fetch media %s: %s", mid_int, e)
            continue

    return media_group


@router.message(F.text)
async def on_text(message: Message):
    text = (message.text or "").strip()
    if not text:
        return

    username = message.from_user.username or f"id{message.from_user.id}"
    task_id = f"tg-{message.message_id}-{message.from_user.id}"

    enqueue(
        {
            "task_id": task_id,
            "user": {"id": message.from_user.id, "username": username},
            "text": text,
        }
    )

    qlen = queue_length()
    position = qlen + 1
    eta_seconds = position * 60

    await message.answer(
        "Ваш вопрос принят, уже готовим для вас ответ.\n"
        f"<b>Позиция в очереди:</b> {position}\n"
        f"<b>Примерное время ожидания:</b> {_format_eta(eta_seconds)}",
        parse_mode=ParseMode.HTML,
    )

    wait_seconds = int(os.getenv("TG_WAIT_SECONDS", "600") or "600")

    pulse_task = asyncio.create_task(asyncio.sleep(120))
    try:
        res_task = asyncio.create_task(asyncio.to_thread(wait_result, task_id, wait_seconds))
        done, _ = await asyncio.wait({res_task, pulse_task}, return_when=asyncio.FIRST_COMPLETED)

        if pulse_task in done and not res_task.done():
            await message.answer("Готовим ответ, это занимает чуть больше времени. Пожалуйста, подождите…")
            res = await res_task
        else:
            res = res_task.result()
    finally:
        if not pulse_task.done():
            pulse_task.cancel()

    if not res:
        await message.answer("Таймаут. Попробуйте позже.")
        return

    if res.get("error"):
        await message.answer("Ошибка генерации ответа. Попробуйте позже.")
        return

    answer_text = res.get("answer_text") or ""
    media_ids = res.get("media_ids") or []

    safe_html = sanitize_telegram_html(answer_text)
    await message.answer(safe_html, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if media_ids:
        await message.answer("Медиа по вашему запросу:", parse_mode=ParseMode.HTML)
        internal_base = _internal_webkb_base()
        media_group = await _build_media_group_as_bytes(media_ids, internal_base)
        if media_group:
            await message.answer_media_group(media_group)