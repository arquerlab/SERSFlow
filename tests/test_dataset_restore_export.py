from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.services.dataset_export import export_dataset_package, import_dataset_package
from sersflow.api.services.dataset_restore import restore_dataset_uploads
from sersflow.core.io.upload_registry import append_upload_registry, make_registry_item, read_upload_registry, unload_files_from_registry
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline
from sersflow.infra.datasets_store import create_dataset, get_dataset
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, upsert_upload_labels, with_connection


def _spectrum_txt(path: Path) -> None:
    path.write_text("wn\tint\n100\t1\n200\t2\n", encoding="utf-8")


def _set_env(tmp_path: Path, monkeypatch, name: str) -> Path:
    upload_root = tmp_path / name / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / name / "sersflow.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / name / "data"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))
    return upload_root


def test_restore_dataset_uploads_reactivates_hidden_file(tmp_path: Path, monkeypatch) -> None:
    upload_root = _set_env(tmp_path, monkeypatch, "reactivate")
    rel = "batch1/a.txt"
    p = upload_root / rel
    p.parent.mkdir(parents=True)
    _spectrum_txt(p)
    append_upload_registry(upload_root, [make_registry_item(batch_id="batch1", filename="a.txt", size_bytes=p.stat().st_size).to_dict()])
    con = with_connection()
    try:
        upsert_upload_labels(con, relative_path=rel, labels={"sample": "A"})
    finally:
        con.close()

    rec = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="restore"), spectra=[SpectrumRef(spectrum_id="s1", relative_path=rel)])
    unloaded, missing = unload_files_from_registry(upload_root_dir=upload_root, relative_paths=[rel])
    assert unloaded == 1 and missing == 0
    assert read_upload_registry(upload_root) == []

    out = restore_dataset_uploads(rec, owner_user_id="dev")
    assert len(out.reactivated) == 1
    assert read_upload_registry(upload_root)[0]["relative_path"] == rel


def test_restore_dataset_uploads_copies_blob_after_upload_deleted(tmp_path: Path, monkeypatch) -> None:
    upload_root = _set_env(tmp_path, monkeypatch, "copy")
    rel = "batch1/a.txt"
    p = upload_root / rel
    p.parent.mkdir(parents=True)
    _spectrum_txt(p)
    rec = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="restore"), spectra=[SpectrumRef(spectrum_id="s1", relative_path=rel)])
    p.unlink()

    out = restore_dataset_uploads(rec, owner_user_id="dev")
    assert len(out.restored) == 1
    restored_rel = out.restored[0].relative_path
    assert (upload_root / restored_rel).exists()
    again = restore_dataset_uploads(rec, owner_user_id="dev")
    assert len(again.already_active) == 1
    assert len(read_upload_registry(upload_root)) == 1


def test_dataset_export_import_roundtrip_uses_blobs_and_labels(tmp_path: Path, monkeypatch) -> None:
    upload_root = _set_env(tmp_path, monkeypatch, "source")
    rel = "batch1/a.txt"
    p = upload_root / rel
    p.parent.mkdir(parents=True)
    _spectrum_txt(p)
    con = with_connection()
    try:
        upsert_upload_labels(con, relative_path=rel, labels={"sample": "A", "ph": 2})
    finally:
        con.close()
    rec = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="exportable"), spectra=[SpectrumRef(spectrum_id="s1", relative_path=rel)])

    package, filename = export_dataset_package(rec.dataset_id, owner_user_id="dev")
    assert filename.endswith(".sersflow-dataset.zip")
    with zipfile.ZipFile(BytesIO(package), "r") as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["schema_version"] == "sersflow.dataset.v1"
    assert manifest["labels"][rel]["sample"] == "A"

    _set_env(tmp_path, monkeypatch, "target")
    imported = import_dataset_package(package, owner_user_id="dev")
    assert imported.imported_spectra == 1
    got = get_dataset(imported.dataset.dataset_id, owner_user_id="dev")
    assert got is not None
    final = run_pipeline(inputs=got.spectra, pipeline=Pipeline(steps=[]), config=EngineConfig(cache_namespace="import"), strict=True)
    assert final["s1"].x.size == 2

    con = with_connection()
    try:
        labels = fetch_upload_labels_for_paths(con, [rel])
    finally:
        con.close()
    assert labels[rel]["sample"] == "A"
