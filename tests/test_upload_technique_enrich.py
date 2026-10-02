from __future__ import annotations

from pathlib import Path

from sersflow.api.routers.io import _ensure_upload_technique_meta
from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.xps_upload_meta import dataset_xps_regions
from tests.test_vms_loader import write_mixed_region_vms


def test_dataset_xps_regions_from_vms(tmp_path: Path) -> None:
    p = write_mixed_region_vms(tmp_path / "mixed.vms")
    ds = load_dataset(p)
    assert dataset_xps_regions(ds) == ["C1s", "O1s"]


def test_ensure_upload_technique_meta_enriches_vms(tmp_path: Path) -> None:
    root = tmp_path / "uploads"
    batch = root / "b1"
    batch.mkdir(parents=True)
    dest = batch / "mixed.vms"
    write_mixed_region_vms(dest)
    row = {
        "batch_id": "b1",
        "filename": "mixed.vms",
        "relative_path": "b1/mixed.vms",
        "size_bytes": dest.stat().st_size,
        "saved_at": "2020-01-01T00:00:00Z",
    }
    out = _ensure_upload_technique_meta(root, row)
    assert out["technique_family"] == "xps"
    assert out["xps_regions"] == ["C1s", "O1s"]
    assert int(out["spectrum_count"]) == 5


def test_ensure_upload_technique_meta_vibrational_path(tmp_path: Path) -> None:
    root = tmp_path / "uploads"
    row = {
        "batch_id": "b1",
        "filename": "sample.wdf",
        "relative_path": "b1/sample.wdf",
        "size_bytes": 1,
        "saved_at": "2020-01-01T00:00:00Z",
    }
    out = _ensure_upload_technique_meta(root, row)
    assert out["technique_family"] == "vibrational"
    assert "xps_regions" not in out or out.get("xps_regions") is None
