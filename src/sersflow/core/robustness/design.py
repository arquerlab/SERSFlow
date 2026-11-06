"""Factorial design of a robustness study: factors, levels, cells, caps and cost estimate.

A *factor* is one analyst choice (background type, fit window, line-shape mix, ...). A *level* is one option of that
choice, expressed as a list of patches (see ``patches``). A *cell* is one combination of one level per factor; the
full factorial has prod(levels) cells. The design is plain data (JSON in / JSON out), so every run is reproducible
from its spec and carries a hash of the exact patches used.

Caps are options, not silent limits: ``max_cells=None`` runs everything; with a number an oversized design is
REFUSED (never silently thinned). Subsampling is an explicit opt-in (``subsample``) and marks the design non-exact.
Exclusion rules (``constraints``, see ``constraints.py``) drop implausible cells before anything is fitted; the
remaining design is unbalanced, so it is also marked non-exact (sequential ANOVA).
"""

from __future__ import annotations

import hashlib
import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from sersflow.core.robustness.constraints import ConstraintError, first_hit, parse_constraints, valid_value_name
from sersflow.core.robustness.patches import canonical, split_patches, upstream_signature, validate_patch

MAX_FACTORS = 12
MAX_LEVELS = 50
MAX_ENUMERATE = 5_000_000
"""Largest full grid that is enumerated to apply exclusion rules."""


class DesignError(ValueError):
    pass


@dataclass(frozen=True)
class Level:
    name: str
    patches: tuple[dict[str, Any], ...] = ()
    description: str = ""
    values: tuple[tuple[str, float], ...] = ()
    """Numbers the level carries for exclusion rules (name -> value); not used by the fit."""


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
    constraints: tuple[dict[str, Any], ...] = ()
    n_excluded: int = 0
    """Cells of the full grid removed by the exclusion rules."""
    excluded_by: dict[str, int] = field(default_factory=dict)

    @property
    def factor_names(self) -> list[str]:
        return [f.name for f in self.factors]

    def design_hash(self) -> str:
        spec: dict[str, Any] = {
            "factors": [
                {
                    "name": f.name,
                    "levels": [
                        {"name": lv.name, "patches": list(lv.patches), **({"values": dict(lv.values)} if lv.values else {})}
                        for lv in f.levels
                    ],
                }
                for f in self.factors
            ],
            "cells": [c.level_index for c in self.cells],
        }
        if self.constraints:
            spec["constraints"] = list(self.constraints)
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
            "constraints": list(self.constraints),
            "n_excluded": self.n_excluded,
            "excluded_by_rule": dict(self.excluded_by),
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
    raw_values = raw.get("values") or {}
    if not isinstance(raw_values, dict):
        raise DesignError(f"factor {factor!r} level {raw.get('name')!r}: values must be an object {{name: number}}")
    values: list[tuple[str, float]] = []
    for k, v in raw_values.items():
        if not valid_value_name(str(k)):
            raise DesignError(f"factor {factor!r} level {raw.get('name')!r}: {k!r} is not a usable value name")
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            raise DesignError(f"factor {factor!r} level {raw.get('name')!r}: value {k!r} must be a finite number")
        values.append((str(k), float(v)))
    return Level(
        name=str(raw["name"]).strip(),
        patches=tuple(patches),
        description=str(raw.get("description") or ""),
        values=tuple(values),
    )


def parse_factors(raw: Any) -> tuple[Factor, ...]:
    if not isinstance(raw, list) or not raw:
        raise DesignError("design needs at least one factor")
    if len(raw) > MAX_FACTORS:
        raise DesignError(f"too many factors ({len(raw)} > {MAX_FACTORS})")
    out: list[Factor] = []
    seen: set[str] = set()
    value_owner: dict[str, str] = {}
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
        keys = {k for lv in levels for k, _ in lv.values}
        for k in sorted(keys):
            if any(k not in dict(lv.values) for lv in levels):
                raise DesignError(f"factor {name!r}: value {k!r} must be given on every level of the factor")
            if k in value_owner:
                raise DesignError(f"value name {k!r} is used by factors {value_owner[k]!r} and {name!r}")
            value_owner[k] = name
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
    constraints: Any = None,
) -> Design:
    """Full factorial from a factor spec, minus the cells removed by ``constraints``.

    ``max_cells`` None = no cap. An oversized design raises ``DesignError`` carrying the cell count, unless
    ``subsample`` ({"n": N, "seed": S}) is given, which draws N cells without replacement (design flagged non-exact).
    ``interaction_order``: 1 = main effects only, 2 = up to pairwise, ... ``"all"`` / None = every order.
    ``constraints``: exclusion rules (see ``constraints.py``) applied before the cap and the subsample; the cap then
    counts the cells that remain. They must keep the nominal cell (first level of every factor). Once a rule removes
    a cell the design is unbalanced: ``exact`` is False and the ANOVA shares are sequential (order-dependent).
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
    sizes = [len(f.levels) for f in factors]

    try:
        rules = parse_constraints(
            constraints,
            [f.name for f in factors],
            [[lv.name for lv in f.levels] for f in factors],
            [[dict(lv.values) for lv in f.levels] for f in factors],
        )
    except ConstraintError as e:
        raise DesignError(str(e)) from e

    pool: list[tuple[int, ...]] | None = None
    excluded_by: dict[str, int] = {}
    n_excluded = 0
    exact = True
    if rules:
        if n_full > MAX_ENUMERATE:
            raise DesignError(
                f"the full grid has {n_full} cells, too many to apply constraints to (limit {MAX_ENUMERATE}); drop levels"
            )
        pool = []
        try:
            for idx in itertools.product(*[range(n) for n in sizes]):
                hit = first_hit(rules, idx)
                if hit is not None:
                    excluded_by[hit] = excluded_by.get(hit, 0) + 1
                    continue
                pool.append(idx)
                if not subsample and max_cells is not None and len(pool) > int(max_cells):
                    raise DesignError(
                        f"design has more than max_cells={int(max_cells)} cells even after the constraints; raise "
                        "max_cells, set it to null for no cap, add constraints, drop levels, or opt in to 'subsample'"
                    )
        except ConstraintError as e:
            raise DesignError(str(e)) from e
        n_excluded = n_full - len(pool)
        if not pool or pool[0] != tuple(0 for _ in sizes):
            raise DesignError(
                "the constraints exclude the nominal cell (the first level of every factor); the nominal cell is the "
                "reference of the study, so reorder the levels or relax the constraints"
            )
        if len(pool) < 2:
            raise DesignError("the constraints leave fewer than 2 cells")
        if n_excluded:
            exact = False
            notes.append(
                f"constraints removed {n_excluded} of {n_full} cells ({len(pool)} remain): the design is unbalanced, "
                "so ANOVA shares are sequential (order-dependent) and approximate"
            )

    combos: list[tuple[int, ...]]
    if subsample:
        n = int(subsample.get("n") or 0)
        if n < 2:
            raise DesignError("subsample.n must be >= 2")
        total = len(pool) if pool is not None else n_full
        if n >= total:
            combos = pool if pool is not None else list(itertools.product(*[range(s) for s in sizes]))
        else:
            rng = np.random.default_rng(seed)
            picks = np.sort(rng.choice(total, size=n, replace=False))
            if pool is not None:
                combos = [pool[int(k)] for k in picks]
            else:
                combos = [tuple(int(v) for v in np.unravel_index(int(k), sizes)) for k in picks]
            exact = False
            notes.append(f"subsampled {n} of {total} cells (seed {seed}): ANOVA is approximate")
    else:
        if pool is None and max_cells is not None and n_full > int(max_cells):
            raise DesignError(
                f"full factorial has {n_full} cells, above max_cells={int(max_cells)}; raise max_cells, "
                "set it to null for no cap, drop levels, or opt in to 'subsample'"
            )
        combos = pool if pool is not None else list(itertools.product(*[range(s) for s in sizes]))

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
        constraints=tuple(constraints or ()),
        n_excluded=n_excluded,
        excluded_by=excluded_by,
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
