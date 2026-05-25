from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from sersflow.core.pipeline import steps as pipeline_steps
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import _run_indexed_steps_for_spectrum
from sersflow.core.spectrum import XY


def _xy() -> XY:
    return XY(
        x=np.asarray([100.0, 200.0, 300.0], dtype=float),
        y=np.asarray([20.0, 50.0, 90.0], dtype=float),
    )


def _run_steps(steps: list[dict[str, Any]], *, cache: InProcessLRUCache[XY] | None = None) -> XY:
    out, _, _ = _run_indexed_steps_for_spectrum(
        xy_initial=_xy(),
        input_hash="input-hash",
        steps_list=steps,
        spectrum_id="s1",
        cache=cache,
        namespace="test",
        up_to_step=None,
        collect_steps=None,
    )
    return out


def _patch_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_correct_baseline(intensity: np.ndarray, method: str = "mor", **kwargs: Any) -> tuple[np.ndarray, dict]:
        scale = float(kwargs.get("half_window", 10.0))
        baseline = np.asarray([scale, scale * 2.0, scale * 4.0], dtype=float)
        return np.asarray(intensity, dtype=float) - baseline, {"baseline": baseline}

    monkeypatch.setattr(pipeline_steps, "correct_baseline", fake_correct_baseline)


def test_spectrum_point_and_legacy_baseline_normalize_by_spectrum_y() -> None:
    legacy = _run_steps(
        [
            {
                "name": "normalize",
                "params": {"method": "baseline", "baseline_point": 200.0},
                "enabled": True,
            }
        ]
    )
    current = _run_steps(
        [
            {
                "name": "normalize",
                "params": {"method": "spectrum_point", "point_x": 200.0},
                "enabled": True,
            }
        ]
    )

    expected = _xy().y / 50.0
    np.testing.assert_allclose(legacy.y, expected)
    np.testing.assert_allclose(current.y, expected)


def test_baseline_point_normalizes_by_selected_baseline_y(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_baseline(monkeypatch)
    out = _run_steps(
        [
            {
                "name": "baseline",
                "params": {"method": "mor", "half_window": 10},
                "enabled": True,
                "step_id": "base",
            },
            {
                "name": "normalize",
                "params": {"method": "baseline_point", "baseline_step_id": "base", "point_x": 200.0},
                "enabled": True,
                "input_from": "initial",
                "step_id": "norm",
            },
        ]
    )

    np.testing.assert_allclose(out.y, _xy().y / 20.0)


def test_baseline_point_rejects_missing_or_invalid_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_baseline(monkeypatch)
    with pytest.raises(ValueError, match="baseline_step_id must be provided"):
        _run_steps(
            [
                {
                    "name": "normalize",
                    "params": {"method": "baseline_point", "point_x": 200.0},
                    "enabled": True,
                }
            ]
        )

    with pytest.raises(ValueError, match="must refer to a baseline step"):
        _run_steps(
            [
                {
                    "name": "crop",
                    "params": {"min_x": 100.0, "max_x": 300.0},
                    "enabled": True,
                    "step_id": "not-base",
                },
                {
                    "name": "normalize",
                    "params": {"method": "baseline_point", "baseline_step_id": "not-base", "point_x": 200.0},
                    "enabled": True,
                    "step_id": "norm",
                },
            ]
        )


def test_baseline_point_cache_includes_referenced_baseline_lineage(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_baseline(monkeypatch)
    cache: InProcessLRUCache[XY] = InProcessLRUCache(max_items=64)

    first = _run_steps(
        [
            {
                "name": "baseline",
                "params": {"method": "mor", "half_window": 10},
                "enabled": True,
                "step_id": "base",
            },
            {
                "name": "normalize",
                "params": {"method": "baseline_point", "baseline_step_id": "base", "point_x": 200.0},
                "enabled": True,
                "input_from": "initial",
                "step_id": "norm",
            },
        ],
        cache=cache,
    )
    second = _run_steps(
        [
            {
                "name": "baseline",
                "params": {"method": "mor", "half_window": 20},
                "enabled": True,
                "step_id": "base",
            },
            {
                "name": "normalize",
                "params": {"method": "baseline_point", "baseline_step_id": "base", "point_x": 200.0},
                "enabled": True,
                "input_from": "initial",
                "step_id": "norm",
            },
        ],
        cache=cache,
    )

    np.testing.assert_allclose(first.y, _xy().y / 20.0)
    np.testing.assert_allclose(second.y, _xy().y / 40.0)
