"""Global format registry."""

from __future__ import annotations

from pathlib import Path

from sersflow.core.io.formats.types import FormatSpec

FORMAT_REGISTRY: dict[str, FormatSpec] = {}
_SUFFIX_INDEX: dict[str, str] = {}


def register_format(spec: FormatSpec) -> FormatSpec:
    if spec.id in FORMAT_REGISTRY:
        raise ValueError(f"Format id already registered: {spec.id!r}")
    for suf in spec.suffixes:
        key = suf.lower()
        if not key.startswith("."):
            key = "." + key
        if key in _SUFFIX_INDEX:
            raise ValueError(
                f"Suffix {key!r} already owned by format {_SUFFIX_INDEX[key]!r}"
            )
        _SUFFIX_INDEX[key] = spec.id
    FORMAT_REGISTRY[spec.id] = spec
    return spec


def get_format_for_suffix(suffix: str) -> FormatSpec | None:
    key = suffix.lower()
    if not key.startswith("."):
        key = "." + key
    fid = _SUFFIX_INDEX.get(key)
    return FORMAT_REGISTRY.get(fid) if fid else None


def get_format_for_path(path: str | Path) -> FormatSpec:
    p = Path(path)
    spec = get_format_for_suffix(p.suffix)
    if spec is None:
        supported = ", ".join(supported_suffixes()) or "(none)"
        raise ValueError(
            f"Unsupported file type: {p.suffix!r} ({p}). Supported: {supported}"
        )
    return spec


def list_formats() -> list[FormatSpec]:
    return [FORMAT_REGISTRY[k] for k in sorted(FORMAT_REGISTRY.keys())]


def supported_suffixes() -> list[str]:
    return sorted(_SUFFIX_INDEX.keys())
