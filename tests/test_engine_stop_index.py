"""Previews must not run steps after the one that was asked for (fits, calibration cohorts, cohort steps)."""

from __future__ import annotations

from sersflow.core.pipeline.engine import _stop_index

_STEPS = [
    {"name": "crop", "step_id": "a", "enabled": True},
    {"name": "group_average", "step_id": "b", "enabled": True},
    {"name": "x_axis_calibration", "step_id": "c", "enabled": True},
    {"name": "baseline", "step_id": "d", "enabled": False},
    {"name": "fitting", "step_id": "e", "enabled": True},
]
_NUMS = [1, 2, 3, 4, 5]


def test_up_to_step_matches_name_id_and_token() -> None:
    assert _stop_index(_STEPS, _NUMS, "x_axis_calibration", None) == 2
    assert _stop_index(_STEPS, _NUMS, "c", None) == 2
    assert _stop_index(_STEPS, _NUMS, "x_axis_calibration__3", None) == 2
    # cohort step: the engine passes it through, but nothing after it is needed
    assert _stop_index(_STEPS, _NUMS, "group_average", None) == 1
    # disabled steps never match; unknown tokens never cut the run short
    assert _stop_index(_STEPS, _NUMS, "baseline", None) is None
    assert _stop_index(_STEPS, _NUMS, "nope", None) is None


def test_collect_steps_stop_at_last_requested_step() -> None:
    assert _stop_index(_STEPS, _NUMS, None, {"x_axis_calibration__3"}) == 2
    assert _stop_index(_STEPS, _NUMS, None, {"crop__1", "x_axis_calibration__3"}) == 2
    assert _stop_index(_STEPS, _NUMS, None, {"fitting"}) == 4
    # a token that matches nothing (e.g. the raw sentinel) means: run everything
    assert _stop_index(_STEPS, _NUMS, None, {"crop__1", "__raw__"}) is None
    assert _stop_index(_STEPS, _NUMS, None, None) is None
