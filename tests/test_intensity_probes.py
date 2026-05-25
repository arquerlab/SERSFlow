from __future__ import annotations

import numpy as np
import pytest

from sersflow.core.metrics.intensity_probes import (
    evaluate_spectral_intensity_probes,
    parse_probes,
    preview_feature_keys_for_pipeline,
)
from sersflow.core.spectrum import XY
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep


def test_fixed_linear_interp() -> None:
    xy = XY(x=np.array([100.0, 200.0, 300.0]), y=np.array([1.0, 5.0, 3.0]))
    params = {
        "probes": [
            {
                "id": "a",
                "target_cm1": 200.0,
                "acquisition": "fixed",
                "method": "linear_interp",
                "extrapolation": "nan",
            }
        ]
    }
    out = evaluate_spectral_intensity_probes(xy, params)
    assert out["I_a"] == 5.0


def test_fixed_nearest() -> None:
    xy = XY(x=np.array([300.0, 100.0, 200.0]), y=np.array([3.0, 1.0, 5.0]))
    params = {
        "probes": [
            {
                "id": "a",
                "target_cm1": 210.0,
                "acquisition": "fixed",
                "method": "nearest",
                "extrapolation": "nan",
            }
        ]
    }
    out = evaluate_spectral_intensity_probes(xy, params)
    assert out["I_a"] == 5.0


def test_nearest_peak_picks_closest() -> None:
    x = np.linspace(100, 400, 50)
    y = np.zeros_like(x)
    y[20] = 10.0  # peak near ~220
    y[30] = 8.0
    xy = XY(x=x, y=y)
    params = {
        "probes": [
            {
                "id": "pk",
                "target_cm1": 225.0,
                "acquisition": "nearest_peak",
                "window_cm1": 80.0,
                "peak_find": {"prominence": 0.1},
            }
        ]
    }
    out = evaluate_spectral_intensity_probes(xy, params)
    assert out["I_pk"] == 10.0
    assert out["peak_pos_cm1_pk"] is not None


def test_nearest_peak_no_peak_found_peak_pos_falls_back_to_target() -> None:
    """When find_peaks finds nothing, peak_pos uses target_cm1 so exports stay numeric."""
    x = np.linspace(100.0, 400.0, 50)
    y = np.ones_like(x)  # no peaks with default prominence
    xy = XY(x=x, y=y)
    target = 250.0
    params = {
        "probes": [
            {
                "id": "np",
                "target_cm1": target,
                "acquisition": "nearest_peak",
                "window_cm1": 200.0,
                "peak_find": {"prominence": 1.0},
            }
        ]
    }
    out = evaluate_spectral_intensity_probes(xy, params)
    assert out["I_np"] is None
    assert out["peak_pos_cm1_np"] == target


def test_parse_probes_requires_list() -> None:
    with pytest.raises(ValueError):
        parse_probes({})


def test_preview_keys_multi_step() -> None:
    pl = Pipeline(
        steps=[
            PipelineStep(
                name="spectral_intensities",
                params={"probes": [{"id": "a", "target_cm1": 100.0, "acquisition": "fixed"}]},
            ),
            PipelineStep(
                name="spectral_intensities",
                params={"probes": [{"id": "b", "target_cm1": 200.0, "acquisition": "fixed"}]},
            ),
        ]
    )
    keys = preview_feature_keys_for_pipeline(pl)
    assert "s0_I_a" in keys
    assert "s1_I_b" in keys
