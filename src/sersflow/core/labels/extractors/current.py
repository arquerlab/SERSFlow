from __future__ import annotations

import re

_CURRENT_RE = re.compile(
    r"^(?P<value>[+-]?\d+(?:[d.]\d+)?)\s*(?P<unit>uA|mA|A)(?:[-_]?\d+)?$",
)
_CURRENT_DENSITY_RE = re.compile(
    r"^(?P<value>[+-]?\d+(?:[d._]\d+)?)\s*(?P<unit>uA|mA|A)"
    r"(?:(?:cm-2)|(?:cm\^-?2)|(?:_?cm2)|(?:_?cm-?2)|(?:cm))(?:[-_]\d+)?$",
)
_CURRENT_DENSITY_UNIT_RE = re.compile(
    r"^(?P<unit>uA|mA|A)(?:(?:cm-2)|(?:cm\^-?2)|(?:cm2)|(?:cm))$",
    flags=re.IGNORECASE,
)


def extract_current(search_text: str) -> tuple[float | None, bool]:
    """
    Extract current or current density from search text.

    Returns (value_amps_or_same_numeric_convention_as_legacy, is_current_density).
    Legacy: density tokens still use the same numeric scaling to 'A' as absolute current.
    """
    if re.search(r"(?<![A-Za-z0-9])OCP(?=$|[_\-\s])", search_text, flags=re.IGNORECASE):
        return 0.0, False

    parts = search_text.split("_")

    def _to_float(value_str: str) -> float:
        return float(value_str.replace("d", ".").replace("_", "."))

    def _convert_to_amps(value: float, unit: str) -> float:
        if unit == "uA":
            return value / 1_000_000.0
        if unit == "mA":
            return value / 1000.0
        return value

    for i, part in enumerate(parts):
        m = _CURRENT_RE.match(part)
        if m:
            return _convert_to_amps(_to_float(m.group("value")), m.group("unit")), False

        if i + 1 < len(parts) and re.fullmatch(r"[+-]?\d+(?:[d._]\d+)?", part):
            m2 = _CURRENT_RE.match(parts[i + 1])
            if m2:
                return _convert_to_amps(_to_float(part), m2.group("unit")), False

    for i, part in enumerate(parts):
        density_part = part
        if i + 1 < len(parts) and part in {"mA", "uA", "A"} and parts[i + 1] in {"cm2", "cm-2"}:
            density_part = f"{part}_{parts[i + 1]}"

        m = _CURRENT_DENSITY_RE.match(density_part)
        if m:
            return _convert_to_amps(_to_float(m.group("value")), m.group("unit")), True

        if i + 1 < len(parts) and re.fullmatch(r"[+-]?\d+(?:[d._]\d+)?", part):
            # Split decimal like "0_50_mA_cm2" -> 0.50 mA/cm^2 (not50 mA/cm^2).
            if (
                i + 3 < len(parts)
                and re.fullmatch(r"\d+(?:[d._]\d+)?", parts[i + 1])
                and parts[i + 2] in {"mA", "uA", "A"}
                and parts[i + 3] in {"cm2", "cm-2"}
            ):
                merged = f"{part}_{parts[i + 1]}"
                return _convert_to_amps(_to_float(merged), parts[i + 2]), True

            if (
                i + 2 < len(parts)
                and parts[i + 1] in {"mA", "uA", "A"}
                and parts[i + 2] in {"cm2", "cm-2"}
            ):
                return _convert_to_amps(_to_float(part), parts[i + 1]), True

            m_unit = _CURRENT_DENSITY_UNIT_RE.match(parts[i + 1])
            if m_unit:
                return _convert_to_amps(_to_float(part), m_unit.group("unit")), True

            m2 = _CURRENT_DENSITY_RE.match(parts[i + 1])
            if m2:
                return _convert_to_amps(_to_float(part), m2.group("unit")), True

    return None, False
