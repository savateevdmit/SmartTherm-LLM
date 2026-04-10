import uuid
from fastapi import APIRouter
from pydantic import BaseModel

from app.infrastructure.redis_queue import enqueue, wait_result, queue_length

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