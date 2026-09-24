"""Error payload shape tests."""

from __future__ import annotations

from sersflow.client.exceptions import JobTimeoutError
from sersflow.mcp.errors import timeout_payload


def test_timeout_resume_hint() -> None:
    exc = JobTimeoutError(job_id="job_1", timeout_s=10.0, last_status="running")
    payload = timeout_payload(
        exc,
        status_tool="get_analysis_jobs",
        wait_tool="post_analysis_jobs_wait",
    )
    assert payload["ok"] is False
    assert payload["error"] == "timeout"
    assert payload["resume"]["tool"] == "get_analysis_jobs"
    assert payload["resume"]["args"]["job_id"] == "job_1"
    assert payload["resume"]["alternate_tool"] == "post_analysis_jobs_wait"
    assert "get_analysis_jobs" in payload["resume"]["hint"]
    assert "post_analysis_jobs_wait" in payload["resume"]["hint"]


def test_timeout_resume_matrix_arg_name() -> None:
    exc = JobTimeoutError(job_id="mj1", timeout_s=5.0, last_status="running")
    payload = timeout_payload(
        exc,
        status_tool="get_explore_matrix_jobs",
        wait_tool="post_explore_matrix_jobs_wait",
    )
    assert payload["resume"]["args"] == {"matrix_job_id": "mj1"}
    assert "matrix_job_id" in payload["resume"]["hint"]
