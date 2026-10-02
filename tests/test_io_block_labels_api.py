from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.services.datasets_service import _persist_multi_spectrum_labels
from sersflow.api.services.ownership import invalidate_registry_cache
from sersflow.core.io.multi_block_labels import get_block_spectra
from sersflow.core.io.upload_registry import make_registry_item, write_upload_registry
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, upsert_upload_labels, with_connection


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "labels.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    upload_root = tmp_path / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))
    upload_root.mkdir(parents=True, exist_ok=True)
    invalidate_registry_cache()
    return upload_root


def test_put_labels_record_index_updates_one_block(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_root = _env(tmp_path, monkeypatch)
    rel = "batch/multi.vms"
    p = upload_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    write_upload_registry(
        upload_root,
        [
            make_registry_item(
                batch_id="batch",
                filename="multi.vms",
                size_bytes=p.stat().st_size,
                owner_user_id="dev",
            ).to_dict()
        ],
    )
    con = with_connection()
    try:
        upsert_upload_labels(
            con,
            relative_path=rel,
            labels={
                "sample": "Cu",
                "acquired_utc": "2020-01-01T00:00:00Z",
                "vms_spectra": {
                    "0": {"xps_region": "C1s", "current_density_A_cm2": 0.05},
                    "1": {"xps_region": "O1s", "current_density_A_cm2": 0.1},
                },
            },
        )
    finally:
        con.close()

    client = TestClient(app)
    r = client.put(
        "/io/labels",
        json={"relative_path": rel, "record_index": 0, "labels": {"potential_V": -0.2, "sample": "block0"}},
    )
    assert r.status_code == 200, r.text

    con = with_connection()
    try:
        lab = fetch_upload_labels_for_paths(con, [rel])[rel]
    finally:
        con.close()
    assert lab["sample"] == "Cu"  # path-level unchanged
    assert lab["acquired_utc"] == "2020-01-01T00:00:00Z"
    blocks = get_block_spectra(lab)
    assert blocks["0"]["potential_V"] == -0.2
    assert blocks["0"]["sample"] == "block0"
    assert blocks["0"]["xps_region"] == "C1s"
    assert blocks["1"]["xps_region"] == "O1s"
    assert blocks["1"].get("potential_V") is None


def test_put_labels_path_leaves_block_map_intact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_root = _env(tmp_path, monkeypatch)
    rel = "batch/file.vms"
    p = upload_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    write_upload_registry(
        upload_root,
        [
            make_registry_item(
                batch_id="batch",
                filename="file.vms",
                size_bytes=p.stat().st_size,
                owner_user_id="dev",
            ).to_dict()
        ],
    )
    con = with_connection()
    try:
        upsert_upload_labels(
            con,
            relative_path=rel,
            labels={
                "sample": "old",
                "acquired_utc": "2020-01-01T00:00:00Z",
                "vms_spectra": {"0": {"xps_region": "C1s", "current_density_A_cm2": 0.05}},
            },
        )
    finally:
        con.close()

    client = TestClient(app)
    r = client.put("/io/labels", json={"relative_path": rel, "labels": {"sample": "new", "gas": "CO2"}})
    assert r.status_code == 200, r.text

    con = with_connection()
    try:
        lab = fetch_upload_labels_for_paths(con, [rel])[rel]
    finally:
        con.close()
    assert lab["sample"] == "new"
    assert lab["gas"] == "CO2"
    assert lab["acquired_utc"] == "2020-01-01T00:00:00Z"
    blocks = get_block_spectra(lab)
    assert blocks["0"]["current_density_A_cm2"] == 0.05


def test_persist_multi_preserves_experimental(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _env(tmp_path, monkeypatch)
    rel = "batch/x.vms"
    con = with_connection()
    try:
        upsert_upload_labels(
            con,
            relative_path=rel,
            labels={
                "vms_spectra": {
                    "0": {
                        "xps_region": "C1s",
                        "spectrum_role": "average",
                        "current_density_A_cm2": 0.05,
                        "potential_V": -0.1,
                    },
                    "1": {
                        "xps_region": "C1s",
                        "spectrum_role": "individual",
                        "current_density_A_cm2": 0.05,
                    },
                }
            },
        )
    finally:
        con.close()

    # Keep only index 0 with refreshed structural meta
    _persist_multi_spectrum_labels(
        relative_path=rel,
        meta_by_index={"0": {"xps_region": "C1s", "spectrum_role": "average", "block_name": "C1s_avg"}},
        vms_spectrum_mode="averages",
        xps_regions_filter=["C1s"],
    )
    con = with_connection()
    try:
        lab = fetch_upload_labels_for_paths(con, [rel])[rel]
    finally:
        con.close()
    blocks = get_block_spectra(lab)
    # Persist must not drop other blocks when updating a subset of indices.
    assert set(blocks.keys()) == {"0", "1"}
    assert blocks["0"]["block_name"] == "C1s_avg"
    assert blocks["0"]["current_density_A_cm2"] == 0.05
    assert blocks["0"]["potential_V"] == -0.1
    assert blocks["1"]["spectrum_role"] == "individual"
    assert lab.get("vms_spectrum_mode") == "averages"
