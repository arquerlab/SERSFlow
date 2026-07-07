from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata, SpectrumRef
from sersflow.api.services.datasets_service import create_dataset_from_uploads
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline
from sersflow.core.io.upload_registry import append_unloaded_registry
from sersflow.infra.blob_store import resolve_blob_path
from sersflow.infra.datasets_store import create_dataset, get_dataset, relink_path_only_dataset_rows_from_upload_items


def _spectrum_txt(path: Path) -> None:
    path.write_text("wn\tint\n100\t1\n200\t2\n", encoding="utf-8")


def test_create_dataset_skips_bad_files_and_keeps_good(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    upload_root = tmp_path / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))

    batch = "batch01"
    good = upload_root / batch / "good.txt"
    bad = upload_root / batch / "bad.unsupported_ext"
    good.parent.mkdir(parents=True, exist_ok=True)
    _spectrum_txt(good)
    bad.write_text("not a spectrum", encoding="utf-8")

    rel_good = f"{batch}/good.txt"
    rel_bad = f"{batch}/bad.unsupported_ext"

    rec, skipped = create_dataset_from_uploads(
        DatasetCreateRequest(relative_paths=[rel_bad, rel_good], metadata=DatasetMetadata(name="mixed")),
        owner_user_id="dev",
    )
    assert len(rec.spectra) == 1
    assert rec.spectra[0].relative_path == rel_good
    assert rec.spectra[0].blob_id
    assert rec.spectra[0].blob_relative_path
    assert resolve_blob_path(str(rec.spectra[0].blob_relative_path)).exists()
    assert len(skipped) == 1
    assert skipped[0]["relative_path"] == rel_bad
    assert "Unsupported file type" in skipped[0]["reason"] or "unsupported_ext" in skipped[0]["reason"].lower()

    good.unlink()
    final = run_pipeline(inputs=rec.spectra, pipeline=Pipeline(steps=[]), config=EngineConfig(cache_namespace="test"), strict=True)
    xy = final[rec.spectra[0].spectrum_id]
    assert xy.x.size == 2
    assert xy.y.size == 2


def test_create_dataset_all_fail_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test2.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data2"))
    upload_root = tmp_path / ".sersflow_uploads2"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))

    batch = "b2"
    bad = upload_root / batch / "only.bad"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("x", encoding="utf-8")
    rel = f"{batch}/only.bad"

    with pytest.raises(ValueError, match="No spectra could be loaded"):
        create_dataset_from_uploads(
            DatasetCreateRequest(relative_paths=[rel], metadata=DatasetMetadata()),
            owner_user_id="dev",
        )


def test_reuploaded_file_relinks_path_only_dataset_from_unloaded_registry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "repair.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "repair_data"))
    upload_root = tmp_path / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))

    old_rel = "oldbatch/sample.txt"
    ds = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="legacy"),
        spectra=[SpectrumRef(spectrum_id="sp_legacy", relative_path=old_rel, record_index=None)],
    )
    old = get_dataset(ds.dataset_id, owner_user_id="dev")
    assert old is not None
    assert old.spectra[0].blob_relative_path is None

    new_file = upload_root / "newbatch" / "sample.txt"
    new_file.parent.mkdir(parents=True, exist_ok=True)
    _spectrum_txt(new_file)
    size = new_file.stat().st_size
    append_unloaded_registry(
        upload_root,
        [
            {
                "batch_id": "oldbatch",
                "filename": "sample.txt",
                "relative_path": old_rel,
                "size_bytes": size,
                "saved_at": "2020-01-01T00:00:00+00:00",
                "unloaded_at": "2020-01-02T00:00:00+00:00",
                "labels": {},
            }
        ],
    )

    relinked = relink_path_only_dataset_rows_from_upload_items(
        [{"batch_id": "newbatch", "filename": "sample.txt", "relative_path": "newbatch/sample.txt", "size_bytes": size}]
    )
    assert relinked == 1

    repaired = get_dataset(ds.dataset_id, owner_user_id="dev")
    assert repaired is not None
    assert repaired.spectra[0].blob_relative_path
    new_file.unlink()
    final = run_pipeline(inputs=repaired.spectra, pipeline=Pipeline(steps=[]), config=EngineConfig(cache_namespace="repair"), strict=True)
    assert final["sp_legacy"].x.size == 2
