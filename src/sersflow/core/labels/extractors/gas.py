from __future__ import annotations

import re


def extract_gas(search_text: str) -> str | None:
    if re.search(r"(?<![A-Za-z0-9])13CO2(?=$|[_\-\s])", search_text, flags=re.IGNORECASE):
        return "13CO2"
    if re.search(r"(?<![A-Za-z0-9])12CO2(?=$|[_\-\s])", search_text, flags=re.IGNORECASE):
        return "CO2"
    if re.search(r"(?<![A-Za-z0-9])CO2(?=$|[_\-\s])", search_text, flags=re.IGNORECASE):
        return "CO2"
    if re.search(r"(?<![A-Za-z0-9])Ar(?=$|[_\-\s])", search_text, flags=re.IGNORECASE):
        return "Ar"
    if re.search(r"(?<![A-Za-z0-9])O2(?=$|[_\-\s])", search_text, flags=re.IGNORECASE):
        return "O2"
    if re.search(r"(?<![A-Za-z0-9])N2(?=$|[_\-\s])", search_text, flags=re.IGNORECASE):
        return "N2"
    return None
