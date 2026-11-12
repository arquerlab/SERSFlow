"""Patch-effect check: does every factor level really change what the optimizer receives?

A level that silently does nothing makes the ANOVA report a ~0 variance share for a choice that was never tested.
The check separates two situations that look alike in the results:

* INERT: the optimizer input (or the pre-fit data) is identical to the nominal one. A bug: reported as an error.
* INSENSITIVE: the input differs but the response hardly moves. A real finding: never flagged here.

Hence the check compares optimizer inputs (``fit_hash``), never responses.

Layers (all run at plan time; the only computation is ``prepare_fit``, no optimisation)
    1. spec     every patch resolves, patched step params differ from nominal, levels of a factor differ pairwise;
    2. upstream for levels that patch steps before the fit: the pre-fit spectra differ from nominal;
    3. fit      one-factor-at-a-time cell vs nominal: fit config / data hash differ on at least one spectrum.

Limitation: layer 3 is one-factor-at-a-time. A level that only acts in combination with another factor level
(an interaction-only effect) can look inert here although it is effective in some cells.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable

from sersflow.core.robustness.cell_fit import prepare_fit
from sersflow.core.robustness.design import Design
from sersflow.core.robustness.fit_hash import sha256_hex, xy_fingerprint
from sersflow.core.robustness.patches import (
    _norm_target,
    apply_patch_reported,
    is_fit_patch,
    resolve_step_index,
    split_patches,
    upstream_signature,
    PatchResult,
)

OK = "ok"
INERT = "inert"
UPSTREAM_INERT = "upstream_inert"
UNRESOLVED = "unresolved_target"
START_ONLY = "start_only"
UNTESTABLE = "untestable"
DUPLICATE_PREFIX = "duplicate_of:"

PrefitFn = Callable[[list[dict[str, Any]]], dict[str, Any]]
"""``prefit_fn(upstream_patches)`` -> ``{spectrum_id: XY}``: the spectra entering the fitting step under those patches."""


def is_error(status: str) -> bool:
    return status in (INERT, UPSTREAM_INERT, UNRESOLVED) or status.startswith(DUPLICATE_PREFIX)


def is_warning(status: str) -> bool:
    return status in (START_ONLY, UNTESTABLE)


@dataclass
class LevelCheck:
    factor: str
    level: str
    status: str
    spectra_changed: int = 0
    n_spectra: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cell_pair: list[str] | None = None
    """(cell with the level, reference cell) the fit-step comparison used."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor": self.factor,
            "level": self.level,
            "status": self.status,
            "spectra_changed": self.spectra_changed,
            "n_spectra": self.n_spectra,
            "details": self.details,
            "notes": self.notes,
            "cell_pair": self.cell_pair,
        }


@dataclass
class PatchCheckReport:
    rows: list[LevelCheck]
    version: int = 1
    limitations: tuple[str, ...] = (
        "Layer 3 is one-factor-at-a-time: a level that only acts together with another factor level can look inert.",
    )

    @property
    def n_errors(self) -> int:
        return sum(1 for r in self.rows if is_error(r.status))

    @property
    def n_warnings(self) -> int:
        return sum(1 for r in self.rows if is_warning(r.status))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "n_errors": self.n_errors,
            "n_warnings": self.n_warnings,
            "rows": [r.to_dict() for r in self.rows],
            "limitations": list(self.limitations),
        }

    def errors(self) -> list[LevelCheck]:
        return [r for r in self.rows if is_error(r.status)]


# --------------------------------------------------------------------------------------------------------------
# layer 1: patches applied to a plain-dict pipeline state
# --------------------------------------------------------------------------------------------------------------

def pipeline_state(steps: list[dict[str, Any]], fitting_idx: int, base_params: dict[str, Any]) -> dict[str, Any]:
    """Plain-data snapshot: the fitting step params plus every upstream step (enabled flag and params)."""
    return {
        "fit": copy.deepcopy(base_params),
        "steps": [
            {
                "index": int(s["index"]),
                "id": s.get("id"),
                "name": s.get("name"),
                "enabled": bool(s.get("enabled", True)),
                "params": copy.deepcopy(s.get("params") or {}),
            }
            for s in steps
        ],
        "fitting_idx": int(fitting_idx),
    }


def apply_to_state(state: dict[str, Any], patches: list[dict[str, Any]]) -> tuple[dict[str, Any], list[PatchResult]]:
    """Apply patches to a copy of the state; returns it with one ``PatchResult`` per patch (never raises)."""
    st = copy.deepcopy(state)
    results: list[PatchResult] = []
    steps = st["steps"]
    for patch in patches:
        if is_fit_patch(patch):
            if patch.get("op") == "set_step_enabled":
                results.append(
                    PatchResult(op="set_step_enabled", target={"step": "fit"}, resolved=False,
                                reason="the fitting step under study cannot be disabled by a patch")
                )
                continue
            st["fit"], r = apply_patch_reported(st["fit"], patch, step_name="fitting")
            results.append(r)
            continue
        tgt = _norm_target(patch)
        try:
            idx = resolve_step_index(steps, tgt, get_name=lambda s: s["name"], get_id=lambda s: s["id"])
        except ValueError as e:
            results.append(PatchResult(op=str(patch.get("op")), target=tgt, resolved=False, reason=str(e)))
            continue
        pos = idx
        step = steps[pos]
        if step["index"] == st["fitting_idx"]:
            results.append(
                PatchResult(op=str(patch.get("op")), target=tgt, resolved=False,
                            reason="an upstream patch cannot target the fitting step under study")
            )
            continue
        tgt = {**tgt, "step_index": step["index"], "step_name": step["name"]}
        if patch.get("op") == "set_step_enabled":
            old = step["enabled"]
            step["enabled"] = bool(patch.get("enabled"))
            results.append(
                PatchResult(op="set_step_enabled", target=tgt, resolved=True, old_value=old,
                            new_value=step["enabled"], noop=old == step["enabled"])
            )
            continue
        step["params"], r = apply_patch_reported(step["params"], patch, step_name=step["name"], target=tgt)
        results.append(r)
    return st, results


def state_hash(state: dict[str, Any]) -> str:
    return sha256_hex(state)


# --------------------------------------------------------------------------------------------------------------
# the check
# --------------------------------------------------------------------------------------------------------------

def _level_patches(design: Design, fi: int, li: int) -> list[dict[str, Any]]:
    return list(design.factors[fi].levels[li].patches)


def _find_pair(design: Design, fi: int, li: int) -> tuple[Any, Any] | None:
    """(cell with factor fi at level li, same cell with fi at level 0), as close to one-factor-at-a-time as the
    design allows (rules or a subsample may have removed the plain OFAT cell)."""
    by_idx = {c.level_index: c for c in design.cells}
    n = len(design.factors)
    best: tuple[int, Any, Any] | None = None
    for c in design.cells:
        if c.level_index[fi] != li:
            continue
        partner_idx = tuple(0 if k == fi else v for k, v in enumerate(c.level_index))
        partner = by_idx.get(partner_idx)
        if partner is None:
            continue
        others = sum(1 for k in range(n) if k != fi and c.level_index[k] != 0)
        if best is None or others < best[0]:
            best = (others, c, partner)
            if others == 0:
                break
    return None if best is None else (best[1], best[2])


def run_patch_check(
    design: Design,
    base_params: dict[str, Any],
    steps: list[dict[str, Any]],
    fitting_idx: int,
    prefit_fn: PrefitFn | None = None,
) -> PatchCheckReport:
    """Check every (factor, level>0) of ``design``. ``steps`` is the pipeline snapshot
    (``[{"index", "id", "name", "enabled", "params"}]``, fitting step included); ``prefit_fn`` supplies the spectra
    entering the fit (omit it to run layer 1 only)."""
    nominal_state = pipeline_state(steps, fitting_idx, base_params)
    nominal_patches: list[dict[str, Any]] = []
    for fi in range(len(design.factors)):
        nominal_patches += _level_patches(design, fi, 0)
    nominal_full, _ = apply_to_state(nominal_state, nominal_patches)
    nominal_hash = state_hash(nominal_full)

    prefit_cache: dict[str, dict[str, Any]] = {}
    fp_cache: dict[tuple[str, str, str], dict[str, Any] | str] = {}

    def prefit(up_patches: list[dict[str, Any]]) -> dict[str, Any]:
        key = upstream_signature(up_patches)
        if key not in prefit_cache:
            prefit_cache[key] = prefit_fn(list(up_patches)) if prefit_fn is not None else {}
        return prefit_cache[key]

    def fit_fp(cell: Any, sid: str, xy: Any) -> dict[str, Any] | str:
        k = (cell.upstream_key, upstream_signature(list(cell.fit_patches)), sid)
        if k not in fp_cache:
            try:
                fp_cache[k] = prepare_fit(xy, base_params, list(cell.fit_patches)).fingerprint()
            except Exception as e:  # an invalid patched step is itself a finding
                fp_cache[k] = f"{type(e).__name__}: {e}"
        return fp_cache[k]

    rows: list[LevelCheck] = []
    for fi, factor in enumerate(design.factors):
        # ---- layer 1 --------------------------------------------------------------------------------------
        state_by_level: dict[int, str] = {}
        for li, level in enumerate(factor.levels):
            lv_state, _ = apply_to_state(nominal_state, list(level.patches))
            state_by_level[li] = state_hash(lv_state)
        level_rows: dict[int, LevelCheck] = {}
        for li in range(1, len(factor.levels)):
            level = factor.levels[li]
            st, results = apply_to_state(nominal_state, list(level.patches))
            row = LevelCheck(factor=factor.name, level=level.name, status=OK, details=[r.to_dict() for r in results])
            bad = [r for r in results if not r.resolved]
            if not level.patches:
                row.status = INERT
                row.notes.append("the level has no patches: it is identical to a level without any change")
            elif bad:
                row.status = UNRESOLVED
                row.notes.extend(r.reason or "unresolved patch" for r in bad)
            else:
                dup = next((j for j in range(li) if state_by_level[j] == state_by_level[li]), None)
                if dup is not None:
                    row.status = DUPLICATE_PREFIX + factor.levels[dup].name
                    row.notes.append("patched pipeline is identical to that level's")
                elif state_hash(st) == state_hash(nominal_state) or state_by_level[li] == state_hash(nominal_state):
                    row.status = INERT
                    row.notes.append("patched step params are identical to the nominal ones (every patch is a no-op)")
            level_rows[li] = row
        # ---- layers 2 and 3 ---------------------------------------------------------------------------------
        sigs: dict[int, tuple[Any, ...]] = {}
        for li, row in level_rows.items():
            if row.status != OK:
                continue
            if prefit_fn is None:
                row.notes.append("no data supplied: only the spec layer ran")
                continue
            pair = _find_pair(design, fi, li)
            if pair is None:
                row.status = UNTESTABLE
                row.notes.append("no allowed cell pair differs only in this factor (exclusion rules / subsample)")
                continue
            cell_a, cell_b = pair
            row.cell_pair = [cell_a.cell_id, cell_b.cell_id]
            if cell_a.level_index != tuple(0 if k != fi else li for k in range(len(design.factors))):
                row.notes.append("plain one-factor cell not in the design; compared the nearest allowed pair")
            xa, xb = prefit(list(cell_a.upstream_patches)), prefit(list(cell_b.upstream_patches))
            sids = sorted(set(xa) & set(xb))
            row.n_spectra = len(sids)
            if not sids:
                row.status = UNTESTABLE
                row.notes.append("no spectrum available for the comparison")
                continue
            up_changed = fit_changed = start_changed = 0
            errors: list[str] = []
            sig: list[Any] = []
            for sid in sids:
                if cell_a.upstream_patches or cell_b.upstream_patches:
                    if xy_fingerprint(xa[sid]) != xy_fingerprint(xb[sid]):
                        up_changed += 1
                fa, fb = fit_fp(cell_a, sid, xa[sid]), fit_fp(cell_b, sid, xb[sid])
                if isinstance(fa, str) or isinstance(fb, str):
                    errors.append(fa if isinstance(fa, str) else str(fb))
                    continue
                sig.append((fa["config_hash"], fa["data_hash"]))
                if fa["config_hash"] != fb["config_hash"] or fa["data_hash"] != fb["data_hash"]:
                    fit_changed += 1
                elif fa["start_hash"] != fb["start_hash"]:
                    start_changed += 1
            sigs[li] = tuple(sig)
            if errors:
                row.status = UNRESOLVED
                row.notes.append("the patched fit cannot be prepared: " + errors[0])
                continue
            row.spectra_changed = fit_changed
            if fit_changed:
                row.status = OK
                if up_changed:
                    row.notes.append(f"upstream data changed on {up_changed} of {len(sids)} spectra")
            elif start_changed:
                row.status = START_ONLY
                row.spectra_changed = start_changed
                row.notes.append(
                    "only initial values of free parameters differ: with multi-start jitter this is not a model choice"
                )
            else:
                has_up = any(not is_fit_patch(p) for p in level.patches)
                row.status = UPSTREAM_INERT if has_up and not any(is_fit_patch(p) for p in level.patches) else INERT
                row.notes.append(
                    "the optimizer receives exactly the nominal input on every spectrum"
                    + ("; the upstream step changed nothing the fit sees" if row.status == UPSTREAM_INERT else "")
                )
        # levels that are distinct as patches but give the optimizer the same input as an earlier level
        for li in sorted(sigs):
            row = level_rows[li]
            if row.status != OK:
                continue
            same = next((lj for lj in sorted(sigs) if lj < li and level_rows[lj].status == OK and sigs[lj] == sigs[li]), None)
            if same is not None:
                row.status = DUPLICATE_PREFIX + factor.levels[same].name
                row.notes.append("the optimizer input equals that level's on every spectrum")
        rows.extend(level_rows[li] for li in sorted(level_rows))
    return PatchCheckReport(rows=rows)
