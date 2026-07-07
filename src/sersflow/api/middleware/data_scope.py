from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sersflow.api.data_scope import reset_data_scope, resolve_data_scope, set_data_scope


class DataScopeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        scope = resolve_data_scope(request)
        token = set_data_scope(scope)
        try:
            return await call_next(request)
        finally:
            reset_data_scope(token)
