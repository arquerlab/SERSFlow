"""Plot tools — write figures to export_dir and return paths (never dump full Plotly into context)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.plot import (
    MapPointsPlotRequest,
    MultiPointsPlotRequest,
    SeriesHeatmapRequest,
    SeriesPointsPlotRequest,
    SpectrumPlotRequest,
)
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def _write_figure(ctx: RuntimeContext, figure: Any, default_name: str, output_path: str | None, confirm: bool) -> dict[str, Any]:
    data = figure.model_dump() if hasattr(figure, "model_dump") else figure
    payload = json.dumps(data, default=str)
    size = len(payload.encode("utf-8"))
    if size > ctx.config.upload_confirm_bytes:
        from sersflow.mcp import confirm as confirm_gates

        blocked = confirm_gates.require_confirm(
            confirm,
            reason="plot_export_exceeds_threshold",
            message=(
                f"Plot JSON is {size} bytes > {ctx.config.upload_confirm_bytes}. "
                "Retry with confirm=true after user approval."
            ),
            details={"bytes": size, "threshold": ctx.config.upload_confirm_bytes},
        )
        if blocked is not None:
            return blocked
    dest = ctx.resolve_export_path(output_path, default_name, confirm=confirm)
    dest.write_text(payload, encoding="utf-8")
    ctx.record_export("plot", dest)
    return summarize.export_result(path=dest, kind="plotly_json", bytes=size)

def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_plot_kinds")
    async def get_plot_kinds() -> str:
        """GET /plot/kinds."""

        def _run():
            resp = ctx.get_client().plot.kinds()
            return {"ok": True, **(resp.model_dump() if hasattr(resp, "model_dump") else resp)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_plot_spectrum")
    async def post_plot_spectrum(
        request: dict[str, Any],
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /plot/spectrum — writes Plotly JSON under export_dir; returns path."""

        def _run():
            req = SpectrumPlotRequest.model_validate(request)
            fig = ctx.get_client().plot.spectrum(req)
            return _write_figure(ctx, fig, "plot_spectrum.json", output_path, confirm)

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_plot_series_info")
    async def get_plot_series_info(relative_path: str, max_points: int = 500) -> str:
        """GET /plot/series-info (compact metadata)."""

        def _run():
            resp = ctx.get_client().plot.series_info(relative_path, max_points=max_points)
            return {"ok": True, **(resp.model_dump() if hasattr(resp, "model_dump") else resp)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_plot_series_points")
    async def post_plot_series_points(
        request: dict[str, Any],
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /plot/series-points — Plotly JSON path."""

        def _run():
            req = SeriesPointsPlotRequest.model_validate(request)
            fig = ctx.get_client().plot.series_points(req)
            return _write_figure(ctx, fig, "plot_series_points.json", output_path, confirm)

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_plot_series_heatmap")
    async def post_plot_series_heatmap(
        request: dict[str, Any],
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /plot/series-heatmap — Plotly JSON path."""

        def _run():
            req = SeriesHeatmapRequest.model_validate(request)
            fig = ctx.get_client().plot.series_heatmap(req)
            return _write_figure(ctx, fig, "plot_series_heatmap.json", output_path, confirm)

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_plot_series_value")
    async def get_plot_series_value(relative_path: str, index: int) -> str:
        """GET /plot/series-value — single series point metadata."""

        def _run():
            data = ctx.get_client().plot.series_value(relative_path, index)
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_plot_map_info")
    async def get_plot_map_info(relative_path: str, max_dim: int = 80) -> str:
        """GET /plot/map-info."""

        def _run():
            resp = ctx.get_client().plot.map_info(relative_path, max_dim=max_dim)
            return {"ok": True, **(resp.model_dump() if hasattr(resp, "model_dump") else resp)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_plot_map_preview_image")
    async def get_plot_map_preview_image(
        relative_path: str,
        crop_to_map: bool = False,
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """GET /plot/map-preview-image — writes PNG under export_dir; returns path."""

        def _run():
            data = ctx.get_client().plot.map_preview_image(relative_path, crop_to_map=crop_to_map)
            size = len(data)
            if size > ctx.config.upload_confirm_bytes:
                from sersflow.mcp import confirm as confirm_gates

                blocked = confirm_gates.require_confirm(
                    confirm,
                    reason="plot_export_exceeds_threshold",
                    message=(
                        f"Map preview is {size} bytes > {ctx.config.upload_confirm_bytes}. "
                        "Retry with confirm=true after user approval."
                    ),
                    details={"bytes": size, "threshold": ctx.config.upload_confirm_bytes},
                )
                if blocked is not None:
                    return blocked
            dest = ctx.resolve_export_path(output_path, "plot_map_preview.png", confirm=confirm)
            dest.write_bytes(data)
            ctx.record_export("plot", dest)
            return summarize.export_result(path=dest, kind="png", bytes=size)
        return await tool_call(ctx, _run)

    @mcp.tool(name="post_plot_map_points")
    async def post_plot_map_points(
        request: dict[str, Any],
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /plot/map-points — Plotly JSON path."""

        def _run():
            req = MapPointsPlotRequest.model_validate(request)
            fig = ctx.get_client().plot.map_points(req)
            return _write_figure(ctx, fig, "plot_map_points.json", output_path, confirm)

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_plot_multi_info")
    async def get_plot_multi_info(relative_path: str) -> str:
        """GET /plot/multi-info (multi-block XPS/VAMAS)."""

        def _run():
            resp = ctx.get_client().plot.multi_info(relative_path)
            data = resp.model_dump() if hasattr(resp, "model_dump") else resp
            # Compact blocks
            if isinstance(data, dict) and isinstance(data.get("blocks"), list):
                data = {
                    **data,
                    "blocks": data["blocks"][:40],
                    "blocks_truncated": len(data["blocks"]) > 40,
                }
            return {"ok": True, **(data if isinstance(data, dict) else {"data": data})}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_plot_multi_points")
    async def post_plot_multi_points(
        request: dict[str, Any],
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /plot/multi-points — Plotly JSON path."""

        def _run():
            req = MultiPointsPlotRequest.model_validate(request)
            fig = ctx.get_client().plot.multi_points(req)
            return _write_figure(ctx, fig, "plot_multi_points.json", output_path, confirm)

        return await tool_call(ctx, _run)
