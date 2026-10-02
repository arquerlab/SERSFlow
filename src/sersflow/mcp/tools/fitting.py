"""Fitting catalog and interactive fit."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.fitting import FitRequest
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_fitting_models")
    async def get_fitting_models() -> str:
        """GET /fitting/models — fitting component catalog (vibrational + XPS types mixed).

        Prefer /meta/pipeline-steps and XPS recipe apply when building technique-specific pipelines.
        """

        def _run():
            resp = ctx.get_client().fitting.models()
            return {"ok": True, "data": resp.model_dump() if hasattr(resp, "model_dump") else resp}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_fitting_fit")
    async def post_fitting_fit(
        request: dict[str, Any],
        return_curve: bool = False,
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /fitting/fit — compact diagnostics; optional curve JSON path when return_curve=true."""

        def _run():
            req = FitRequest.model_validate(request)
            resp = ctx.get_client().fitting.fit(req)
            data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
            curve_keys = {"x", "y", "y_fit", "residual", "components", "curve"}
            compact = {
                k: v
                for k, v in (data.items() if isinstance(data, dict) else [])
                if k not in curve_keys
            }
            out: dict[str, Any] = {"ok": True, "diagnostics": compact}
            if return_curve:
                dest = ctx.resolve_export_path(
                    output_path, "fitting_fit_curve.json", confirm=confirm
                )
                dest.write_text(json.dumps(data, default=str), encoding="utf-8")
                ctx.record_export("fitting:fit", dest)
                out["curve_path"] = str(dest.resolve())
            return out

        return await tool_call(ctx, _run)
