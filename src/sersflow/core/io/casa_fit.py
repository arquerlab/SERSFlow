"""Parse CasaXPS fit components stored in VAMAS block comments.

CasaXPS writes its region and component definitions into the comment lines of each VAMAS block::

    CASA region (*Co 2p*) (*Shirley*) 306.89756 326.3172 1 4 6 0 0 -450 0 0 (*NoTag*) 0 0 0
    CASA comp (*Co3+*) (*GL(30)*) Area 21108.783 1e-020 301742.6 -1 1 MFWHM 3.2240763 3.159771 3.559771 -1 1
        Position 320.2 320.2 320.3 -1 1 RSF 1 MASS 0 INDEX -1 (*3+*) CONST (**) UNCORRECTEDRSF 0

Positions are KINETIC energies (CasaXPS convention). ``be`` is ``photon energy - KE`` (CasaXPS does not
subtract the analyser work function here), so it matches what CasaXPS reports; it is not the same axis as the
loader's work-function-corrected binding energy.

Each constrained quantity is ``value min max link factor``: ``link`` is the 0-based index of another component
of the same region the quantity is tied to (``-1`` = not tied, the min/max are then the allowed interval); for
tied quantities ``factor`` is the ratio (area, FWHM) or offset (position) to that component.

Parsing is deliberately tolerant: malformed lines are skipped, never raised.
"""

from __future__ import annotations

import math
import re
from typing import Any

_REGION_RE = re.compile(r"^CASA region \(\*(?P<name>.*?)\*\) \(\*(?P<bg>.*?)\*\)\s+(?P<ke0>\S+)\s+(?P<ke1>\S+)(?P<rest>.*)$")
_COMP_RE = re.compile(r"^CASA comp \(\*(?P<name>.*?)\*\) \(\*(?P<shape>.*?)\*\)\s+(?P<rest>.*)$")
_GL_RE = re.compile(r"^(?P<kind>GL|SGL)\((?P<m>[-+0-9.eE]+)\)$", re.IGNORECASE)
_TAG_RE = re.compile(r"\(\*(?P<tag>.*?)\*\)")


def _f(tok: str) -> float | None:
    try:
        v = float(tok)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _quantity(tokens: list[str], key: str) -> dict[str, Any] | None:
    """Five numbers after ``key``: value, min, max, link code, link factor."""
    try:
        i = tokens.index(key)
    except ValueError:
        return None
    vals = [_f(t) for t in tokens[i + 1 : i + 6]]
    if len(vals) < 5 or vals[0] is None:
        return None
    link = None
    if vals[3] is not None and vals[3] >= 0:
        link = int(vals[3])
    return {
        "value": vals[0],
        "min": vals[1],
        "max": vals[2],
        "linked_to": link,
        "link_factor": vals[4] if link is not None else None,
    }


def parse_casa_comments(
    comment_lines: list[str] | tuple[str, ...] | None,
    *,
    photon_energy_eV: float | None = None,
) -> dict[str, Any] | None:
    """
    Parse the CASA region / component lines of one block.

    Returns ``None`` when the block carries no ``CASA comp`` line, else
    ``{"region": {name, background, ke_start_eV, ke_end_eV}, "components": [...], "raw": [...]}``.
    """
    region: dict[str, Any] | None = None
    comps: list[dict[str, Any]] = []
    raw: list[str] = []
    for line in comment_lines or []:
        s = str(line).strip()
        if s.startswith("CASA region"):
            m = _REGION_RE.match(s)
            if m and region is None:
                region = {
                    "name": m.group("name"),
                    "background": m.group("bg"),
                    "ke_start_eV": _f(m.group("ke0")),
                    "ke_end_eV": _f(m.group("ke1")),
                }
                if photon_energy_eV is not None:
                    region["be_start_eV"] = _be(photon_energy_eV, region["ke_start_eV"])
                    region["be_end_eV"] = _be(photon_energy_eV, region["ke_end_eV"])
                raw.append(s)
            continue
        if not s.startswith("CASA comp"):
            continue
        m = _COMP_RE.match(s)
        if not m:
            continue
        tokens = m.group("rest").split()
        area = _quantity(tokens, "Area")
        fwhm = _quantity(tokens, "MFWHM")
        pos = _quantity(tokens, "Position")
        if pos is None or area is None:
            continue
        shape = m.group("shape")
        gl = _GL_RE.match(shape)
        comp: dict[str, Any] = {
            "index": len(comps),
            "name": m.group("name"),
            "lineshape": shape,
            "m": float(gl.group("m")) if gl else None,
            "area": area["value"],
            "fwhm": fwhm["value"] if fwhm else None,
            "ke_eV": pos["value"],
            "be_eV": _be(photon_energy_eV, pos["value"]),
            "area_constraint": area,
            "fwhm_constraint": fwhm,
            "position_constraint": pos,
        }
        rsf = _quantity_simple(tokens, "RSF")
        if rsf is not None:
            comp["rsf"] = rsf
        tags = _TAG_RE.findall(m.group("rest"))
        if tags and tags[0] and tags[0] != "NoTag":
            comp["tag"] = tags[0]
        comps.append(comp)
        raw.append(s)
    if not comps:
        return None
    return {"region": region, "components": comps, "raw": raw}


def _quantity_simple(tokens: list[str], key: str) -> float | None:
    try:
        return _f(tokens[tokens.index(key) + 1])
    except (ValueError, IndexError):
        return None


def _be(photon_energy_eV: float | None, ke: float | None) -> float | None:
    if photon_energy_eV is None or ke is None:
        return None
    return float(photon_energy_eV) - float(ke)
