from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.infra.sessions_store import create_session, get_session, update_session_pipeline


def _fitting_params_minimal() -> dict:
    """Flattened fitting params (same shape as UI after Save pipeline)."""
    return {
        "output_mode": "fit",
        "fill_opacity": 0.15,
        "initial_guess_mode": "default",
        "components": [{"component_id": "g1", "component_type": "gaussian"}],
        "p0": [500.0, 80.0, 10.0],
        "bounds_lower": [480.0, 0.0, 1e-6],
        "bounds_upper": [520.0, None, 50.0],
    }


def _spectral_intensities_params_minimal() -> dict:
    """Matches frontend defaultSpectralIntensitiesParams (first probe)."""
    return {
        "probes": [
            {
                "id": "p1",
                "target_cm1": 1000.0,
                "acquisition": "fixed",
                "method": "linear_interp",
                "extrapolation": "nan",
                "no_peak_fallback": "none",
                "peak_find": {},
            }
        ]
    }


def test_session_pipeline_put_get_roundtrip_fitting_and_spectral_intensities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))

    pipe_in = Pipeline(
        steps=[
            PipelineStep(name="crop", params={"min_x": 100.0, "max_x": 2000.0}),
            PipelineStep(name="fitting", params=_fitting_params_minimal()),
            PipelineStep(name="spectral_intensities", params=_spectral_intensities_params_minimal()),
        ]
    )
    rec = create_session(dataset_id="ds_x", pipeline=Pipeline(steps=[]), subset=SubsetStrategy(kind="all"))
    updated = update_session_pipeline(rec.session_id, pipe_in)
    assert updated is not None

    loaded = get_session(rec.session_id)
    assert loaded is not None
    assert loaded.pipeline.model_dump() == pipe_in.model_dump()


def test_default_spectral_intensities_pipeline_validates() -> None:
    """UI default intensities template must validate as Pipeline."""
    raw = {
        "steps": [
            {
                "name": "spectral_intensities",
                "params": _spectral_intensities_params_minimal(),
                "enabled": True,
            },
        ]
    }
    Pipeline.model_validate(raw)
