from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sersflow.core.labels.normalize import build_search_text
from sersflow.core.labels.extractors.compound import extract_compound_and_concentration
from sersflow.core.labels.extractors.current import extract_current
from sersflow.core.labels.extractors.electrolyte import extract_electrolyte
from sersflow.core.labels.extractors.gas import extract_gas
from sersflow.core.labels.extractors.laser import extract_laser_power_percent, extract_laser_wavelength_nm
from sersflow.core.labels.extractors.ph import extract_ph
from sersflow.core.labels.extractors.potential import extract_potential
from sersflow.core.labels.extractors.sample import extract_sample

logger = logging.getLogger(__name__)

# Saturated Ag/AgCl vs SHE (V) and Nernst slope (V/pH) at ~25 °C for RHE conversion.
_AGCL_TO_SHE_V = 0.197
_NERNST_V_PER_PH = 0.05916


def _apply_potential_as_rhe(
    path: Path,
    search_text: str,
    *,
    ph: float | None,
    out: dict[str, Any],
) -> None:
    """
    Store potential as RHE (``potential_V``) with ``potential_ref`` in ``VRHE`` or ``OCP``.

    - VRHE / RHE tokens: use value as-is.
    - VAgAgCl: ``E_RHE = E_AgAgCl + 0.197 + 0.05916 * pH`` (requires pH).
    - Plain ``V`` (not VRHE): stored as-is with ``potential_ref`` ``\"V\"`` (not assumed RHE).
    """
    pot = extract_potential(search_text)
    if pot is None:
        return
    v_raw, ref = pot
    if ref == "OCP":
        out["potential_V"] = float(v_raw)
        out["potential_ref"] = "OCP"
        return
    if ref == "VRHE":
        out["potential_V"] = float(v_raw)
        out["potential_ref"] = "VRHE"
        return
    if ref == "VAgAgCl":
        if ph is None:
            logger.warning(
                "Labels %s: potential vs Ag/AgCl but no pH in path context — "
                "cannot convert to RHE; omitting potential.",
                path,
            )
            return
        out["potential_V"] = float(v_raw) + _AGCL_TO_SHE_V + _NERNST_V_PER_PH * float(ph)
        out["potential_ref"] = "VRHE"
        return
    if ref == "V":
        out["potential_V"] = float(v_raw)
        out["potential_ref"] = "V"
        return


def extract_labels(
    path: Path,
    parent_levels: int = 3,
    *,
    previous_labels: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Extract a normalized label dict from filepath context (filename + parent folders).

    Current is always emitted as ``current_density_A_cm2`` (A·cm⁻²). If the filename token
    looks like bulk current (A), a warning is logged. Electrolyte concentration is only
    ``concentration_M`` (molar) when a molarity was parsed, plus ``electrolyte`` compound name.

    ``potential_V`` is on the RHE scale when ``potential_ref`` is ``VRHE``, or when converted from
    Ag/AgCl. For ``potential_ref`` ``OCP``, the value is the OCP convention (often 0).
    Plain-filename ``…V`` tokens (ref ``V``) store the parsed volts with ``potential_ref`` ``\"V\"``
    (not assumed RHE). Potentials vs Ag/AgCl use
    ``E_RHE = E_AgAgCl + 0.197 + 0.05916 * pH`` (requires pH).

    Keys are omitted when not detected (except empty dict when nothing found).
    """
    search_text = build_search_text(path, parent_levels=parent_levels)
    out: dict[str, Any] = {"search_text": search_text}

    sample = extract_sample(search_text)
    if sample:
        out["sample"] = sample

    gas = extract_gas(search_text)
    if gas:
        out["gas"] = gas

    ph = extract_ph(search_text)
    if ph is not None:
        out["ph"] = ph

    current_a, parsed_is_density = extract_current(search_text)
    if current_a is not None:
        if not parsed_is_density:
            logger.warning(
                "Labels %s: current token looks like bulk current (A), not mA/cm²; "
                "stored as current_density_A_cm2 anyway — verify the value.",
                path,
            )
        if previous_labels is not None and previous_labels.get("current_is_density") is False and parsed_is_density:
            logger.warning(
                "Labels %s: stored labels had current_is_density=False and the path now parses as "
                "current density (True) — interpretation changed.",
                path,
            )
        out["current_density_A_cm2"] = current_a

    _apply_potential_as_rhe(path, search_text, ph=ph, out=out)

    laser_nm = extract_laser_wavelength_nm(search_text)
    if laser_nm is not None:
        out["laser_nm"] = laser_nm

    laser_pct = extract_laser_power_percent(search_text)
    if laser_pct is not None:
        out["laser_power_pct"] = laser_pct

    conc = extract_compound_and_concentration(search_text)
    if conc:
        out["electrolyte"] = conc["compound"]
        out["concentration_M"] = conc["value_M"]
    else:
        elec = extract_electrolyte(search_text)
        if elec:
            out["electrolyte"] = elec

    # Trim internal helper from default API consumers / persistence
    out.pop("search_text", None)
    return out
