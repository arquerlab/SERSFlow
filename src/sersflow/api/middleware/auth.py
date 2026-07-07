from __future__ import annotations

import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sersflow.api.auth_session import COOKIE_NAME, verify_session

logger = logging.getLogger(__name__)

DEV_USER_ID = "dev"


def auth_disabled() -> bool:
    return os.environ.get("SERSFLOW_AUTH_DISABLED", "0").strip().lower() in {"1", "true", "yes", "y"}


def _is_public_path(path: str, method: str) -> bool:
    if path == "/health" or path == "/favicon.ico":
        return True
    if path == "/" or path == "/preprocess":
        return method == "GET"
    if path.startswith("/static/"):
        return True
    if path in {"/docs", "/openapi.json", "/redoc"}:
        return True
    if path == "/auth/login" and method == "POST":
        return True
    return False


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if auth_disabled():
            request.state.user_id = DEV_USER_ID
            return await call_next(request)

        path = request.url.path
        if _is_public_path(path, request.method):
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        try:
            user_id = verify_session(token)
        except RuntimeError:
            logger.error("Auth misconfiguration: SERSFLOW_AUTH_SECRET is not set")
            return JSONResponse(status_code=500, content={"detail": "Auth is not configured"})

        if user_id is None:
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        request.state.user_id = user_id
        return await call_next(request)
