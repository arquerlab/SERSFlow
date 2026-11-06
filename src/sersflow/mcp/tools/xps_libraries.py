"""XPS chemical-states and fitting-recipes MCP tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.schemas.sessions import SessionPipelineUpdateRequest
from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def _acquisition_pass_energy(
    ctx: RuntimeContext,
    *,
    pass_energy: int | None,
    preferred_pass_energy: int | None,
    dataset_id: str | None,
    spectrum_id: str | None,
) -> int | None:
    """X3: when no pass energy is given, read it from the dataset spectrum's acquisition metadata."""
    if pass_energy is not None or preferred_pass_energy is not None or not dataset_id:
        return preferred_pass_energy
    if not spectrum_id:
        raise ValueError("spectrum_id is required together with dataset_id to read the acquisition pass energy")
    acq = ctx.get_client().datasets.spectrum_acquisition(dataset_id, spectrum_id, include_arrays=False)
    pe = acq.get("pass_energy_eV")
    if pe is None:
        return None
    try:
        return int(round(float(pe)))
    except (TypeError, ValueError):
        return None


def _compact_chemical_entry(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "section_id": e.get("section_id"),
        "element": e.get("element"),
        "line": e.get("line"),
        "compound": e.get("compound"),
        "phase": e.get("phase"),
        "value_eV": e.get("value_eV"),
        "energy_kind": e.get("energy_kind"),
        "provenance": e.get("provenance"),
        "fwhm_eV": e.get("fwhm_eV"),
    }


def _compact_method(m: dict[str, Any], *, include_body: bool) -> dict[str, Any]:
    body = m.get("procedure_markdown")
    excerpt = None
    if isinstance(body, str) and body.strip():
        excerpt = body.strip()[:240]
    out: dict[str, Any] = {
        "id": m.get("id"),
        "chapter": m.get("chapter"),
        "instrument": m.get("instrument"),
        "software": m.get("software"),
        "background": m.get("background"),
        "excerpt": excerpt,
    }
    if include_body:
        out["procedure_markdown"] = body
    return out


def _compact_compound_fit(f: dict[str, Any]) -> dict[str, Any]:
    peaks = f.get("peaks") if isinstance(f.get("peaks"), list) else []
    return {
        "id": f.get("id"),
        "element": f.get("element"),
        "region": f.get("region"),
        "compound": f.get("compound"),
        "source_table": f.get("source_table"),
        "pass_energies": f.get("pass_energies") or [],
        "peak_count": len(peaks),
        "spin_orbit_split_eV": f.get("spin_orbit_split_eV"),
    }


def _fitting_step_from_apply(applied: dict[str, Any]) -> PipelineStep:
    params: dict[str, Any] = {
        "components": applied.get("components") or [],
        "p0": applied.get("p0") or [],
        "bounds_lower": applied.get("bounds_lower") or [],
        "bounds_upper": applied.get("bounds_upper") or [],
        "vary": applied.get("vary") or [],
        "param_links": applied.get("param_links") or [],
        "xps_region": applied.get("xps_region"),
        "recipe_id": applied.get("recipe_id"),
        "recipe_pass_energy": applied.get("recipe_pass_energy"),
    }
    region = str(applied.get("xps_region") or "fit").strip() or "fit"
    return PipelineStep(name="fitting", params=params, enabled=True, step_id=f"fit_{region}")


def _merge_apply_into_pipeline(pipeline: Pipeline, applied: dict[str, Any]) -> Pipeline:
    step = _fitting_step_from_apply(applied)
    region = str(applied.get("xps_region") or "").strip()
    steps = list(pipeline.steps)
    replaced = False
    for i, existing in enumerate(steps):
        if existing.name != "fitting":
            continue
        existing_region = str((existing.params or {}).get("xps_region") or "").strip()
        if region and existing_region == region:
            steps[i] = step
            replaced = True
            break
        if not region and not existing_region:
            steps[i] = step
            replaced = True
            break
    if not replaced:
        steps.append(step)
    return Pipeline(steps=steps, technique_family="xps")


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_xps_chemical_states")
    async def get_xps_chemical_states(
        element: str | None = None,
        line: str | None = None,
        q: str | None = None,
        provenance: str | None = None,
        include_sections: bool = False,
        limit: int = 50,
    ) -> str:
        """Search XPS chemical-states reference library (compact; requires element/line/q/provenance)."""

        def _run():
            has_filter = any(
                (v or "").strip() if isinstance(v, str) else v
                for v in (element, line, q, provenance)
            )
            lim = max(1, min(int(limit), 200))
            if not has_filter:
                raise ValueError(
                    "get_xps_chemical_states requires at least one of "
                    "element, line, q, or provenance (catalog is ~40k entries)."
                )
            data = ctx.get_client().xps.chemical_states(
                element=element,
                line=line,
                q=q,
                provenance=provenance,
                include_sections=include_sections,
            )
            entries = data.get("entries") or []
            if not isinstance(entries, list):
                entries = []
            truncated = len(entries) > lim
            entries = entries[:lim]
            sections_out: list[dict[str, Any]] = []
            if include_sections:
                for s in data.get("sections") or []:
                    if not isinstance(s, dict):
                        continue
                    sec_entries = s.get("entries") or []
                    if isinstance(sec_entries, list):
                        sec_entries = [_compact_chemical_entry(e) for e in sec_entries[:lim] if isinstance(e, dict)]
                    sections_out.append(
                        {
                            "id": s.get("id"),
                            "element": s.get("element"),
                            "line": s.get("line"),
                            "energy_kind": s.get("energy_kind"),
                            "entry_count": s.get("entry_count"),
                            "entries": sec_entries,
                        }
                    )
            return {
                "ok": True,
                "source": data.get("source"),
                "entry_count": data.get("entry_count"),
                "returned": len(entries),
                "truncated": truncated,
                "entries": [_compact_chemical_entry(e) for e in entries if isinstance(e, dict)],
                "sections": sections_out,
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_xps_fitting_recipes_index")
    async def get_xps_fitting_recipes_index(
        q: str | None = None,
        element: str | None = None,
        region: str | None = None,
        source_table: str | None = None,
        limit: int = 25,
    ) -> str:
        """Compact XPS fitting-recipe search index (packaged Biesinger catalogs)."""

        def _run():
            data = ctx.get_client().xps.fitting_recipes_index(
                element=element,
                region=region,
                q=q,
                source_table=source_table,
                limit=max(1, min(int(limit), 200)),
            )
            items = data.get("items") or []
            return {"ok": True, "data": {"items": items, "count": data.get("count", len(items))}}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_xps_fitting_recipes")
    async def get_xps_fitting_recipes(
        element: str | None = None,
        region: str | None = None,
        q: str | None = None,
        source_table: str | None = None,
        chapter: int | None = None,
        include_methods: bool = True,
        include_method_body: bool = False,
        recipe_id: str | None = None,
        limit: int = 50,
    ) -> str:
        """Full XPS fitting-recipes catalog (compact). Pass recipe_id for one detailed compound fit."""

        def _run():
            data = ctx.get_client().xps.fitting_recipes(
                element=element,
                region=region,
                q=q,
                source_table=source_table,
                chapter=chapter,
                include_methods=include_methods,
            )
            fits = data.get("compound_fits") or []
            if not isinstance(fits, list):
                fits = []
            detail = None
            rid = (recipe_id or "").strip()
            if rid:
                for f in fits:
                    if isinstance(f, dict) and str(f.get("id") or "") == rid:
                        detail = f
                        break
                if detail is None:
                    raise ValueError(f"recipe_id not found in filtered catalog: {rid!r}")
            lim = max(1, min(int(limit), 200))
            methods = data.get("method_defaults") or []
            if not isinstance(methods, list):
                methods = []
            return {
                "ok": True,
                "source": data.get("source"),
                "compound_fit_count": data.get("compound_fit_count", len(fits)),
                "method_count": data.get("method_count", len(methods)),
                "compound_fits": [_compact_compound_fit(f) for f in fits[:lim] if isinstance(f, dict)],
                "truncated": len(fits) > lim,
                "recipe_detail": detail,
                "method_defaults": [
                    _compact_method(m, include_body=include_method_body)
                    for m in methods
                    if isinstance(m, dict)
                ],
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="apply_xps_fitting_recipe")
    async def apply_xps_fitting_recipe(
        recipe_id: str,
        pass_energy: int | None = None,
        include_background: bool = True,
        preferred_pass_energy: int | None = None,
        lock_satellites: bool = True,
        lock_spin_orbit: bool = True,
        spin_orbit_partner_splitting_eV: float | None = None,
        spin_orbit_partner_subshell: str | None = None,
        dataset_id: str | None = None,
        spectrum_id: str | None = None,
    ) -> str:
        """
        Expand an XPS fitting recipe into pipeline fitting-step params.

        Satellite ratios and spin-orbit doublet AREA ratios (p 1:2, d 2:3, f 3:4; lock_spin_orbit) are locked by
        default; doublet FWHM follows the recipe table ratio (Ti/V 2p1/2 Coster-Kronig broadening) or is equal.
        One-member recipes (Co/Ni/Fe/Mn/Cr 2p3/2 multiplets) stay single unless spin_orbit_partner_splitting_eV is
        given: then each peak gets a 2p1/2 partner at +splitting (you must supply the splitting; widen the fit window).

        X3: pass dataset_id + spectrum_id (and no pass_energy) to take the pass energy from the spectrum's acquisition metadata.
        """

        def _run():
            preferred_pass_energy_eff = _acquisition_pass_energy(
                ctx,
                pass_energy=pass_energy,
                preferred_pass_energy=preferred_pass_energy,
                dataset_id=dataset_id,
                spectrum_id=spectrum_id,
            )
            data = ctx.get_client().xps.apply_fitting_recipe(
                recipe_id,
                pass_energy=pass_energy,
                include_background=include_background,
                preferred_pass_energy=preferred_pass_energy_eff,
                lock_satellites=lock_satellites,
                lock_spin_orbit=lock_spin_orbit,
                spin_orbit_partner_splitting_eV=spin_orbit_partner_splitting_eV,
                spin_orbit_partner_subshell=spin_orbit_partner_subshell,
            )
            return {"ok": True, "data": data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_xps_add_spin_orbit_partner")
    async def post_xps_add_spin_orbit_partner(
        params: dict[str, Any],
        component_id: str,
        splitting_eV: float,
        subshell: str,
        partner_id: str | None = None,
        lock_area: bool = True,
        link_shape: bool = True,
        fwhm_ratio: float | None = None,
    ) -> str:
        """
        POST /xps/spin-orbit-partner — F3 "Create x 2": add the spin-orbit partner of ONE peak to fitting-step params.

        params: the fitting step's params (components, p0, bounds_lower, bounds_upper, vary, param_links).
        subshell: p (2p1/2 of 2p3/2, area 1:2), d (3d3/2, 2:3) or f (4f5/2, 3:4). splitting_eV > 0 (partner at
        higher BE). Links: pos offset, FWHM equal (or fwhm_ratio, e.g. ~2 for Ti/V 2p1/2), shape equal
        (link_shape), area ratio (lock_area). Returns {params, partner_id}; put params back into the pipeline step.
        """

        def _run():
            data = ctx.get_client().xps.add_spin_orbit_partner(
                {
                    "params": params,
                    "component_id": component_id,
                    "splitting_eV": splitting_eV,
                    "subshell": subshell,
                    "partner_id": partner_id,
                    "lock_area": lock_area,
                    "link_shape": link_shape,
                    "fwhm_ratio": fwhm_ratio,
                }
            )
            return {"ok": True, "data": data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_xps_apply_recipe_to_pipeline_draft")
    async def post_xps_apply_recipe_to_pipeline_draft(
        recipe_id: str,
        pass_energy: int | None = None,
        include_background: bool = True,
        preferred_pass_energy: int | None = None,
        lock_satellites: bool = True,
        lock_spin_orbit: bool = True,
        spin_orbit_partner_splitting_eV: float | None = None,
        spin_orbit_partner_subshell: str | None = None,
        dataset_id: str | None = None,
        spectrum_id: str | None = None,
        pipeline: dict[str, Any] | None = None,
        confirm: bool = False,
    ) -> str:
        """Apply recipe and return an XPS pipeline draft ready for post_pipelines / put_sessions_pipeline."""

        def _run():
            client = ctx.get_client()
            applied = client.xps.apply_fitting_recipe(
                recipe_id,
                pass_energy=pass_energy,
                include_background=include_background,
                preferred_pass_energy=_acquisition_pass_energy(
                    ctx,
                    pass_energy=pass_energy,
                    preferred_pass_energy=preferred_pass_energy,
                    dataset_id=dataset_id,
                    spectrum_id=spectrum_id,
                ),
                lock_satellites=lock_satellites,
                lock_spin_orbit=lock_spin_orbit,
                spin_orbit_partner_splitting_eV=spin_orbit_partner_splitting_eV,
                spin_orbit_partner_subshell=spin_orbit_partner_subshell,
            )
            base = Pipeline.model_validate(pipeline) if pipeline else Pipeline(steps=[], technique_family="xps")
            merged = _merge_apply_into_pipeline(base, applied)
            blocked = confirm_gates.check_fitting_components(
                merged,
                max_components=ctx.config.fitting_confirm_max_components,
                confirm=confirm,
            )
            if blocked is not None:
                return blocked
            return {
                "ok": True,
                "recipe_id": applied.get("recipe_id"),
                "xps_region": applied.get("xps_region"),
                "warnings": applied.get("warnings") or [],
                "pass_energy_resolution": applied.get("pass_energy_resolution"),
                "pipeline": merged.model_dump(),
                "technique_family": "xps",
            }

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_xps_apply_recipe_to_session")
    async def post_xps_apply_recipe_to_session(
        session_id: str,
        recipe_id: str,
        pass_energy: int | None = None,
        include_background: bool = True,
        preferred_pass_energy: int | None = None,
        lock_satellites: bool = True,
        lock_spin_orbit: bool = True,
        spin_orbit_partner_splitting_eV: float | None = None,
        spin_orbit_partner_subshell: str | None = None,
        dataset_id: str | None = None,
        spectrum_id: str | None = None,
        confirm: bool = False,
    ) -> str:
        """Apply XPS recipe into session working pipeline as a fitting step (technique_family=xps)."""

        def _run():
            client = ctx.get_client()
            sess = client.sessions.get(session_id)
            applied = client.xps.apply_fitting_recipe(
                recipe_id,
                pass_energy=pass_energy,
                include_background=include_background,
                preferred_pass_energy=_acquisition_pass_energy(
                    ctx,
                    pass_energy=pass_energy,
                    preferred_pass_energy=preferred_pass_energy,
                    dataset_id=dataset_id,
                    spectrum_id=spectrum_id,
                ),
                lock_satellites=lock_satellites,
                lock_spin_orbit=lock_spin_orbit,
                spin_orbit_partner_splitting_eV=spin_orbit_partner_splitting_eV,
                spin_orbit_partner_subshell=spin_orbit_partner_subshell,
            )
            merged = _merge_apply_into_pipeline(sess.session.pipeline, applied)
            blocked = confirm_gates.check_fitting_components(
                merged,
                max_components=ctx.config.fitting_confirm_max_components,
                confirm=confirm,
            )
            if blocked is not None:
                return blocked
            resp = client.sessions.update_pipeline(
                session_id, SessionPipelineUpdateRequest(pipeline=merged)
            )
            return {
                "ok": True,
                "session_id": session_id,
                "recipe_id": applied.get("recipe_id"),
                "xps_region": applied.get("xps_region"),
                "warnings": applied.get("warnings") or [],
                "pass_energy_resolution": applied.get("pass_energy_resolution"),
                "pipeline_hash": resp.pipeline_hash,
                "n_steps": len(resp.pipeline.steps),
                "technique_family": getattr(resp.pipeline, "technique_family", "xps"),
            }

        return await tool_call(ctx, _run)
