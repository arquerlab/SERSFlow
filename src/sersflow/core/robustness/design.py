"""Factorial design of a robustness study: factors, levels, cells, caps and cost estimate.

A *factor* is one analyst choice (background type, fit window, line-shape mix, ...). A *level* is one option of that
choice, expressed as a list of patches (see ``patches``). A *cell* is one combination of one level per factor; the
full factorial has prod(levels) cells. The design is plain data (JSON in / JSON out), so every run is reproducible
from its spec and carries a hash of the exact patches used.

Caps are options, not silent limits: ``max_cells=None`` runs everything; with a number an oversized design is
REFUSED (never silently thinned). Subsampling is an explicit opt-in (``subsample``) and marks the design non-exact.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from sersflow.core.robustness.patches import canonical, split_patches, upstream_signature, validate_patch

MAX_FACTORS = 12
MAX_LEVELS = 50


class DesignError(ValueError):
    pass


@dataclass(frozen=True)
class Level:
    name: str
    patches: tuple[dict[str, Any], ...] = ()
    description: str = ""


@dataclass(frozen=True)
class Factor:
    name: str
    levels: tuple[Level, ...]
    description: str = ""


@dataclass(frozen=True)
class Cell:
    cell_id: str
    levels: tuple[str, ...]
    """Level name per factor, in factor order."""
    level_index: tuple[int, ...]
    fit_patches: tuple[dict[str, Any], ...]
    upstream_patches: tuple[dict[str, Any], ...]
    upstream_key: str


@dataclass
class Design:
    factors: tuple[Factor, ...]
    cells: list[Cell]
    exact: bool = True
    """True when every combination of the full factorial is present (exact ANOVA); False after subsampling."""
    n_full: int = 0
    interaction_order: int | None = None
    """None = all interactions."""
    seed: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def factor_names(self) -> list[str]:
        return [f.name for f in self.factors]

    def design_hash(self) -> str:
        spec = {
            "factors": [
                {
                    "name": f.name,
                    "levels": [{"name": lv.name, "patches": list(lv.patches)} for lv in f.levels],
                }
                for f in self.factors
            ],
            "cells": [c.level_index for c in self.cells],
        }
        return hashlib.sha256(canonical(spec).encode("utf-8")).hexdigest()

    def n_upstream_groups(self) -> int:
        return len({c.upstream_key for c in self.cells})

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "factors": [
                {"name": f.name, "description": f.description, "levels": [lv.name for lv in f.levels]}
                for f in self.factors
            ],
            "n_cells": len(self.cells),
            "n_full_factorial": self.n_full,
            "exact": self.exact,
            "interaction_order": self.interaction_order,
            "n_upstream_groups": self.n_upstream_groups(),
            "design_hash": self.design_hash(),
            "seed": self.seed,
            "notes": list(self.notes),
        }


def _parse_level(raw: Any, factor: str) -> Level:
    if isinstance(raw, str):
        return Level(name=raw)
    if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
        raise DesignError(f"factor {factor!r}: every level needs a name")
    patches = raw.get("patches") or []
    if not isinstance(patches, list):
        raise DesignError(f"factor {factor!r} level {raw.get('name')!r}: patches must be a list")
    for p in patches:
        try:
            validate_patch(p)
        except ValueError as e:
            raise DesignError(f"factor {factor!r} level {raw.get('name')!r}: {e}") from e
    return Level(name=str(raw["name"]).strip(), patches=tuple(patches), description=str(raw.get("description") or ""))


def parse_factors(raw: Any) -> tuple[Factor, ...]:
    if not isinstance(raw, list) or not raw:
        raise DesignError("design needs at least one factor")
    if len(raw) > MAX_FACTORS:
        raise DesignError(f"too many factors ({len(raw)} > {MAX_FACTORS})")
    out: list[Factor] = []
    seen: set[str] = set()
    for f in raw:
        if not isinstance(f, dict) or not str(f.get("name") or "").strip():
            raise DesignError("every factor needs a name")
        name = str(f["name"]).strip()
        if name in seen:
            raise DesignError(f"duplicate factor name {name!r}")
        seen.add(name)
        levels_raw = f.get("levels")
        if not isinstance(levels_raw, list) or len(levels_raw) < 2:
            raise DesignError(f"factor {name!r} needs at least two levels")
        if len(levels_raw) > MAX_LEVELS:
            raise DesignError(f"factor {name!r} has too many levels ({len(levels_raw)} > {MAX_LEVELS})")
        levels = tuple(_parse_level(lv, name) for lv in levels_raw)
        names = [lv.name for lv in levels]
        if len(set(names)) != len(names):
            raise DesignError(f"factor {name!r} has duplicate level names")
        out.append(Factor(name=name, levels=levels, description=str(f.get("description") or "")))
    return tuple(out)


def n_full_factorial(factors: tuple[Factor, ...]) -> int:
    return int(math.prod(len(f.levels) for f in factors))


def build_design(
    factors_raw: Any,
    *,
    max_cells: int | None = None,
    interaction_order: int | str | None = None,
    subsample: dict[str, Any] | None = None,
) -> Design:
    """Full factorial from a factor spec.

    ``max_cells`` None = no cap. An oversized design raises ``DesignError`` carrying the cell count, unless
    ``subsample`` ({"n": N, "seed": S}) is given, which draws N cells without replacement (design flagged non-exact).
    ``interaction_order``: 1 = main effects only, 2 = up to pairwise, ... ``"all"`` / None = every order.
    """
    factors = parse_factors(factors_raw)
    n_full = n_full_factorial(factors)
    notes: list[str] = []
    if interaction_order in (None, "all"):
        order = None
    else:
        order = int(interaction_order)
        if order < 1:
            raise DesignError("interaction_order must be >= 1 or 'all'")
    seed = int((subsample or {}).get("seed") or 0)

    combos: list[tuple[int, ...]]
    exact = True
    if subsample:
        n = int(subsample.get("n") or 0)
        if n < 2:
            raise DesignError("subsample.n must be >= 2")
        if n >= n_full:
            combos = list(itertools.product(*[range(len(f.levels)) for f in factors]))
        else:
            rng = np.random.default_rng(seed)
            picks = np.sort(rng.choice(n_full, size=n, replace=False))
            sizes = [len(f.levels) for f in factors]
            combos = [tuple(int(v) for v in np.unravel_index(int(k), sizes)) for k in picks]
            exact = False
            notes.append(f"subsampled {n} of {n_full} cells (seed {seed}): ANOVA is approximate")
    else:
        if max_cells is not None and n_full > int(max_cells):
            raise DesignError(
                f"full factorial has {n_full} cells, above max_cells={int(max_cells)}; raise max_cells, "
                "set it to null for no cap, drop levels, or opt in to 'subsample'"
            )
        combos = list(itertools.product(*[range(len(f.levels)) for f in factors]))

    cells: list[Cell] = []
    for k, idx in enumerate(combos):
        fit_p: list[dict[str, Any]] = []
        up_p: list[dict[str, Any]] = []
        for f, li in zip(factors, idx):
            fp, up = split_patches(list(f.levels[li].patches))
            fit_p += fp
            up_p += up
        cells.append(
            Cell(
                cell_id=f"c{k:05d}",
                levels=tuple(f.levels[li].name for f, li in zip(factors, idx)),
                level_index=tuple(idx),
                fit_patches=tuple(fit_p),
                upstream_patches=tuple(up_p),
                upstream_key=upstream_signature(up_p),
            )
        )
    return Design(
        factors=factors,
        cells=cells,
        exact=exact,
        n_full=n_full,
        interaction_order=order,
        seed=seed,
        notes=notes,
    )


def estimate_cost(
    *,
    n_cells: int,
    n_spectra: int,
    n_starts: int,
    n_upstream_groups: int = 1,
    noise_replicates: int = 0,
) -> dict[str, Any]:
    """Number of fits and pipeline collections a study needs (shown before running)."""
    n_fits = int(n_cells) * int(n_spectra) * max(1, int(n_starts))
    n_noise = int(n_spectra) * int(noise_replicates) if noise_replicates else 0
    return {
        "n_cells": int(n_cells),
        "n_spectra": int(n_spectra),
        "n_starts": max(1, int(n_starts)),
        "n_fits": n_fits,
        "n_noise_fits": n_noise,
        "n_total_fits": n_fits + n_noise,
        "n_upstream_groups": int(n_upstream_groups),
    }
