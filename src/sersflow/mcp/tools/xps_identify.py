"""X2: element / chemical-state identification MCP tools (markers, survey peak detection, region sets)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_xps_line_markers")
    async def get_xps_line_markers(
        element: str | None = None,
        be_min: float | None = None,
        be_max: float | None = None,
        photon_energy_eV: float | None = None,
        include_auger: bool = True,
    ) -> str:
        """GET /xps/line-markers - element-line markers for labelling a survey, derived from the chemical-state library.

        Only the lines the PHI handbook / Biesinger tables contain exist (e.g. Fe 2p but not Fe 3p): a missing marker
        does not mean the element is absent. basis=elemental is the median of the elemental entries,
        compounds_median is approximate (see be_min_eV / be_max_eV). Auger lines need photon_energy_eV.
        """

        def _run():
            data = ctx.get_client().xps.line_markers(
                element=element, be_min=be_min, be_max=be_max, photon_energy_eV=photon_energy_eV, include_auger=include_auger
            )
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_xps_reference_markers")
    async def get_xps_reference_markers(element: str, line: str | None = None) -> str:
        """GET /xps/reference-markers - chemical-state reference energies of one element/line grouped by compound
        (median, min-max, n entries, provenance); use them to place Co0 / Co2+ / Co3+ style guides on a narrow scan."""

        def _run():
            return {"ok": True, **ctx.get_client().xps.reference_markers(element, line)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_xps_survey_detect")
    async def post_xps_survey_detect(
        x: list[float],
        y: list[float],
        prominence_pct: float = 2.0,
        smooth_eV: float = 0.8,
        tolerance_eV: float = 2.0,
        photon_energy_eV: float | None = None,
    ) -> str:
        """POST /xps/survey/detect - local maxima of a survey (smoothed, prominence filter) matched by POSITION to the
        library lines. A labelling aid: candidates list the best match and alternatives; no intensity-ratio check."""

        def _run():
            data = ctx.get_client().xps.survey_detect(
                {
                    "x": x,
                    "y": y,
                    "prominence_pct": prominence_pct,
                    "smooth_eV": smooth_eV,
                    "tolerance_eV": tolerance_eV,
                    "photon_energy_eV": photon_energy_eV,
                }
            )
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_xps_region_sets")
    async def get_xps_region_sets(set_id: str | None = None) -> str:
        """GET /xps/region-sets - saved survey region sets (named element-line windows); set_id returns one."""

        def _run():
            client = ctx.get_client().xps
            data = client.get_region_set(set_id) if set_id else client.list_region_sets()
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_xps_region_sets")
    async def post_xps_region_sets(
        name: str, regions: list[dict[str, Any]], notes: str = "", source: dict[str, Any] | None = None
    ) -> str:
        """POST /xps/region-sets - save a named list of element-line windows. Each region needs be_min_eV < be_max_eV
        (label, element, line, be_eV optional). No quantification is attached yet (Q1)."""

        def _run():
            data = ctx.get_client().xps.create_region_set(
                {"name": name, "regions": regions, "notes": notes, "source": source or {}}
            )
            return {"ok": True, **data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="delete_xps_region_sets")
    async def delete_xps_region_sets(set_id: str, confirm: bool = False) -> str:
        """DELETE /xps/region-sets/{set_id} - delete a saved region set. Needs confirm=true."""

        def _run():
            client = ctx.get_client().xps
            rs = client.get_region_set(set_id)
            blocked = confirm_gates.require_destructive_confirm(
                confirm,
                what="Deleting a region set",
                details={"set_id": set_id, "name": rs.get("name"), "n_regions": rs.get("n_regions")},
            )
            if blocked is not None:
                return blocked
            return {"ok": True, **client.delete_region_set(set_id)}

        return await tool_call(ctx, _run)
