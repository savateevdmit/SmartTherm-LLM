from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class RagHit:
    answer_id: int
    question_id: int
    question_text: str
    answer_text: str
    dist: float
    media_ids: List[int]


@dataclass(frozen=True)
class AnswerResult:
    answer_text: str
    media_ids: List[int]
    min_dist: float
    rag_hits: List[RagHit]
    is_relevant: bool