from __future__ import annotations

import pytest

from sersflow.api.schemas.pipeline import PipelineStep


def test_pipeline_step_defaults_omit_new_fields():
    s = PipelineStep(name="crop", params={"min_x": 100.0, "max_x": 200.0})
    assert s.input_from == "previous"
    assert s.after_step_id is None
    assert s.step_id is None


def test_after_step_requires_after_step_id():
    with pytest.raises(ValueError):
        PipelineStep(name="crop", params={"min_x": 100.0, "max_x": 200.0}, input_from="after_step")


def test_normalize_point_params_remain_method_specific_params():
    s = PipelineStep(
        name="normalize",
        params={"method": "baseline_point", "baseline_step_id": "base-step", "point_x": 1000.0},
        step_id="norm-step",
    )
    assert s.step_id == "norm-step"
    assert s.params["method"] == "baseline_point"
    assert s.params["baseline_step_id"] == "base-step"
    assert s.params["point_x"] == 1000.0
