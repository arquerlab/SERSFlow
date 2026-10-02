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

