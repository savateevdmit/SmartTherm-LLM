import os
import asyncio
import logging

from app.infrastructure.logging_setup import setup_logging
from app.infrastructure.redis_queue import dequeue, set_result
from app.infrastructure.telegram_logger import send_log_message
from app.ai.answer_service import AnswerService

log = logging.getLogger("kb_admin")


def _vps_proxy() -> str:
    return (os.getenv("VPS_PROXY", "") or "").strip()


def _format_log(
    username: str,
    question: str,
    answer: str,
    min_dist: float,
    answer_ids: list[int],
    source: str = "telegram",
    tg_username: str = "",
) -> str:
    q = (question or "").strip()
    a = (answer or "").strip()

    if len(q) > 1000:
        q = q[:1000] + "…"
    if len(a) > 3000:
        a = a[:3000] + "…"

    ids_str = ", ".join(map(str, answer_ids)) if answer_ids else "—"

    if source == "web":
        source_label = "Сайт"
        user_label = f"@{tg_username} (через сайт)" if tg_username else f"{username} (через сайт)"
    else:
        source_label = "Telegram"
        user_label = f"@{username}"

    return (
        f"<b>Источник:</b> {source_label}\n"
        f"<b>Пользователь:</b> {user_label}\n"
        f"<b>Вопрос:</b>\n{q}\n\n"
        f"<b>Ответ:</b>\n{a}\n\n"
        f"<b>Номера ответов из БД:</b> {ids_str}\n"
        f"<b>Расстояние до ближайшего вектора:</b> {min_dist:.3f}"
    )


async def main():
    setup_logging()
    log.info("LLM worker started")

    proxy = _vps_proxy()
    if proxy:
        log.info("VPS proxy is configured for worker: %s", proxy)
    else:
        log.info("VPS proxy is not configured for worker (VPS_PROXY is empty)")

    from app.db import init_db
    init_db()

    from app.db_init import check_schema_or_raise
    check_schema_or_raise()

    log.info("Loading embedding model...")
    try:
        from app.embeddings import load_model_on_startup
        load_model_on_startup()
    except Exception as e:
        log.error("Embedding model preload failed: %s — will load lazily.", e)

    log.info("Worker ready, waiting for tasks...")
    from app.db import SessionLocal

    while True:
        task = dequeue(block_seconds=5)
        if not task:
            await asyncio.sleep(0.1)
            continue

        task_id = task.get("task_id", "")
        user = task.get("user") or {}
        username = user.get("username") or "unknown"
        text = task.get("text") or ""
        source = task.get("source") or "telegram"
        tg_username = task.get("tg_username") or ""

        try:
            db = SessionLocal()
            try:
                svc = AnswerService(db)
                result = svc.generate(text)
            finally:
                db.close()

            set_result(
                task_id,
                {
                    "answer_text": result.answer_text,
                    "media_ids": result.media_ids,
                    "min_dist": result.min_dist,
                    "is_relevant": result.is_relevant,
                },
                ttl_seconds=900,
            )

            answer_ids = [h.question_id for h in (result.rag_hits or [])]

            await send_log_message(
                _format_log(
                    username, text, result.answer_text, result.min_dist, answer_ids,
                    source=source, tg_username=tg_username,
                ),
                media_ids=result.media_ids,
            )
            log.info("Task done task_id=%s user=%s", task_id, username)

        except Exception:
            log.exception("Task failed task_id=%s", task_id)
            set_result(task_id, {"error": "internal_error"}, ttl_seconds=300)


if __name__ == "__main__":
    asyncio.run(main())