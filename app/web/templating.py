from fastapi.templating import Jinja2Templates
from app.config import settings

templates = Jinja2Templates(directory="app/templates")


def _base_path() -> str:
    return settings.root_path or ""


def _url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{_base_path()}{path}"


def _media_url(name) -> str:
    if name is None:
        return ""
    try:
        num = int(name)
    except Exception:
        return ""
    return _url(f"/media/{num}.jpg")


templates.env.globals["url"] = _url
templates.env.globals["media_url"] = _media_url
templates.env.globals["app_settings"] = settings