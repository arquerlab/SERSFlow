"""Mocked tool smoke: upload → dataset → analysis wait → export."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from sersflow.client import SersflowClient
from sersflow.mcp.config import McpConfig
from sersflow.mcp.runtime import RuntimeContext
from sersflow.mcp.tools._util import tool_call


def test_analysis_export_smoke(tmp_path: Path) -> None:
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    job_polls = {"n": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/datasets" and request.method == "GET":
            return httpx.Response(200, json={"items": [], "count": 0})
        if path == "/openapi.json":
            return httpx.Response(200, json={"info": {"version": "0.2.0", "title": "SpecFlow API"}})
        if path == "/io/upload":
            return httpx.Response(200, text="Uploaded 1 file(s) to batch abc123 (0.001 MB).")
        if path == "/datasets" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "dataset": {
                        "dataset_id": "ds1",
                        "spectra": [{"spectrum_id": "s1", "relative_path": "a.txt"}],
                        "metadata": {"name": "demo", "tags": []},
                    },
                    "skipped_files": [],
                },
            )
        if path == "/analysis/runs" and request.method == "POST":
            return httpx.Response(
                200,
                json={"run_id": "run1", "job_id": "job1", "status": "running", "message": None},
            )
        if path == "/analysis/jobs/job1":
            job_polls["n"] += 1
            status = "completed" if job_polls["n"] >= 2 else "running"
            return httpx.Response(
                200,
                json={
                    "job_id": "job1",
                    "run_id": "run1",
                    "status": status,
                    "progress_done": 1,
                    "progress_total": 1,
                    "error": None,
                    "created_at": "t",
                    "updated_at": "t",
                },
            )
        if path == "/analysis/runs/run1/export":
            return httpx.Response(200, content=b"spectrum_id,I_a\ns1,1.0\n")
        return httpx.Response(404, json={"detail": f"unhandled {path}"})

    transport = httpx.MockTransport(handle)
    cfg = McpConfig(
        base_url="http://test",
        export_dir=str(export_dir),
        api_start_enabled=False,
        job_wait_timeout_s=5.0,
        job_poll_interval_s=0.01,
    )
    ctx = RuntimeContext(cfg)
    client = SersflowClient("http://test", transport=transport)
    ctx.client = client
    ctx.auth_mode = "open_or_disabled"
    ctx.server_openapi_version = "0.2.0"
    ctx._ready = True

    sample = tmp_path / "a.txt"
    sample.write_text("x", encoding="utf-8")

    async def _run() -> None:
        def upload():
            from sersflow.mcp import confirm, summarize

            blocked = confirm.check_upload_size(
                [sample], threshold=cfg.upload_confirm_bytes, confirm=False
            )
            assert blocked is None
            res = client.io.upload_files([sample])
            return summarize.upload_result(res)

        up = json.loads(await tool_call(ctx, upload, check_compat=False))
        assert up["ok"] is True
        assert up["batch_id"] == "abc123"

        def create_ds():
            from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
            from sersflow.mcp import summarize

            req = DatasetCreateRequest(
                relative_paths=["a.txt"], metadata=DatasetMetadata(name="demo")
            )
            return summarize.dataset_get(client.datasets.create(req))

        ds = json.loads(await tool_call(ctx, create_ds, check_compat=False))
        assert ds["dataset_id"] == "ds1"

        def create_run():
            from sersflow.api.schemas.analysis import AnalysisRunCreateRequest
            from sersflow.api.schemas.pipeline import Pipeline
            from sersflow.api.schemas.sessions import SubsetStrategy

            req = AnalysisRunCreateRequest(
                dataset_id="ds1",
                pipeline=Pipeline(steps=[]),
                subset=SubsetStrategy(kind="all"),
                async_=True,
            )
            resp = client.analysis.create_run(req)
            return {"ok": True, "run_id": resp.run_id, "job_id": resp.job_id}

        run = json.loads(await tool_call(ctx, create_run, check_compat=False))
        assert run["job_id"] == "job1"

        def wait_job():
            from sersflow.mcp import summarize

            job = client.analysis.wait_for_job("job1", timeout_s=5.0, poll_interval_s=0.01)
            return summarize.job_summary(job)

        waited = json.loads(await tool_call(ctx, wait_job, check_compat=False))
        assert waited["status"] == "completed"

        def export():
            from sersflow.mcp import summarize

            dest = ctx.resolve_export_path(None, "analysis_run1_features.csv")
            client.analysis.export_features_to_file("run1", dest)
            ctx.record_export("analysis:run1", dest)
            return summarize.export_result(path=dest, run_id="run1")

        exported = json.loads(await tool_call(ctx, export, check_compat=False))
        assert exported["ok"] is True
        assert Path(exported["path"]).is_file()

    asyncio.run(_run())
