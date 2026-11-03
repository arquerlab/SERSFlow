"""Group / average spectra of a cohort (pure logic, no I/O).

Used by the ``group_average`` cohort step: spectra (already processed by the steps before it) are
grouped by labels and/or numeric ranges and reduced to one spectrum per group.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Literal, Mapping, Sequence

import numpy as np

from sersflow.core.pipeline.hashing import canonical_json, sha256_hex
from sersflow.core.spectrum import XY

GroupMode = Literal["all", "by_label", "by_range"]
Reducer = Literal["cumulative", "mean", "median"]

SPECTRUM_ROLE_GROUP_MEAN = "group_mean"
REGION_LABEL = "xps_region"

# Labels never copied onto a derived spectrum (they describe a single source block).
_PER_SOURCE_LABEL_KEYS = frozenset({"block_name", "replicate_index", "spectrum_role"})


@dataclass(frozen=True)
class GroupAverageParams:
    mode: GroupMode = "all"
    group_by: tuple[str, ...] = ()
    range_label: str | None = None
    range_width: float | None = None
    range_origin: float | None = None
    split_by_region: bool = True
    reducer: Reducer = "cumulative"
    min_group_size: int = 1

    @staticmethod
    def from_dict(raw: Mapping[str, Any] | None) -> "GroupAverageParams":
        p = dict(raw or {})
        mode = str(p.get("method") or p.get("mode") or "all").strip().lower()
        if mode not in ("all", "by_label", "by_range"):
            raise ValueError(f"group_average: unknown mode {mode!r}")
        gb = p.get("group_by") or ()
        if isinstance(gb, str):
            gb = gb.split(",")
        group_by = tuple(str(k).strip() for k in gb if str(k).strip())
        reducer = str(p.get("reducer") or "cumulative").strip().lower()
        if reducer == "sum":
            reducer = "cumulative"
        if reducer not in ("cumulative", "mean", "median"):
            raise ValueError(f"group_average: unknown reducer {reducer!r}")
        width = p.get("range_width")
        origin = p.get("range_origin")
        rl = str(p.get("range_label") or "").strip() or None
        out = GroupAverageParams(
            mode=mode,  # type: ignore[arg-type]
            group_by=group_by,
            range_label=rl,
            range_width=float(width) if width not in (None, "") else None,
            range_origin=float(origin) if origin not in (None, "") else None,
            split_by_region=bool(p.get("split_by_region", True)),
            reducer=reducer,  # type: ignore[arg-type]
            min_group_size=max(1, int(p.get("min_group_size") or 1)),
        )
        out.validate()
        return out

    def validate(self) -> None:
        if self.mode == "by_label" and not self.group_by:
            raise ValueError("group_average: mode 'by_label' needs at least one group_by label")
        if self.mode == "by_range":
            if not self.range_label:
                raise ValueError("group_average: mode 'by_range' needs range_label")
            if self.range_width is None or not (self.range_width > 0) or not math.isfinite(self.range_width):
                raise ValueError("group_average: mode 'by_range' needs a positive range_width")

    def rule_dict(self) -> dict[str, Any]:
        """Everything that defines *which* spectra form a group (the reducer is not part of identity)."""
        return {
            "mode": self.mode,
            "group_by": list(self.group_by),
            "range_label": self.range_label,
            "range_width": self.range_width,
            "range_origin": self.range_origin,
            "split_by_region": self.split_by_region,
        }


@dataclass(frozen=True)
class GroupMember:
    spectrum_id: str
    xy: XY
    labels: Mapping[str, Any]


@dataclass
class AveragedGroup:
    spectrum_id: str
    key: dict[str, Any]
    member_ids: list[str]
    xy: XY
    labels: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def label_as_number(value: Any) -> float | None:
    """Float for numeric labels; ISO-8601 timestamps become epoch seconds. None when not numeric."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        v = float(value)
        return v if math.isfinite(v) else None
    s = str(value).strip()
    if not s:
        return None
    try:
        v = float(s)
        return v if math.isfinite(v) else None
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _key_token(value: Any) -> Any:
    """Normalise a label value for use as a group key component (stable across float noise)."""
    num = label_as_number(value)
    if num is not None and not isinstance(value, str):
        return float(f"{num:.9g}")
    if value is None:
        return None
    return str(value).strip()


def make_group_spectrum_id(dataset_id: str, rule: Mapping[str, Any], key: Mapping[str, Any]) -> str:
    """Deterministic id: same dataset + grouping rule + group key -> same id, whatever the upstream steps."""
    digest = sha256_hex(canonical_json({"dataset_id": dataset_id, "rule": dict(rule), "key": dict(key)}))
    return f"grp_{digest[:16]}"


def _group_members(
    members: Sequence[GroupMember], params: GroupAverageParams
) -> list[tuple[dict[str, Any], list[GroupMember]]]:
    """Partition members into ordered (key, members) groups."""
    # 1) base partition: region (optional) + label values
    buckets: dict[str, tuple[dict[str, Any], list[GroupMember]]] = {}
    order: list[str] = []
    for m in members:
        key: dict[str, Any] = {}
        if params.split_by_region:
            region = str(m.labels.get(REGION_LABEL) or "").strip()
            if region:
                key[REGION_LABEL] = region
        if params.mode == "by_label":
            for lab in params.group_by:
                if lab != REGION_LABEL or REGION_LABEL not in key:
                    key[lab] = _key_token(m.labels.get(lab))
        bk = canonical_json(key)
        if bk not in buckets:
            buckets[bk] = (key, [])
            order.append(bk)
        buckets[bk][1].append(m)

    if params.mode != "by_range":
        return [buckets[bk] for bk in order]

    # 2) numeric binning inside each base bucket
    assert params.range_label and params.range_width
    width = float(params.range_width)
    out: list[tuple[dict[str, Any], list[GroupMember]]] = []
    for bk in order:
        base_key, mems = buckets[bk]
        vals = [(label_as_number(m.labels.get(params.range_label)), m) for m in mems]
        numeric = [(v, m) for v, m in vals if v is not None]
        if not numeric:
            raise ValueError(
                f"group_average: label {params.range_label!r} is missing or not numeric for the spectra "
                f"of group {base_key or 'all'}"
            )
        origin = params.range_origin if params.range_origin is not None else min(v for v, _ in numeric)
        bins: dict[int, list[tuple[float, GroupMember]]] = {}
        for v, m in numeric:
            bins.setdefault(int(math.floor((v - origin) / width + 1e-12)), []).append((v, m))
        for b in sorted(bins):
            k = dict(base_key)
            lo = origin + b * width
            k["range_label"] = params.range_label
            k["range_start"] = float(f"{lo:.9g}")
            k["range_end"] = float(f"{lo + width:.9g}")
            out.append((k, [m for _, m in sorted(bins[b], key=lambda t: t[0])]))
    return out


def reduce_spectra(xys: Sequence[XY], reducer: Reducer = "cumulative") -> tuple[XY, list[str]]:
    """Combine spectra (sum / mean / median); differing x grids are interpolated onto the first spectrum's grid (overlap only)."""
    if not xys:
        raise ValueError("reduce_spectra: no spectra")
    warnings: list[str] = []
    ref_x = np.asarray(xys[0].x, dtype=float)
    ys: list[np.ndarray] = []
    for i, xy in enumerate(xys):
        x = np.asarray(xy.x, dtype=float)
        y = np.asarray(xy.y, dtype=float)
        if x.shape == ref_x.shape and np.allclose(x, ref_x, equal_nan=True):
            ys.append(y)
            continue
        if x.size < 2:
            raise ValueError("group_average: member spectrum has fewer than 2 points")
        order = np.argsort(x)
        xs, yo = x[order], y[order]
        yi = np.interp(ref_x, xs, yo, left=np.nan, right=np.nan)
        ys.append(yi)
        if i == 1 or not warnings:
            warnings.append("x axes differ between members; interpolated onto the first member's axis")
    stack = np.vstack(ys)
    valid = np.all(np.isfinite(stack), axis=0)
    if not valid.all():
        if not valid.any():
            raise ValueError("group_average: member spectra do not overlap on the x axis")
        warnings.append("members do not fully overlap; result cropped to the common x range")
        ref_x = ref_x[valid]
        stack = stack[:, valid]
    if reducer == "median":
        y = np.median(stack, axis=0)
    elif reducer == "mean":
        y = np.mean(stack, axis=0)
    else:  # cumulative: sum of the members
        y = np.sum(stack, axis=0)
    return XY(x=ref_x, y=y), warnings


def combine_labels(
    members: Sequence[GroupMember], key: Mapping[str, Any], *, n_averaged: int, reducer: str
) -> dict[str, Any]:
    """Derived labels: grouped labels keep their value; numeric ones get mean/min/max; others 'mixed'."""
    keys: list[str] = []
    for m in members:
        for k in m.labels:
            if k not in keys and k not in _PER_SOURCE_LABEL_KEYS:
                keys.append(k)
    out: dict[str, Any] = {}
    for k in keys:
        vals = [m.labels.get(k) for m in members]
        distinct = {canonical_json(v) for v in vals}
        if len(distinct) == 1:
            out[k] = vals[0]
            continue
        nums = [label_as_number(v) for v in vals]
        if all(n is not None for n in nums) and not all(isinstance(v, str) and label_as_number(v) is None for v in vals):
            arr = np.asarray(nums, dtype=float)
            out[k] = float(np.mean(arr))
            out[f"{k}_min"] = float(np.min(arr))
            out[f"{k}_max"] = float(np.max(arr))
        else:
            out[k] = "mixed"
    for k, v in key.items():
        if k not in ("range_label", "range_start", "range_end"):
            out[k] = v
    out["spectrum_role"] = SPECTRUM_ROLE_GROUP_MEAN
    out["n_averaged"] = int(n_averaged)
    out["group_reducer"] = reducer
    out["group_key"] = dict(key)
    out["member_spectrum_ids"] = [m.spectrum_id for m in members]
    return out


def group_average(
    members: Iterable[GroupMember],
    params: GroupAverageParams,
    *,
    dataset_id: str,
) -> list[AveragedGroup]:
    """Group ``members`` according to ``params`` and reduce each group to one spectrum."""
    params.validate()
    usable = [m for m in members if m.xy.x.size > 0]
    if not usable:
        return []
    rule = params.rule_dict()
    groups: list[AveragedGroup] = []
    for key, mems in _group_members(usable, params):
        if len(mems) < params.min_group_size:
            continue
        xy, warnings = reduce_spectra([m.xy for m in mems], params.reducer)
        labels = combine_labels(mems, key, n_averaged=len(mems), reducer=params.reducer)
        groups.append(
            AveragedGroup(
                spectrum_id=make_group_spectrum_id(dataset_id, rule, key),
                key=key,
                member_ids=[m.spectrum_id for m in mems],
                xy=xy,
                labels=labels,
                warnings=warnings,
            )
        )
    return groups
