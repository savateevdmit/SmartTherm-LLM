import uuid
import json
import logging
from typing import List, Union

import anyio
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

from app.db import get_db
from app.models import Answer
from app.deps import require_login, require_csrf
from app.validators import validate_question_text, validate_answer_text, parse_tags
from app.embeddings import encode_question_embedding
from app.media import save_images, delete_media_files
from app.infrastructure.redis_queue import enqueue, wait_result, queue_length

log = logging.getLogger("kb_admin")
router = APIRouter(prefix="/api")


class AskRequest(BaseModel):
    user_id: int
    username: str
    text: str
    source: str = "telegram"
    tg_username: str = ""


class AskResponse(BaseModel):
    task_id: str
    queue_position: int = 1
    eta_seconds: int = 30


class ResultResponse(BaseModel):
    status: str
    answer_text: str | None = None
    media_ids: list[int] = []
    min_dist: float | None = None
    is_relevant: bool | None = None
    error: str | None = None


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    task_id = str(uuid.uuid4())
    enqueue(
        {
            "task_id": task_id,
            "user": {"id": req.user_id, "username": req.username},
            "text": req.text,
            "source": req.source or "telegram",
            "tg_username": (req.tg_username or "").strip(),
        }
    )
    qlen = queue_length()
    position = max(qlen, 1)
    return AskResponse(task_id=task_id, queue_position=position, eta_seconds=position * 30)


@router.get("/result/{task_id}", response_model=ResultResponse)
def result(task_id: str):
    res = wait_result(task_id, timeout_seconds=1)
    if not res:
        return ResultResponse(status="pending")

    if res.get("error"):
        return ResultResponse(status="done", error=res.get("error"))

    return ResultResponse(
        status="done",
        answer_text=res.get("answer_text"),
        media_ids=res.get("media_ids") or [],
        min_dist=res.get("min_dist"),
        is_relevant=res.get("is_relevant"),
    )


def _normalize_files(files) -> List[UploadFile]:
    if files is None:
        return []
    lst = files if isinstance(files, list) else [files]
    return [f for f in lst if f and getattr(f, "filename", "")]


def _emb_to_json(emb) -> str | None:
    if emb is None:
        return None
    return json.dumps(emb, ensure_ascii=False, separators=(",", ":"))


async def _embed_with_timeout(text: str, seconds: int = 60):
    with anyio.fail_after(seconds):
        return await anyio.to_thread.run_sync(encode_question_embedding, text)


def _insert_question(db: Session, text_val: str, tags_val, emb) -> int:
    emb_json = _emb_to_json(emb)
    if emb_json is None:
        db.execute(
            sql_text("INSERT INTO questions (text, tags) VALUES (:text, :tags)"),
            {"text": text_val, "tags": tags_val},
        )
    else:
        db.execute(
            sql_text(
                "INSERT INTO questions (text, embedding, tags) "
                "VALUES (:text, VEC_FromText(:emb_json), :tags)"
            ),
            {"text": text_val, "emb_json": emb_json, "tags": tags_val},
        )
    return int(db.execute(sql_text("SELECT LAST_INSERT_ID()")).scalar_one())


@router.post("/questions/create")
async def api_question_create(
    request: Request,
    text: str = Form(...),
    answer_text: str = Form(...),
    tags: str = Form(""),
    csrf: str = Form(""),
    files: Union[UploadFile, List[UploadFile], None] = File(default=None),
    db: Session = Depends(get_db),
):

    try:
        sess = require_login(request)
        require_csrf(sess, csrf)
    except Exception:
        return JSONResponse({"ok": False, "error": "Требуется авторизация или ошибка CSRF."}, status_code=403)

    try:
        text = validate_question_text(text)
        answer_text = validate_answer_text(answer_text)
        tags_csv, _ = parse_tags(tags)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    files_list = _normalize_files(files)
    media_ids: List[int] = []
    if files_list:
        try:
            media_ids = await save_images(files_list)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    try:
        emb = await _embed_with_timeout(text, seconds=60)
    except TimeoutError:
        delete_media_files(media_ids)
        return JSONResponse({"ok": False, "error": "Таймаут генерации embedding (60с)."}, status_code=500)
    except Exception as e:
        delete_media_files(media_ids)
        log.exception("Embedding error on question create (API)")
        return JSONResponse({"ok": False, "error": f"Ошибка embedding: {type(e).__name__}: {e}"}, status_code=500)

    try:
        qid = _insert_question(db, text, tags_csv or None, emb)
        db.add(Answer(question_id=qid, text=answer_text, visual_path=media_ids or None))
        db.commit()
    except Exception:
        log.exception("DB error on question create (API)")
        db.rollback()
        delete_media_files(media_ids)
        return JSONResponse({"ok": False, "error": "Ошибка сохранения в БД."}, status_code=500)

    return JSONResponse({"ok": True, "question_id": qid, "text_preview": text[:80]})