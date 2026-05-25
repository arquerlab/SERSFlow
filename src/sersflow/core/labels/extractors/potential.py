from __future__ import annotations

import re


def extract_potential(search_text: str) -> tuple[float, str] | None:
    """Return (volts, ref) with ref in VRHE, VAgAgCl, V, or OCP."""
    def _to_float(value_str: str) -> float:
        return float(value_str.replace("d", ".").replace("_", "."))

    m = re.search(
        r"(?P<value>[+-]?\d+(?:[d._]\d+)?)VRHE(?=$|[_\-\s])",
        search_text,
        flags=re.IGNORECASE,
    )
    if m:
        return _to_float(m.group("value")), "VRHE"

    m = re.search(
        r"(?P<value>[+-]?\d+(?:[d._]\d+)?)RHE(?=$|[_\-\s])",
        search_text,
        flags=re.IGNORECASE,
    )
    if m:
        return _to_float(m.group("value")), "VRHE"

    m = re.search(
        r"(?P<value>[+-]?\d+(?:[d._]\d+)?)(?:VAGAGCL|V_AGAGCL)(?=$|[_\-\s])",
        search_text,
        flags=re.IGNORECASE,
    )
    if m:
        return _to_float(m.group("value")), "VAgAgCl"

    m = re.search(
        r"(?P<value>[+-]?\d+(?:[d._]\d+)?)V(?=$|[_\-\s])",
        search_text,
        flags=re.IGNORECASE,
    )
    if m:
        return _to_float(m.group("value")), "V"

    if re.search(r"(?<![A-Za-z0-9])OCP(?=$|[_\-\s])", search_text, flags=re.IGNORECASE):
        return 0.0, "OCP"

    return None
