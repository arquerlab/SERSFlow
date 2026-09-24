"""Payload and contract helper tests."""

from __future__ import annotations

import pytest

from sersflow.mcp import summarize
from sersflow.mcp.tools.explore import _validate_matrix_args


def test_explore_result_truncates_matrices() -> None:
    big = [[float(i) for i in range(50)] for _ in range(50)]
    out = summarize.explore_result(
        {
            "explore_id": "e1",
            "artifact_dir": "/secret/artifacts/e1",
            "results": {"corr": big, "method": "pearson", "n": 10},
        }
    )
    assert out["explore_id"] == "e1"
    assert "artifact_dir" not in out
    assert "corr" not in (out.get("results") or {})
    assert "corr_shape" in out["summary"] or "result_keys" in out["summary"]
    assert out["scalars"].get("method") == "pearson"
    assert out["scalars"].get("n") == 10


def test_matrix_args_validation() -> None:
    with pytest.raises(ValueError, match="analysis_run_id"):
        _validate_matrix_args(
            dataset_id=None, analysis_run_id=None, session_id=None, pipeline=None
        )
    with pytest.raises(ValueError, match="dataset_id"):
        _validate_matrix_args(
            dataset_id="ds", analysis_run_id=None, session_id=None, pipeline=None
        )
    _validate_matrix_args(
        dataset_id="ds", analysis_run_id=None, session_id="s1", pipeline=None
    )
    _validate_matrix_args(
        dataset_id=None, analysis_run_id="run1", session_id=None, pipeline=None
    )


def test_matrix_job_summary() -> None:
    s = summarize.matrix_job_summary(
        {"matrix_job_id": "mj", "status": "completed", "error": None, "extra_blob": "x" * 100}
    )
    assert s["matrix_job_id"] == "mj"
    assert s["status"] == "completed"
    assert "extra_blob" not in s
