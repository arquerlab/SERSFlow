"""Meta tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_health")
    async def get_health() -> str:
        """GET /health — API health check."""

        def _run():
            client = ctx.ensure_ready()
            return {"ok": True, **client.meta.health()}

        return await tool_call(ctx, _run, check_compat=False)

    @mcp.tool(name="get_mcp_meta")
    async def get_mcp_meta() -> str:
        """MCP + OpenAPI versions, auth mode, warnings, non-secret config."""

        def _run():
            return ctx.meta_payload()

        return await tool_call(ctx, _run, check_compat=False)

    @mcp.tool(name="get_meta_formats")
    async def get_meta_formats() -> str:
        """GET /meta/formats — registered file formats (technique + capabilities)."""

        def _run() -> dict[str, Any]:
            data = ctx.get_client().meta.formats()
            items = data.get("items") or []
            compact = []
            for it in items if isinstance(items, list) else []:
                if not isinstance(it, dict):
                    continue
                compact.append(
                    {
                        "id": it.get("id"),
                        "label": it.get("label") or it.get("name"),
                        "technique_family": it.get("technique_family"),
                        "suffixes": it.get("suffixes") or it.get("extensions"),
                        "capabilities": it.get("capabilities"),
                        "dataset_kinds": it.get("dataset_kinds"),
                    }
                )
            return {"ok": True, "items": compact, "count": len(compact)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_meta_formats_by_id")
    async def get_meta_formats_by_id(format_id: str) -> str:
        """GET /meta/formats/{format_id}."""

        def _run() -> dict[str, Any]:
            data = ctx.get_client().meta.format_by_id(format_id)
            return {"ok": True, "format": data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_meta_pipeline_steps")
    async def get_meta_pipeline_steps(
        technique_family: str | None = None,
        capability: list[str] | None = None,
    ) -> str:
        """GET /meta/pipeline-steps — step palette filtered by technique/capabilities."""

        def _run() -> dict[str, Any]:
            data = ctx.get_client().meta.pipeline_steps(
                technique_family=technique_family, capabilities=capability
            )
            items = data.get("items") or []
            compact = []
            for it in items if isinstance(items, list) else []:
                if not isinstance(it, dict):
                    continue
                compact.append(
                    {
                        "id": it.get("id"),
                        "label": it.get("label") or it.get("name"),
                        "category": it.get("category"),
                        "palette_group": it.get("palette_group"),
                        "requires_technique": it.get("requires_technique")
                        or it.get("technique_families"),
                        "requires_capabilities": it.get("requires_capabilities")
                        or it.get("required_capabilities"),
                        "description": (it.get("description") or "")[:160] or None,
                    }
                )
            return {"ok": True, "items": compact, "count": len(compact)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_meta_pipeline_steps_by_id")
    async def get_meta_pipeline_steps_by_id(step_id: str) -> str:
        """GET /meta/pipeline-steps/{step_id}."""

        def _run() -> dict[str, Any]:
            data = ctx.get_client().meta.pipeline_step_by_id(step_id)
            return {"ok": True, "step": data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_pipeline_baseline_methods")
    async def get_pipeline_baseline_methods() -> str:
        """GET /pipeline/baseline-methods — baseline categories including lmfitxps Shirley/Tougaard."""

        def _run() -> dict[str, Any]:
            data = ctx.get_client().pipeline.baseline_methods()
            return {"ok": True, **data}

        return await tool_call(ctx, _run)
