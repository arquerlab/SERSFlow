from __future__ import annotations

from pathlib import Path

from sersflow.core.io.upload_registry import resolve_uploaded_path, upload_root


def resolve_existing_upload(relative_path: str) -> Path:
    root = upload_root()
    p = resolve_uploaded_path(root, relative_path)
    if not p.exists():
        raise FileNotFoundError(relative_path)
    return p

