from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from sersflow.api.schemas.xps import (
    ChemicalStatesResponse,
    FittingRecipeApplyResponse,
    FittingRecipesIndexResponse,
    FittingRecipesResponse,
)
from sersflow.core.xps.chemical_states import (
    list_chemical_state_entries,
    load_chemical_states_catalog,
)
from sersflow.core.xps.fitting_recipes import (
    list_compound_fit_index,
    list_compound_fits,
    list_method_defaults,
    load_fitting_recipes_catalog,
)
from sersflow.core.xps.recipe_apply import apply_recipe_id

router = APIRouter(prefix="/xps", tags=["XPS"])


@router.get("/chemical-states", response_model=ChemicalStatesResponse)
def get_chemical_states(
    element: str | None = Query(default=None, description="Element symbol filter, e.g. Ag"),
    line: str | None = Query(default=None, description="Orbital / Auger line filter, e.g. 3d or MNN"),
    q: str | None = Query(default=None, description="Substring match on compound / phase"),
    provenance: str | None = Query(
        default=None,
        description="Provenance filter: phi_handbook | biesinger_thesis | biesinger_lit_compile",
    ),
    include_sections: bool = Query(
        default=False,
        description="If true, also return section summaries (with nested entries when unfiltered).",
    ),
) -> dict[str, Any]:
    catalog = load_chemical_states_catalog()
    entries = list_chemical_state_entries(
        element=element, line=line, q=q, provenance=provenance
    )
    payload: dict[str, Any] = {
        "source": catalog.source,
        "entries": [e.to_public_dict() for e in entries],
        "entry_count": len(entries),
        "sections": [],
    }
    if include_sections:
        if element is None and line is None and q is None and provenance is None:
            payload["sections"] = [s.to_public_dict() for s in catalog.sections]
        else:
            by_section: dict[str, list[Any]] = {}
            for e in entries:
                by_section.setdefault(e.section_id, []).append(e)
            sections_out = []
            for section in catalog.sections:
                matched = by_section.get(section.id)
                if not matched:
                    continue
                sections_out.append(
                    {
                        "id": section.id,
                        "element": section.element,
                        "line": section.line,
                        "energy_kind": section.energy_kind,
                        "entry_count": len(matched),
                        "entries": [e.to_public_dict() for e in matched],
                    }
                )
            payload["sections"] = sections_out
    return payload


@router.get("/fitting-recipes/index", response_model=FittingRecipesIndexResponse)
def get_fitting_recipes_index(
    element: str | None = Query(default=None, description="Element filter, e.g. Ni"),
    region: str | None = Query(default=None, description="Region substring, e.g. 2p"),
    q: str | None = Query(
        default=None,
        description="Substring on compound, element, region, id, or source_table",
    ),
    source_table: str | None = Query(default=None, description="Thesis table id, e.g. 3.1"),
    limit: int = Query(default=25, ge=1, le=200),
) -> dict[str, Any]:
    items = list_compound_fit_index(
        element=element, region=region, q=q, source_table=source_table, limit=limit
    )
    return {"items": items, "count": len(items)}


@router.get("/fitting-recipes/{recipe_id}/apply", response_model=FittingRecipeApplyResponse)
def apply_fitting_recipe(
    recipe_id: str,
    pass_energy: int | None = Query(default=None, description="Pass energy eV for FWHM column"),
    include_background: bool = Query(
        default=True, description="Prepend Shirley active background when appropriate"
    ),
    preferred_pass_energy: int | None = Query(
        default=None,
        description="Acquisition pass energy hint when pass_energy is omitted",
    ),
) -> dict[str, Any]:
    try:
        return apply_recipe_id(
            recipe_id,
            pass_energy=pass_energy,
            include_background=include_background,
            preferred_pass_energy=preferred_pass_energy,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/fitting-recipes", response_model=FittingRecipesResponse)
def get_fitting_recipes(
    element: str | None = Query(default=None, description="Element filter for compound fits, e.g. Ni"),
    region: str | None = Query(
        default=None, description="Region substring filter, e.g. 2p3/2 or Ni_2p"
    ),
    q: str | None = Query(
        default=None,
        description="Substring on compound, element, region, id, or source_table",
    ),
    source_table: str | None = Query(default=None, description="Thesis table id, e.g. 3.1"),
    chapter: int | None = Query(default=None, description="Filter method_defaults by chapter"),
    include_methods: bool = Query(
        default=True, description="Include Experimental method defaults / how-to markdown"
    ),
) -> dict[str, Any]:
    catalog = load_fitting_recipes_catalog()
    fits = list_compound_fits(
        element=element, region=region, q=q, source_table=source_table
    )
    methods = list_method_defaults(chapter=chapter) if include_methods else []
    return {
        "source": catalog.source,
        "method_defaults": [m.to_public_dict() for m in methods],
        "compound_fits": [f.to_public_dict() for f in fits],
        "method_count": len(methods),
        "compound_fit_count": len(fits),
    }
