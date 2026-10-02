"""
Loader for packaged XPS chemical-states tables (PHI handbook + Biesinger literature).

Reference data is shipped as JSON under ``sersflow.core.xps.data`` so it stays
versioned with the package and separate from the mutable workspace SQLite DB.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any, Literal

from sersflow.core.xps.catalog_validate import validate_chemical_states_raw

logger = logging.getLogger(__name__)

EnergyKind = Literal["binding", "kinetic"]
Provenance = Literal["phi_handbook", "biesinger_thesis", "biesinger_lit_compile"]

_AUGER_TOKENS = ("KLL", "LMM", "MNN", "MNV", "MVV", "LVV", "NOO")


@dataclass(frozen=True)
class ChemicalStateEntry:
    compound: str
    phase: str | None
    value_eV: float
    references: tuple[str, ...]
    raw_line: str | None
    page: int | None
    section_id: str
    element: str
    line: str
    energy_kind: EnergyKind
    provenance: str | None = None
    source_detail: str | None = None
    auger_parameter: float | None = None
    fwhm_eV: float | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "element": self.element,
            "line": self.line,
            "energy_kind": self.energy_kind,
            "compound": self.compound,
            "phase": self.phase,
            "value_eV": self.value_eV,
            "references": list(self.references),
            "raw_line": self.raw_line,
            "page": self.page,
            "provenance": self.provenance,
            "source_detail": self.source_detail,
            "auger_parameter": self.auger_parameter,
            "fwhm_eV": self.fwhm_eV,
        }


@dataclass(frozen=True)
class ChemicalStateSection:
    id: str
    element: str
    line: str
    energy_kind: EnergyKind
    entries: tuple[ChemicalStateEntry, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "element": self.element,
            "line": self.line,
            "energy_kind": self.energy_kind,
            "entry_count": len(self.entries),
            "entries": [e.to_public_dict() for e in self.entries],
        }


@dataclass(frozen=True)
class ChemicalStatesCatalog:
    source: dict[str, Any]
    sections: tuple[ChemicalStateSection, ...]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "source": dict(self.source),
            "sections": [s.to_public_dict() for s in self.sections],
            "entry_count": sum(len(s.entries) for s in self.sections),
        }


def _data_path() -> Any:
    return resources.files("sersflow.core.xps.data").joinpath("chemical_states.json")


def _normalize_energy_kind(line: str, declared: str | None) -> EnergyKind:
    up = (line or "").upper()
    if any(tok in up for tok in _AUGER_TOKENS):
        return "kinetic"
    if declared == "kinetic":
        return "kinetic"
    return "binding"


def _parse_catalog(raw: dict[str, Any]) -> ChemicalStatesCatalog:
    source = dict(raw.get("source") or {})
    fallback_page = source.get("handbook_page")
    sections: list[ChemicalStateSection] = []
    for sec in raw.get("sections") or []:
        element = str(sec["element"])
        line = str(sec["line"])
        energy_kind = _normalize_energy_kind(line, sec.get("energy_kind"))
        section_id = str(sec["id"])
        entries: list[ChemicalStateEntry] = []
        for item in sec.get("entries") or []:
            refs = tuple(str(r) for r in (item.get("references") or []) if str(r).strip())
            page_val = item.get("page", fallback_page)
            page = int(page_val) if page_val is not None else None
            auger = item.get("auger_parameter")
            fwhm = item.get("fwhm_eV")
            entries.append(
                ChemicalStateEntry(
                    compound=str(item["compound"]),
                    phase=(str(item["phase"]) if item.get("phase") not in (None, "") else None),
                    value_eV=float(item["value_eV"]),
                    references=refs,
                    raw_line=(str(item["raw_line"]) if item.get("raw_line") else None),
                    page=page,
                    section_id=section_id,
                    element=element,
                    line=line,
                    energy_kind=energy_kind,
                    provenance=(str(item["provenance"]) if item.get("provenance") else None),
                    source_detail=(str(item["source_detail"]) if item.get("source_detail") else None),
                    auger_parameter=(float(auger) if auger is not None else None),
                    fwhm_eV=(float(fwhm) if fwhm is not None else None),
                )
            )
        sections.append(
            ChemicalStateSection(
                id=section_id,
                element=element,
                line=line,
                energy_kind=energy_kind,
                entries=tuple(entries),
            )
        )
    return ChemicalStatesCatalog(source=source, sections=tuple(sections))


@lru_cache(maxsize=1)
def load_chemical_states_catalog() -> ChemicalStatesCatalog:
    text = _data_path().read_text(encoding="utf-8")
    raw = json.loads(text)
    for w in validate_chemical_states_raw(raw):
        logger.warning("chemical_states catalog: %s", w)
    return _parse_catalog(raw)


def list_chemical_state_entries(
    *,
    element: str | None = None,
    line: str | None = None,
    q: str | None = None,
    provenance: str | None = None,
) -> list[ChemicalStateEntry]:
    """
    Filter packaged chemical-state entries.

    - ``element`` / ``line``: case-insensitive exact match
    - ``q``: case-insensitive substring against compound and phase
    - ``provenance``: case-insensitive exact match (e.g. phi_handbook)
    """
    catalog = load_chemical_states_catalog()
    element_key = element.strip().lower() if element else None
    line_key = line.strip().lower() if line else None
    q_key = q.strip().lower() if q else None
    prov_key = provenance.strip().lower() if provenance else None

    out: list[ChemicalStateEntry] = []
    for section in catalog.sections:
        if element_key is not None and section.element.lower() != element_key:
            continue
        if line_key is not None and section.line.lower() != line_key:
            continue
        for entry in section.entries:
            if q_key is not None:
                hay = f"{entry.compound} {entry.phase or ''}".lower()
                if q_key not in hay:
                    continue
            if prov_key is not None and (entry.provenance or "").lower() != prov_key:
                continue
            out.append(entry)
    return out
