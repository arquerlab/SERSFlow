from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable
from uuid import uuid4


@dataclass(frozen=True)
class UploadRegistryItem:
    batch_id: str
    filename: str
    relative_path: str
    size_bytes: int
    saved_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "filename": self.filename,
            "relative_path": self.relative_path,
            "size_bytes": int(self.size_bytes),
            "saved_at": self.saved_at,
        }


def upload_root() -> Path:
    return Path(os.environ.get("SERSFLOW_UPLOAD_DIR", str(Path.cwd() / "uploads"))).resolve()


def registry_path(upload_root_dir: Path) -> Path:
    return upload_root_dir / "upload_registry.jsonl"


def append_upload_registry(upload_root_dir: Path, items: Iterable[dict[str, Any]]) -> None:
    upload_root_dir.mkdir(parents=True, exist_ok=True)
    p = registry_path(upload_root_dir)
    wrote_any = False
    with p.open("a", encoding="utf-8") as f:
        for item in items:
            if not item:
                continue
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            wrote_any = True
    if not wrote_any and p.exists() and p.stat().st_size == 0:
        pass


def read_upload_registry(upload_root_dir: Path) -> list[dict[str, Any]]:
    p = registry_path(upload_root_dir)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                out.append(json.loads(s))
            except json.JSONDecodeError:
                continue
    return out


def write_upload_registry(upload_root_dir: Path, items: Iterable[dict[str, Any]]) -> None:
    upload_root_dir.mkdir(parents=True, exist_ok=True)
    p = registry_path(upload_root_dir)
    tmp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(upload_root_dir),
            prefix=p.name + ".",
            suffix=".tmp",
            newline="\n",
        ) as tmp:
            tmp_path = Path(tmp.name)
            for item in items:
                if not item:
                    continue
                tmp.write(json.dumps(item, ensure_ascii=False) + "\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        tmp_path.replace(p)
    finally:
        try:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def ensure_within_root(root: Path, candidate: Path) -> Path:
    """
    Resolve `candidate` and ensure it stays within `root`.
    """
    root = root.resolve()
    resolved = candidate.resolve()
    if resolved == root or root in resolved.parents:
        return resolved
    raise ValueError("Path traversal detected (candidate is outside upload root).")


def resolve_uploaded_path(upload_root_dir: Path, relative_path: str) -> Path:
    """
    Resolve an upload `relative_path` against `upload_root_dir` safely.
    """
    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise ValueError("relative_path must be a non-empty string")
    return ensure_within_root(upload_root_dir, upload_root_dir / relative_path)


def new_batch_dir(upload_root_dir: Path) -> tuple[str, Path]:
    batch_id = uuid4().hex
    batch_dir = upload_root_dir / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    return batch_id, batch_dir


def make_registry_item(*, batch_id: str, filename: str, size_bytes: int) -> UploadRegistryItem:
    rel = str(Path(batch_id) / filename).replace("\\", "/")
    return UploadRegistryItem(
        batch_id=batch_id,
        filename=filename,
        relative_path=rel,
        size_bytes=int(size_bytes),
        saved_at=datetime.now(timezone.utc).isoformat(),
    )


def unload_files_from_registry(
    *,
    upload_root_dir: Path,
    relative_paths: list[str],
) -> tuple[int, int]:
    """
    Delete previously uploaded files and remove them from the registry.

    Returns:
        (deleted_count, missing_count)
    """
    if not isinstance(relative_paths, list) or not all(isinstance(x, str) for x in relative_paths):
        raise ValueError("relative_paths must be list[str]")
    if any((not x) or ("\x00" in x) for x in relative_paths):
        raise ValueError("relative_paths contains invalid entries")
    registry = read_upload_registry(upload_root_dir)
    to_remove = set(relative_paths)

    deleted = 0
    missing = 0
    kept: list[dict[str, Any]] = []

    for item in registry:
        rel = item.get("relative_path")
        if rel in to_remove:
            target = ensure_within_root(upload_root_dir, upload_root_dir / rel)
            try:
                target.unlink()
                deleted += 1
            except FileNotFoundError:
                missing += 1
            except OSError:
                kept.append(item)
            continue
        kept.append(item)

    write_upload_registry(upload_root_dir, kept)

    # Best-effort cleanup: remove empty batch dirs
    for rel in to_remove:
        try:
            batch = ensure_within_root(upload_root_dir, (upload_root_dir / rel).parent)
            if batch.is_dir():
                next(batch.iterdir())
        except StopIteration:
            try:
                batch.rmdir()
            except OSError:
                pass
        except Exception:
            pass

    return deleted, missing

