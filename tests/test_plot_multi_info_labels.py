from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.services.ownership import invalidate_registry_cache
from sersflow.core.io.upload_registry import make_registry_item, write_upload_registry
from sersflow.infra.upload_labels_store import upsert_upload_labels, with_connection

h5py = pytest.importorskip("h5py")


def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "plot.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    upload_root = tmp_path / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))
    upload_root.mkdir(parents=True, exist_ok=True)
    invalidate_registry_cache()
    return upload_root


def _write_nxs(path: Path) -> None:
    with h5py.File(path, "w") as f:
        entry = f.create_group("entry")
        data = entry.create_group("C1s")
        data.create_dataset("binding_energy", data=np.linspace(290, 280, 5))
        data.create_dataset("spectrum", data=np.ones(5))
        data.create_dataset("spectrum_1", data=np.ones(5) * 2)
        inst = entry.create_group("instrument")
        ig = inst.create_group("C1s")
        ig.create_dataset("number_of_iterations", data=2)


def test_multi_info_merges_experimental_from_upload_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_root = _env(tmp_path, monkeypatch)
    rel = "batch/sample.nxs"
    p = upload_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    _write_nxs(p)
    write_upload_registry(
        upload_root,
        [
            make_registry_item(
                batch_id="batch",
                filename="sample.nxs",
                size_bytes=p.stat().st_size,
                owner_user_id="dev",
                technique_family="xps",
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
                "vms_spectra": {
                    "0": {
                        "xps_region": "C1s",
                        "spectrum_role": "average",
                        "current_density_A_cm2": 0.05,
                        "potential_V": -0.2,
                        "potential_ref": "VRHE",
                    },
                    "1": {
                        "xps_region": "C1s",
                        "spectrum_role": "individual",
                        "gas": "CO2",
                    },
                },
            },
        )
    finally:
        con.close()

    client = TestClient(app)
    r = client.get("/plot/multi-info", params={"relative_path": rel})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_multi"] is True
    assert data["count"] == 2
    b0 = data["blocks"][0]
    assert b0["current_density_A_cm2"] == pytest.approx(0.05)
    assert b0["potential_V"] == pytest.approx(-0.2)
    assert b0["potential_ref"] == "VRHE"
    assert b0["sample"] == "Cu"  # path-level experimental inherited
    b1 = data["blocks"][1]
    assert b1["gas"] == "CO2"
    field_ids = {f["id"] for f in data["fields"]}
    assert "current_density_A_cm2" in field_ids
    assert "potential_V" in field_ids
    assert "gas" in field_ids


def test_multi_info_non_multi_txt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_root = _env(tmp_path, monkeypatch)
    rel = "batch/plain.txt"
    p = upload_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("Wavenumber\tIntensity\n500\t1\n", encoding="utf-8")
    write_upload_registry(
        upload_root,
        [
            make_registry_item(
                batch_id="batch",
                filename="plain.txt",
                size_bytes=p.stat().st_size,
                owner_user_id="dev",
            ).to_dict()
        ],
    )
    client = TestClient(app)
    r = client.get("/plot/multi-info", params={"relative_path": rel})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["is_multi"] is False
    assert data["blocks"] == []
