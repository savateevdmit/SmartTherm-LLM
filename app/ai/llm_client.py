import os
import time
import logging
import requests

log = logging.getLogger("kb_admin")


def _server_url() -> str:
    url = os.getenv("LLM_SERVER_URL", "").strip()
    if not url:
        raise RuntimeError("LLM_SERVER_URL is not set (expected e.g. http://127.0.0.1:8080)")
    return url.rstrip("/")


def _get_int(name: str, default: int) -> int:
    v = os.getenv(name, "").strip()
    return int(v) if v else default


def _get_float(name: str, default: float) -> float:
    v = os.getenv(name, "").strip()
    return float(v) if v else default


def chat_completion(system: str, user: str) -> str:
    from app.infrastructure.llm_loader import ensure_loaded, keep_alive

    ensure_loaded()

    url = f"{_server_url()}/v1/chat/completions"

    seed = _get_int("LLM_SEED", 42)
    temperature = _get_float("LLM_TEMPERATURE", 0.0)
    top_p = _get_float("LLM_TOP_P", 1.0)
    max_tokens = _get_int("LLM_MAX_TOKENS", 4096)
    retries = _get_int("LLM_RETRIES", 5)
    backoff_base = _get_float("LLM_RETRY_BACKOFF_SEC", 1.0)
    timeout = _get_int("LLM_TIMEOUT", 900)

    payload = {
        "model": "local-model",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stream": False,
        "seed": seed,
    }

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)

            if r.status_code in (429, 503, 502, 504):
                raise requests.HTTPError(f"{r.status_code} from LLM server", response=r)

            r.raise_for_status()
            data = r.json()
            result = data["choices"][0]["message"]["content"]
            keep_alive()
            return result

        except Exception as e:
            last_exc = e
            wait = backoff_base * attempt
            log.warning(
                "LLM request failed (attempt %s/%s): %s. Sleeping %.1fs",
                attempt,
                retries,
                e,
                wait,
            )
            time.sleep(wait)

    raise RuntimeError(f"LLM server unavailable after {retries} retries: {last_exc}")