"""Size limits for data a user sends to the server (uploads, package imports)."""

from __future__ import annotations

import os
from typing import BinaryIO

_CHUNK = 1024 * 1024


class PayloadTooLarge(ValueError):
    """Raised when an upload or an archive member exceeds the configured limit."""


def max_upload_bytes() -> int:
    """Largest single file accepted, from ``SERSFLOW_MAX_UPLOAD_MB`` (default 2048 MB; 0 disables the limit)."""
    raw = (os.environ.get("SERSFLOW_MAX_UPLOAD_MB") or "").strip()
    try:
        mb = float(raw) if raw else 2048.0
    except ValueError:
        mb = 2048.0
    return int(mb * 1024 * 1024) if mb > 0 else 0


def _too_large(what: str, limit: int) -> PayloadTooLarge:
    return PayloadTooLarge(f"{what} is larger than the {limit // (1024 * 1024)} MB limit (SERSFLOW_MAX_UPLOAD_MB)")


def copy_limited(src: BinaryIO, dst: BinaryIO, *, what: str = "file", limit: int | None = None) -> int:
    """Copy ``src`` to ``dst`` in chunks; raise ``PayloadTooLarge`` as soon as the limit is passed."""
    cap = max_upload_bytes() if limit is None else int(limit)
    total = 0
    while True:
        chunk = src.read(_CHUNK)
        if not chunk:
            return total
        total += len(chunk)
        if cap and total > cap:
            raise _too_large(what, cap)
        dst.write(chunk)


def read_limited(src: BinaryIO, *, what: str = "file", limit: int | None = None) -> bytes:
    """Read all of ``src`` into memory, refusing more than the limit."""
    cap = max_upload_bytes() if limit is None else int(limit)
    if not cap:
        return src.read()
    data = src.read(cap + 1)
    if len(data) > cap:
        raise _too_large(what, cap)
    return data


def check_zip_member(info, *, limit: int | None = None) -> None:  # type: ignore[no-untyped-def]
    """Refuse a zip member whose DECLARED uncompressed size exceeds the limit (zip bombs), before reading it."""
    cap = max_upload_bytes() if limit is None else int(limit)
    if cap and int(getattr(info, "file_size", 0) or 0) > cap:
        raise _too_large(f"archive member {info.filename!r}", cap)
