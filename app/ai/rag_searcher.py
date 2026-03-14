import os
import json
from typing import List, Any

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.embeddings import encode_question_embedding
from app.ai.types import RagHit


def _get_int(name: str, default: int) -> int:
    v = os.getenv(name, "").strip()
    return int(v) if v else default


RAG_TOP_K = _get_int("RAG_TOP_K", 3)


def _parse_visual_path(vp: Any) -> List[int]:
    """
    MySQL JSON column may be returned as:
    - list[int]
    - JSON string like "[10254, 20043]"
    """
    if vp is None:
        return []

    if isinstance(vp, str):
        try:
            vp = json.loads(vp)
        except Exception:
            return []

    if not isinstance(vp, list):
        return []

    out: List[int] = []
    for x in vp:
        try:
            out.append(int(x))
        except Exception:
            pass
    return out


class RagSearcher:
    def __init__(self, db: Session):
        self.db = db

    def search(self, query_text: str, top_k: int = RAG_TOP_K) -> List[RagHit]:
        emb = encode_question_embedding(query_text)
        if not emb:
            return []

        emb_json = json.dumps(emb, separators=(",", ":"))

        sql = sql_text(
            """
            SELECT
              a.id AS answer_id,
              q.id AS question_id,
              q.text AS question_text,
              a.text AS answer_text,
              COALESCE(VEC_DISTANCE(q.embedding, VEC_FromText(:emb_json)), 999) AS dist,
              a.visual_path AS visual_path
            FROM questions q
            JOIN answers a ON a.question_id = q.id
            ORDER BY dist ASC
            LIMIT :top_k
            """
        )

        rows = self.db.execute(sql, {"emb_json": emb_json, "top_k": top_k}).mappings().all()

        hits: List[RagHit] = []
        for r in rows:
            media_ids = _parse_visual_path(r.get("visual_path"))

            hits.append(
                RagHit(
                    answer_id=int(r["answer_id"]),
                    question_id=int(r["question_id"]),
                    question_text=r["question_text"],
                    answer_text=r["answer_text"],
                    dist=float(r["dist"]),
                    media_ids=media_ids,
                )
            )

        return hits