from __future__ import annotations

import re


def extract_ph(search_text: str) -> float | None:
    m = re.search(
        r"(?<![A-Za-z0-9])pH[_\s]*(?P<value>\d+(?:[d._]\d+)?)(?=$|[_\-\s])",
        search_text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    return float(m.group("value").replace("d", ".").replace("_", "."))
