"""
Loader for packaged XPS fitting recipes (Biesinger thesis extract).

Method defaults (how-to) and compound-specific peak packs are shipped as JSON
under ``sersflow.core.xps.data``, separate from the mutable workspace SQLite DB.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from sersflow.core.xps.catalog_validate import validate_fitting_recipes_raw

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MethodDefault:
    id: str
    chapter: int
    instrument: str | None
    software: str | None
    background: str | None
    charge_ref: dict[str, Any]
    default_lineshape: dict[str, Any]
    metal_lineshape: dict[str, Any]
    constraints: tuple[dict[str, Any], ...]
    gl_examples: tuple[dict[str, Any], ...]
    procedure_markdown: str | None
    raw: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "chapter": self.chapter,
            "instrument": self.instrument,
            "software": self.software,
            "background": self.background,
            "charge_ref": dict(self.charge_ref),
            "default_lineshape": dict(self.default_lineshape),
            "metal_lineshape": dict(self.metal_lineshape),
            "constraints": [dict(c) for c in self.constraints],
            "gl_examples": [dict(g) for g in self.gl_examples],
            "procedure_markdown": self.procedure_markdown,
        }


@dataclass(frozen=True)
class CompoundFit:
    id: str
    element: str
    region: str
    compound: str
    source_table: str | None
    pdf_page: int | None
    pass_energies: tuple[int, ...]
    peaks: tuple[dict[str, Any], ...]
    footnotes: tuple[str, ...]
    raw: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        out = {
            "id": self.id,
            "element": self.element,
            "region": self.region,
            "compound": self.compound,
            "source_table": self.source_table,
            "pdf_page": self.pdf_page,
            "pass_energies": list(self.pass_energies),
            "peaks": [dict(p) for p in self.peaks],
            "footnotes": list(self.footnotes),
        }
        for key in ("spin_orbit_split_eV", "charge_ref_eV", "procedure_markdown"):
            if key in self.raw and self.raw[key] is not None:
                out[key] = self.raw[key]
        return out


@dataclass(frozen=True)
class FittingRecipesCatalog:
    source: dict[str, Any]
    method_defaults: tuple[MethodDefault, ...]
    compound_fits: tuple[CompoundFit, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "source": dict(self.source),
            "method_defaults": [m.to_public_dict() for m in self.method_defaults],
            "compound_fits": [c.to_public_dict() for c in self.compound_fits],
            "method_count": len(self.method_defaults),
            "compound_fit_count": len(self.compound_fits),
        }


def _data_path() -> Any:
    return resources.files("sersflow.core.xps.data").joinpath("fitting_recipes.json")


def _parse_catalog(raw: dict[str, Any]) -> FittingRecipesCatalog:
    methods: list[MethodDefault] = []
    for item in raw.get("method_defaults") or []:
        methods.append(
            MethodDefault(
                id=str(item["id"]),
                chapter=int(item.get("chapter") or 0),
                instrument=(str(item["instrument"]) if item.get("instrument") else None),
                software=(str(item["software"]) if item.get("software") else None),
                background=(str(item["background"]) if item.get("background") else None),
                charge_ref=dict(item.get("charge_ref") or {}),
                default_lineshape=dict(item.get("default_lineshape") or {}),
                metal_lineshape=dict(item.get("metal_lineshape") or {}),
                constraints=tuple(dict(c) for c in (item.get("constraints") or [])),
                gl_examples=tuple(dict(g) for g in (item.get("gl_examples") or [])),
                procedure_markdown=(
                    str(item["procedure_markdown"]) if item.get("procedure_markdown") else None
                ),
                raw=dict(item),
            )
        )

    fits: list[CompoundFit] = []
    for item in raw.get("compound_fits") or []:
        fits.append(
            CompoundFit(
                id=str(item["id"]),
                element=str(item["element"]),
                region=str(item["region"]),
                compound=str(item["compound"]),
                source_table=(str(item["source_table"]) if item.get("source_table") else None),
                pdf_page=(int(item["pdf_page"]) if item.get("pdf_page") is not None else None),
                pass_energies=tuple(int(x) for x in (item.get("pass_energies") or [])),
                peaks=tuple(dict(p) for p in (item.get("peaks") or [])),
                footnotes=tuple(str(f) for f in (item.get("footnotes") or [])),
                raw=dict(item),
            )
        )

    return FittingRecipesCatalog(
        source=dict(raw.get("source") or {}),
        method_defaults=tuple(methods),
        compound_fits=tuple(fits),
    )


@lru_cache(maxsize=1)
def load_fitting_recipes_catalog() -> FittingRecipesCatalog:
    text = _data_path().read_text(encoding="utf-8")
    raw = json.loads(text)
    for w in validate_fitting_recipes_raw(raw):
        logger.warning("fitting_recipes catalog: %s", w)
    return _parse_catalog(raw)


def list_method_defaults(*, chapter: int | None = None) -> list[MethodDefault]:
    catalog = load_fitting_recipes_catalog()
    if chapter is None:
        return list(catalog.method_defaults)
    return [m for m in catalog.method_defaults if m.chapter == chapter]


def list_compound_fits(
    *,
    element: str | None = None,
    region: str | None = None,
    q: str | None = None,
    source_table: str | None = None,
) -> list[CompoundFit]:
    """
    Filter compound fit packs.

    - ``element``: case-insensitive exact match
    - ``region``: case-insensitive substring against region (e.g. ``2p3/2`` or ``Ni_2p``)
    - ``q``: case-insensitive substring against compound, element, region, id, or source_table
    - ``source_table``: exact table id (e.g. ``3.1``)
    """
    catalog = load_fitting_recipes_catalog()
    element_key = element.strip().lower() if element else None
    region_key = region.strip().lower() if region else None
    q_key = q.strip().lower() if q else None
    table_key = source_table.strip() if source_table else None

    out: list[CompoundFit] = []
    for fit in catalog.compound_fits:
        if element_key is not None and fit.element.lower() != element_key:
            continue
        if region_key is not None and region_key not in fit.region.lower():
            continue
        if q_key is not None:
            alias_bits: list[str] = []
            raw_aliases = fit.raw.get("aliases")
            if isinstance(raw_aliases, list):
                alias_bits = [str(a) for a in raw_aliases]
            hay = " ".join(
                [
                    fit.compound,
                    fit.element,
                    fit.region,
                    fit.region.replace("_", " "),
                    fit.region.replace("_", ""),
                    fit.id,
                    fit.source_table or "",
                    *alias_bits,
                ]
            ).lower()
            if q_key not in hay:
                continue
        if table_key is not None and (fit.source_table or "") != table_key:
            continue
        out.append(fit)
    return out


def get_compound_fit(recipe_id: str) -> CompoundFit | None:
    rid = recipe_id.strip()
    if not rid:
        return None
    catalog = load_fitting_recipes_catalog()
    for fit in catalog.compound_fits:
        if fit.id == rid:
            return fit
    return None


def compound_fit_display_label(fit: CompoundFit) -> str:
    compound = fit.compound
    region = fit.region.replace("_", " ")
    parts = [compound, region]
    st = (fit.source_table or "").strip()
    if st and not st.lower().startswith("experimental"):
        parts.append(f"table {st}")
    return " · ".join(parts)


def list_compound_fit_index(
    *,
    element: str | None = None,
    region: str | None = None,
    q: str | None = None,
    source_table: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Lightweight index rows for type-ahead (no peaks / footnotes)."""
    lim = max(1, min(int(limit), 200))
    fits = list_compound_fits(
        element=element, region=region, q=q, source_table=source_table
    )
    out: list[dict[str, Any]] = []
    for fit in fits[:lim]:
        aliases = fit.raw.get("aliases") if isinstance(fit.raw.get("aliases"), list) else []
        out.append(
            {
                "id": fit.id,
                "element": fit.element,
                "region": fit.region,
                "compound": fit.compound,
                "source_table": fit.source_table,
                "pass_energies": list(fit.pass_energies),
                "label": compound_fit_display_label(fit),
                "aliases": [str(a) for a in aliases if str(a).strip()],
            }
        )
    return out
