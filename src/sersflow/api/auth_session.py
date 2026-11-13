from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


COOKIE_NAME = "sersflow_session"


def _secret() -> bytes:
    raw = os.environ.get("SERSFLOW_AUTH_SECRET", "").strip()
    if not raw:
        if os.environ.get("SERSFLOW_AUTH_DISABLED", "0").strip().lower() in {"1", "true", "yes", "y"}:
            return b"sersflow-dev-auth-secret"
        raise RuntimeError("SERSFLOW_AUTH_SECRET is required when auth is enabled")
    return raw.encode("utf-8")


def session_ttl_seconds() -> int:
    hours = float(os.environ.get("SERSFLOW_SESSION_TTL_HOURS", "168"))
    return max(60, int(hours * 3600))


def sign_session(*, user_id: str, version: int = 0) -> str:
    """``version`` is the user's ``session_version`` at login; the middleware rejects the cookie once it changes."""
    now = int(time.time())
    payload = {"user_id": user_id, "exp": now + session_ttl_seconds(), "iat": now, "ver": int(version)}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_session(token: str | None) -> str | None:
    """User id of a correctly signed, unexpired token (signature / expiry only; see ``verify_session_claims``)."""
    claims = verify_session_claims(token)
    return claims[0] if claims else None


def verify_session_claims(token: str | None) -> tuple[str, int] | None:
    """(user_id, session version) of a correctly signed, unexpired token. Tokens from before versions count as 0."""
    if not token:
        return None
    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    body, sig = parts
    expected = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(body.encode("ascii")).decode("utf-8"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None
    user_id = str(payload.get("user_id") or "").strip()
    exp = int(payload.get("exp") or 0)
    if not user_id or exp < int(time.time()):
        return None
    try:
        version = int(payload.get("ver") or 0)
    except (TypeError, ValueError):
        return None
    return user_id, version


def cookie_secure(request: Any = None) -> bool:
    """
    Whether to mark cookies ``Secure``.

    ``SERSFLOW_COOKIE_SECURE=1`` forces it; ``=0`` forbids it. Unset (the default) it follows the request: Secure
    when the browser reached us over HTTPS (directly, or through a proxy that sets ``X-Forwarded-Proto``). A plain
    http client on the loopback interface (the MCP server) still gets a cookie it can send back.
    """
    raw = os.environ.get("SERSFLOW_COOKIE_SECURE", "").strip().lower()
    if raw in {"1", "true", "yes", "y"}:
        return True
    if raw in {"0", "false", "no", "n"} or request is None:
        return False
    try:
        forwarded = str(request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
        return forwarded == "https" or str(request.url.scheme).lower() == "https"
    except Exception:  # noqa: BLE001 - never fail a login over a header
        return False


_WEAK_SECRET_WARNED = False


def warn_if_weak_secret() -> None:
    """Log once at startup when the signing secret is short enough to be guessable."""
    global _WEAK_SECRET_WARNED
    raw = os.environ.get("SERSFLOW_AUTH_SECRET", "").strip()
    if raw and len(raw) < 32 and not _WEAK_SECRET_WARNED:
        _WEAK_SECRET_WARNED = True
        import logging

        logging.getLogger(__name__).warning(
            "SERSFLOW_AUTH_SECRET is only %d characters; use at least 32 random characters "
            "(python -c \"import secrets; print(secrets.token_urlsafe(48))\"). "
            "Changing it signs everyone out.",
            len(raw),
        )
