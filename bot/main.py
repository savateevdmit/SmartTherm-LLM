import os
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from app.infrastructure.logging_setup import setup_logging
from bot.handlers import router

log = logging.getLogger("kb_admin")

VPS_PROXY = os.getenv("VPS_PROXY")


async def main():
    setup_logging()

    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TG_BOT_TOKEN is not set")

    session = AiohttpSession(proxy=VPS_PROXY)
    bot = Bot(token=token, session=session)

    dp = Dispatcher()
    dp.include_router(router)

    log.info(f"🚀 Bot started via VPS proxy: {VPS_PROXY}")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
