from __future__ import annotations

import re

from sersflow.core.labels.patterns import is_metadata_token


def extract_sample(search_text: str) -> str | None:
    """
    Extract sample name from the first segment (filename only).

    Stops at metadata tokens (laser, current, potential, gas, etc.).
    """
    filename_segment = search_text.split("__", 1)[0]
    tokens = [t for t in filename_segment.split("_") if t]
    if not tokens:
        return None

    lowered = [t.lower() for t in tokens]
    if len(tokens) >= 3 and lowered[:3] == ["new", "batch", "cu"]:
        return "_".join(tokens[:3])

    if len(tokens) >= 2 and lowered[:2] == ["ap", "catalyst"]:
        return "_".join(tokens[:2])

    sample_tokens: list[str] = []
    for i, tok in enumerate(tokens):
        t = tok.lower()

        if i + 1 < len(tokens) and re.fullmatch(r"\d{3}", t) and tokens[i + 1].lower() == "nm":
            break

        if i + 1 < len(tokens) and t == "time" and tokens[i + 1].lower() == "resolved":
            break

        if i + 1 < len(tokens) and re.fullmatch(r"\d+", t) and tokens[i + 1].lower() == "sec":
            break

        if i + 1 < len(tokens) and re.fullmatch(r"\d+", t) and tokens[i + 1].lower() == "accu":
            break

        if is_metadata_token(tok):
            break

        sample_tokens.append(tok)

    if not sample_tokens:
        return tokens[0]

    if (
        len(sample_tokens) >= 2
        and sample_tokens[0] in {"Cu", "Ag", "Au", "Pt", "Ni", "Fe", "Co"}
        and re.fullmatch(r"\d{2,4}", sample_tokens[1])
    ):
        return f"{sample_tokens[0]}_{sample_tokens[1]}"

    return "_".join(sample_tokens)
