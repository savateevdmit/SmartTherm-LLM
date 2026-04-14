import os
import json
import time
import logging
from typing import Optional

import redis
from redis.connection import ConnectionPool

log = logging.getLogger("kb_admin")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.getenv("QUEUE_NAME", "smarttherm_llm")

_pool: Optional[ConnectionPool] = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=20,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _pool


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=_get_pool())


def ping_redis() -> bool:
    try:
        get_redis().ping()
        return True
    except Exception as e:
        log.warning("Redis unavailable: %s", e)
        return False


def enqueue(task: dict) -> str:
    task_id = task["task_id"]
    try:
        get_redis().rpush(QUEUE_NAME, json.dumps(task, ensure_ascii=False))
    except redis.RedisError as e:
        log.error("Redis enqueue error: %s", e)
        raise
    return task_id


def queue_length() -> int:
    try:
        return int(get_redis().llen(QUEUE_NAME) or 0)
    except Exception:
        return 0


def dequeue(block_seconds: int = 5) -> Optional[dict]:
    try:
        res = get_redis().blpop(QUEUE_NAME, timeout=block_seconds)
        if not res:
            return None
        _, payload = res
        return json.loads(payload)
    except redis.RedisError as e:
        log.error("Redis dequeue error: %s", e)
        return None


def set_result(task_id: str, result: dict, ttl_seconds: int = 600):
    key = f"result:{task_id}"
    try:
        get_redis().set(key, json.dumps(result, ensure_ascii=False), ex=ttl_seconds)
    except redis.RedisError as e:
        log.error("Redis set_result error for task %s: %s", task_id, e)
        raise


def wait_result(task_id: str, timeout_seconds: int = 120) -> Optional[dict]:
    r = get_redis()
    key = f"result:{task_id}"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            raw = r.get(key)
            if raw:
                return json.loads(raw)
        except redis.RedisError as e:
            log.warning("Redis get error while waiting for %s: %s", task_id, e)
            time.sleep(1)
            continue
        time.sleep(0.25)
    return None