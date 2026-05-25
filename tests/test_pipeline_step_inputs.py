"""Tests for per-step pipeline input XY (used by analysis feature extraction)."""

from __future__ import annotations

import numpy as np

from sersflow.core.pipeline.engine import _run_indexed_steps_for_spectrum
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums
from sersflow.core.spectrum import XY


def test_collect_step_inputs_second_crop_sees_first_crop_output() -> None:
    """Later crop with default input_from=previous must record that step's input as the prior crop output."""
    x = np.linspace(0.0, 1000.0, 1000)
    y = np.ones_like(x)
    xy0 = XY(x=x, y=y)
    steps = [
        {"name": "crop", "params": {"min_x": 0.0, "max_x": 400.0}, "enabled": True},
        {"name": "crop", "params": {"min_x": 200.0, "max_x": 300.0}, "enabled": True},
    ]
    sns = assign_pipeline_step_nums(steps)
    final, _, per_in = _run_indexed_steps_for_spectrum(
        xy_initial=xy0,
        input_hash="testhash",
        steps_list=steps,
        spectrum_id="sid",
        cache=None,
        namespace="ns",
        up_to_step=None,
        collect_steps=None,
        step_nums=sns,
        collect_step_inputs=True,
    )
    assert float(per_in[sns[0]].x.max()) > 500.0  # input to first crop is full range
    assert float(per_in[sns[1]].x.max()) <= 400.0  # input to second crop is after first crop
    assert 200.0 <= float(final.x.min()) <= 250.0
    assert 250.0 <= float(final.x.max()) <= 300.0


def test_collect_intermediate_by_token_step_num() -> None:
    """collect_steps supports tokens like 'crop__2' for specific occurrences."""
    x = np.linspace(0.0, 1000.0, 1000)
    y = np.ones_like(x)
    xy0 = XY(x=x, y=y)
    steps = [
        {"name": "crop", "params": {"min_x": 0.0, "max_x": 400.0}, "enabled": True},
        {"name": "crop", "params": {"min_x": 200.0, "max_x": 300.0}, "enabled": True},
    ]
    sns = assign_pipeline_step_nums(steps)
    _final, per_spec, _per_in = _run_indexed_steps_for_spectrum(
        xy_initial=xy0,
        input_hash="testhash",
        steps_list=steps,
        spectrum_id="sid",
        cache=None,
        namespace="ns",
        up_to_step=None,
        collect_steps={"crop__2"},
        step_nums=sns,
        collect_step_inputs=False,
    )
    assert "crop__2" in per_spec
    assert per_spec["crop__2"].x.size > 0
