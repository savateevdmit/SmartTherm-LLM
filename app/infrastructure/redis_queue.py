import os
import json
import time
from typing import Any, Optional

import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.getenv("QUEUE_NAME", "smarttherm_llm")


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def enqueue(task: dict) -> str:
    r = get_redis()
    task_id = task["task_id"]
    r.rpush(QUEUE_NAME, json.dumps(task, ensure_ascii=False))
    return task_id

def queue_length() -> int:
    r = get_redis()
    try:
        return int(r.llen(QUEUE_NAME) or 0)
    except Exception:
        return 0

def dequeue(block_seconds: int = 5) -> Optional[dict]:
    r = get_redis()
    res = r.blpop(QUEUE_NAME, timeout=block_seconds)
    if not res:
        return None
    _, payload = res
    return json.loads(payload)


def set_result(task_id: str, result: dict, ttl_seconds: int = 600):
    r = get_redis()
    key = f"result:{task_id}"
    r.set(key, json.dumps(result, ensure_ascii=False), ex=ttl_seconds)


def wait_result(task_id: str, timeout_seconds: int = 120) -> Optional[dict]:
    r = get_redis()
    key = f"result:{task_id}"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        raw = r.get(key)
        if raw:
            return json.loads(raw)
        time.sleep(0.25)
    return None