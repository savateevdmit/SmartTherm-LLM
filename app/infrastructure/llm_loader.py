import asyncio
import http.client
import json
import logging
import os
import socket
import threading
import time
from typing import Any, Optional

log = logging.getLogger("kb_admin")

def _lazy_mode() -> bool:
    v = (os.getenv("LLM_LAZY_LOAD", "0") or "0").strip().lower()
    return v in ("1", "true", "yes", "on")

def _idle_timeout() -> float:
    v = (os.getenv("LLM_IDLE_UNLOAD_SECONDS", "300") or "300").strip()
    try:
        return max(1.0, float(v))
    except ValueError:
        return 300.0

def _container_name() -> str:
    return (os.getenv("LLM_CONTAINER_NAME", "smarttherm-llama") or "smarttherm-llama").strip()

def _start_timeout() -> int:
    v = (os.getenv("LLM_CONTAINER_START_TIMEOUT", "120") or "120").strip()
    try:
        return max(10, int(v))
    except ValueError:
        return 120

def _server_url() -> str:
    return (os.getenv("LLM_SERVER_URL", "http://llama:8080") or "http://llama:8080").rstrip("/")

def _health_url() -> str:
    return f"{_server_url()}/health"

def _docker_sock() -> str:
    return "/var/run/docker.sock"

def _nvidia_smi_info() -> str:
    import subprocess
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=10)
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        return out if out else (err or "nvidia-smi: нет вывода")
    except FileNotFoundError:
        return "nvidia-smi: утилита не найдена"
    except Exception as e:
        return f"nvidia-smi: ошибка запуска — {e}"

class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str):
        super().__init__("localhost")
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)

def _docker_request(method: str, path: str, payload: Optional[dict[str, Any]] = None):
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    conn = _UnixHTTPConnection(_docker_sock())
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        text = raw.decode("utf-8", errors="replace") if raw else ""
        content_type = resp.getheader("Content-Type", "")

        if resp.status >= 400:
            if resp.status == 404:
                raise RuntimeError(f"Container not found (404): {text}")
            if resp.status != 304: # 304 means already started/stopped
                raise RuntimeError(f"Docker API {method} {path} failed: {resp.status} {text}")

        if "application/json" in content_type and text:
            return resp.status, json.loads(text)
        return resp.status, text
    finally:
        conn.close()

def _get_container_state(name: str) -> dict:
    status, data = _docker_request("GET", f"/containers/{name}/json")
    return data.get("State") or {}

def _start_container(name: str) -> None:
    log.info("[LLMLoader] Sending POST /containers/%s/start", name)
    status, _ = _docker_request("POST", f"/containers/{name}/start")
    if status == 304:
        log.info("[LLMLoader] Container %s already started.", name)

def _stop_container(name: str) -> None:
    log.info("[LLMLoader] Sending POST /containers/%s/stop", name)
    status, _ = _docker_request("POST", f"/containers/{name}/stop?t=15")
    if status == 304:
        log.info("[LLMLoader] Container %s already stopped.", name)

def _wait_healthy(timeout: int) -> None:
    import requests
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = requests.get(_health_url(), timeout=5)
            if r.status_code == 200:
                log.info("[LLMLoader] llama-server /health OK.")
                return
        except Exception as e:
            last_exc = e
        time.sleep(2)
    raise RuntimeError(f"llama-server did not become healthy in {timeout}s: {last_exc}")

async def _notify_error(context: str, error: Exception) -> None:
    from app.infrastructure.telegram_logger import send_log_message
    gpu_info = _nvidia_smi_info()
    text = (
        f"<b>Ошибка загрузки модели: {context}</b>\n\n"
        f"<code>{type(error).__name__}: {error}</code>\n\n"
        f"<b>nvidia-smi:</b>\n<pre>{gpu_info[:2500]}</pre>"
    )
    try:
        await send_log_message(text)
    except Exception as notify_exc:
        log.error("Failed to send TG error notification: %s", notify_exc)

class _LLMLoader:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_used = 0.0
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop_watchdog = threading.Event()

    def startup(self) -> None:
        if not _lazy_mode():
            log.info("[LLMLoader] Eager mode — llama container always running.")
            return

        name = _container_name()
        log.info("[LLMLoader] Lazy mode ON — container '%s' starts on demand, stops after %.0fs idle.", name, _idle_timeout())

        try:
            state = _get_container_state(name)
            if state.get("Running"):
                log.info("[LLMLoader] Container '%s' is running. Stopping it for lazy mode...", name)
                _stop_container(name)
                log.info("[LLMLoader] Container stopped. VRAM is free.")
        except Exception as e:
            log.error("[LLMLoader] startup preparation failed: %s", e)
            self._schedule_notify("startup prepare", e)
            raise

        self._start_watchdog()

    def ensure_loaded_sync(self) -> None:
        if not _lazy_mode():
            return

        with self._lock:
            name = _container_name()
            state = _get_container_state(name)
            if not state.get("Running"):
                self._do_start(name)
            self._last_used = time.monotonic()

    async def ensure_loaded_async(self) -> None:
        await asyncio.to_thread(self.ensure_loaded_sync)

    def keep_alive(self) -> None:
        self._last_used = time.monotonic()

    def _do_start(self, name: str) -> None:
        timeout = _start_timeout()
        log.info("[LLMLoader] Starting container '%s' on demand...", name)
        try:
            _start_container(name)
            log.info("[LLMLoader] Container started. Waiting for /health...")
            _wait_healthy(timeout)
            self._last_used = time.monotonic()
            log.info("[LLMLoader] Container ready for requests.")
        except Exception as e:
            log.error("[LLMLoader] Failed to start container '%s': %s", name, e)
            self._schedule_notify("lazy start container", e)
            raise

    def _do_stop(self, name: str) -> None:
        log.info("[LLMLoader] Stopping container '%s' after idle timeout...", name)
        try:
            _stop_container(name)
            log.info("[LLMLoader] Container stopped, VRAM freed.")
        except Exception as e:
            log.error("[LLMLoader] Failed to stop container '%s': %s", name, e)
            self._schedule_notify("idle stop container", e)

    def _schedule_notify(self, context: str, error: Exception) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_notify_error(context, error))
        except RuntimeError:
            def _run():
                asyncio.run(_notify_error(context, error))
            threading.Thread(target=_run, daemon=True).start()

    def _start_watchdog(self) -> None:
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        self._stop_watchdog.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="llm-watchdog",
        )
        self._watchdog_thread.start()
        log.info("[LLMLoader] Watchdog started (idle=%.0fs).", _idle_timeout())

    def _watchdog_loop(self) -> None:
        while not self._stop_watchdog.is_set():
            time.sleep(5)
            with self._lock:
                name = _container_name()
                try:
                    state = _get_container_state(name)
                    if not state.get("Running"):
                        continue
                except Exception:
                    continue

                idle = time.monotonic() - self._last_used
                if idle >= _idle_timeout():
                    log.info("[LLMLoader] Idle %.0fs >= %.0fs — stopping container.", idle, _idle_timeout())
                    self._do_stop(name)

_loader = _LLMLoader()

def startup() -> None:
    _loader.startup()

def ensure_loaded() -> None:
    _loader.ensure_loaded_sync()

async def ensure_loaded_async() -> None:
    await _loader.ensure_loaded_async()

def keep_alive() -> None:
    _loader.keep_alive()