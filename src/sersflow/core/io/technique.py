"""Infer spectroscopy technique family from file path and axis labels."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

TechniqueFamily = Literal["vibrational", "xps"]

_VIBRATIONAL_AXIS = re.compile(r"\b(wavenumber|wave|wn|raman)\b", re.IGNORECASE)
_XPS_AXIS = re.compile(r"\b(binding(\s*energy)?|be)\b", re.IGNORECASE)


def peek_txt_x_axis_label(path: Path, *, encoding: str = "utf-8") -> str | None:
    """Return the first header cell of a delimited TXT file, or None."""
    path = Path(path)
    try:
        with path.open("r", encoding=encoding, errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                for delim in ("\t", ",", ";", " "):
                    if delim in s or delim == " ":
                        parts = [p.strip() for p in s.split(delim) if p.strip()]
                        if parts:
                            return parts[0]
                return s
    except OSError:
        return None
    return None


def sniff_technique_from_axis_label(label: str | None) -> TechniqueFamily | None:
    """Return technique if label is recognized, else None."""
    if not label:
        return None
    label = label.strip()
    if not label:
        return None
    if _XPS_AXIS.search(label):
        return "xps"
    if _VIBRATIONAL_AXIS.search(label):
        return "vibrational"
    low = label.lower()
    if low in {"be", "binding energy", "binding_energy", "e_bind"}:
        return "xps"
    if low in {"wn", "wave", "wavenumber", "raman shift", "raman_shift", "cm-1", "cm^-1"}:
        return "vibrational"
    return None


def infer_technique_family(
    path: str | Path,
    *,
    x_axis_label: str | None = None,
) -> TechniqueFamily:
    """
    Infer technique family via the format registry (or axis sniff for ambiguous formats).
    """
    from sersflow.core.io.formats import get_format_for_suffix

    p = Path(path)
    spec = get_format_for_suffix(p.suffix)
    if spec is None:
        raise ValueError(
            f"Cannot infer technique for {p.name}: unsupported or ambiguous file type {p.suffix!r}."
        )
    if spec.technique != "sniff":
        return spec.technique  # type: ignore[return-value]

    label = (x_axis_label or "").strip()
    if not label:
        label = (peek_txt_x_axis_label(p) or "").strip()
    sniffed = sniff_technique_from_axis_label(label)
    if sniffed:
        return sniffed
    raise ValueError(
        f"Cannot infer technique for {p.name}: x-axis header {label!r} is unrecognized. "
        "Use a header containing wavenumber/wn/wave (vibrational) or Binding energy/BE (XPS)."
    )


def assert_homogeneous_technique_families(
    paths: list[str | Path],
) -> TechniqueFamily:
    """Infer family for each path; raise ValueError if more than one family is present."""
    by_family: dict[TechniqueFamily, list[str]] = {"vibrational": [], "xps": []}
    for raw in paths:
        p = Path(raw)
        fam = infer_technique_family(p)
        by_family[fam].append(str(raw))
    present = [f for f, items in by_family.items() if items]
    if not present:
        raise ValueError("No files provided to infer technique family")
    if len(present) > 1:
        parts = []
        for fam in present:
            sample = ", ".join(by_family[fam][:5])
            extra = f" (+{len(by_family[fam]) - 5} more)" if len(by_family[fam]) > 5 else ""
            parts.append(f"{fam}: {sample}{extra}")
        raise ValueError(
            "Cannot mix vibrational and XPS files in one dataset. " + "; ".join(parts)
        )
    return present[0]


def normalize_technique_family(
    value: str | None,
    *,
    default: TechniqueFamily | None = None,
) -> TechniqueFamily:
    """
    Normalize a technique family string.

    If ``value`` is empty/None and ``default`` is set, return ``default``.
    Otherwise require an explicit ``vibrational`` or ``xps``.
    """
    if value is None or str(value).strip() == "":
        if default is not None:
            return default
        raise ValueError("technique_family is required (vibrational or xps)")
    fam = str(value).strip().lower()
    if fam not in ("vibrational", "xps"):
        raise ValueError(f"Invalid technique_family {value!r}; expected 'vibrational' or 'xps'")
    return fam  # type: ignore[return-value]


def assert_matching_technique_families(
    dataset_family: str | None,
    pipeline_family: str | None,
    *,
    context: str = "dataset and pipeline",
) -> TechniqueFamily:
    """
    Require dataset and pipeline technique families to match.

    Missing dataset family defaults to vibrational (legacy rows). Missing pipeline
    family is an error — pipelines must declare a family explicitly.
    """
    ds = normalize_technique_family(dataset_family, default="vibrational")
    pipe = normalize_technique_family(pipeline_family, default=None)
    if ds != pipe:
        raise ValueError(
            f"technique_family mismatch for {context}: dataset is {ds!r} but "
            f"pipeline is {pipe!r}. Use a {ds} pipeline with this dataset."
        )
    return ds
