from typing import Optional, Dict, Any
from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.security import sessions, get_cookie_name
from app.models import Admin
from app.config import settings


def _base_path() -> str:
    return (settings.root_path or "").rstrip("/")


def _u(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{_base_path()}{path}"


def get_session(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get(get_cookie_name(), "")
    if not token:
        return None
    return sessions.get(token)


def redirect_to_login(next_url: str = "/questions") -> RedirectResponse:
    return RedirectResponse(url=_u(f"/login?next={_u(next_url)}"), status_code=303)


def require_login(request: Request) -> Dict[str, Any]:
    sess = get_session(request)
    if not sess:
        raise NotAuthenticated()
    return sess


def require_role(request: Request, role: str) -> Dict[str, Any]:
    sess = require_login(request)
    if sess.get("role") != role:
        raise Forbidden()
    return sess


def get_current_admin(db: Session, request: Request) -> Optional[Admin]:
    sess = get_session(request)
    if not sess:
        return None
    return db.get(Admin, sess["admin_id"])


def require_csrf(sess: Dict[str, Any], form_csrf: str) -> None:
    if not form_csrf or form_csrf != sess.get("csrf"):
        raise BadRequest("Ошибка CSRF. Обновите страницу и попробуйте снова")


class NotAuthenticated(Exception):
    pass


class Forbidden(Exception):
    pass


class BadRequest(Exception):
    def __init__(self, message: str):
        self.message = message