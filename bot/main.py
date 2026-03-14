import os
import asyncio
import logging

from aiogram import Bot, Dispatcher

from app.infrastructure.logging_setup import setup_logging
from bot.handlers import router

log = logging.getLogger("kb_admin")


async def main():
    setup_logging()

    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TG_BOT_TOKEN is not set")

    bot = Bot(token=token)
    dp = Dispatcher()
    dp.include_router(router)

    log.info("Telegram bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())