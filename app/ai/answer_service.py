import os
import logging
from typing import List

from sqlalchemy.orm import Session

from app.ai.rag_searcher import RagSearcher
from app.ai.telegram_cleaner import TelegramCleaner
from app.ai.types import AnswerResult, RagHit
from app.ai.prompts import (
    SYSTEM_PROMPT_TEMPLATE,
    PID_GUIDE_TEXT,
    PID_SECTION_TEMPLATE,
    PID_KEYWORDS,
)
from app.ai.llm_client import chat_completion

log = logging.getLogger("kb_admin")


def _get_float(name: str, default: float) -> float:
    v = os.getenv(name, "").strip()
    return float(v) if v else default


def _get_int(name: str, default: int) -> int:
    v = os.getenv(name, "").strip()
    return int(v) if v else default


RELEVANCE_THRESHOLD = _get_float("RAG_RELEVANCE_THRESHOLD", 0.55)

RAG_TOP_K = _get_int("RAG_TOP_K", 10)

NOT_FOUND_MESSAGE = (
    "Извините, но в этой теме я пока что плохо разбираюсь."
    "Скоро обязательно изучу! \n\n"
    "Если вопрос срочный, попробуйте переформулировать или загляните в группу поддержки SmartTherm в Telegram - https://t.me/smartTherm"
)


def _is_pid_question(q: str) -> bool:
    if not q:
        return False
    ql = q.lower()
    for kw in PID_KEYWORDS:
        kw_norm = kw.strip().lower()
        if kw_norm and kw_norm in ql:
            return True
    return False


class AnswerService:
    def __init__(self, db: Session):
        self.db = db

    def generate(self, user_query: str) -> AnswerResult:
        rag = RagSearcher(self.db)

        hits: List[RagHit] = rag.search(user_query, top_k=RAG_TOP_K)
        min_dist = float(hits[0].dist) if hits else 999.0
        is_relevant = bool(hits) and min_dist < RELEVANCE_THRESHOLD

        log.info(
            "RAG: query=%r, top_k=%d, min_dist=%.3f, threshold=%.3f, relevant=%s",
            user_query, RAG_TOP_K, min_dist, RELEVANCE_THRESHOLD, is_relevant,
        )

        if not is_relevant:
            log.info(
                "RAG: min_dist=%.3f >= threshold=%.3f — returning NOT_FOUND",
                min_dist, RELEVANCE_THRESHOLD,
            )
            return AnswerResult(
                answer_text=NOT_FOUND_MESSAGE,
                media_ids=[],
                min_dist=min_dist,
                rag_hits=hits,
                is_relevant=False,
            )

        rag_lines = []
        for i, h in enumerate(hits, 1):
            rag_lines.append(
                f"[#{i}] [Dist: {float(h.dist):.3f}] "
                f"Q{h.question_id}: {h.question_text}\n"
                f"A{h.answer_id}: {h.answer_text}"
            )
        rag_str = "\n\n".join(rag_lines)

        is_pid = _is_pid_question(user_query)
        pid_section = (
            PID_SECTION_TEMPLATE.format(pid_text=PID_GUIDE_TEXT) if is_pid else ""
        )

        system_content = SYSTEM_PROMPT_TEMPLATE.format(
            pid_section=pid_section,
            relevance_threshold=RELEVANCE_THRESHOLD,
        )

        relevance_block = (
            f"RELEVANCE: min_dist={min_dist:.3f}, threshold={RELEVANCE_THRESHOLD:.2f}, "
            f"is_relevant=YES, top_k={len(hits)}"
        )

        user_message_content = (
            f"{relevance_block}\n\n"
            f"KB Findings (top-{len(hits)}, от ближайшего к дальнему):\n{rag_str}\n\n"
            f"User Question:\n{user_query}"
        )

        log.info(
            "LLM INPUT:\n"
            "========== SYSTEM ==========\n%s\n"
            "========== USER ==========\n%s\n"
            "==========================",
            system_content,
            user_message_content,
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