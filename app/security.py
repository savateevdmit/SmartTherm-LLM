import secrets
import time
import sqlite3
from dataclasses import dataclass
from typing import Optional, Dict, Any
import os

from passlib.context import CryptContext
from app.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

MIN_PASSWORD_CHARS = 8
MAX_PASSWORD_CHARS = 1024


def password_length_ok(password: str) -> tuple[bool, str]:
    if password is None:
        return False, "Пароль обязателен."
    if len(password) < MIN_PASSWORD_CHARS:
        return False, f"Пароль должен быть не короче {MIN_PASSWORD_CHARS} символов."
    if len(password) > MAX_PASSWORD_CHARS:
        return False, f"Пароль слишком длинный (>{MAX_PASSWORD_CHARS} символов)."
    return True, ""


def hash_password(password: str) -> str:
    ok, err = password_length_ok(password)
    if not ok:
        raise ValueError(err)
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if password is None:
            return False
        if len(password) > MAX_PASSWORD_CHARS:
            return False
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


@dataclass
class SessionData:
    admin_id: int
    username: str
    role: str
    issued_at: int


def now_ts() -> int:
    return int(time.time())


def get_cookie_name() -> str:
    return settings.session_cookie_name


class SqliteSessionStore:
    """
    Cookie token -> session data stored in local sqlite.
    Pros: survives restart, works with multiple workers (same DB file), simple.
    """
    def __init__(self, path: str = "sessions.sqlite3"):

        DEFAULT_SESSIONS_DB = os.getenv("SESSIONS_DB_PATH", "sessions.sqlite3")
        self.path = DEFAULT_SESSIONS_DB
        self._init_db()

    def _conn(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  token TEXT PRIMARY KEY,
                  admin_id INTEGER NOT NULL,
                  username TEXT NOT NULL,
                  role TEXT NOT NULL,
                  issued_at INTEGER NOT NULL,
                  csrf TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_admin_id ON sessions(admin_id)")
            conn.commit()
        finally:
            conn.close()

    def create(self, session: SessionData) -> str:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO sessions(token, admin_id, username, role, issued_at, csrf) VALUES (?,?,?,?,?,?)",
                (token, session.admin_id, session.username, session.role, session.issued_at, csrf),
            )
            conn.commit()
        finally:
            conn.close()
        return token

    def get(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            conn.close()

    def delete(self, token: str) -> None:
        if not token:
            return
        conn = self._conn()
        try:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
        finally:
            conn.close()

    def rotate_csrf(self, token: str) -> str:
        if not token:
            return ""
        csrf = secrets.token_urlsafe(32)
        conn = self._conn()
        try:
            conn.execute("UPDATE sessions SET csrf = ? WHERE token = ?", (csrf, token))
            conn.commit()
        finally:
            conn.close()
        return csrf


sessions = SqliteSessionStore()