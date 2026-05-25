from __future__ import annotations

import re

GAS_TOKENS = {"AR", "O2", "N2", "CO2", "12CO2", "13CO2"}
MODE_TOKENS = {
    "MAP",
    "MAPPING",
    "TR",
    "TIME_RESOLVED",
    "TIMERESOLVED",
    "TIME-RESOLVED",
}


def is_metadata_token(token: str) -> bool:
    """
    Return True if `token` is measurement/metadata, not a chemical sample name.

    Used when stopping sample-name accumulation and when rejecting false compound hits.
    """
    t = token.strip()
    if not t:
        return True
    tl = t.lower()

    # Gas / feed
    if t.upper() in GAS_TOKENS or tl in {"gas", "feeding", "feed", "purged", "bpurged"}:
        return True

    # pH
    if re.fullmatch(r"ph\d+(?:[d._]\d+)?", tl) or tl == "ph":
        return True

    # Measurement mode
    if t.upper() in MODE_TOKENS or tl in {"time", "resolved", "mapping"}:
        return True

    # Laser wavelength
    if re.fullmatch(r"\d{3}nm", tl) or re.fullmatch(r"\d{3}_nm", tl):
        return True
    if tl == "nm":
        return True

    # Laser power
    if re.fullmatch(r"\d+(?:[d._]\d+)?%", tl):
        return True
    if re.fullmatch(r"\d+(?:[d._]\d+)?p\d*", tl):
        return True

    # Objective
    if re.fullmatch(r"\d{1,3}x", tl):
        return True

    # Accumulations
    if tl in {"accu", "aqq"} or re.fullmatch(r"\d+aqq", tl):
        return True

    # Grating
    if re.fullmatch(r"\d+g", tl):
        return True

    # Exposure time
    if tl in {"sec", "s"} or re.fullmatch(r"\d+sec", tl) or re.fullmatch(r"\d+s", tl):
        return True

    # Wavenumber / Raman shift
    if re.fullmatch(r"\d+cm-?1", tl) or re.fullmatch(r"\d+cm1", tl) or re.fullmatch(r"\d+cm", tl):
        return True
    if tl in {"cm2", "cm-2"}:
        return True

    # Current / current-density tokens
    if re.search(r"(?:^|[+\-])\d+(?:[d._]\d+)?(?:ua|ma|a)(?:$|[-_]?\d+$)", tl):
        return True
    if re.search(r"(?:ua|ma|a)cm(?:-?2|\^?-?2|2)?$", tl):
        return True

    # Potential tokens / OCP
    if tl in {"ocp", "vrhe", "rhe", "v", "vagagcl"}:
        return True
    if re.search(r"(?:^|[+\-])\d+(?:[d._]\d+)?(?:vrhe|rhe|vagagcl|v)$", tl):
        return True

    return False
