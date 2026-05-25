from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True)
class StoredBlob:
    blob_id: str
    blob_relative_path: str
    size_bytes: int


def data_root() -> Path:
    return Path(os.environ.get("SERSFLOW_DATA_DIR", str(Path.cwd() / ".sersflow_data"))).resolve()


def blob_root() -> Path:
    return data_root() / "blobs"


def ensure_within_data_root(candidate: Path) -> Path:
    root = data_root()
    resolved = candidate.resolve()
    if resolved == root or root in resolved.parents:
        return resolved
    raise ValueError("Path traversal detected (candidate is outside data root).")


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            if chunk:
                h.update(chunk)
    return h.hexdigest()


def store_blob_from_file(path: Path) -> StoredBlob:
    source = Path(path).resolve()
    if not source.exists():
        raise FileNotFoundError(str(path))
    blob_id = _hash_file(source)
    suffix = source.suffix.lower()
    rel = Path("blobs") / blob_id[:2] / f"{blob_id}{suffix}"
    target = data_root() / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        tmp_path: Path | None = None
        try:
            with NamedTemporaryFile(delete=False, dir=str(target.parent), prefix=target.name + ".", suffix=".tmp") as tmp:
                tmp_path = Path(tmp.name)
                with source.open("rb") as src:
                    shutil.copyfileobj(src, tmp)
            tmp_path.replace(target)
        finally:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
    return StoredBlob(blob_id=blob_id, blob_relative_path=rel.as_posix(), size_bytes=int(source.stat().st_size))


def resolve_blob_path(blob_relative_path: str) -> Path:
    if not blob_relative_path or "\x00" in blob_relative_path:
        raise ValueError("blob_relative_path must be a non-empty string")
    p = ensure_within_data_root(data_root() / blob_relative_path)
    if not p.exists():
        raise FileNotFoundError(blob_relative_path)
    return p


def delete_blob_if_unreferenced(blob_relative_path: str) -> bool:
    p = resolve_blob_path(blob_relative_path)
    try:
        p.unlink()
    except FileNotFoundError:
        return False
    try:
        parent = p.parent
        if parent.is_dir():
            next(parent.iterdir())
    except StopIteration:
        try:
            parent.rmdir()
        except OSError:
            pass
    except Exception:
        pass
    return True
