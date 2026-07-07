from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from unittest.mock import MagicMock

from sersflow.api.middleware.auth import DEV_USER_ID

from sersflow.api.routers import explore as explore_router
from sersflow.api.schemas.explore import MatrixExportRequest
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.sessions_service import pipeline_hash, subset_hash
from sersflow.infra.analysis_store import create_run_pending, update_run_status
from sersflow.infra.explore_store import create_matrix_job_pending, get_matrix_job


def _mock_request() -> MagicMock:
    req = MagicMock()
    req.state.user_id = DEV_USER_ID
    return req


def test_matrix_job_can_store_pipeline_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "m.db"))

    p = Pipeline(steps=[{"name": "crop", "enabled": True, "params": {"min_cm1": 100, "max_cm1": 2000}}])  # type: ignore[arg-type]
    jid = create_matrix_job_pending(
        dataset_id="ds_x",
        session_id=None,
        pipeline_hash="ph_x",
        pipeline_json=p.model_dump_json(),
        subset_hash="sh_x",
        up_to_step=None,
    )
    rec = get_matrix_job(jid)
    assert rec is not None
    assert rec.session_id is None
    assert rec.pipeline_json is not None


def test_matrix_job_from_analysis_run_uses_stored_pipeline_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setattr(explore_router, "execute_matrix_export_job", lambda _jid: None)

    p = Pipeline(steps=[{"name": "normalize", "enabled": True, "params": {"method": "max"}}])  # type: ignore[arg-type]
    run_id = create_run_pending(
        dataset_id="ds_x",
        session_id=None,
        pipeline_hash=pipeline_hash(p),
        subset_hash=subset_hash(SubsetStrategy(kind="all")),
        pipeline_json=p.model_dump_json(),
        label=None,
        pinned=True,
        client_job_key=None,
        params={"subset": SubsetStrategy(kind="all").model_dump()},
    )
    update_run_status(run_id=run_id, status="completed", finished=True)

    resp = explore_router.post_matrix_job(MatrixExportRequest(analysis_run_id=run_id), _mock_request())
    rec = get_matrix_job(resp.matrix_job_id)

    assert rec is not None
    assert rec.dataset_id == "ds_x"
    assert rec.session_id is None
    assert rec.pipeline_json == p.model_dump_json()
    assert rec.pipeline_hash == pipeline_hash(p)


def test_matrix_job_from_analysis_run_requires_pipeline_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "m.db"))
    run_id = create_run_pending(
        dataset_id="ds_x",
        session_id="sess_x",
        pipeline_hash="ph_x",
        subset_hash="sh_x",
        pipeline_json=None,
        label=None,
        pinned=True,
        client_job_key=None,
        params=None,
    )
    update_run_status(run_id=run_id, status="completed", finished=True)

    with pytest.raises(HTTPException) as exc:
        explore_router.post_matrix_job(MatrixExportRequest(analysis_run_id=run_id), _mock_request())

    assert exc.value.status_code == 400
    assert "stored pipeline snapshot" in str(exc.value.detail)
