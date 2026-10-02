"""XPS fitting-recipes MCP tools (read-only index + apply)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_xps_fitting_recipes_index")
    async def get_xps_fitting_recipes_index(
        q: str | None = None,
        element: str | None = None,
        region: str | None = None,
        limit: int = 25,
    ) -> str:
        """Compact XPS fitting-recipe search index (packaged Biesinger catalogs)."""

        def _run():
            from sersflow.core.xps.fitting_recipes import list_compound_fit_index

            items = list_compound_fit_index(
                element=element, region=region, q=q, limit=limit
            )
            return {"ok": True, "data": {"items": items, "count": len(items)}}

        return await tool_call(ctx, _run)

    @mcp.tool(name="apply_xps_fitting_recipe")
    async def apply_xps_fitting_recipe(
        recipe_id: str,
        pass_energy: int | None = None,
        include_background: bool = True,
        preferred_pass_energy: int | None = None,
    ) -> str:
        """Expand an XPS fitting recipe into pipeline fitting-step params."""

        def _run():
            from sersflow.core.xps.recipe_apply import apply_recipe_id

            data = apply_recipe_id(
                recipe_id,
                pass_energy=pass_energy,
                include_background=include_background,
                preferred_pass_energy=preferred_pass_energy,
            )
            return {"ok": True, "data": data}

        return await tool_call(ctx, _run)
