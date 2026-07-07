from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

from starlette.requests import Request

ACT_AS_COOKIE = "sersflow_act_as"
ACT_AS_ALL = "all"

_scope: ContextVar[DataScope | None] = ContextVar("data_scope", default=None)


@dataclass(frozen=True)
class DataScope:
    actor_user_id: str
    owner_user_id: str
    view_all: bool
    is_superuser: bool
    act_as_label: str


def set_data_scope(scope: DataScope) -> Token:
    return _scope.set(scope)


def reset_data_scope(token: Token) -> None:
    _scope.reset(token)


def get_data_scope() -> DataScope | None:
    return _scope.get()


def resolve_data_scope(request: Request) -> DataScope:
    from sersflow.api.middleware.auth import DEV_USER_ID, auth_disabled
    from sersflow.infra.auth_store import get_user_by_id, get_user_by_username

    actor_id = str(getattr(request.state, "user_id", "") or "")
    if auth_disabled():
        return DataScope(
            actor_user_id=actor_id or DEV_USER_ID,
            owner_user_id=actor_id or DEV_USER_ID,
            view_all=True,
            is_superuser=True,
            act_as_label=ACT_AS_ALL,
        )

    actor = get_user_by_id(actor_id)
    if actor is None or not actor.is_superuser:
        return DataScope(
            actor_user_id=actor_id,
            owner_user_id=actor_id,
            view_all=False,
            is_superuser=False,
            act_as_label=actor.username if actor else actor_id,
        )

    raw = (request.cookies.get(ACT_AS_COOKIE) or ACT_AS_ALL).strip()
    if not raw or raw == ACT_AS_ALL:
        return DataScope(
            actor_user_id=actor_id,
            owner_user_id=actor_id,
            view_all=True,
            is_superuser=True,
            act_as_label=ACT_AS_ALL,
        )

    target = get_user_by_id(raw) or get_user_by_username(raw)
    if target is None:
        return DataScope(
            actor_user_id=actor_id,
            owner_user_id=actor_id,
            view_all=True,
            is_superuser=True,
            act_as_label=ACT_AS_ALL,
        )

    return DataScope(
        actor_user_id=actor_id,
        owner_user_id=target.user_id,
        view_all=False,
        is_superuser=True,
        act_as_label=target.username,
    )
