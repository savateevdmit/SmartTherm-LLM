import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _get_int(name: str, default: int) -> int:
    v = os.getenv(name, "").strip()
    return int(v) if v else default


def _get_optional_int(name: str):
    v = os.getenv(name, "").strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _get_bool01(name: str, default: bool) -> bool:
    v = os.getenv(name, "").strip()
    if not v:
        return default
    return v in ("1", "true", "True", "yes", "YES", "on", "ON")


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("DB_HOST", "127.0.0.1")
    db_port: int = _get_int("DB_PORT", 3307)
    db_user: str = os.getenv("DB_USER", "root")
    db_password: str = os.getenv("DB_PASSWORD", "")
    db_name: str = os.getenv("DB_NAME", "")

    secret_key: str = os.getenv("APP_SECRET_KEY", "change-me")
    session_cookie_name: str = os.getenv("SESSION_COOKIE_NAME", "kb_admin_session")
    cookie_secure: bool = _get_bool01("COOKIE_SECURE", False)

    root_path: str = os.getenv("ROOT_PATH", "").rstrip("/")

    media_dir: str = os.getenv("MEDIA_DIR", "../media")
    max_upload_mb: int = _get_int("MAX_UPLOAD_MB", 15)

    hf_token: str = os.getenv("HF_TOKEN", "").strip()

    embed_model_id: str = os.getenv("EMBED_MODEL_ID", "google/embeddinggemma-300m")
    embed_device: str = os.getenv("EMBED_DEVICE", "cpu")
    embed_truncate_dim: int | None = _get_optional_int("EMBED_TRUNCATE_DIM")

    llm_lazy_load: bool = _get_bool01("LLM_LAZY_LOAD", False)
    llm_idle_unload_seconds: int = _get_int("LLM_IDLE_UNLOAD_SECONDS", 300)


settings = Settings()