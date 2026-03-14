import os
import logging
from typing import List

from sqlalchemy.orm import Session

from app.ai.rag_searcher import RagSearcher
from app.ai.telegram_cleaner import TelegramCleaner
from app.ai.types import AnswerResult, RagHit
from app.ai.prompts import USER_GUIDE_TEXT, SYSTEM_PROMPT_TEMPLATE
from app.ai.llm_client import chat_completion

log = logging.getLogger("kb_admin")


def _get_float(name: str, default: float) -> float:
    v = os.getenv(name, "").strip()
    return float(v) if v else default


RELEVANCE_THRESHOLD = _get_float("RAG_RELEVANCE_THRESHOLD", 0.55)


class AnswerService:
    def __init__(self, db: Session):
        self.db = db

    def generate(self, user_query: str) -> AnswerResult:
        rag = RagSearcher(self.db)
        hits: List[RagHit] = rag.search(user_query)

        min_dist = 100.0
        is_relevant = False
        if hits:
            min_dist = float(hits[0].dist)
            is_relevant = min_dist < RELEVANCE_THRESHOLD

        relevance_instruction = ""
        if not is_relevant:
            relevance_instruction = (
                "\n\n!!! ВНИМАНИЕ: Вопрос пользователя не найден в Базе Знаний и имеет высокую семантическую дистанцию. "
                "Высока вероятность ОФТОПИКА. "
                "Если вопрос не касается контроллера SmartTherm, отопления, ESP или Home Assistant — ОТКАЖИСЬ ОТВЕЧАТЬ."
            )

        rag_str = "\n".join([f"Q: {h.question_text}\nA: {h.answer_text}" for h in hits]) if hits else "No matches."

        system_content = SYSTEM_PROMPT_TEMPLATE.format(manual_text=USER_GUIDE_TEXT)
        user_message_content = (
            f"{relevance_instruction}\n"
            f"KB Findings (Min Dist: {min_dist:.2f}):\n{rag_str}\n\n"
            f"User Question:\n{user_query}"
        )

        raw_text = chat_completion(system_content, user_message_content)
        answer_text = TelegramCleaner.format_for_telegram(raw_text)

        media_ids: List[int] = []
        for h in hits[:3]:
            media_ids.extend(h.media_ids)
        media_ids = sorted({int(x) for x in media_ids})

        return AnswerResult(
            answer_text=answer_text,
            media_ids=media_ids,
            min_dist=min_dist,
            rag_hits=hits,
            is_relevant=is_relevant,
        )