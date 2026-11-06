"""X1: fit history (STORE / RECALL / RESET) MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_fitting_history")
    async def get_fitting_history(scope_key: str, include_params: bool = False, limit: int = 50) -> str:
        """GET /fitting/history - saved model states (snapshots) of one fitting step scope, newest first.

        Each snapshot has label, pinned, a fit summary (chi2, redchi, rmse, area_pct per component), a params_hash and
        (include_params=true) the fitting-step params to put back into a pipeline (RECALL).
        """

        def _run():
            data = ctx.get_client().fitting.list_history(scope_key, include_params=include_params, limit=limit)
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_fitting_history")
    async def post_fitting_history(
        scope_key: str,
        params: dict[str, Any],
        summary: dict[str, Any] | None = None,
        label: str = "",
        pinned: bool = False,
    ) -> str:
        """POST /fitting/history - STORE a fitting-step model state. A label (or pinned=true) keeps it until deleted;
        unnamed snapshots equal to the newest one are not duplicated and only the latest 50 unpinned are kept."""

        def _run():
            data = ctx.get_client().fitting.add_history(
                {"scope_key": scope_key, "params": params, "summary": summary or {}, "label": label, "pinned": pinned}
            )
            return {"ok": True, "history_id": data.get("history_id"), "created": data.get("created"), "label": data.get("label")}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_fitting_history_compare")
    async def get_fitting_history_compare(history_id_a: str, history_id_b: str) -> str:
        """GET /fitting/history/compare - parameter table A vs B (value, delta, vary), component differences, window, stats."""

        def _run():
            return {"ok": True, **ctx.get_client().fitting.compare_history(history_id_a, history_id_b)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="delete_fitting_history")
    async def delete_fitting_history(
        history_id: str | None = None, scope_key: str | None = None, confirm: bool = False
    ) -> str:
        """DELETE /fitting/history - delete ONE snapshot (history_id) or RESET a scope (scope_key: all unpinned). Needs confirm=true."""

        def _run():
            if (history_id is None) == (scope_key is None):
                raise ValueError("give exactly one of history_id or scope_key")
            blocked = confirm_gates.require_destructive_confirm(
                confirm,
                what="Deleting fit history",
                details={"history_id": history_id, "scope_key": scope_key, "scope_deletes": "unpinned snapshots only"},
            )
            if blocked is not None:
                return blocked
            client = ctx.get_client().fitting
            data = client.delete_history(history_id) if history_id else client.clear_history(str(scope_key))
            return {"ok": True, **data}

        return await tool_call(ctx, _run)
