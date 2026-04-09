from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5


def spectrum_id_from_ref(*, relative_path: str, record_index: int | None = None) -> str:
    """
    Create a stable spectrum id from a path-based reference.

    This is deterministic so cached results can be reused across sessions.
    """
    key = f"{relative_path}#{record_index}" if record_index is not None else relative_path
    return f"sp_{uuid5(NAMESPACE_URL, key).hex}"

