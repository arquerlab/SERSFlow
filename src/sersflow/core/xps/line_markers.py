"""
Element-line and chemical-state markers (X2), derived from the chemical-state library.

There is no stand-alone element/line table in the project (the RSF library of Q1 is deferred), so survey markers are
DERIVED from the chemical-state library (PHI Handbook Appendix B + Biesinger): per element and line the elemental /
metal entries give the marker energy (median), and for elements without an elemental entry (C, O, N, ...) the median
over all compounds is used and flagged ``compounds_median`` with its min-max spread. Only the lines the handbook
tabulates exist (for example Fe 2p but not Fe 3p), so a missing marker never proves an element is absent.
Auger lines are kinetic energies; they become binding-energy markers only when the photon energy is known.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

from sersflow.core.xps.chemical_states import ChemicalStateEntry, load_chemical_states_catalog

_EPS = 1e-9


def _is_elemental(e: ChemicalStateEntry, element: str) -> bool:
    return e.compound.strip().lower() == element.lower() or str(e.phase or "").strip().lower() == "metal"


def _is_splitting_line(line: str) -> bool:
    return "split" in line.lower()


def element_line_markers(
    *,
    element: str | None = None,
    be_min: float | None = None,
    be_max: float | None = None,
    photon_energy_eV: float | None = None,
    include_auger: bool = True,
) -> dict[str, Any]:
    """Markers (one per element/line section) within an optional binding-energy window."""
    cat = load_chemical_states_catalog()
    out: list[dict[str, Any]] = []
    skipped_auger = 0
    for s in cat.sections:
        if element and s.element.lower() != element.strip().lower():
            continue
        if _is_splitting_line(s.line) or not s.entries:
            continue
        vals_all = [float(e.value_eV) for e in s.entries]
        vals_el = [float(e.value_eV) for e in s.entries if _is_elemental(e, s.element)]
        vals = vals_el or vals_all
        basis = "elemental" if vals_el else "compounds_median"
        med = float(statistics.median(vals))
        lo, hi = float(min(vals)), float(max(vals))
        kind = "core"
        ke = None
        if s.energy_kind == "kinetic":
            if not include_auger:
                continue
            if photon_energy_eV is None:
                skipped_auger += 1
                continue
            kind = "auger"
            ke = med
            med, lo, hi = float(photon_energy_eV) - med, float(photon_energy_eV) - hi, float(photon_energy_eV) - lo
        if be_min is not None and med < be_min - _EPS:
            continue
        if be_max is not None and med > be_max + _EPS:
            continue
        out.append(
            {
                "element": s.element,
                "line": s.line,
                "label": f"{s.element} {s.line}",
                "section_id": s.id,
                "kind": kind,
                "be_eV": med,
                "be_min_eV": lo,
                "be_max_eV": hi,
                "ke_eV": ke,
                "basis": basis,
                "n_entries": len(vals),
            }
        )
    out.sort(key=lambda m: m["be_eV"])
    return {
        "markers": out,
        "count": len(out),
        "auger_skipped_no_photon_energy": skipped_auger,
        "note": (
            "Derived from the chemical-state library (handbook lines only). basis=elemental: median of the elemental "
            "entries; compounds_median: median over compounds (approximate, see be_min/be_max). Not a full line table."
        ),
    }


def reference_markers(element: str, line: str | None = None) -> dict[str, Any]:
    """Chemical-state reference energies of one element/line grouped by compound (median, min-max, provenance)."""
    cat = load_chemical_states_catalog()
    groups: dict[tuple[str, str], list[ChemicalStateEntry]] = defaultdict(list)
    section_ids: set[str] = set()
    for s in cat.sections:
        if s.element.lower() != element.strip().lower():
            continue
        if line and s.line.lower() != line.strip().lower():
            continue
        if _is_splitting_line(s.line):
            continue
        section_ids.add(s.id)
        for e in s.entries:
            groups[(s.line, e.compound.strip())].append(e)
    items: list[dict[str, Any]] = []
    for (ln, compound), entries in groups.items():
        vals = sorted({round(float(e.value_eV), 3) for e in entries})
        allv = [float(e.value_eV) for e in entries]
        items.append(
            {
                "compound": compound,
                "line": ln,
                "energy_kind": entries[0].energy_kind,
                "median_eV": float(statistics.median(allv)),
                "min_eV": float(min(allv)),
                "max_eV": float(max(allv)),
                "n_entries": len(entries),
                "distinct_values_eV": vals,
                "phases": sorted({str(e.phase) for e in entries if e.phase}),
                "provenance": sorted({str(e.provenance) for e in entries if e.provenance}),
                "elemental": _is_elemental(entries[0], element),
            }
        )
    items.sort(key=lambda g: (g["line"], g["median_eV"]))
    return {"element": element, "line": line, "sections": sorted(section_ids), "compounds": items, "count": len(items)}
