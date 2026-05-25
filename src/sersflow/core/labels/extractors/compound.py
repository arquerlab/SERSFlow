from __future__ import annotations

import re

from sersflow.core.labels.patterns import GAS_TOKENS, is_metadata_token
from sersflow.core.labels.extractors.sample import extract_sample


def extract_compound_and_concentration(search_text: str) -> dict[str, object] | None:
    """
    Extract compound + concentration (M, mM, uM, nM). Returns dict with
    compound, value, unit, value_M or None.
    """

    def _to_float(value_str: str) -> float:
        return float(value_str.replace("d", ".").replace("_", "."))

    _ALLOWED_CONC_UNITS = {"M", "mM", "uM", "nM"}

    def _normalize_unit(unit: str) -> str:
        u = unit.strip().replace("μ", "u")
        if u in {"M", "mM", "uM", "nM"}:
            return u
        if u.lower() == "m":
            return "M"
        if u.lower() == "nm":
            return "nm"
        return unit

    def _unit_to_M(value: float, unit: str) -> float:
        u = unit
        if u == "M":
            return value
        if u == "mM":
            return value / 1_000.0
        if u == "uM":
            return value / 1_000_000.0
        if u == "nM":
            return value / 1_000_000_000.0
        return value

    def _is_compound_token(token: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,20}", token)) and not bool(
            re.fullmatch(r"\d+[a-z]+", token.lower())
        )

    tokens = [t for t in re.split(r"[_\s]+", search_text) if t]

    sample_name = extract_sample(search_text) or ""
    sample_tokens_upper = {t.upper() for t in sample_name.split("_") if t}
    non_compound_tokens_upper = {
        "CU",
        "AG",
        "AU",
        "PT",
        "NI",
        "FE",
        "CO",
        "AP",
        "CATALYST",
        "NEW",
        "BATCH",
        "CONTROL",
        "TEST",
        "SAMPLE",
    }

    conc_token_re = re.compile(
        r"^(?:aq)?(?P<value>\d+(?:[d._]\d+)?)(?P<unit>(?:m|u|n)?M)$",
        re.IGNORECASE,
    )
    value_only_re = re.compile(r"^(?:aq)?(?P<value>\d+(?:[d._]\d+)?)$", re.IGNORECASE)
    unit_only_re = re.compile(r"^(?P<unit>(?:m|u|n)?M)$", re.IGNORECASE)

    preferred = {"KHCO3", "K2SO4", "H2SO4", "KOH"}
    candidates: list[dict[str, object]] = []

    for i, tok in enumerate(tokens):
        m = conc_token_re.match(tok)
        if m and i + 1 < len(tokens) and _is_compound_token(tokens[i + 1]):
            value = _to_float(m.group("value"))
            unit = _normalize_unit(m.group("unit"))
            if unit not in _ALLOWED_CONC_UNITS:
                continue
            compound = tokens[i + 1].upper()
            if (
                compound in sample_tokens_upper
                or compound in non_compound_tokens_upper
                or compound in GAS_TOKENS
                or is_metadata_token(tokens[i + 1])
            ):
                continue
            candidates.append(
                {"compound": compound, "value": value, "unit": unit, "value_M": _unit_to_M(value, unit)}
            )

        m_val = value_only_re.match(tok)
        if m_val and i + 2 < len(tokens):
            m_unit = unit_only_re.match(tokens[i + 1])
            comp = tokens[i + 2]
            if m_unit and _is_compound_token(comp):
                value = _to_float(m_val.group("value"))
                unit = _normalize_unit(m_unit.group("unit"))
                if unit not in _ALLOWED_CONC_UNITS:
                    continue
                compound = comp.upper()
                if (
                    compound in sample_tokens_upper
                    or compound in non_compound_tokens_upper
                    or compound in GAS_TOKENS
                    or is_metadata_token(comp)
                ):
                    continue
                candidates.append(
                    {"compound": compound, "value": value, "unit": unit, "value_M": _unit_to_M(value, unit)}
                )

        if i + 1 < len(tokens) and _is_compound_token(tok):
            m2 = conc_token_re.match(tokens[i + 1])
            if m2:
                value = _to_float(m2.group("value"))
                unit = _normalize_unit(m2.group("unit"))
                if unit not in _ALLOWED_CONC_UNITS:
                    continue
                compound = tok.upper()
                if (
                    compound in sample_tokens_upper
                    or compound in non_compound_tokens_upper
                    or compound in GAS_TOKENS
                    or is_metadata_token(tok)
                ):
                    continue
                candidates.append(
                    {"compound": compound, "value": value, "unit": unit, "value_M": _unit_to_M(value, unit)}
                )

            if i + 2 < len(tokens):
                m2_val = value_only_re.match(tokens[i + 1])
                m2_unit = unit_only_re.match(tokens[i + 2])
                if m2_val and m2_unit:
                    value = _to_float(m2_val.group("value"))
                    unit = _normalize_unit(m2_unit.group("unit"))
                    if unit not in _ALLOWED_CONC_UNITS:
                        continue
                    compound = tok.upper()
                    if (
                        compound in sample_tokens_upper
                        or compound in non_compound_tokens_upper
                        or compound in GAS_TOKENS
                        or is_metadata_token(tok)
                    ):
                        continue
                    candidates.append(
                        {
                            "compound": compound,
                            "value": value,
                            "unit": unit,
                            "value_M": _unit_to_M(value, unit),
                        }
                    )

    if not candidates:
        return None

    for c in candidates:
        if c["compound"] in preferred:
            return c
    return candidates[0]
