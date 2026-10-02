"""Lightweight structural validation for packaged XPS JSON catalogs.

Raises ``ValueError`` with a clear path when required fields are missing or mistyped.
This is intentional schema-lite validation (no external jsonschema dependency).
"""

from __future__ import annotations

from typing import Any

from sersflow.core.xps.lineshape_kinds import KNOWN_LINESHAPE_KINDS

_KNOWN_ENERGY_KINDS = frozenset({"binding", "kinetic"})
_KNOWN_PROVENANCE = frozenset(
    {"phi_handbook", "biesinger_thesis", "biesinger_lit_compile"}
)


def _require_dict(obj: Any, path: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError(f"{path}: expected object, got {type(obj).__name__}")
    return obj


def _require_str(obj: dict[str, Any], key: str, path: str) -> str:
    if key not in obj:
        raise ValueError(f"{path}: missing required field {key!r}")
    val = obj[key]
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{path}.{key}: expected non-empty string")
    return val


def _require_list(obj: dict[str, Any], key: str, path: str) -> list[Any]:
    if key not in obj:
        raise ValueError(f"{path}: missing required field {key!r}")
    val = obj[key]
    if not isinstance(val, list):
        raise ValueError(f"{path}.{key}: expected array")
    return val


def validate_chemical_states_raw(raw: dict[str, Any]) -> list[str]:
    """
    Validate chemical_states.json structure.

    Returns soft warnings (e.g. unknown provenance). Raises ValueError on hard errors.
    """
    warnings: list[str] = []
    data = _require_dict(raw, "chemical_states")
    if "source" in data and data["source"] is not None and not isinstance(data["source"], dict):
        raise ValueError("chemical_states.source: expected object")
    sections = _require_list(data, "sections", "chemical_states")
    seen_ids: set[str] = set()
    for i, sec in enumerate(sections):
        sp = f"chemical_states.sections[{i}]"
        s = _require_dict(sec, sp)
        sid = _require_str(s, "id", sp)
        if sid in seen_ids:
            raise ValueError(f"{sp}.id: duplicate section id {sid!r}")
        seen_ids.add(sid)
        _require_str(s, "element", sp)
        _require_str(s, "line", sp)
        ek = s.get("energy_kind")
        if ek is not None and str(ek) not in _KNOWN_ENERGY_KINDS:
            warnings.append(f"{sp}.energy_kind: unknown {ek!r}")
        entries = _require_list(s, "entries", sp)
        for j, item in enumerate(entries):
            ep = f"{sp}.entries[{j}]"
            e = _require_dict(item, ep)
            _require_str(e, "compound", ep)
            if "value_eV" not in e:
                raise ValueError(f"{ep}: missing required field 'value_eV'")
            try:
                float(e["value_eV"])
            except (TypeError, ValueError) as err:
                raise ValueError(f"{ep}.value_eV: expected number") from err
            prov = e.get("provenance")
            if prov is not None and str(prov) not in _KNOWN_PROVENANCE:
                warnings.append(f"{ep}.provenance: unknown {prov!r}")
    return warnings


def validate_fitting_recipes_raw(raw: dict[str, Any]) -> list[str]:
    """
    Validate fitting_recipes.json structure.

    Returns soft warnings for incomplete peak lineshapes. Raises ValueError on hard errors.
    """
    warnings: list[str] = []
    data = _require_dict(raw, "fitting_recipes")
    if "source" in data and data["source"] is not None and not isinstance(data["source"], dict):
        raise ValueError("fitting_recipes.source: expected object")

    methods = data.get("method_defaults")
    if methods is None:
        methods = []
    if not isinstance(methods, list):
        raise ValueError("fitting_recipes.method_defaults: expected array")
    seen_method_ids: set[str] = set()
    for i, item in enumerate(methods):
        mp = f"fitting_recipes.method_defaults[{i}]"
        m = _require_dict(item, mp)
        mid = _require_str(m, "id", mp)
        if mid in seen_method_ids:
            raise ValueError(f"{mp}.id: duplicate method id {mid!r}")
        seen_method_ids.add(mid)

    fits = _require_list(data, "compound_fits", "fitting_recipes")
    seen_fit_ids: set[str] = set()
    for i, item in enumerate(fits):
        fp = f"fitting_recipes.compound_fits[{i}]"
        f = _require_dict(item, fp)
        fid = _require_str(f, "id", fp)
        if fid in seen_fit_ids:
            raise ValueError(f"{fp}.id: duplicate compound_fit id {fid!r}")
        seen_fit_ids.add(fid)
        _require_str(f, "element", fp)
        _require_str(f, "region", fp)
        _require_str(f, "compound", fp)
        peaks = _require_list(f, "peaks", fp)
        if not peaks:
            raise ValueError(f"{fp}.peaks: must be non-empty")
        so = f.get("spin_orbit_split_eV")
        labels: list[str] = []
        for j, peak in enumerate(peaks):
            pp = f"{fp}.peaks[{j}]"
            p = _require_dict(peak, pp)
            lab = str(p.get("label") or f"p{j + 1}")
            labels.append(lab)
            if "be_eV" in p and p["be_eV"] is not None:
                try:
                    float(p["be_eV"])
                except (TypeError, ValueError) as err:
                    raise ValueError(f"{pp}.be_eV: expected number") from err
            ls = p.get("lineshape")
            if ls is None:
                warnings.append(f"{pp}: missing lineshape (apply will default to gl)")
                continue
            if not isinstance(ls, dict):
                raise ValueError(f"{pp}.lineshape: expected object")
            kind = str(ls.get("kind") or "").strip().lower()
            if not kind:
                warnings.append(f"{pp}.lineshape: missing kind (apply will default to gl)")
            elif kind not in KNOWN_LINESHAPE_KINDS:
                warnings.append(f"{pp}.lineshape.kind: unknown {kind!r}")
        if so is not None:
            joined = " ".join(labels).lower().replace(" ", "")
            has3 = "2p3/2" in joined or "2p32" in joined
            has1 = "2p1/2" in joined or "2p12" in joined
            if not (has3 and has1):
                warnings.append(
                    f"{fp}: spin_orbit_split_eV set but peaks lack a 2p3/2+2p1/2 label pair"
                )
    return warnings
