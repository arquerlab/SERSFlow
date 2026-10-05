"""Merge Biesinger thesis O 1s tables 2.11 and 3.7 into chemical_states.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECIPES = ROOT / "src/sersflow/core/xps/data/fitting_recipes.json"
CHEM = ROOT / "src/sersflow/core/xps/data/chemical_states.json"

PHASE_LABELS = {
    "lattice_oxide": "lattice oxide",
    "hydroxide_hydrated_defective": "hydroxide, hydrated or defective oxide",
    "hydroxide_hydrated_defective_organic": "hydroxide, hydrated, defective or organic",
    "water_organic": "water / organic O",
    "physisorbed_water": "physisorbed water",
}


def _phase_for(label: str | None) -> str | None:
    if not label:
        return None
    return PHASE_LABELS.get(str(label), str(label).replace("_", " "))


def _fwhm_prefer(peak: dict) -> float | None:
    for key in ("fwhm_10", "fwhm_20"):
        v = peak.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def build_entries(recipes: dict) -> list[dict]:
    out: list[dict] = []
    for fit in recipes.get("compound_fits") or []:
        table = str(fit.get("source_table") or "")
        if table not in ("2.11", "3.7"):
            continue
        if str(fit.get("region") or "").replace(" ", "_").upper() not in ("O_1S", "O1S"):
            continue
        compound = str(fit.get("compound") or "").strip()
        page = fit.get("pdf_page")
        pdf_idx = (int(page) - 1) if isinstance(page, int) else None
        for peak in fit.get("peaks") or []:
            be = peak.get("be_eV")
            if not isinstance(be, (int, float)):
                continue
            label = peak.get("label")
            phase = _phase_for(label if isinstance(label, str) else None)
            fwhm = _fwhm_prefer(peak)
            std = peak.get("be_std_eV")
            std_s = f" ± {float(std):g} eV" if isinstance(std, (int, float)) else ""
            area = peak.get("area_pct")
            area_s = f"; area {float(area):g}%" if isinstance(area, (int, float)) else ""
            fwhm_s = f"; FWHM={fwhm:g} eV" if fwhm is not None else ""
            phase_s = f" ({phase})" if phase else ""
            raw = f"{compound}{phase_s} O 1s = {float(be):g}{std_s}{fwhm_s}{area_s} (this work, Table {table})"
            entry: dict = {
                "compound": compound,
                "phase": phase,
                "value_eV": float(be),
                "references": [],
                "raw_line": raw,
                "page": int(page) if isinstance(page, int) else None,
                "pdf_page_index": pdf_idx,
                "provenance": "biesinger_thesis",
                "source_detail": f"Table {table}",
            }
            if fwhm is not None:
                entry["fwhm_eV"] = fwhm
            out.append(entry)
    return out


def main() -> None:
    recipes = json.loads(RECIPES.read_text(encoding="utf-8"))
    chem = json.loads(CHEM.read_text(encoding="utf-8"))
    new_entries = build_entries(recipes)
    if not new_entries:
        raise SystemExit("No O 1s recipe peaks found to merge")

    sections = chem.get("sections") or []
    o_sec = next((s for s in sections if s.get("id") == "O_1s"), None)
    if o_sec is None:
        raise SystemExit("O_1s section missing")

    existing = o_sec.get("entries") or []
    # Drop prior merge of these tables so re-run is idempotent.
    kept = [
        e
        for e in existing
        if not (
            e.get("provenance") == "biesinger_thesis"
            and str(e.get("source_detail") or "") in ("Table 2.11", "Table 3.7")
        )
    ]
    o_sec["entries"] = kept + new_entries
    CHEM.write_text(json.dumps(chem, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"O_1s entries: {len(kept)} kept + {len(new_entries)} biesinger = {len(o_sec['entries'])}")
    by_table: dict[str, int] = {}
    for e in new_entries:
        by_table[str(e.get("source_detail"))] = by_table.get(str(e.get("source_detail")), 0) + 1
    print(by_table)


if __name__ == "__main__":
    main()
