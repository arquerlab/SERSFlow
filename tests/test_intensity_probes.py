from __future__ import annotations

import numpy as np
import pytest

from sersflow.core.metrics.intensity_probes import (
    collect_spectral_intensity_features_for_pipeline,
    evaluate_spectral_intensity_probes,
    parse_probes,
    preview_feature_keys_for_pipeline,
    resolve_baseline_curve_xy,
)
from sersflow.core.pipeline.engine import _run_indexed_steps_for_spectrum
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


def test_baseline_source_samples_baseline_curve() -> None:
    signal_xy = XY(x=np.array([100.0, 200.0, 300.0]), y=np.array([10.0, 50.0, 30.0]))
    baseline_xy = XY(x=np.array([100.0, 200.0, 300.0]), y=np.array([2.0, 2.0, 2.0]))
    params = {
        "probes": [
            {
                "id": "b",
                "target_cm1": 200.0,
                "acquisition": "fixed",
                "method": "linear_interp",
                "source": "baseline",
                "baseline_step_id": "base-step",
            }
        ]
    }
    out = evaluate_spectral_intensity_probes(
        signal_xy,
        params,
        baseline_curves={"base-step": baseline_xy},
    )
    assert out["I_b"] == 2.0


def test_parse_probes_baseline_requires_step_id() -> None:
    with pytest.raises(ValueError, match="baseline_step_id"):
        parse_probes({"probes": [{"target_cm1": 100.0, "source": "baseline"}]})


def test_resolve_baseline_curve_xy(monkeypatch: pytest.MonkeyPatch) -> None:
    from sersflow.core.pipeline import steps as pipeline_steps

    def fake_correct_baseline(intensity: np.ndarray, method: str = "mor", **kwargs: object) -> tuple[np.ndarray, dict]:
        baseline = np.asarray([10.0, 20.0, 30.0], dtype=float)
        return np.asarray(intensity, dtype=float) - baseline, {"baseline": baseline}

    monkeypatch.setattr(pipeline_steps, "correct_baseline", fake_correct_baseline)

    pipeline = Pipeline(
        steps=[
            PipelineStep(
                name="baseline",
                step_id="base-step",
                params={"method": "mor", "half_window": 10},
            ),
            PipelineStep(
                name="spectral_intensities",
                step_id="int-step",
                params={"probes": [{"id": "p1", "target_cm1": 200.0, "acquisition": "fixed"}]},
            ),
        ]
    )
    baseline_input = XY(x=np.array([100.0, 200.0, 300.0]), y=np.array([30.0, 70.0, 110.0]))
    _, _, per_step_input = _run_indexed_steps_for_spectrum(
        xy_initial=baseline_input,
        input_hash="input-hash",
        steps_list=[s.model_dump() for s in pipeline.steps],
        spectrum_id="s1",
        cache=None,
        namespace="test",
        up_to_step=None,
        collect_steps=None,
        step_nums=[1, 2],
        collect_step_inputs=True,
    )
    curve = resolve_baseline_curve_xy(
        pipeline,
        "base-step",
        per_step_input_xy=per_step_input,
        before_index=1,
    )
    assert curve.y[1] == 20.0


def test_collect_signal_and_baseline_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    from sersflow.core.pipeline import steps as pipeline_steps

    def fake_correct_baseline(intensity: np.ndarray, method: str = "mor", **kwargs: object) -> tuple[np.ndarray, dict]:
        baseline = np.asarray([10.0, 20.0, 30.0], dtype=float)
        return np.asarray(intensity, dtype=float) - baseline, {"baseline": baseline}

    monkeypatch.setattr(pipeline_steps, "correct_baseline", fake_correct_baseline)

    pipeline = Pipeline(
        steps=[
            PipelineStep(
                name="baseline",
                step_id="base-step",
                params={"method": "mor", "half_window": 10},
            ),
            PipelineStep(
                name="spectral_intensities",
                step_id="int-step",
                params={
                    "probes": [
                        {
                            "id": "peak",
                            "target_cm1": 200.0,
                            "acquisition": "fixed",
                            "method": "nearest",
                            "source": "signal",
                        },
                        {
                            "id": "base",
                            "target_cm1": 200.0,
                            "acquisition": "fixed",
                            "method": "nearest",
                            "source": "baseline",
                            "baseline_step_id": "base-step",
                        },
                    ]
                },
            ),
        ]
    )
    xy_initial = XY(x=np.array([100.0, 200.0, 300.0]), y=np.array([30.0, 70.0, 110.0]))
    final_xy, _, per_step_input = _run_indexed_steps_for_spectrum(
        xy_initial=xy_initial,
        input_hash="input-hash",
        steps_list=[s.model_dump() for s in pipeline.steps],
        spectrum_id="s1",
        cache=None,
        namespace="test",
        up_to_step=None,
        collect_steps=None,
        step_nums=[1, 2],
        collect_step_inputs=True,
    )
    keys, feats = collect_spectral_intensity_features_for_pipeline(
        final_xy,
        pipeline,
        per_step_input_xy=per_step_input,
    )
    assert "I_peak" in keys
    assert "I_base" in keys
    assert feats["I_peak"] == 50.0
    assert feats["I_base"] == 20.0
    assert feats["I_peak"] != feats["I_base"]
