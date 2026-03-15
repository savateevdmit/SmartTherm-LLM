import os
import asyncio
import logging

import aiohttp
from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, InputMediaPhoto
from aiogram.types.input_file import BufferedInputFile

from app.infrastructure.redis_queue import enqueue, wait_result, queue_length

log = logging.getLogger("kb_admin")
router = Router()


def _root_path() -> str:
    return (os.getenv("ROOT_PATH", "") or "").rstrip("/")


def _public_base_url() -> str:
    return (os.getenv("WEBKB_PUBLIC_BASE_URL", "") or "").rstrip("/")


def _internal_webkb_base() -> str:
    return (os.getenv("WEBKB_INTERNAL_BASE_URL", "http://webkb:8052") or "").rstrip("/")


def _media_path(media_id: int) -> str:
    return f"/media/{media_id}.jpg"


async def _fetch_media_bytes(url: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=30) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Failed to fetch media: {resp.status}")
            return await resp.read()


def _format_eta(seconds: int) -> str:
    if seconds <= 60:
        return f"{seconds} сек"
    minutes = int((seconds + 59) // 60)  # ceil
    return f"{minutes} мин"


async def _build_media_group(media_ids: list, public_base: str, internal_base: str) -> list[InputMediaPhoto]:
    media_group: list[InputMediaPhoto] = []

    for mid in (media_ids or [])[:3]:
        try:
            mid_int = int(mid)
        except Exception:
            continue

        # If you have a truly public base URL, Telegram can fetch by URL.
        if public_base:
            url = f"{public_base}{_media_path(mid_int)}"
            media_group.append(InputMediaPhoto(media=url))
            continue

        # Otherwise fetch from internal webkb and send bytes.
        try:
            internal_url = f"{internal_base}{_media_path(mid_int)}"
            content = await _fetch_media_bytes(internal_url)
            f = BufferedInputFile(content, filename=f"{mid_int}.jpg")
            media_group.append(InputMediaPhoto(media=f))
        except Exception as e:
            log.warning("Failed to fetch media %s: %s", mid_int, e)
            continue

    return media_group


@router.message(CommandStart())
async def on_start(message: Message):
    await message.answer(
        "Здравствуйте!\n\n"
        "Я бот технической поддержки контроллера котла отопления <b>SmartTherm</b>.\n"
        "Вы можете задать мне любой интересующий вас вопрос.",
        parse_mode=ParseMode.HTML,
    )


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
    eta_seconds = position * 30

    await message.answer(
        "Ваш вопрос принят, уже готовим для вас ответ.\n"
        f"<b>Позиция в очереди:</b> {position}\n"
        f"<b>Примерное время ожидания:</b> {_format_eta(eta_seconds)}",
        parse_mode=ParseMode.HTML,
    )

    res = await asyncio.to_thread(wait_result, task_id, 180)
    if not res:
        await message.answer("Таймаут. Попробуйте позже.")
        return

    if res.get("error"):
        await message.answer("Ошибка генерации ответа. Попробуйте позже.")
        return

    answer_text = res.get("answer_text") or ""
    media_ids = res.get("media_ids") or []

    await message.answer(answer_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    if media_ids:
        await message.answer("Медиа по вашему запросу:", parse_mode=ParseMode.HTML)

        public_base = _public_base_url()
        internal_base = _internal_webkb_base()

        media_group = await _build_media_group(media_ids, public_base, internal_base)
        if media_group:
            await message.answer_media_group(media_group)