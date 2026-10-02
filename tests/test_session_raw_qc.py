"""Session run supports up_to_step=__raw__ (QC cohort) and __source__ (true raw)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.services.datasets_service import create_dataset_from_uploads
from tests.test_vms_loader import write_mixed_region_vms


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "sess.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SERSFLOW_AUTH_DISABLED", "1")
    upload_root = tmp_path / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))
    upload_root.mkdir(parents=True, exist_ok=True)
    return TestClient(app), upload_root


def _setup_session_with_c1s_filter(api, upload_root: Path):
    batch = "rawqc"
    dest = upload_root / batch / "mixed.vms"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_mixed_region_vms(dest)
    rel = f"{batch}/mixed.vms"

    rec, skipped = create_dataset_from_uploads(
        DatasetCreateRequest(
            relative_paths=[rel],
            metadata=DatasetMetadata(name="raw-qc"),
            vms_spectrum_mode="all",
        ),
        owner_user_id="dev",
    )
    assert not skipped
    assert len(rec.spectra) == 5

    r = api.post("/sessions", json={"dataset_id": rec.dataset_id})
    assert r.status_code == 200, r.text
    session_id = r.json()["session"]["session_id"]

    pipe = Pipeline(
        technique_family="xps",
        steps=[
            PipelineStep(
                name="metadata_filter",
                params={"filters": [{"field": "xps_region", "op": "in", "values": ["C1s"]}]},
            )
        ]
    )
    r = api.put(f"/sessions/{session_id}/pipeline", json={"pipeline": pipe.model_dump()})
    assert r.status_code == 200, r.text
    return session_id, rec


def test_session_raw_up_to_step_skips_metadata_filter_as_cohort(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """__raw__ applies cohort QC only; metadata_filter is an engine mask, not session QC."""
    api, upload_root = client
    session_id, _rec = _setup_session_with_c1s_filter(api, upload_root)

    r = api.post(
        f"/sessions/{session_id}/run",
        json={"scope": "subset", "return": {"kind": "final"}, "up_to_step": "__raw__"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 5


def test_session_final_applies_metadata_filter_mask(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    api, upload_root = client
    session_id, _rec = _setup_session_with_c1s_filter(api, upload_root)

    r = api.post(
        f"/sessions/{session_id}/run",
        json={"scope": "subset", "return": {"kind": "final"}},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    # Empty-masked spectra are omitted from the session plot payload.
    assert len(items) == 3
    assert all(len(it["x"]) > 0 for it in items)


def test_session_source_up_to_step_skips_qc(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    api, upload_root = client
    session_id, rec = _setup_session_with_c1s_filter(api, upload_root)

    r = api.post(
        f"/sessions/{session_id}/run",
        json={"scope": "subset", "return": {"kind": "final"}, "up_to_step": "__source__"},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    # True raw: all subset spectra, ignoring pipeline transforms including metadata_filter.
    assert len(items) == len(rec.spectra) == 5
