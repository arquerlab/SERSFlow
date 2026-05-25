from __future__ import annotations

import re


def extract_laser_wavelength_nm(search_text: str) -> int | None:
    segments = search_text.split("__")
    for seg in segments:
        m = re.search(r"(?<!\d)(?P<nm>\d{3})_?nm(?=$|[_\-\s])", seg, flags=re.IGNORECASE)
        if m:
            return int(m.group("nm"))

        tokens = [t for t in re.split(r"[_\s]+", seg) if t]
        for i in range(len(tokens) - 1):
            if re.fullmatch(r"\d{3}", tokens[i]) and tokens[i + 1].lower() == "nm":
                return int(tokens[i])
    return None


def extract_laser_power_percent(search_text: str) -> float | None:
    def _to_float(value_str: str) -> float:
        return float(value_str.replace("d", ".").replace("_", "."))

    segments = search_text.split("__")
    for seg in segments:
        m = re.search(
            r"(?<![A-Za-z0-9])(?P<value>\d+(?:[d._]\d+)?)%(?=$|[_\-\s]|[A-Za-z])",
            seg,
        )
        if m:
            return _to_float(m.group("value"))

        tokens = [t for t in re.split(r"[_\s]+", seg) if t]
        for i in range(len(tokens) - 1):
            if re.fullmatch(r"\d+(?:[d._]\d+)?", tokens[i]) and tokens[i + 1] == "%":
                return _to_float(tokens[i])

        m = re.search(
            r"(?<![A-Za-z0-9])(?P<value>\d+(?:[d._]\d+)?)p(?=$|[_\-\s])",
            seg,
            flags=re.IGNORECASE,
        )
        if m:
            return _to_float(m.group("value"))
    return None
