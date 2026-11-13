"""D1: an analysis run reuses the fit made by the pipeline worker instead of fitting every spectrum twice."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services import analysis_runner
from sersflow.core.metrics import fitting_features
from sersflow.infra.datasets_store import create_dataset
from sersflow.infra.sessions_store import create_session
from sersflow.infra.sqlite_db import connect


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, dict], dict]:
    pytest.importorskip("lmfitxps")
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "b1").mkdir(exist_ok=True)
    x = np.linspace(300.0, 280.0, 200)
    refs = []
    for k in range(3):
        rng = np.random.default_rng(k)
        y = 10.0 + (200.0 + 20 * k) * np.exp(-((x - 290.0) ** 2) / (2 * 1.5**2)) + rng.normal(0.0, 1.0, x.size)
        (tmp_path / "b1" / f"s{k}.txt").write_text(
            "be\tint\n" + "\n".join(f"{a}\t{b}" for a, b in zip(x, y)) + "\n", encoding="utf-8"
        )
        refs.append(SpectrumRef(spectrum_id=f"sp_{k}", relative_path=f"b1/s{k}.txt", record_index=None))
    ds = create_dataset(owner_user_id="dev", metadata=DatasetMetadata(name="fit", technique_family="xps"), spectra=refs)
    pipe = Pipeline(
        steps=[
            PipelineStep(
                name="fitting",
                params={
                    "components": [
                        {"component_id": "bg", "component_type": "shirley_bg"},
                        {"component_id": "p1", "component_type": "gaussian"},
                    ],
                    "p0": [0.001, 0.0, 290.0, 150.0, 3.0],
                    "bounds_lower": [0.0, None, 285.0, 0.0, 0.5],
                    "bounds_upper": [0.01, None, 295.0, None, 8.0],
                    "vary": [True, True, True, True, True],
                    "fit_min_x": 284.0,
                    "fit_max_x": 296.0,
                    "technique_family": "xps",
                },
            )
        ],
        technique_family="xps",
    )
    sess = create_session(dataset_id=ds.dataset_id, pipeline=pipe, subset=SubsetStrategy(kind="all"))
    client = TestClient(app)
    r = client.post("/analysis/runs", json={"dataset_id": ds.dataset_id, "session_id": sess.session_id})
    assert r.status_code in (200, 202), r.text
    run_id = r.json()["run_id"]
    assert client.get(f"/analysis/runs/{run_id}").json()["run"]["status"] == "completed"
    with connect() as con:
        rows = con.execute(
            "SELECT spectrum_id, features_json FROM analysis_spectrum_rows WHERE run_id = ?", (run_id,)
        ).fetchall()
        warnings = con.execute("SELECT warnings_json FROM analysis_runs WHERE run_id = ?", (run_id,)).fetchone()[0]
    return {r["spectrum_id"]: json.loads(r["features_json"]) for r in rows}, json.loads(warnings or "{}")


def test_feature_rows_do_not_fit_a_second_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    real_fit = fitting_features.fit_curve

    def counting_fit(prob):
        calls["n"] += 1
        return real_fit(prob)

    # Patches the API process only: the pipeline workers (separate processes) still fit normally.
    monkeypatch.setattr(fitting_features, "fit_curve", counting_fit)
    monkeypatch.setattr(analysis_runner, "REUSE_WORKER_FITS", True)
    rows, warnings = _run(tmp_path, monkeypatch)
    assert calls["n"] == 0
    assert len(rows) == 3
    assert warnings["fit_failures"]["n_ok"] == 3
    for feats in rows.values():
        assert abs(feats["fit_p1_pos"] - 290.0) < 0.2
        assert feats["fit_p1_pos_stderr"] is not None and feats["fit_p1_area"] is not None


def test_reused_fit_gives_the_same_numbers_as_refitting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    monkeypatch.setattr(analysis_runner, "REUSE_WORKER_FITS", True)
    reused, w_reused = _run(tmp_path / "a", monkeypatch)
    monkeypatch.setattr(analysis_runner, "REUSE_WORKER_FITS", False)
    refit, w_refit = _run(tmp_path / "b", monkeypatch)
    assert reused.keys() == refit.keys() and len(reused) == 3
    for sid in reused:
        assert reused[sid] == refit[sid], sid
    assert w_reused == w_refit
