from __future__ import annotations

import re

from sersflow.core.labels.extractors.compound import extract_compound_and_concentration


def extract_electrolyte(search_text: str) -> str | None:
    parsed = extract_compound_and_concentration(search_text)
    if parsed:
        return str(parsed["compound"])

    # Accept typical delimiters found in filenames and full paths (Windows uses `\`).
    _DELIM = r"(?:$|[_\-\s\\/])"

    for pat, label in [
        (rf"(?<![A-Za-z0-9])KHCO3(?={_DELIM})", "KHCO3"),
        (rf"(?<![A-Za-z0-9])K2SO4(?={_DELIM})", "K2SO4"),
        (rf"(?<![A-Za-z0-9])H2SO4(?={_DELIM})", "H2SO4"),
        (rf"(?<![A-Za-z0-9])KOH(?={_DELIM})", "KOH"),
    ]:
        if re.search(pat, search_text, flags=re.IGNORECASE):
            return label
    return None
