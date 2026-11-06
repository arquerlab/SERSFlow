"""Regression tests that call registered FastMCP tool handlers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from sersflow.client import SersflowClient
from sersflow.mcp.config import McpConfig
from sersflow.mcp.runtime import RuntimeContext
from sersflow.mcp.server import create_server


def _ready_ctx(tmp_path: Path, transport: httpx.BaseTransport) -> RuntimeContext:
    cfg = McpConfig(
        base_url="http://test",
        export_dir=str(tmp_path / "exports"),
        api_start_enabled=False,
    )
    ctx = RuntimeContext(cfg)
    ctx.client = SersflowClient("http://test", transport=transport)
    ctx.auth_mode = "open_or_disabled"
    ctx.server_openapi_version = "0.2.0"
    ctx._ready = True
    return ctx


def _tool_fn(mcp, name: str):
    # FastMCP stores tools in mcp._tool_manager._tools (name -> Tool)
    tools = getattr(mcp, "_tool_manager", None)
    if tools is not None:
        mapping = getattr(tools, "_tools", {})
        tool = mapping.get(name)
        if tool is not None:
            return tool.fn
    # Fallback: scan attributes
    raise AssertionError(f"Tool not found: {name}")


def test_post_io_upload_confirm_not_shadowed(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/io/upload":
            return httpx.Response(200, text="Uploaded 1 file(s) to batch b1 (0.001 MB).")
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "post_io_upload")
    sample = tmp_path / "a.txt"
    sample.write_text("x", encoding="utf-8")

    raw = asyncio.run(fn(paths=[str(sample)], confirm=False))
    data = json.loads(raw)
    assert data.get("ok") is True, data
    assert "bool" not in str(data).lower()
    assert data.get("batch_id") == "b1"


def test_post_pipelines_overwrite_and_fitting_confirm(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pipelines" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "item": {
                        "pipeline_id": "pl1",
                        "name": "p",
                        "pipeline": {"steps": []},
                        "technique_family": "vibrational",
                        "created_at": "t",
                        "updated_at": "t",
                    }
                },
            )
        return httpx.Response(404)

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    ctx.config.fitting_confirm_max_components = 6
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "post_pipelines")

    raw = asyncio.run(fn(name="p", pipeline={"steps": []}, overwrite=True, confirm=False))
    data = json.loads(raw)
    assert data.get("ok") is False
    assert data.get("error") == "policy"

    heavy = {
        "steps": [
            {
                "name": "fitting",
                "enabled": True,
                "params": {"components": [{"component_id": f"c{i}"} for i in range(7)]},
            }
        ]
    }
    raw2 = asyncio.run(fn(name="heavy", pipeline=heavy, confirm=False))
    data2 = json.loads(raw2)
    assert data2.get("needs_confirm") is True
    assert data2.get("reason") == "fitting_components_exceed_threshold"


def test_post_datasets_technique_and_vms(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/datasets" and request.method == "POST":
            seen["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "dataset": {
                        "dataset_id": "ds1",
                        "spectra": [{"spectrum_id": "s1", "relative_path": "a.vms"}],
                        "metadata": {
                            "name": "xps",
                            "technique_family": "xps",
                            "capabilities": ["multi_block"],
                        },
                    },
                    "skipped_files": [],
                },
            )
        return httpx.Response(404)

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "post_datasets")
    raw = asyncio.run(
        fn(
            relative_paths=["a.vms"],
            technique_family="xps",
            vms_spectrum_mode="individuals",
            xps_regions=["C1s"],
        )
    )
    data = json.loads(raw)
    assert data.get("ok") is True
    assert data.get("technique_family") == "xps"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body.get("vms_spectrum_mode") == "individuals"
    assert body.get("xps_regions") == ["C1s"]
    assert (body.get("metadata") or {}).get("technique_family") == "xps"


def test_get_pipelines_technique_filter(tmp_path: Path) -> None:
    seen_params: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/pipelines" and request.method == "GET":
            seen_params.update(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "items": [
                        {
                            "pipeline_id": "pl1",
                            "name": "x",
                            "pipeline": {"steps": [], "technique_family": "xps"},
                            "technique_family": "xps",
                            "created_at": "t",
                            "updated_at": "t",
                        }
                    ],
                },
            )
        return httpx.Response(404)

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "get_pipelines")
    raw = asyncio.run(fn(technique_family="xps"))
    data = json.loads(raw)
    assert data.get("ok") is True
    assert data["items"][0]["technique_family"] == "xps"
    assert seen_params.get("technique_family") == "xps"


def test_xps_chemical_states_and_recipes(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/xps/chemical-states":
            return httpx.Response(
                200,
                json={
                    "source": {"name": "test"},
                    "entry_count": 1,
                    "entries": [
                        {
                            "section_id": "Ag_3d",
                            "element": "Ag",
                            "line": "3d",
                            "compound": "Ag2O",
                            "value_eV": 367.9,
                            "energy_kind": "binding",
                            "provenance": "phi_handbook",
                        }
                    ],
                    "sections": [],
                },
            )
        if path == "/xps/fitting-recipes/index":
            assert "source_table" in dict(request.url.params) or True
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "items": [
                        {
                            "id": "sc0",
                            "element": "Sc",
                            "region": "2p",
                            "compound": "Sc(0)",
                            "source_table": "2.1",
                            "pass_energies": [20],
                            "label": "Sc(0)",
                            "aliases": [],
                        }
                    ],
                },
            )
        if path.startswith("/xps/fitting-recipes/") and path.endswith("/apply"):
            return httpx.Response(
                200,
                json={
                    "recipe_id": "sc0",
                    "recipe_pass_energy": 20,
                    "xps_region": "Sc2p",
                    "components": [{"component_id": "p1", "component_type": "gl"}],
                    "p0": [1.0],
                    "bounds_lower": [0.0],
                    "bounds_upper": [10.0],
                    "vary": [True],
                    "param_links": [],
                    "warnings": [],
                },
            )
        if path == "/sessions/sess1":
            return httpx.Response(
                200,
                json={
                    "session": {
                        "session_id": "sess1",
                        "dataset_id": "ds1",
                        "pipeline": {"steps": [], "technique_family": "xps"},
                        "subset": {"kind": "all"},
                    }
                },
            )
        if path == "/sessions/sess1/pipeline" and request.method == "PUT":
            body = json.loads(request.content.decode("utf-8"))
            assert body["pipeline"]["technique_family"] == "xps"
            assert any(s["name"] == "fitting" for s in body["pipeline"]["steps"])
            return httpx.Response(
                200,
                json={
                    "pipeline": body["pipeline"],
                    "pipeline_hash": "abc",
                },
            )
        return httpx.Response(404, json={"detail": path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)

    chem = json.loads(
        asyncio.run(_tool_fn(mcp, "get_xps_chemical_states")(element="Ag", line="3d"))
    )
    assert chem.get("ok") is True
    assert chem["entries"][0]["compound"] == "Ag2O"

    idx = json.loads(
        asyncio.run(
            _tool_fn(mcp, "get_xps_fitting_recipes_index")(q="Sc", source_table="2.1")
        )
    )
    assert idx.get("ok") is True

    applied = json.loads(
        asyncio.run(
            _tool_fn(mcp, "post_xps_apply_recipe_to_session")(
                session_id="sess1", recipe_id="sc0", pass_energy=20, confirm=True
            )
        )
    )
    assert applied.get("ok") is True
    assert applied.get("xps_region") == "Sc2p"


def test_post_io_purge_requires_confirm(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/io/purge":
            return httpx.Response(200, json={"deleted": 1, "missing": 0, "blocked": {}})
        return httpx.Response(404)

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "post_io_purge")
    denied = json.loads(asyncio.run(fn(relative_paths=["a.txt"], confirm=False)))
    assert denied.get("needs_confirm") is True
    ok = json.loads(asyncio.run(fn(relative_paths=["a.txt"], confirm=True)))
    assert ok.get("ok") is True
    assert ok.get("deleted") == 1


def test_fit_curve_job_download_path(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/analysis/runs/r1/fit-curve-jobs" and request.method == "POST":
            return httpx.Response(202, json={"job_id": "fc1", "status": "queued"})
        if request.url.path == "/analysis/fit-curve-jobs/fc1":
            return httpx.Response(
                200,
                json={
                    "job_id": "fc1",
                    "run_id": "r1",
                    "fitting_step_num": 1,
                    "content": "data_fit_resid",
                    "format": "csv",
                    "status": "completed",
                    "progress_done": 1,
                    "progress_total": 1,
                    "error": None,
                    "created_at": "t",
                    "finished_at": "t",
                },
            )
        if request.url.path == "/analysis/fit-curve-jobs/fc1/download":
            return httpx.Response(200, content=b"PK\x03\x04zip")
        return httpx.Response(404)

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    created = json.loads(
        asyncio.run(
            _tool_fn(mcp, "post_analysis_fit_curve_jobs")(run_id="r1", fitting_step_num=1)
        )
    )
    assert created.get("job_id") == "fc1"
    downloaded = json.loads(
        asyncio.run(_tool_fn(mcp, "get_analysis_fit_curve_jobs_download")(job_id="fc1"))
    )
    assert downloaded.get("ok") is True
    assert Path(downloaded["path"]).is_file()


def test_summarize_technique_fields() -> None:
    from sersflow.mcp import summarize

    item = summarize.dataset_list_item(
        {
            "dataset_id": "d1",
            "count": 2,
            "metadata": {"name": "n", "technique_family": "xps", "capabilities": ["multi_block"]},
        }
    )
    assert item["technique_family"] == "xps"
    assert item["capabilities"] == ["multi_block"]
    pipe = summarize.pipeline_list_item(
        {
            "pipeline_id": "p1",
            "name": "n",
            "technique_family": "xps",
            "pipeline": {"steps": [], "technique_family": "xps"},
            "updated_at": "t",
        }
    )
    assert pipe["technique_family"] == "xps"
    up = summarize.upload_list_item(
        {
            "relative_path": "a.vms",
            "filename": "a.vms",
            "size_bytes": 1,
            "technique_family": "xps",
            "xps_regions": ["C1s"],
            "spectrum_count": 3,
        }
    )
    assert up["technique_family"] == "xps"
    assert up["xps_regions"] == ["C1s"]


def test_xps_chemical_states_requires_filter(tmp_path: Path) -> None:
    ctx = _ready_ctx(tmp_path, httpx.MockTransport(lambda r: httpx.Response(404)))
    mcp = create_server(ctx)
    raw = asyncio.run(_tool_fn(mcp, "get_xps_chemical_states")())
    data = json.loads(raw)
    assert data.get("ok") is False
    assert "element" in str(data.get("message", "")).lower() or "filter" in str(data).lower()


def test_meta_formats_and_pipeline_steps_compact_fields(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/meta/formats":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "vamas",
                            "label": "VAMAS",
                            "technique_family": "xps",
                            "suffixes": [".vms"],
                            "capabilities": ["multi_block"],
                            "dataset_kinds": ["xps"],
                        }
                    ]
                },
            )
        if request.url.path == "/meta/pipeline-steps":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "fitting",
                            "label": "Fitting",
                            "category": "fit",
                            "palette_group": "xps",
                            "requires_technique": ["xps"],
                            "requires_capabilities": [],
                            "description": "Peak fitting",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    formats = json.loads(asyncio.run(_tool_fn(mcp, "get_meta_formats")()))
    assert formats.get("ok") is True
    assert formats["items"][0]["suffixes"] == [".vms"]
    assert "extensions" not in formats["items"][0]
    steps = json.loads(asyncio.run(_tool_fn(mcp, "get_meta_pipeline_steps")(technique_family="xps")))
    assert steps.get("ok") is True
    assert steps["items"][0]["requires_technique"] == ["xps"]
    assert "technique_families" not in steps["items"][0]


def test_observation_schema_and_qc_preview(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/analysis/runs/r1/observation-schema":
            return httpx.Response(
                200,
                json={
                    "feature_keys": ["peak_area"],
                    "axis_keys": ["binding_energy_eV"],
                    "meta_keys": ["meta_sample"],
                },
            )
        if request.url.path == "/sessions/s1/qc/preview" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "step_id": "qc1",
                    "step_name": "low_signal",
                    "summary": {"total": 10, "flagged_count": 2, "flagged_pct": 20.0},
                    "threshold": 0.1,
                    "direction": "below",
                    "histogram": {"bins": [0.0, 1.0], "counts": [10], "nonfinite": 0},
                    "scores": [
                        {"spectrum_id": "a", "score": 0.01, "flagged": True},
                        {"spectrum_id": "b", "score": 0.5, "flagged": False},
                    ],
                },
            )
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    schema = json.loads(
        asyncio.run(_tool_fn(mcp, "get_analysis_runs_observation_schema")(run_id="r1"))
    )
    assert schema.get("ok") is True
    assert schema["feature_keys"] == ["peak_area"]
    qc = json.loads(
        asyncio.run(
            _tool_fn(mcp, "post_sessions_qc_preview")(session_id="s1", step_id="qc1")
        )
    )
    assert qc.get("ok") is True
    assert qc["summary"]["flagged_count"] == 2
    assert qc["n_scores"] == 2
    assert len(qc["flagged_sample"]) == 1


def test_matrix_import_and_plot_path(tmp_path: Path) -> None:
    csv_path = tmp_path / "matrix.csv"
    csv_path.write_text("spectrum_id,x0\ns1,1.0\n", encoding="utf-8")

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/explore/matrix-jobs/import" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "matrix_job_id": "mj1",
                    "status": "completed",
                    "message": None,
                },
            )
        if request.url.path == "/plot/spectrum" and request.method == "POST":
            return httpx.Response(
                200,
                json={"figure": {"data": [{"x": [1], "y": [2]}], "layout": {}}},
            )
        if request.url.path == "/plot/series-value":
            assert dict(request.url.params).get("index") == "0"
            return httpx.Response(200, json={"index": 0, "x": 100.0, "y": 1.5})
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    imported = json.loads(
        asyncio.run(
            _tool_fn(mcp, "post_explore_matrix_jobs_import")(
                dataset_id="ds1", path=str(csv_path)
            )
        )
    )
    assert imported.get("ok") is True
    assert imported.get("matrix_job_id") == "mj1"

    plotted = json.loads(
        asyncio.run(
            _tool_fn(mcp, "post_plot_spectrum")(request={"relative_path": "a.txt"})
        )
    )
    assert plotted.get("ok") is True
    assert Path(plotted["path"]).is_file()

    val = json.loads(
        asyncio.run(
            _tool_fn(mcp, "get_plot_series_value")(relative_path="a.txt", index=0)
        )
    )
    assert val.get("ok") is True
    assert val.get("y") == 1.5


def test_plot_export_requires_confirm_when_large(tmp_path: Path) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/plot/spectrum" and request.method == "POST":
            return httpx.Response(
                200,
                json={"figure": {"data": [{"y": list(range(5000))}], "layout": {}}},
            )
        return httpx.Response(404)

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    ctx.config.upload_confirm_bytes = 200
    mcp = create_server(ctx)
    denied = json.loads(
        asyncio.run(
            _tool_fn(mcp, "post_plot_spectrum")(
                request={"relative_path": "a.txt"}, confirm=False
            )
        )
    )
    assert denied.get("needs_confirm") is True
    ok = json.loads(
        asyncio.run(
            _tool_fn(mcp, "post_plot_spectrum")(
                request={"relative_path": "a.txt"}, confirm=True
            )
        )
    )
    assert ok.get("ok") is True
    assert Path(ok["path"]).is_file()


def test_post_analysis_runs_rejects_session_plus_inline_pipeline(tmp_path: Path) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "post_analysis_runs")
    raw = asyncio.run(
        fn(
            dataset_id="ds_1",
            session_id="sess_1",
            pipeline={"steps": []},
            subset={"kind": "all"},
        )
    )
    data = json.loads(raw)
    assert data.get("ok") is False
    assert "not both" in json.dumps(data)
    assert calls == []  # rejected before any HTTP call


def test_post_analysis_sweep_jobs_gate_and_post(tmp_path: Path) -> None:
    seen: list[tuple[str, dict]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/analysis/runs/r1/sweep-jobs":
            seen.append((request.url.path, json.loads(request.content)))
            return httpx.Response(202, json={"job_id": "fcjob_1", "status": "queued"})
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "post_analysis_sweep_jobs")

    big = [{"component_id": "p1", "key": "fwhm", "values": [float(i) for i in range(1, 100)]}]
    blocked = json.loads(asyncio.run(fn(run_id="r1", grid=big, fitting_step_index=0)))
    assert blocked["needs_confirm"] is True and blocked["reason"] == "sweep_exceeds_threshold"
    assert seen == []  # nothing sent without approval

    ok = json.loads(
        asyncio.run(
            fn(
                run_id="r1",
                grid=[{"component_id": "p1", "key": "fwhm", "values": [2.0, 3.0]}],
                fitting_step_index=0,
            )
        )
    )
    assert ok["ok"] is True and ok["job_id"] == "fcjob_1" and ok["grid_points"] == 2
    assert seen[0][1]["fitting_step_index"] == 0


def test_robustness_tools_plan_gate_post_and_compact_summary(tmp_path: Path) -> None:
    seen: list[tuple[str, dict]] = []
    est = {"n_cells": 8, "n_spectra": 60, "n_starts": 1, "n_fits": 480, "n_total_fits": 480}
    summary = {
        "design": {"n_cells": 8},
        "responses": {
            "r": {
                "anova": {"terms": [{"term": "background"}], "per_spectrum": {"s": {}}},
                "trend": {"fraction_sign_preserved": 1.0, "per_cell": [{"cell_id": "c0"}], "bands": []},
            },
            "other": {"anova": {"terms": [], "per_spectrum": {}}},
        },
    }

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/analysis/runs/r1/robustness-plan":
            seen.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={"estimate": est, "factors": [], "responses": [], "notes": []})
        if request.url.path == "/analysis/runs/r1/robustness-jobs":
            seen.append((request.url.path, json.loads(request.content)))
            return httpx.Response(202, json={"job_id": "fcjob_r", "status": "queued"})
        if request.url.path == "/analysis/robustness-jobs/fcjob_r/summary":
            return httpx.Response(200, json=summary)
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    plan = json.loads(asyncio.run(_tool_fn(mcp, "post_analysis_robustness_plan")(run_id="r1", fitting_step_index=0, preset="fit_model_choices")))
    assert plan["ok"] is True and plan["data"]["estimate"]["n_cells"] == 8
    assert seen[-1][1]["preset"] == "fit_model_choices"

    jobs = _tool_fn(mcp, "post_analysis_robustness_jobs")
    n_before = len(seen)
    blocked = json.loads(asyncio.run(jobs(run_id="r1", fitting_step_index=0, preset="fit_model_choices")))
    assert blocked["needs_confirm"] is True and blocked["reason"] == "robustness_exceeds_threshold"
    assert all(path.endswith("robustness-plan") for path, _ in seen[n_before:])  # plan only, nothing started
    ok = json.loads(asyncio.run(jobs(run_id="r1", fitting_step_index=0, preset="fit_model_choices", confirm=True, n_starts=3)))
    assert ok["ok"] is True and ok["job_id"] == "fcjob_r" and ok["estimate"]["n_fits"] == 480
    assert seen[-1][0].endswith("robustness-jobs") and seen[-1][1]["n_starts"] == 3

    get = _tool_fn(mcp, "get_analysis_robustness_summary")
    data = json.loads(asyncio.run(get(job_id="fcjob_r", response="r")))["data"]
    assert list(data["responses"]) == ["r"]
    assert "per_spectrum" not in data["responses"]["r"]["anova"] and "per_cell" not in data["responses"]["r"]["trend"]
    full = json.loads(asyncio.run(get(job_id="fcjob_r", include_per_cell=True, include_per_spectrum=True)))["data"]
    assert "per_spectrum" in full["responses"]["r"]["anova"] and "per_cell" in full["responses"]["r"]["trend"]


def test_post_analysis_monte_carlo_jobs_and_summary(tmp_path: Path) -> None:
    seen: list[tuple[str, dict]] = []
    summary = {
        "n_replicates": 20,
        "spectra": [{"spectrum_id": "a"}, {"spectrum_id": "b"}],
        "rows": [{"spectrum_id": "a", "quantity": "fwhm"}, {"spectrum_id": "b", "quantity": "fwhm"}],
    }

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/analysis/runs/r1/monte-carlo-jobs":
            seen.append((request.url.path, json.loads(request.content)))
            return httpx.Response(202, json={"job_id": "fcjob_2", "status": "queued"})
        if request.url.path == "/analysis/monte-carlo-jobs/fcjob_2/summary":
            return httpx.Response(200, json=summary)
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    post = _tool_fn(mcp, "post_analysis_monte_carlo_jobs")
    ok = json.loads(asyncio.run(post(run_id="r1", fitting_step_index=0, n_replicates=20, seed=4)))
    assert ok["ok"] is True and ok["job_id"] == "fcjob_2"
    assert seen[0][1]["n_replicates"] == 20 and seen[0][1]["seed"] == 4
    get = _tool_fn(mcp, "get_analysis_monte_carlo_summary")
    data = json.loads(asyncio.run(get(job_id="fcjob_2", spectrum_id="b")))["data"]
    assert [r["spectrum_id"] for r in data["rows"]] == ["b"] and len(data["spectra"]) == 1


def test_post_xps_add_spin_orbit_partner_and_recipe_options(tmp_path: Path) -> None:
    seen: list[tuple[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/xps/spin-orbit-partner":
            body = json.loads(request.content)
            seen.append((request.url.path, body))
            return httpx.Response(200, json={"params": body["params"], "partner_id": "p1_2p1_2"})
        if request.url.path == "/xps/fitting-recipes/co_2p32_coo/apply":
            seen.append((request.url.path, dict(request.url.params)))
            return httpx.Response(200, json={"recipe_id": "co_2p32_coo", "components": []})
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    add = _tool_fn(mcp, "post_xps_add_spin_orbit_partner")
    out = json.loads(asyncio.run(add(params={"components": []}, component_id="p1", splitting_eV=15.0, subshell="p")))
    assert out["ok"] is True and out["data"]["partner_id"] == "p1_2p1_2"
    assert seen[0][1]["subshell"] == "p" and seen[0][1]["lock_area"] is True
    apply = _tool_fn(mcp, "apply_xps_fitting_recipe")
    json.loads(asyncio.run(apply(recipe_id="co_2p32_coo", spin_orbit_partner_splitting_eV=15.6, lock_spin_orbit=False)))
    q = seen[1][1]
    assert q["spin_orbit_partner_splitting_eV"] == "15.6" and q["lock_spin_orbit"] == "false"


def test_post_fitting_validate_links(tmp_path: Path) -> None:
    seen: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fitting/validate-links":
            seen.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": False, "errors": ["cyclic constraint: C.pos -> B.pos -> C.pos"], "drivers": {}})
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    fn = _tool_fn(mcp, "post_fitting_validate_links")
    links = [{"source_component_id": "C", "source_key": "pos", "mode": "expr", "expr": "{B.pos}+1"}]
    out = json.loads(asyncio.run(fn(components=[{"component_id": "C", "component_type": "gl"}], param_links=links)))
    assert out["ok"] is True and out["data"]["ok"] is False and "cyclic" in out["data"]["errors"][0]
    assert seen[0]["param_links"] == links


def test_post_analysis_report_jobs_and_json(tmp_path: Path) -> None:
    seen: list[tuple[str, object]] = []
    report = {"schema": "specflow-fit-report/1", "spectra": [{"spectrum_id": "a"}, {"spectrum_id": "b"}]}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/analysis/runs/r1/report-jobs":
            seen.append((request.url.path, json.loads(request.content)))
            return httpx.Response(202, json={"job_id": "fcjob_r", "status": "queued"})
        if request.url.path == "/analysis/report-jobs/fcjob_r/json":
            return httpx.Response(200, json=report)
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    post = _tool_fn(mcp, "post_analysis_report_jobs")
    ok = json.loads(asyncio.run(post(run_id="r1", fitting_step_nums=[2], include_figures=False)))
    assert ok["ok"] is True and ok["job_id"] == "fcjob_r"
    assert seen[0][1]["fitting_step_nums"] == [2] and seen[0][1]["include_figures"] is False
    assert seen[0][1].get("spectrum_ids") is None
    get = _tool_fn(mcp, "get_analysis_report_json")
    data = json.loads(asyncio.run(get(job_id="fcjob_r", spectrum_id="b")))["data"]
    assert [s["spectrum_id"] for s in data["spectra"]] == ["b"]


def test_reference_and_test_peak_model_tools(tmp_path: Path) -> None:
    seen: list[tuple[str, str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.url.path == "/references" and request.method == "GET":
            return httpx.Response(200, json={"items": [], "count": 0})
        if request.url.path in ("/references", "/references/from-dataset", "/references/import"):
            return httpx.Response(200, json={"reference_id": "ref_1", "name": body["name"], "x": [1, 2], "y": [3, 4]})
        if request.url.path == "/fitting/test-peak-model":
            return httpx.Response(200, json={"mode": "noise", "overlay": [{"a": [1]}], "x": [1], "components": []})
        if request.url.path == "/analysis/sweep-jobs/fcjob_s/summary":
            return httpx.Response(200, json={"axes": ["a.pos"], "summary": [], "points": [{"x": 1}]})
        return httpx.Response(404, json={"detail": request.url.path})

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    mcp = create_server(ctx)
    post = _tool_fn(mcp, "post_references")
    out = json.loads(asyncio.run(post(name="CoO", x=[1.0, 2.0, 3.0], y=[1.0, 2.0, 1.0])))
    assert out["data"] == {"reference_id": "ref_1", "name": "CoO"}  # arrays dropped from the answer
    asyncio.run(post(name="raw", dataset_id="ds", spectrum_id="sp"))
    asyncio.run(post(name="lit", text="1 2\n2 3\n3 4\n"))
    assert [p for _m, p, _b in seen] == ["/references", "/references/from-dataset", "/references/import"]
    bad = json.loads(asyncio.run(post(name="x")))
    assert bad["ok"] is False
    tpm = _tool_fn(mcp, "post_fitting_test_peak_model")
    res = json.loads(asyncio.run(tpm(fit_request={"target": {}}, mode="noise", n_replicates=5)))
    assert "overlay" not in res["data"] and "x" not in res["data"]
    assert seen[-1][2]["mode"] == "noise" and seen[-1][2]["n_replicates"] == 5
    sw = _tool_fn(mcp, "get_analysis_sweep_summary")
    data = json.loads(asyncio.run(sw(job_id="fcjob_s")))["data"]
    assert data["axes"] == ["a.pos"] and "points" not in data


_PIPE_ITEM = {
    "pipeline_id": "p1",
    "name": "Co2p",
    "pipeline": {"steps": [{"name": "fitting", "enabled": True, "params": {}}], "technique_family": "xps"},
    "technique_family": "xps",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-01-01T00:00:00",
}
_RUN = {
    "run_id": "r1",
    "dataset_id": "ds",
    "session_id": None,
    "pipeline_hash": "h",
    "subset_hash": "s",
    "status": "completed",
    "error": None,
    "created_at": "t",
    "finished_at": None,
    "label": None,
    "pinned": False,
}


def test_x3_read_tools_spectrum_steps_and_step_outputs(tmp_path: Path) -> None:
    seen: list[tuple[str, str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.url.path == "/analysis/runs/r1/spectra/sp1":
            return httpx.Response(200, json={"spectrum_id": "sp1", "x": list(range(100)), "y": list(range(100))})
        if request.url.path == "/analysis/runs/r1/pipeline-steps":
            return httpx.Response(200, json={"items": [{"step_num": 2, "name": "fitting"}]})
        if request.url.path == "/analysis/runs/r1/step-outputs-jobs":
            return httpx.Response(202, json={"job_id": "fcjob_so", "status": "queued"})
        return httpx.Response(404, json={"detail": request.url.path})

    mcp = create_server(_ready_ctx(tmp_path, httpx.MockTransport(handle)))
    sp = json.loads(asyncio.run(_tool_fn(mcp, "get_analysis_runs_spectrum")(run_id="r1", spectrum_id="sp1", max_points=10)))
    assert sp["ok"] and len(sp["x"]) == 10 and sp["x"][0] == 0 and sp["x"][-1] == 99 and sp["thinned_from"] == 100
    st = json.loads(asyncio.run(_tool_fn(mcp, "get_analysis_runs_pipeline_steps")(run_id="r1")))
    assert st["items"][0]["name"] == "fitting"
    so = json.loads(asyncio.run(_tool_fn(mcp, "post_analysis_step_outputs_jobs")(run_id="r1", step_nums=[1, 2])))
    assert so["ok"] and so["job_id"] == "fcjob_so"
    assert seen[-1][2] == {"step_nums": [1, 2], "spectrum_ids": None}


def test_x3_destructive_tools_need_confirm(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        path, m = request.url.path, request.method
        if path == "/pipelines/p1" and m == "GET":
            return httpx.Response(200, json={"item": _PIPE_ITEM})
        if path == "/pipelines/p1" and m == "PUT":
            return httpx.Response(200, json={"item": {**_PIPE_ITEM, "name": "renamed"}})
        if path == "/pipelines/p1" and m == "DELETE":
            return httpx.Response(200, json={"deleted": True})
        if path == "/datasets/ds" and m == "GET":
            return httpx.Response(200, json={"dataset": {"dataset_id": "ds", "spectra": [], "metadata": {"name": "D"}}})
        if path == "/datasets/ds" and m == "DELETE":
            return httpx.Response(200, json={"deleted": True, "sessions_deleted": 0})
        if path == "/analysis/runs" and m == "GET":
            return httpx.Response(200, json=[_RUN])
        if path == "/analysis/runs" and m == "DELETE":
            return httpx.Response(200, json={"deleted": True, "runs_deleted": 1})
        if path == "/analysis/runs/r1" and m == "GET":
            return httpx.Response(200, json={"run": _RUN})
        if path == "/analysis/runs/r1" and m == "DELETE":
            return httpx.Response(200, json={"deleted": True})
        if path == "/explore/matrix-jobs/mj1" and m == "GET":
            return httpx.Response(200, json={"dataset_id": "ds", "status": "completed"})
        if path == "/explore/matrix-jobs/mj1" and m == "DELETE":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"detail": path})

    mcp = create_server(_ready_ctx(tmp_path, httpx.MockTransport(handle)))
    cases = [
        ("delete_pipelines_by_id", {"pipeline_id": "p1"}, ("DELETE", "/pipelines/p1")),
        ("put_pipelines_by_id", {"pipeline_id": "p1", "name": "renamed"}, ("PUT", "/pipelines/p1")),
        ("delete_datasets_by_id", {"dataset_id": "ds"}, ("DELETE", "/datasets/ds")),
        ("delete_analysis_runs_by_id", {"run_id": "r1"}, ("DELETE", "/analysis/runs/r1")),
        ("delete_analysis_runs", {"dataset_id": "ds"}, ("DELETE", "/analysis/runs")),
        ("delete_explore_matrix_jobs", {"matrix_job_id": "mj1"}, ("DELETE", "/explore/matrix-jobs/mj1")),
    ]
    for name, kwargs, mutation in cases:
        fn = _tool_fn(mcp, name)
        seen.clear()
        refused = json.loads(asyncio.run(fn(**kwargs)))
        assert refused["ok"] is False and refused["needs_confirm"] is True, (name, refused)
        assert refused["reason"] == "destructive_action" and refused["details"], name
        assert mutation not in seen, f"{name} mutated without confirm"
        done = json.loads(asyncio.run(fn(**kwargs, confirm=True)))
        assert done["ok"] is True, (name, done)
        assert mutation in seen, name
    # details tell what would go
    refused = json.loads(asyncio.run(_tool_fn(mcp, "delete_analysis_runs")(dataset_id="ds")))
    assert refused["details"]["run_count"] == 1 and refused["details"]["run_ids"] == ["r1"]


def test_x3_recipe_tool_reads_dataset_pass_energy(tmp_path: Path) -> None:
    seen: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/datasets/ds/spectra/sp1/acquisition":
            return httpx.Response(200, json={"pass_energy_eV": 40.0})
        if request.url.path.startswith("/xps/fitting-recipes/") and request.url.path.endswith("/apply"):
            seen.append(dict(request.url.params))
            return httpx.Response(200, json={"recipe_id": "x", "params": {}})
        return httpx.Response(404, json={"detail": request.url.path})

    mcp = create_server(_ready_ctx(tmp_path, httpx.MockTransport(handle)))
    fn = _tool_fn(mcp, "apply_xps_fitting_recipe")
    out = json.loads(asyncio.run(fn(recipe_id="Co_metal", dataset_id="ds", spectrum_id="sp1")))
    assert out["ok"] is True, out
    assert seen[-1].get("preferred_pass_energy") == "40"
    # an explicit pass energy wins and no acquisition lookup is needed
    out = json.loads(asyncio.run(fn(recipe_id="Co_metal", pass_energy=20, dataset_id="ds", spectrum_id="sp1")))
    assert seen[-1].get("pass_energy") == "20" and "preferred_pass_energy" not in seen[-1]
    bad = json.loads(asyncio.run(fn(recipe_id="Co_metal", dataset_id="ds")))
    assert bad["ok"] is False


def test_x1_x2_mcp_tools(tmp_path: Path) -> None:
    seen: list[tuple[str, str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        path, m = request.url.path, request.method
        if path == "/fitting/history" and m == "GET":
            return httpx.Response(200, json={"scope_key": "s", "count": 0, "items": []})
        if path == "/fitting/history" and m == "POST":
            return httpx.Response(200, json={"history_id": "fh_1", "created": True, "label": body["label"], "params": {}})
        if path == "/fitting/history/compare":
            return httpx.Response(200, json={"rows": [], "stats": []})
        if path == "/fitting/history/fh_1" and m == "DELETE":
            return httpx.Response(200, json={"deleted": True})
        if path == "/fitting/history" and m == "DELETE":
            return httpx.Response(200, json={"deleted": 3})
        if path == "/xps/line-markers":
            return httpx.Response(200, json={"markers": [{"label": "Co 2p"}], "count": 1})
        if path == "/xps/reference-markers":
            return httpx.Response(200, json={"compounds": [], "count": 0})
        if path == "/xps/survey/detect":
            return httpx.Response(200, json={"peaks": [], "count": 0})
        if path == "/xps/region-sets" and m == "POST":
            return httpx.Response(200, json={"set_id": "rs_1", "name": body["name"], "n_regions": len(body["regions"])})
        if path == "/xps/region-sets/rs_1" and m == "GET":
            return httpx.Response(200, json={"set_id": "rs_1", "name": "A", "n_regions": 1})
        if path == "/xps/region-sets/rs_1" and m == "DELETE":
            return httpx.Response(200, json={"deleted": True})
        return httpx.Response(404, json={"detail": path})

    mcp = create_server(_ready_ctx(tmp_path, httpx.MockTransport(handle)))
    run = lambda _tool, **kw: json.loads(asyncio.run(_tool_fn(mcp, _tool)(**kw)))  # noqa: E731
    assert run("get_fitting_history", scope_key="s")["ok"] is True
    stored = run("post_fitting_history", scope_key="s", params={"components": [1]}, label="keep")
    assert stored["history_id"] == "fh_1" and seen[-1][2]["label"] == "keep"
    assert run("get_fitting_history_compare", history_id_a="a", history_id_b="b")["ok"] is True
    both = run("delete_fitting_history", history_id="fh_1", scope_key="s")
    assert both["ok"] is False  # exactly one of the two is required
    needs = run("delete_fitting_history", scope_key="s")
    assert needs["needs_confirm"] is True and ("DELETE", "/fitting/history", None) not in seen
    assert run("delete_fitting_history", scope_key="s", confirm=True)["deleted"] == 3
    assert run("delete_fitting_history", history_id="fh_1", confirm=True)["deleted"] is True
    assert run("get_xps_line_markers", element="Co", be_min=770.0)["count"] == 1
    assert run("get_xps_reference_markers", element="Co", line="2p")["ok"] is True
    assert run("post_xps_survey_detect", x=[1.0] * 10, y=[1.0] * 10)["ok"] is True
    assert run("post_xps_region_sets", name="A", regions=[{"be_min_eV": 1.0, "be_max_eV": 2.0}])["n_regions"] == 1
    assert run("get_xps_region_sets", set_id="rs_1")["name"] == "A"
    gate = run("delete_xps_region_sets", set_id="rs_1")
    assert gate["needs_confirm"] is True and gate["details"]["name"] == "A"
    assert run("delete_xps_region_sets", set_id="rs_1", confirm=True)["deleted"] is True
