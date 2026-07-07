from __future__ import annotations

from pathlib import Path

from sersflow.api.services.ownership import OwnershipError, assert_path_owner, registry_owner_for_path
from sersflow.core.io.upload_registry import resolve_uploaded_path, upload_root


def resolve_existing_upload(relative_path: str, *, owner_user_id: str) -> Path:
    assert_path_owner(owner_user_id, relative_path)
    root = upload_root()
    p = resolve_uploaded_path(root, relative_path)
    if not p.exists():
        raise FileNotFoundError(relative_path)
    return p


def resolve_existing_upload_or_missing(relative_path: str, *, owner_user_id: str) -> Path | None:
    """Like resolve_existing_upload but returns None when path is not owned or missing."""
    try:
        return resolve_existing_upload(relative_path, owner_user_id=owner_user_id)
    except (OwnershipError, FileNotFoundError):
        return None
