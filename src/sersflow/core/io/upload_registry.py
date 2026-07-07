from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterable
from uuid import uuid4

from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection


@dataclass(frozen=True)
class UploadRegistryItem:
    batch_id: str
    filename: str
    relative_path: str
    size_bytes: int
    saved_at: str
    modified_utc: str | None = None
    labels: dict[str, Any] | None = None
    wn_min: float | None = None
    wn_max: float | None = None
    spectrum_count: int | None = None
    owner_user_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "batch_id": self.batch_id,
            "filename": self.filename,
            "relative_path": self.relative_path,
            "size_bytes": int(self.size_bytes),
            "saved_at": self.saved_at,
        }
        if self.modified_utc is not None:
            d["modified_utc"] = self.modified_utc
        if self.labels is not None:
            d["labels"] = self.labels
        if self.wn_min is not None:
            d["wn_min"] = float(self.wn_min)
        if self.wn_max is not None:
            d["wn_max"] = float(self.wn_max)
        if self.spectrum_count is not None:
            d["spectrum_count"] = int(self.spectrum_count)
        if self.owner_user_id is not None:
            d["owner_user_id"] = self.owner_user_id
        return d


def upload_root() -> Path:
    return Path(os.environ.get("SERSFLOW_UPLOAD_DIR", str(Path.cwd() / ".sersflow_uploads"))).resolve()


def registry_path(upload_root_dir: Path) -> Path:
    return upload_root_dir / "upload_registry.jsonl"


def unloaded_registry_path(upload_root_dir: Path) -> Path:
    return upload_root_dir / "unloaded_registry.jsonl"


def _replace_with_retries(source: Path, target: Path, *, attempts: int = 8, delay_s: float = 0.05) -> None:
    """
    Atomically replace a registry file, retrying transient Windows file locks.
    """
    last_error: PermissionError | None = None
    for attempt in range(attempts):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(delay_s * (attempt + 1))
    if last_error is not None:
        raise last_error


def append_unloaded_registry(upload_root_dir: Path, items: Iterable[dict[str, Any]]) -> None:
    upload_root_dir.mkdir(parents=True, exist_ok=True)
    p = unloaded_registry_path(upload_root_dir)
    with p.open("a", encoding="utf-8") as f:
        for item in items:
            if not item:
                continue
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def read_unloaded_registry(upload_root_dir: Path) -> list[dict[str, Any]]:
    p = unloaded_registry_path(upload_root_dir)
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


def write_unloaded_registry(upload_root_dir: Path, items: Iterable[dict[str, Any]]) -> None:
    upload_root_dir.mkdir(parents=True, exist_ok=True)
    p = unloaded_registry_path(upload_root_dir)
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
        _replace_with_retries(tmp_path, p)
    finally:
        try:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def update_unloaded_labels(upload_root_dir: Path, relative_path: str, labels: dict[str, Any]) -> bool:
    if not relative_path or "\x00" in relative_path:
        return False
    items = read_unloaded_registry(upload_root_dir)
    found = False
    for item in items:
        if item.get("relative_path") == relative_path:
            item["labels"] = dict(labels)
            found = True
    if found:
        write_unloaded_registry(upload_root_dir, items)
    return found


def update_upload_registry_labels(upload_root_dir: Path, relative_path: str, labels: dict[str, Any]) -> bool:
    if not relative_path or "\x00" in relative_path:
        return False
    registry = read_upload_registry(upload_root_dir)
    found = False
    for item in registry:
        if item.get("relative_path") == relative_path:
            item["labels"] = dict(labels)
            found = True
    if found:
        write_upload_registry(upload_root_dir, registry)
    return found


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


def append_upload_registry_unique(upload_root_dir: Path, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    registry = read_upload_registry(upload_root_dir)
    active = {str(item.get("relative_path") or "") for item in registry}
    to_add: list[dict[str, Any]] = []
    for item in items:
        rel = str(item.get("relative_path") or "")
        if not rel or rel in active:
            continue
        to_add.append(dict(item))
        active.add(rel)
    if to_add:
        append_upload_registry(upload_root_dir, to_add)
    return to_add


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
        _replace_with_retries(tmp_path, p)
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


def make_registry_item(
    *,
    batch_id: str,
    filename: str,
    relative_subpath: str | None = None,
    size_bytes: int,
    modified_utc: str | None = None,
    labels: dict[str, Any] | None = None,
    wn_min: float | None = None,
    wn_max: float | None = None,
    spectrum_count: int | None = None,
    owner_user_id: str | None = None,
) -> UploadRegistryItem:
    rel_part = relative_subpath if relative_subpath else filename
    rel = str(Path(batch_id) / rel_part).replace("\\", "/")
    return UploadRegistryItem(
        batch_id=batch_id,
        filename=filename,
        relative_path=rel,
        size_bytes=int(size_bytes),
        saved_at=datetime.now(timezone.utc).isoformat(),
        modified_utc=modified_utc,
        labels=labels,
        wn_min=wn_min,
        wn_max=wn_max,
        spectrum_count=spectrum_count,
        owner_user_id=owner_user_id,
    )


def reactivate_unloaded_registry_entries(
    upload_root_dir: Path,
    relative_paths: Iterable[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    wanted = {str(x) for x in relative_paths if x}
    if not wanted:
        return [], set()
    active = read_upload_registry(upload_root_dir)
    active_paths = {str(item.get("relative_path") or "") for item in active}
    unloaded = read_unloaded_registry(upload_root_dir)
    kept_unloaded: list[dict[str, Any]] = []
    restored: list[dict[str, Any]] = []
    restored_paths: set[str] = set()
    for item in unloaded:
        rel = str(item.get("relative_path") or "")
        if rel in wanted and rel not in active_paths:
            rec = dict(item)
            rec.pop("unloaded_at", None)
            restored.append(rec)
            restored_paths.add(rel)
            active_paths.add(rel)
            continue
        kept_unloaded.append(item)
    if restored:
        append_upload_registry(upload_root_dir, restored)
        write_unloaded_registry(upload_root_dir, kept_unloaded)
    return restored, restored_paths


def unload_files_from_registry(
    *,
    upload_root_dir: Path,
    relative_paths: list[str],
) -> tuple[int, int]:
    """
    Hide uploaded files from the active registry without deleting bytes on disk.

    Returns:
        (unloaded_count, missing_count)
    """
    if not isinstance(relative_paths, list) or not all(isinstance(x, str) for x in relative_paths):
        raise ValueError("relative_paths must be list[str]")
    if any((not x) or ("\x00" in x) for x in relative_paths):
        raise ValueError("relative_paths contains invalid entries")
    registry = read_upload_registry(upload_root_dir)
    to_remove = set(relative_paths)

    db_labels: dict[str, dict[str, Any]] = {}
    try:
        con = with_connection()
        try:
            db_labels = fetch_upload_labels_for_paths(con, to_remove)
        finally:
            con.close()
    except Exception:
        db_labels = {}

    unloaded_at = datetime.now(timezone.utc).isoformat()
    unloaded_entries: list[dict[str, Any]] = []

    unloaded = 0
    kept: list[dict[str, Any]] = []
    found: set[str] = set()

    for item in registry:
        rel = item.get("relative_path")
        if rel in to_remove:
            found.add(str(rel))
            rec = dict(item)
            reg_labels = rec.get("labels") if isinstance(rec.get("labels"), dict) else {}
            if isinstance(rel, str) and rel in db_labels:
                rec["labels"] = dict(db_labels[rel])
            else:
                rec["labels"] = dict(reg_labels) if reg_labels else {}
            rec["unloaded_at"] = unloaded_at
            unloaded_entries.append(rec)
            unloaded += 1
            continue
        kept.append(item)

    write_upload_registry(upload_root_dir, kept)
    if unloaded_entries:
        append_unloaded_registry(upload_root_dir, unloaded_entries)

    missing = len(to_remove - found)
    return unloaded, missing


def purge_files_from_registry(
    *,
    upload_root_dir: Path,
    relative_paths: list[str],
) -> tuple[int, int, dict[str, int]]:
    """
    Permanently delete upload files and remove registry entries.

    Path-only datasets still depend on active upload paths, so those paths are
    blocked until they are migrated to blobs or the dataset is deleted.
    """
    if not isinstance(relative_paths, list) or not all(isinstance(x, str) for x in relative_paths):
        raise ValueError("relative_paths must be list[str]")
    if any((not x) or ("\x00" in x) for x in relative_paths):
        raise ValueError("relative_paths contains invalid entries")

    from sersflow.infra.datasets_store import path_only_dataset_reference_counts

    to_purge = set(relative_paths)
    blocked = path_only_dataset_reference_counts(to_purge)
    allowed = to_purge - set(blocked)
    active = read_upload_registry(upload_root_dir)
    unloaded = read_unloaded_registry(upload_root_dir)

    kept_active = [item for item in active if item.get("relative_path") not in allowed]
    kept_unloaded = [item for item in unloaded if item.get("relative_path") not in allowed]

    deleted = 0
    missing = 0
    for rel in allowed:
        target = ensure_within_root(upload_root_dir, upload_root_dir / rel)
        try:
            target.unlink()
            deleted += 1
        except FileNotFoundError:
            missing += 1

    write_upload_registry(upload_root_dir, kept_active)
    write_unloaded_registry(upload_root_dir, kept_unloaded)

    for rel in allowed:
        try:
            parent = ensure_within_root(upload_root_dir, (upload_root_dir / rel).parent)
            if parent.is_dir():
                next(parent.iterdir())
        except StopIteration:
            try:
                parent.rmdir()
            except OSError:
                pass
        except Exception:
            pass

    return deleted, missing, blocked


def preview_purge_files(
    *,
    upload_root_dir: Path,
    relative_paths: list[str] | None = None,
    hidden_only: bool = True,
) -> dict[str, Any]:
    """
    Preview permanent deletion candidates without deleting files.
    """
    if relative_paths is not None:
        if not isinstance(relative_paths, list) or not all(isinstance(x, str) for x in relative_paths):
            raise ValueError("relative_paths must be list[str]")
        if any((not x) or ("\x00" in x) for x in relative_paths):
            raise ValueError("relative_paths contains invalid entries")

    from sersflow.infra.datasets_store import path_only_dataset_reference_counts

    source_rows = read_unloaded_registry(upload_root_dir) if hidden_only else [
        *read_upload_registry(upload_root_dir),
        *read_unloaded_registry(upload_root_dir),
    ]
    wanted = set(relative_paths) if relative_paths is not None else None
    by_rel: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        rel = str(row.get("relative_path") or "")
        if not rel:
            continue
        if wanted is not None and rel not in wanted:
            continue
        by_rel.setdefault(rel, dict(row))

    blocked = path_only_dataset_reference_counts(by_rel.keys())
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    total_size = 0
    for rel, row in sorted(by_rel.items()):
        exists = False
        size = 0
        try:
            p = ensure_within_root(upload_root_dir, upload_root_dir / rel)
            exists = p.exists()
            if exists:
                size = int(p.stat().st_size)
            else:
                size = int(row.get("size_bytes") or 0)
                missing.append(rel)
        except (OSError, ValueError):
            size = int(row.get("size_bytes") or 0)
            missing.append(rel)
        total_size += max(0, size)
        items.append(
            {
                "relative_path": rel,
                "filename": str(row.get("filename") or Path(rel).name),
                "size_bytes": max(0, size),
                "exists": exists,
                "blocked_count": int(blocked.get(rel, 0)),
            }
        )

    return {
        "items": items,
        "total_files": len(items),
        "total_size_bytes": int(total_size),
        "blocked": blocked,
        "missing": missing,
    }
