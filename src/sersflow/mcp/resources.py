"""MCP read-only resources."""

from __future__ import annotations

import asyncio
import json
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

from sersflow.mcp import summarize
from sersflow.mcp.errors import exception_to_payload

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext

T = TypeVar("T")


async def _safe_thread(fn: Callable[[], T]) -> str:
    """Run sync resource body off the event loop (spawn/health must not stall stdio)."""

    def _wrapped() -> str:
        try:
            out = fn()
            return out if isinstance(out, str) else json.dumps(out, default=str)
        except Exception as e:
            return json.dumps(exception_to_payload(e), default=str)

    return await asyncio.to_thread(_wrapped)


def register_resources(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.resource("sersflow://pipelines")
    async def pipelines_catalog() -> str:
        """Saved pipeline catalog (id, name, n_steps, technique_family)."""

        def _run() -> str:
            client = ctx.ensure_ready()
            bad = ctx.require_compatible()
            if bad is not None:
                return json.dumps(bad, default=str)
            resp = client.pipelines.list(limit=200)
            items = [summarize.pipeline_list_item(i) for i in resp.items]
            return json.dumps({"count": resp.count, "items": items}, default=str)

        return await _safe_thread(_run)

    @mcp.resource("sersflow://openapi/summary")
    async def openapi_summary() -> str:
        """Curated OpenAPI capability sheet (not full spec dump)."""

        def _run() -> str:
            client = ctx.ensure_ready()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                spec = client.meta.check_server()
            info = spec.get("info") if isinstance(spec, dict) else {}
            paths = spec.get("paths") if isinstance(spec, dict) else {}
            tags = spec.get("tags") if isinstance(spec, dict) else []
            tag_names = []
            if isinstance(tags, list):
                for t in tags:
                    if isinstance(t, dict) and t.get("name"):
                        tag_names.append(t["name"])
            payload: dict[str, Any] = {
                "title": info.get("title") if isinstance(info, dict) else None,
                "version": info.get("version") if isinstance(info, dict) else None,
                "tags": tag_names,
                "path_count": len(paths) if isinstance(paths, dict) else 0,
                "capability_blurb": (
                    "SpecFlow MCP covers io (upload/unload/purge/labels), datasets (incl. VAMAS/XPS "
                    "create options + package import/export), sessions (pipeline/subset/QC/run), "
                    "pipelines (create/list/import/export), XPS libraries (chemical-states + fitting "
                    "recipes index/apply-to-session), analysis (runs/exports/fit-curve jobs), "
                    "explore (correlation/VIF/PCA/sPCA/matrix/cluster/fpca), and plot tools that "
                    "write figure paths under export_dir. Explore tools return compact summaries; "
                    "use export + read_tabular_file for tables. No delete tools."
                ),
            }
            return json.dumps(payload, default=str)

        return await _safe_thread(_run)

    @mcp.resource("sersflow://analysis/runs/{run_id}/export/manifest")
    async def analysis_export_manifest(run_id: str) -> str:
        """Export manifest for an analysis run plus local cached export paths."""

        def _run() -> str:
            client = ctx.ensure_ready()
            bad = ctx.require_compatible()
            if bad is not None:
                return json.dumps(bad, default=str)
            man = client.analysis.export_manifest(run_id)
            data = man.model_dump() if hasattr(man, "model_dump") else man
            cached = ctx.export_paths.get(f"analysis:{run_id}", [])
            return json.dumps({"manifest": data, "local_export_paths": cached}, default=str)

        return await _safe_thread(_run)

    @mcp.resource("sersflow://meta/formats")
    async def meta_formats() -> str:
        """File format catalog (id + technique_family)."""

        def _run() -> str:
            client = ctx.ensure_ready()
            bad = ctx.require_compatible()
            if bad is not None:
                return json.dumps(bad, default=str)
            data = client.meta.formats()
            items = []
            for it in data.get("items") or []:
                if isinstance(it, dict):
                    items.append(
                        {
                            "id": it.get("id"),
                            "technique_family": it.get("technique_family"),
                            "suffixes": it.get("suffixes"),
                            "capabilities": it.get("capabilities"),
                        }
                    )
            return json.dumps({"items": items, "count": len(items)}, default=str)

        return await _safe_thread(_run)

    @mcp.resource("sersflow://xps/fitting-recipes/index")
    async def xps_recipes_index() -> str:
        """Compact XPS fitting-recipe index snapshot (capped)."""

        def _run() -> str:
            client = ctx.ensure_ready()
            bad = ctx.require_compatible()
            if bad is not None:
                return json.dumps(bad, default=str)
            data = client.xps.fitting_recipes_index(limit=100)
            return json.dumps(data, default=str)

        return await _safe_thread(_run)

    @mcp.resource("sersflow://xps/chemical-states/summary")
    async def xps_chemical_states_summary() -> str:
        """Chemical-states catalog source metadata (no entry dump)."""

        def _run() -> str:
            client = ctx.ensure_ready()
            bad = ctx.require_compatible()
            if bad is not None:
                return json.dumps(bad, default=str)
            # Tiny filtered probe for source metadata only
            data = client.xps.chemical_states(element="Ag", line="3d", include_sections=False)
            return json.dumps(
                {
                    "source": data.get("source"),
                    "probe": {"element": "Ag", "line": "3d", "entry_count": data.get("entry_count")},
                    "hint": (
                        "Use get_xps_chemical_states with element/line/q/provenance; "
                        "never request the full catalog."
                    ),
                },
                default=str,
            )

        return await _safe_thread(_run)
