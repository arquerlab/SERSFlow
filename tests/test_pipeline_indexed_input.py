from __future__ import annotations

import uuid
from types import SimpleNamespace

import numpy as np
import pytest

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.core.pipeline.engine import run_pipeline


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    return tmp_path


def _write_linear_spectrum(upload_dir: str) -> SimpleNamespace:
    """X from 100..600 step 100; y matches."""
    (upload_dir / "b").mkdir()
    (upload_dir / "b" / "s.txt").write_text(
        "wn\tint\n"
        "100\t1\n200\t2\n300\t3\n400\t4\n500\t5\n600\t6\n",
        encoding="utf-8",
    )
    return SimpleNamespace(spectrum_id="s1", relative_path="b/s.txt", record_index=None)


def test_second_crop_initial_vs_previous_changes_width(upload_dir):
    ref = _write_linear_spectrum(upload_dir)
    # After c1, x are 200,300,400. A second crop 300–500 on *previous* yields 300,400.
    # The same bounds on *initial* still include 500 from the raw spectrum -> 300,400,500.
    c1 = PipelineStep(
        name="crop",
        params={"min_x": 150.0, "max_x": 400.0},
        enabled=True,
        step_id=str(uuid.uuid4()),
    )
    c2_prev = PipelineStep(
        name="crop",
        params={"min_x": 300.0, "max_x": 500.0},
        enabled=True,
        input_from="previous",
        step_id=str(uuid.uuid4()),
    )
    c2_init = PipelineStep(
        name="crop",
        params={"min_x": 300.0, "max_x": 500.0},
        enabled=True,
        input_from="initial",
        step_id=str(uuid.uuid4()),
    )
    out_prev = run_pipeline(inputs=[ref], pipeline=Pipeline(steps=[c1, c2_prev]))
    out_init = run_pipeline(inputs=[ref], pipeline=Pipeline(steps=[c1, c2_init]))
    assert out_prev["s1"].x.shape == (2,)
    assert out_init["s1"].x.shape == (3,)


def test_after_step_uses_anchor_not_disabled_passthrough(upload_dir):
    """
    Row 1 disabled passes through row 0. Row 2 with after_step -> row 0 should use row 0 output,
    not the pass-through at index 1.
    """
    ref = _write_linear_spectrum(upload_dir)
    sid0 = str(uuid.uuid4())
    sid1 = str(uuid.uuid4())
    sid2 = str(uuid.uuid4())
    s0 = PipelineStep(
        name="crop",
        params={"min_x": 100.0, "max_x": 300.0},
        enabled=True,
        step_id=sid0,
    )
    s1 = PipelineStep(
        name="normalize",
        params={"method": "max"},
        enabled=False,
        step_id=sid1,
    )
    s2 = PipelineStep(
        name="crop",
        params={"min_x": 150.0, "max_x": 250.0},
        enabled=True,
        input_from="after_step",
        after_step_id=sid0,
        step_id=sid2,
    )
    out = run_pipeline(inputs=[ref], pipeline=Pipeline(steps=[s0, s1, s2]))
    # After s0, x are 100,200,300. Cropping 150-250 leaves 200 only -> length 1.
    direct = PipelineStep(
        name="crop",
        params={"min_x": 150.0, "max_x": 250.0},
        enabled=True,
        input_from="previous",
        step_id=str(uuid.uuid4()),
    )
    out_linear = run_pipeline(inputs=[ref], pipeline=Pipeline(steps=[s0, direct]))
    np.testing.assert_allclose(out["s1"].x, out_linear["s1"].x)
    np.testing.assert_allclose(out["s1"].y, out_linear["s1"].y)


def test_disabled_middle_is_pass_through_for_previous_input(upload_dir):
    ref = _write_linear_spectrum(upload_dir)
    s0 = PipelineStep(
        name="crop",
        params={"min_x": 200.0, "max_x": 400.0},
        enabled=True,
        step_id=str(uuid.uuid4()),
    )
    s1_off = PipelineStep(
        name="normalize",
        params={"method": "max"},
        enabled=False,
        step_id=str(uuid.uuid4()),
    )
    s2 = PipelineStep(
        name="normalize",
        params={"method": "max"},
        enabled=True,
        input_from="previous",
        step_id=str(uuid.uuid4()),
    )
    out = run_pipeline(inputs=[ref], pipeline=Pipeline(steps=[s0, s1_off, s2]))
    out_cmp = run_pipeline(inputs=[ref], pipeline=Pipeline(steps=[s0, s2]))
    np.testing.assert_allclose(out["s1"].y, out_cmp["s1"].y)
