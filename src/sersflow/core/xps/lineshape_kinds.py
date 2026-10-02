"""Shared XPS lineshape kind tokens (catalog validation + recipe apply)."""

from __future__ import annotations

# Kinds that map onto registered fitting components (apply path).
SUPPORTED_COMPONENT_KINDS = frozenset(
    {
        "gl",
        "la",
        "lf",
        "a_gl",
        "gaussian",
        "lorentzian",
        "pseudo_voigt",
        "voigt",
        "apv",
    }
)

# Aliases accepted in packaged JSON that normalize onto SUPPORTED_COMPONENT_KINDS.
LINESHAPE_KIND_ALIASES: dict[str, str] = {
    "agl": "a_gl",
    "asymmetric_gl": "a_gl",
}

# Everything catalog_validate accepts without "unknown kind" (includes soft-fail shapes).
KNOWN_LINESHAPE_KINDS = frozenset(
    {
        *SUPPORTED_COMPONENT_KINDS,
        *LINESHAPE_KIND_ALIASES.keys(),
        "asymmetric_voigt",
        "ds",
        "gds",
    }
)


def normalize_lineshape_kind(kind: str) -> str:
    """Lowercase + alias map (``agl`` → ``a_gl``). Empty string if blank."""
    k = str(kind or "").strip().lower()
    if not k:
        return ""
    return LINESHAPE_KIND_ALIASES.get(k, k)
