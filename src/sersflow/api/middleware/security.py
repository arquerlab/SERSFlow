"""Response headers and an optional same-origin check for state-changing requests."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def allowed_origins() -> frozenset[str]:
    """
    ``SERSFLOW_ALLOWED_ORIGINS``: comma-separated origins (``https://host[:port]``) the UI is served from.

    When set, a browser request that changes state must carry one of them in its ``Origin`` header. Unset (the
    default) nothing is enforced: behind a reverse proxy the public origin cannot be derived reliably, and the
    session cookie is already ``SameSite=Lax``. Requests without an ``Origin`` header (API clients, the MCP
    server) are never blocked.
    """
    raw = os.environ.get("SERSFLOW_ALLOWED_ORIGINS", "")
    return frozenset(o.strip().rstrip("/").lower() for o in raw.split(",") if o.strip())


def _origin_of(value: str) -> str:
    parts = urlsplit(value.strip())
    if not parts.scheme or not parts.netloc:
        return value.strip().rstrip("/").lower()
    return f"{parts.scheme}://{parts.netloc}".lower()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            allowed = allowed_origins()
            if origin and allowed and _origin_of(origin) not in allowed:
                return JSONResponse(status_code=403, content={"detail": "Cross-origin request refused"})

        response = await call_next(request)
        # Do not let another site frame the UI (clickjacking) or a browser guess content types.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
