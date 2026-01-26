import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response, RedirectResponse, PlainTextResponse

from app.deps import NotAuthenticated, Forbidden, BadRequest

log = logging.getLogger("kb_admin")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp: Response = await call_next(request)

        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "base-uri 'self'; "
            "frame-ancestors 'none';"
        )
        return resp


class AppErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except NotAuthenticated:
            return RedirectResponse(url="/login", status_code=303)
        except Forbidden:
            return PlainTextResponse("Доступ запрещён", status_code=403)
        except BadRequest as e:
            return PlainTextResponse(e.message, status_code=400)
        except Exception as e:
            log.exception("Unhandled error on %s %s", request.method, request.url.path)
            return PlainTextResponse("Внутренняя ошибка сервера", status_code=500)