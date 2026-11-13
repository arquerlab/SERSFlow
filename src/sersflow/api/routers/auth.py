from __future__ import annotations

import logging
import threading
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from sersflow.api.auth_session import COOKIE_NAME, cookie_secure, session_ttl_seconds, sign_session
from sersflow.api.data_scope import ACT_AS_ALL, ACT_AS_COOKIE, get_data_scope, resolve_data_scope
from sersflow.api.deps import current_user_id
from sersflow.api.middleware.auth import DEV_USER_ID, auth_disabled
from sersflow.infra.auth_store import (
    UserRecord,
    get_user_by_id,
    get_user_by_username,
    list_users,
    session_state,
    verify_user,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

# Failed-login throttle, per username (requests arrive through one reverse proxy, so the client IP is not usable).
# In-memory: it resets on restart, which is acceptable for slowing down password guessing.
_LOGIN_MAX_FAILURES = 10
_LOGIN_WINDOW_S = 300.0
_login_failures: dict[str, list[float]] = {}
_login_lock = threading.Lock()


def _login_retry_after(username: str) -> int:
    """Seconds until this username may try again (0 when not throttled)."""
    key = username.strip().lower()
    now = time.monotonic()
    with _login_lock:
        recent = [t for t in _login_failures.get(key, []) if now - t < _LOGIN_WINDOW_S]
        if recent:
            _login_failures[key] = recent
        else:
            _login_failures.pop(key, None)
        if len(recent) >= _LOGIN_MAX_FAILURES:
            return max(1, int(_LOGIN_WINDOW_S - (now - recent[0])) + 1)
    return 0


def _record_login_failure(username: str) -> None:
    key = username.strip().lower()
    with _login_lock:
        if len(_login_failures) > 10_000:  # bound memory against made-up usernames
            _login_failures.clear()
        _login_failures.setdefault(key, []).append(time.monotonic())


def _clear_login_failures(username: str) -> None:
    with _login_lock:
        _login_failures.pop(username.strip().lower(), None)


def reset_login_throttle() -> None:
    with _login_lock:
        _login_failures.clear()


def _dev_user() -> UserRecord:
    """Synthetic actor used when SERSFLOW_AUTH_DISABLED is set."""
    return UserRecord(
        user_id=DEV_USER_ID,
        username="dev",
        created_at="",
        is_superuser=True,
    )


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserInfo(BaseModel):
    user_id: str
    username: str
    is_superuser: bool = False


class ActAsState(BaseModel):
    scope: str
    label: str
    user_id: str | None = None


class ActAsRequest(BaseModel):
    scope: Literal["all"] | str = Field(
        description='Use "all" or a username / user_id to view that user\'s data only.',
    )


class UserListItem(BaseModel):
    user_id: str
    username: str
    is_superuser: bool = False


def _user_payload(user) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user": UserInfo(
            user_id=user.user_id,
            username=user.username,
            is_superuser=user.is_superuser,
        ).model_dump(),
    }
    if not user.is_superuser:
        return payload
    scope = get_data_scope()
    if scope is None or scope.view_all:
        payload["act_as"] = ActAsState(scope=ACT_AS_ALL, label="All users").model_dump()
    else:
        target = get_user_by_id(scope.owner_user_id)
        label = target.username if target else scope.owner_user_id
        payload["act_as"] = ActAsState(
            scope=scope.owner_user_id,
            label=label,
            user_id=scope.owner_user_id,
        ).model_dump()
    return payload


def _require_superuser(request: Request):
    if auth_disabled():
        return _dev_user()
    actor_id = current_user_id(request)
    actor = get_user_by_id(actor_id)
    if actor is None or not actor.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser required")
    return actor


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    if auth_disabled():
        # Open mode: no credentials required; UI/API treat the actor as synthetic dev.
        return _user_payload(_dev_user())
    wait_s = _login_retry_after(payload.username)
    if wait_s:
        raise HTTPException(
            status_code=429,
            detail="Too many failed sign-in attempts for this user. Try again later.",
            headers={"Retry-After": str(wait_s)},
        )
    user = verify_user(username=payload.username, password=payload.password)
    if user is None:
        _record_login_failure(payload.username)
        logger.warning("failed sign-in for username %r", payload.username.strip()[:64])
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _clear_login_failures(payload.username)
    state = session_state(user.user_id)
    token = sign_session(user_id=user.user_id, version=state[0] if state else 0)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
        max_age=session_ttl_seconds(),
        path="/",
    )
    if user.is_superuser:
        response.set_cookie(
            key=ACT_AS_COOKIE,
            value=ACT_AS_ALL,
            httponly=True,
            samesite="lax",
            secure=cookie_secure(request),
            max_age=60 * 60 * 24 * 30,
            path="/",
        )
    return _user_payload(user)


@router.post("/logout")
def logout(response: Response, request: Request) -> dict[str, bool]:
    _ = current_user_id(request)
    response.delete_cookie(key=COOKIE_NAME, path="/")
    response.delete_cookie(key=ACT_AS_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    if auth_disabled():
        return _user_payload(_dev_user())
    user_id = current_user_id(request)
    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _user_payload(user)


@router.get("/users", response_model=list[UserListItem])
def users_endpoint(request: Request) -> list[UserListItem]:
    _require_superuser(request)
    return [
        UserListItem(user_id=u.user_id, username=u.username, is_superuser=u.is_superuser)
        for u in list_users()
    ]


@router.get("/act-as", response_model=ActAsState)
def get_act_as(request: Request) -> ActAsState:
    _require_superuser(request)
    scope = resolve_data_scope(request)
    if scope.view_all:
        return ActAsState(scope=ACT_AS_ALL, label="All users")
    target = get_user_by_id(scope.owner_user_id)
    label = target.username if target else scope.owner_user_id
    return ActAsState(scope=scope.owner_user_id, label=label, user_id=scope.owner_user_id)


@router.post("/act-as", response_model=ActAsState)
def set_act_as(payload: ActAsRequest, request: Request, response: Response) -> ActAsState:
    _require_superuser(request)
    raw = payload.scope.strip()
    if not raw or raw == ACT_AS_ALL:
        cookie_value = ACT_AS_ALL
        label = "All users"
        scope_value = ACT_AS_ALL
        user_id = None
    else:
        target = get_user_by_id(raw) or get_user_by_username(raw)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        cookie_value = target.user_id
        label = target.username
        scope_value = target.user_id
        user_id = target.user_id
    response.set_cookie(
        key=ACT_AS_COOKIE,
        value=cookie_value,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
        max_age=60 * 60 * 24 * 30,
        path="/",
    )
    return ActAsState(scope=scope_value, label=label, user_id=user_id)
