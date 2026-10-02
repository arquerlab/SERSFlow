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
    ) -> str:
        """Expand an XPS fitting recipe into pipeline fitting-step params."""

        def _run():
            data = ctx.get_client().xps.apply_fitting_recipe(
                recipe_id,
                pass_energy=pass_energy,
                include_background=include_background,
                preferred_pass_energy=preferred_pass_energy,
            )
            return {"ok": True, "data": data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_xps_apply_recipe_to_pipeline_draft")
    async def post_xps_apply_recipe_to_pipeline_draft(
        recipe_id: str,
        pass_energy: int | None = None,
        include_background: bool = True,
        preferred_pass_energy: int | None = None,
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
                preferred_pass_energy=preferred_pass_energy,
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
                preferred_pass_energy=preferred_pass_energy,
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
                "pipeline_hash": resp.pipeline_hash,
                "n_steps": len(resp.pipeline.steps),
                "technique_family": getattr(resp.pipeline, "technique_family", "xps"),
            }

        return await tool_call(ctx, _run)
