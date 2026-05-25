from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.core.io.upload_registry import (
    append_unloaded_registry,
    append_upload_registry,
    ensure_within_root,
    make_registry_item,
    preview_purge_files,
    purge_files_from_registry,
    read_unloaded_registry,
    read_upload_registry,
    unload_files_from_registry,
    update_unloaded_labels,
    update_upload_registry_labels,
    upload_root,
)
from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.infra.datasets_store import create_dataset
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, upsert_upload_labels, with_connection


def test_upload_root_defaults_to_hidden_local_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERSFLOW_UPLOAD_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    assert upload_root() == (tmp_path / ".sersflow_uploads").resolve()


def test_ensure_within_root_allows_nested(tmp_path: Path) -> None:
    root = tmp_path / ".sersflow_uploads"
    root.mkdir()
    nested = root / "a" / "b.txt"
    nested.parent.mkdir(parents=True)
    nested.write_text("x", encoding="utf-8")
    assert ensure_within_root(root, nested) == nested.resolve()


def test_ensure_within_root_blocks_traversal(tmp_path: Path) -> None:
    root = tmp_path / ".sersflow_uploads"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="Path traversal"):
        ensure_within_root(root, outside)


def test_unload_appends_unloaded_history_and_keeps_sqlite_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / ".sersflow_uploads"
    root.mkdir()
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(root.resolve()))
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(db_file.resolve()))

    batch_id = "batch1test"
    fname = "sample.wdf"
    rel = f"{batch_id}/{fname}"
    batch_dir = root / batch_id
    batch_dir.mkdir(parents=True)
    (batch_dir / fname).write_bytes(b"x")

    item = make_registry_item(
        batch_id=batch_id,
        filename=fname,
        size_bytes=1,
        labels={"sample": "X"},
    ).to_dict()
    append_upload_registry(root, [item])

    con = with_connection()
    upsert_upload_labels(con, relative_path=rel, labels={"sample": "X", "ph": 2.5})
    con.close()

    unloaded_count, missing = unload_files_from_registry(upload_root_dir=root, relative_paths=[rel])
    assert unloaded_count == 1
    assert missing == 0
    assert (batch_dir / fname).exists()

    unloaded = read_unloaded_registry(root)
    assert len(unloaded) == 1
    assert unloaded[0]["relative_path"] == rel
    assert unloaded[0]["labels"]["ph"] == 2.5

    con = with_connection()
    try:
        lbl = fetch_upload_labels_for_paths(con, [rel])
    finally:
        con.close()
    assert rel in lbl
    assert lbl[rel]["ph"] == 2.5
    assert read_upload_registry(root) == []


def test_update_unloaded_labels_rewrites_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".sersflow_uploads"
    root.mkdir()
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(root.resolve()))

    append_unloaded_registry(
        root,
        [
            {
                "batch_id": "b",
                "filename": "f.txt",
                "relative_path": "b/f.txt",
                "size_bytes": 0,
                "saved_at": "2020-01-01T00:00:00+00:00",
                "unloaded_at": "2020-01-02T00:00:00+00:00",
                "labels": {"a": 1},
            }
        ],
    )
    ok = update_unloaded_labels(root, "b/f.txt", {"a": 2, "gas": "Ar"})
    assert ok is True
    rows = read_unloaded_registry(root)
    assert len(rows) == 1
    assert rows[0]["labels"]["a"] == 2
    assert rows[0]["labels"]["gas"] == "Ar"


def test_update_upload_registry_retries_transient_replace_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / ".sersflow_uploads"
    root.mkdir()
    rel = "b/f.txt"
    append_upload_registry(
        root,
        [
            make_registry_item(
                batch_id="b",
                filename="f.txt",
                size_bytes=1,
                labels={"sample": "old"},
            ).to_dict()
        ],
    )

    original_replace = Path.replace
    failures = 0

    def flaky_replace(self: Path, target: Path) -> Path:
        nonlocal failures
        if self.name.startswith("upload_registry.jsonl.") and failures == 0:
            failures += 1
            raise PermissionError("temporarily locked")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    ok = update_upload_registry_labels(root, rel, {"sample": "new"})

    assert ok is True
    assert failures == 1
    rows = read_upload_registry(root)
    assert rows[0]["labels"] == {"sample": "new"}


def test_preview_and_purge_hidden_uploads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".sersflow_uploads"
    root.mkdir()
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(root.resolve()))
    monkeypatch.setenv("SERSFLOW_DB_PATH", str((tmp_path / "purge.db").resolve()))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str((tmp_path / "data").resolve()))

    rel = "b/f.txt"
    target = root / rel
    target.parent.mkdir(parents=True)
    target.write_bytes(b"12345")
    append_upload_registry(root, [make_registry_item(batch_id="b", filename="f.txt", size_bytes=5).to_dict()])

    unloaded, missing = unload_files_from_registry(upload_root_dir=root, relative_paths=[rel])
    assert unloaded == 1
    assert missing == 0
    assert target.exists()

    preview = preview_purge_files(upload_root_dir=root)
    assert preview["total_files"] == 1
    assert preview["total_size_bytes"] == 5
    assert preview["items"][0]["blocked_count"] == 0

    deleted, missing, blocked = purge_files_from_registry(upload_root_dir=root, relative_paths=[rel])
    assert deleted == 1
    assert missing == 0
    assert blocked == {}
    assert not target.exists()
    assert read_unloaded_registry(root) == []

    deleted2, missing2, blocked2 = purge_files_from_registry(upload_root_dir=root, relative_paths=[rel])
    assert deleted2 == 0
    assert missing2 == 1
    assert blocked2 == {}


def test_purge_blocks_path_only_dataset_dependency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / ".sersflow_uploads"
    root.mkdir()
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(root.resolve()))
    monkeypatch.setenv("SERSFLOW_DB_PATH", str((tmp_path / "blocked.db").resolve()))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str((tmp_path / "data-blocked").resolve()))

    rel = "b/legacy.txt"
    target = root / rel
    target.parent.mkdir(parents=True)
    create_dataset(metadata=DatasetMetadata(name="legacy"), spectra=[SpectrumRef(spectrum_id="s1", relative_path=rel)])
    append_unloaded_registry(
        root,
        [
            {
                "batch_id": "b",
                "filename": "legacy.txt",
                "relative_path": rel,
                "size_bytes": 6,
                "saved_at": "2020-01-01T00:00:00+00:00",
                "unloaded_at": "2020-01-02T00:00:00+00:00",
                "labels": {},
            }
        ],
    )
    preview = preview_purge_files(upload_root_dir=root)
    assert preview["blocked"][rel] == 1
    assert preview["items"][0]["blocked_count"] == 1

    deleted, missing, blocked = purge_files_from_registry(upload_root_dir=root, relative_paths=[rel])
    assert deleted == 0
    assert missing == 0
    assert blocked[rel] == 1
    assert not target.exists()
    assert read_unloaded_registry(root)[0]["relative_path"] == rel

