from __future__ import annotations

import re
from pathlib import Path


def standardize_segment(name: str) -> str:
    """Normalize a path segment: strip run suffixes, replace spaces, preserve cm-2."""
    # Remove trailing run suffixes like "-3", "-3-6"; do NOT strip "-2" in "cm-2".
    name = re.sub(r"(?<!cm)(?:-\d+)+$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"-again$", "", name, flags=re.IGNORECASE)
    name = name.replace(" ", "_")
    return name


def build_search_text(path: Path, parent_levels: int = 3) -> str:
    """
    Build standardized search text from filename + up to N parent folder names.

    Filename segment is first (joined with '__'), then parents.
    """
    segments: list[str] = [standardize_segment(path.with_suffix("").name)]

    parent = path.parent
    for _ in range(max(0, parent_levels)):
        if parent is None or parent.name == "":
            break
        segments.append(standardize_segment(parent.name))
        parent = parent.parent

    return "__".join(segments)


def search_text_from(x: str | Path, *, parent_levels: int = 3) -> str:
    """Path or pre-standardized string -> search text for extractors."""
    if isinstance(x, Path):
        return build_search_text(x, parent_levels=parent_levels)
    return standardize_segment(str(x))
