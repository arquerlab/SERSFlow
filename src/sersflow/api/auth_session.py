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


def sign_session(*, user_id: str) -> str:
    now = int(time.time())
    payload = {"user_id": user_id, "exp": now + session_ttl_seconds(), "iat": now}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_session(token: str | None) -> str | None:
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
    return user_id


def cookie_secure() -> bool:
    return os.environ.get("SERSFLOW_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "y"}
