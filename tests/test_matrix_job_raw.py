"""Matrix export supports up_to_step=__raw__ (QC cohort, no XY transforms)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.services.datasets_service import create_dataset_from_uploads
from sersflow.api.services.matrix_export_runner import execute_matrix_export_job
from sersflow.infra.explore_store import create_matrix_job_pending, get_matrix_job


def _spectrum_txt(path: Path, *, scale: float) -> None:
    lines = ["wn\tint", f"100\t{1.0 * scale}", f"200\t{2.0 * scale}", f"300\t{3.0 * scale}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SERSFLOW_AUTH_DISABLED", "1")
    upload_root = tmp_path / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))
    upload_root.mkdir(parents=True, exist_ok=True)
    return TestClient(app), upload_root


def test_matrix_job_raw_skips_xy_pipeline_steps(client, tmp_path: Path) -> None:
    api, upload_root = client
    batch = "rawmx"
    a = upload_root / batch / "a.txt"
    b = upload_root / batch / "b.txt"
    a.parent.mkdir(parents=True, exist_ok=True)
    _spectrum_txt(a, scale=1.0)
    _spectrum_txt(b, scale=2.0)

    rec, skipped = create_dataset_from_uploads(
        DatasetCreateRequest(
            relative_paths=[f"{batch}/a.txt", f"{batch}/b.txt"],
            metadata=DatasetMetadata(name="raw-matrix"),
        ),
        owner_user_id="dev",
    )
    assert not skipped
    assert len(rec.spectra) == 2

    pipe = Pipeline(
        steps=[
            PipelineStep(name="normalize", params={"method": "max"}, enabled=True),
        ]
    )
    jid = create_matrix_job_pending(
        dataset_id=rec.dataset_id,
        session_id=None,
        pipeline_hash="ph",
        pipeline_json=pipe.model_dump_json(),
        subset_hash="sh",
        up_to_step="__raw__",
    )
    execute_matrix_export_job(jid)
    job = get_matrix_job(jid)
    assert job is not None
    assert job.status == "completed", job.error
    assert job.npz_path

    data = np.load(job.npz_path, allow_pickle=True)
    Y = np.asarray(data["Y"], dtype=np.float64)
    x = np.asarray(data["x"], dtype=np.float64)
    assert x.tolist() == [100.0, 200.0, 300.0]
    # Raw intensities (not max-normalized): scales 1 and 2 preserved.
    assert Y.shape == (2, 3)
    rows = {tuple(np.round(row, 6)) for row in Y}
    assert (1.0, 2.0, 3.0) in rows
    assert (2.0, 4.0, 6.0) in rows

    # Full pipeline (empty up_to_step) would max-normalize both rows to [1/3, 2/3, 1].
    jid2 = create_matrix_job_pending(
        dataset_id=rec.dataset_id,
        session_id=None,
        pipeline_hash="ph2",
        pipeline_json=pipe.model_dump_json(),
        subset_hash="sh",
        up_to_step=None,
    )
    execute_matrix_export_job(jid2)
    job2 = get_matrix_job(jid2)
    assert job2 is not None and job2.status == "completed", job2.error if job2 else None
    Y2 = np.asarray(np.load(job2.npz_path, allow_pickle=True)["Y"], dtype=np.float64)
    for row in Y2:
        np.testing.assert_allclose(row, [1.0 / 3.0, 2.0 / 3.0, 1.0], rtol=0, atol=1e-5)

    # API accepts __raw__ as well.
    r = api.post(
        "/explore/matrix-jobs",
        json={
            "dataset_id": rec.dataset_id,
            "pipeline": pipe.model_dump(),
            "up_to_step": "__raw__",
            "async": False,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("completed", "queued", "running")
