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
_CALIB_RE = re.compile(r"^Calib\s+M\s*=\s*(?P<m>\S+)\s+A\s*=\s*(?P<a>\S+)\s*(?P<mode>.*)$")


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


def parse_casa_calibration(comment_lines: list[str] | tuple[str, ...] | None) -> dict[str, Any] | None:
    """
    Parse the CasaXPS energy-scale calibration line of one block, e.g. ``Calib M = 3.4120 A = 0 BE ADD``.

    CasaXPS applies ``BE = photon energy - KE - M`` (``A`` is a multiplicative term, 0 = unused). The
    loader's binding-energy axis subtracts the analyser work function instead, so the loader axis maps onto
    the CasaXPS one by ``BE_casa = BE_loader + (work_function - M)``. Returns ``None`` when absent.
    """
    for line in comment_lines or []:
        m = _CALIB_RE.match(str(line).strip())
        if not m:
            continue
        shift = _f(m.group("m"))
        if shift is None:
            continue
        return {"M_eV": shift, "A": _f(m.group("a")), "mode": m.group("mode").strip() or None}
    return None


def parse_casa_region(
    comment_lines: list[str] | tuple[str, ...] | None,
    *,
    photon_energy_eV: float | None = None,
) -> dict[str, Any] | None:
    """
    First ``CASA region`` line of a block with its numeric fields, e.g. ``... 306.91016 326.33032 1 4 6 0 0 -450 0 0``:
    KE start, KE end, then ``[1] 4`` = Av Width, ``6`` = Start Offset %, ``0`` = End Offset %, then four background
    parameters. Field meaning verified on CasaXPS Shirley exports for Av Width (4 -> centred +-3 channels) and the
    Start Offset (applied at the start = low-KE = high-BE end); the End Offset position is inferred (0 in all data
    seen). ``be_min_eV`` / ``be_max_eV`` are ``photon energy - KE`` (CasaXPS calibrated frame) and the offsets are
    also mapped onto the low-/high-BE ends.
    """
    for line in comment_lines or []:
        s = str(line).strip()
        if not s.startswith("CASA region"):
            continue
        m = _REGION_RE.match(s)
        if not m:
            continue
        ke0, ke1 = _f(m.group("ke0")), _f(m.group("ke1"))
        nums: list[float] = []
        for tok in m.group("rest").split():
            v = _f(tok)
            if v is None:
                break
            nums.append(v)
        out: dict[str, Any] = {"name": m.group("name"), "background": m.group("bg"), "ke_start_eV": ke0, "ke_end_eV": ke1, "fields": nums}
        if len(nums) >= 4:
            out["av_width"] = nums[1]
            out["start_offset_pct"] = nums[2]
            out["end_offset_pct"] = nums[3]
        if photon_energy_eV is not None and ke0 is not None and ke1 is not None:
            be0, be1 = _be(photon_energy_eV, ke0), _be(photon_energy_eV, ke1)
            if be0 is not None and be1 is not None:
                out["be_min_eV"], out["be_max_eV"] = min(be0, be1), max(be0, be1)
                if "start_offset_pct" in out:
                    start_is_high = be0 >= be1
                    out["offset_high_pct"] = out["start_offset_pct"] if start_is_high else out["end_offset_pct"]
                    out["offset_low_pct"] = out["end_offset_pct"] if start_is_high else out["start_offset_pct"]
        return out
    return None


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
