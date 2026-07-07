from __future__ import annotations

from sersflow.api.data_scope import get_data_scope
from sersflow.api.middleware.auth import auth_disabled


def has_global_access(user_id: str) -> bool:
    """True when the request may read/write across all users' data."""
    if auth_disabled():
        return True
    scope = get_data_scope()
    if scope is None:
        from sersflow.infra.auth_store import is_superuser

        return is_superuser(user_id)
    return scope.view_all


def resolve_owner_user_id(passed_user_id: str) -> str:
    """Owner id used for scoped reads/writes (respects superuser act-as)."""
    scope = get_data_scope()
    if scope is None or scope.view_all:
        return passed_user_id
    return scope.owner_user_id
