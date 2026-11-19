"""Route-level smoke tests for the spectrum-matrix multivariate endpoints (store layer stubbed)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

from sersflow.api.routers import explore as ex
from sersflow.api.schemas.explore import (
    FPCADiscreteRequest,
    MatrixPreprocess,
    Spectrum2DCOSRequest,
    SpectrumCorrelationRequest,
    SpectrumMCRRequest,
    SpectrumNMFRequest,
)


@pytest.fixture
def matrix_env(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    x = np.linspace(100, 1000, 90)
    c = np.linspace(1, 0, 24)
    s1 = np.exp(-0.5 * ((x - 300) / 20) ** 2)
    s2 = np.exp(-0.5 * ((x - 700) / 25) ** 2)
    Y = np.outer(c, s1) + np.outer(1 - c, s2) + 0.003 * rng.standard_normal((24, 90)) + 0.05
    npz = tmp_path / "matrix.npz"
    np.savez_compressed(npz, Y=Y.astype(np.float32), x=x, spectrum_ids=np.array([f"s{i}" for i in range(24)]))
    mj = SimpleNamespace(status="completed", npz_path=str(npz), dataset_id="ds")
    monkeypatch.setattr(ex, "get_matrix_job_for_user", lambda *_a, **_k: mj)
    monkeypatch.setattr(ex, "current_user_id", lambda *_a, **_k: "dev")
    monkeypatch.setattr(ex, "_artifact_subdir", lambda sub: str(tmp_path / sub))
    monkeypatch.setattr(ex, "create_explore_run", lambda **_k: "eid1")
    monkeypatch.setattr(ex, "finish_explore_run", lambda **_k: None)
    monkeypatch.setattr(ex, "prune_explore_runs", lambda **_k: None)
    return SimpleNamespace(req=object())


def test_correlation_route(matrix_env):
    out = ex.post_spectrum_correlation(
        SpectrumCorrelationRequest(
            matrix_job_id="m", axis="channels", method="spearman", reorder=True,
            preprocess=MatrixPreprocess(bin=2, row_norm="area"),
        ),
        matrix_env.req,
    )
    r = out.results
    assert not r["reordered"] and len(r["labels"]) == 45 and np.asarray(r["R"]).shape == (45, 45)
    assert np.all(np.diff(r["x"]) > 0)
    assert any("bin" in s for s in r["matrix_preprocessing"]["steps"])


def test_pca_with_varimax_and_preprocess(matrix_env):
    out = ex.post_fpca_discrete(
        FPCADiscreteRequest(
            matrix_job_id="m", n_components=3, rotation="varimax",
            preprocess=MatrixPreprocess(crop=[150, 950], smooth_window=5, scale="pareto"),
        ),
        matrix_env.req,
    )
    r = out.results
    assert r["rotation"]["applied"] and r["n_components"] == 3
    assert min(r["x_cm1"]) >= 145
    assert r["matrix_preprocessing"]["steps"]


def test_varimax_rejected_for_spca(matrix_env):
    with pytest.raises(HTTPException) as e:
        ex.post_fpca_discrete(
            FPCADiscreteRequest(matrix_job_id="m", method="spca", rotation="varimax"), matrix_env.req
        )
    assert e.value.status_code == 400


def test_nmf_and_mcr_routes(matrix_env):
    nmf = ex.post_spectrum_nmf(
        SpectrumNMFRequest(matrix_job_id="m", n_components=2, n_starts=2, scan_k=[1, 2, 3]), matrix_env.req
    ).results
    assert nmf["r2"] > 0.95 and len(nmf["scan"]) == 3
    mcr = ex.post_spectrum_mcr(
        SpectrumMCRRequest(matrix_job_id="m", n_components=2, closure=True, fixed_spectrum_ids=["s0"]),
        matrix_env.req,
    ).results
    assert mcr["fixed_spectrum_ids"] == ["s0"] and mcr["r2"] > 0.9
    with pytest.raises(HTTPException):
        ex.post_spectrum_mcr(
            SpectrumMCRRequest(matrix_job_id="m", fixed_spectrum_ids=["nope"]), matrix_env.req
        )


def test_2dcos_sample_order_and_missing_column_args(matrix_env):
    r = ex.post_spectrum_2dcos(
        Spectrum2DCOSRequest(matrix_job_id="m", preprocess=MatrixPreprocess(bin=3)), matrix_env.req
    ).results
    assert r["n_spectra"] == 24 and len(r["synchronous"]) == 30 and not r["resampled"]
    with pytest.raises(HTTPException) as e:
        ex.post_spectrum_2dcos(
            Spectrum2DCOSRequest(matrix_job_id="m", perturbation="observation_column"), matrix_env.req
        )
    assert e.value.status_code == 400


def test_2dcos_observation_column(matrix_env, monkeypatch):
    monkeypatch.setattr(ex, "get_run_for_user", lambda *_a, **_k: SimpleNamespace(status="completed"))
    t = np.sort(np.random.default_rng(2).uniform(0, 1, 24))
    monkeypatch.setattr(
        ex,
        "load_explore_feature_matrix",
        lambda _rid, cols: (t[:, None], [f"s{i}" for i in range(24)], cols),
    )
    r = ex.post_spectrum_2dcos(
        Spectrum2DCOSRequest(
            matrix_job_id="m", perturbation="observation_column", analysis_run_id="r", perturbation_column="E_V",
            preprocess=MatrixPreprocess(bin=3),
        ),
        matrix_env.req,
    ).results
    assert r["perturbation_label"] == "E_V" and r["resampled"]


def test_async_dispatch_runs_in_background_and_records_status(matrix_env, monkeypatch):
    import time

    done = {}
    monkeypatch.setattr(ex, "finish_explore_run", lambda **k: done.update(k))
    out = ex.post_spectrum_nmf(
        SpectrumNMFRequest(matrix_job_id="m", n_components=2, n_starts=1, run_async=True), matrix_env.req
    )
    assert out.results == {"status": "running"} and out.explore_id == "eid1"
    for _ in range(100):
        if done:
            break
        time.sleep(0.05)
    assert done.get("status") == "completed"


def test_async_failure_is_recorded(matrix_env, monkeypatch):
    import time

    done = {}
    monkeypatch.setattr(ex, "finish_explore_run", lambda **k: done.update(k))
    monkeypatch.setattr(ex, "run_nmf", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    ex.post_spectrum_nmf(SpectrumNMFRequest(matrix_job_id="m", run_async=True), matrix_env.req)
    for _ in range(100):
        if done:
            break
        time.sleep(0.05)
    assert done.get("status") == "failed" and "boom" in done.get("error", "")


def test_spectra_list_endpoint(matrix_env, monkeypatch):
    monkeypatch.setattr(
        ex, "spectrum_export_lookup",
        lambda _d: {"s0": {"relative_path": "a/b/file.txt", "record_index": 3, "axis_z": 1.5}},
    )
    out = ex.list_matrix_job_spectra("m", matrix_env.req, limit=5)
    assert out["n"] == 24 and out["truncated"] and len(out["items"]) == 5
    assert out["items"][0]["label"] == "#0 · file.txt[3] · z=1.5"
    assert out["items"][1]["label"] == "#1"


def test_sparse_pca_async_and_varimax_guard(matrix_env, monkeypatch):
    import time

    done = {}
    monkeypatch.setattr(ex, "finish_explore_run", lambda **k: done.update(k))
    out = ex.post_fpca_discrete(
        FPCADiscreteRequest(matrix_job_id="m", method="spca", n_components=2, run_async=True), matrix_env.req
    )
    assert out.results == {"status": "running"}
    for _ in range(200):
        if done:
            break
        time.sleep(0.05)
    assert done.get("status") == "completed"
