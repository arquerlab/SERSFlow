"""Software and file provenance for reports (R1): name, version, git commit, file SHA-256."""

from __future__ import annotations

import functools
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

SOFTWARE_NAME = "SpecFlow (sersflow)"


@functools.lru_cache(maxsize=1)
def git_commit() -> str | None:
    """Commit of the running code: ``SERSFLOW_GIT_COMMIT`` env, else ``git rev-parse HEAD`` of the source tree."""
    env = os.environ.get("SERSFLOW_GIT_COMMIT", "").strip()
    if env:
        return env
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5, check=True
        )
        sha = out.stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}" if sha else None
    except Exception:
        return None


def software_info() -> dict[str, Any]:
    from sersflow import __version__

    return {"name": SOFTWARE_NAME, "version": __version__, "git_commit": git_commit()}


@functools.lru_cache(maxsize=512)
def _sha256_cached(path: str, size: int, mtime_ns: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_sha256(path: str | os.PathLike[str]) -> str | None:
    """SHA-256 of a file (cached on path, size and mtime); None when it cannot be read."""
    try:
        st = os.stat(path)
        return _sha256_cached(str(path), int(st.st_size), int(st.st_mtime_ns))
    except OSError:
        return None
