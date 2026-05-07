import json
import asyncio
import os
from pathlib import Path
from typing import List, Union, Optional
from dataclasses import dataclass
import logging

try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
except ImportError:
    exit(1)

import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('media_extractor.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

TELEGRAM_API_ID = 34829352
TELEGRAM_API_HASH = ""
TELEGRAM_PHONE = ""
CHANNEL_OR_GROUP = "smartTherm"

KNOWLEDGE_BASE_JSON = "KB_ST_FULL.json"
MEDIA_OUTPUT_DIR = "media"


@dataclass
class MediaFile:
    message_id: int
    file_type: str
    file_name: str
    file_path: str
    answer_id: int



def parse_visual_path(visual_path: Union[str, list, None]) -> List[int]:
    if not visual_path:
        return []

    if isinstance(visual_path, list):
        return [int(x) for x in visual_path if x]

    if isinstance(visual_path, str):
        if not visual_path.strip():
            return []
        try:
            values = visual_path.replace(',', ' ').split()
            return [int(x) for x in values if x.strip()]
        except ValueError:
            logger.warning(f"Не удалось распарсить visual_path: {visual_path}")
            return []

    return []


async def export_media_from_telegram() -> dict:
    Path(MEDIA_OUTPUT_DIR).mkdir(exist_ok=True)
    logger.info(f"Папка для медиа: {MEDIA_OUTPUT_DIR}")

    try:
        with open(KNOWLEDGE_BASE_JSON, 'r', encoding='utf-8') as f:
            kb_data = json.load(f)
    except FileNotFoundError:
        logger.error(f"Файл {KNOWLEDGE_BASE_JSON} не найден")
        return {}
    except json.JSONDecodeError:
        logger.error(f"Ошибка парсинга JSON")
        return {}

    message_ids_to_fetch = {}

    answers = kb_data.get('answers', [])
    logger.info(f"Обработка {len(answers)} ответов...")

    for answer in answers:
        answer_id = answer.get('id')
        visual_path = answer.get('visual_path')

        msg_ids = parse_visual_path(visual_path)

        if msg_ids:
            for msg_id in msg_ids:
                if msg_id not in message_ids_to_fetch:
                    message_ids_to_fetch[msg_id] = []
                message_ids_to_fetch[msg_id].append(answer_id)

    logger.info(f"Найдено уникальных ID сообщений: {len(message_ids_to_fetch)}")

    if not message_ids_to_fetch:
        logger.warning("Не найдено ID сообщений для выгрузки")
        return {}

    try:
        async with TelegramClient('session_name', TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
            if not await client.is_user_authorized():
                logger.info("Требуется авторизация")
                await client.send_code_request(TELEGRAM_PHONE)
                code = input('Введите код: ')

                try:
                    await client.sign_in(TELEGRAM_PHONE, code)
                except SessionPasswordNeededError:
                    password = input('Введите пароль 2FA: ')
                    await client.sign_in(password=password)

            logger.info("Авторизация успешна")

            try:
                entity = await client.get_entity(CHANNEL_OR_GROUP)
            except Exception as e:
                logger.error(f"Ошибка получения группы: {e}")
                return {}

            downloaded_files = {}
            failed_messages = []

            logger.info(f"Начало выгрузки медиафайлов...")

            for i, (msg_id, answer_ids) in enumerate(message_ids_to_fetch.items(), 1):
                try:
                    message = await client.get_messages(entity, ids=msg_id)

                    if not message:
                        logger.warning(f"Сообщение {msg_id} не найдено")
                        failed_messages.append(msg_id)
                        continue

                    if not message.media:
                        logger.info(f"Сообщение {msg_id} - текстовое (без медиа)")
                        continue

                    media_type = "unknown"
                    file_name = f"{msg_id}"

                    if message.photo:
                        media_type = "photo"
                        file_name = f"{msg_id}.jpg"
                    elif message.document:
                        media_type = "document"
                        original_name = message.document.attributes[0].file_name if hasattr(
                            message.document.attributes[0], 'file_name') else ""
                        file_name = f"{msg_id}_{original_name}" if original_name else f"{msg_id}"
                    elif message.video:
                        media_type = "video"
                        file_name = f"{msg_id}.mp4"
                    elif message.audio:
                        media_type = "audio"
                        file_name = f"{msg_id}.mp3"
                    elif message.voice:
                        media_type = "voice"
                        file_name = f"{msg_id}.ogg"

                    file_path = os.path.join(MEDIA_OUTPUT_DIR, file_name)
                    await client.download_media(message.media, file=file_path)

                    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                    logger.info(
                        f"[{i}/{len(message_ids_to_fetch)}] Сообщение {msg_id} ({media_type}): {file_name} ({file_size} bytes)")

                    downloaded_files[msg_id] = {
                        'type': media_type,
                        'file_name': file_name,
                        'file_size': file_size,
                        'answer_ids': answer_ids
                    }

                except Exception as e:
                    logger.error(f"Ошибка при выгрузке сообщения {msg_id}: {e}")
                    failed_messages.append(msg_id)

            if failed_messages:
                logger.warning(f"Сообщения с ошибками: {failed_messages}")

            return downloaded_files

    except Exception as e:
        logger.error(f"Ошибка подключения: {e}")
        return {}


def save_report(downloaded_files: dict):
    report = {
        'total_files': len(downloaded_files),
        'timestamp': str(asyncio.get_event_loop().time()),
        'files': downloaded_files
    }

    report_path = os.path.join(MEDIA_OUTPUT_DIR, 'media_report.json')
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"Отчет сохранен: {report_path}")


async def main():
    downloaded_files = await export_media_from_telegram()
    save_report(downloaded_files)


if __name__ == "__main__":
    asyncio.run(main())