from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.upload_registry import resolve_uploaded_path, upload_root
from sersflow.core.pipeline.cache import CacheInterface
from sersflow.core.pipeline.hashing import sha256_hex
from sersflow.core.pipeline.steps import (
    DEFAULT_STEPS,
    normalize_by_reference_point,
    normalization_point_x,
    params_fingerprint,
)
from sersflow.core.spectrum import EMPTY_XY, XY, extract_xy
from sersflow.infra.blob_store import resolve_blob_path

logger = logging.getLogger(__name__)


def _parse_collect_token(token: str) -> tuple[str, int | None]:
    """
    Parse collect token:
    - "crop" -> ("crop", None)
    - "crop__3" -> ("crop", 3)

    Must not treat "crop__3" as the full name. We split from the right and accept only a numeric suffix.
    """
    s = str(token or "").strip()
    if not s:
        return ("", None)
    if "__" not in s:
        return (s, None)
    left, right = s.rsplit("__", 1)
    if right.isdigit() and left:
        return (left, int(right))
    return (s, None)


@dataclass(frozen=True)
class EngineConfig:
    cache_namespace: str = "default"


class SpectrumRefLike(Protocol):
    spectrum_id: str
    relative_path: str
    record_index: int | None
    blob_relative_path: str | None


class PipelineStepLike(Protocol):
    name: str
    params: dict[str, Any]
    enabled: bool
    impl_version: str | None


class PipelineLike(Protocol):
    steps: list[PipelineStepLike]


def _resolve_existing_upload_path(relative_path: str) -> Path:
    root = upload_root()
    p = resolve_uploaded_path(root, relative_path)
    if not p.exists():
        raise FileNotFoundError(relative_path)
    return p


def _ref_value(ref: Any, key: str, default: Any = None) -> Any:
    if isinstance(ref, dict):
        return ref.get(key, default)
    return getattr(ref, key, default)


def _resolve_ref_path(ref: Any) -> Path:
    blob_relative_path = _ref_value(ref, "blob_relative_path")
    if blob_relative_path:
        return resolve_blob_path(str(blob_relative_path))
    return _resolve_existing_upload_path(str(_ref_value(ref, "relative_path")))


def _file_input_hash(p: Path) -> str:
    st = p.stat()
    return sha256_hex(f"{p.as_posix()}|{int(st.st_mtime_ns)}|{int(st.st_size)}")


def _cache_key(
    *,
    namespace: str,
    spectrum_id: str,
    step_name: str,
    params_hash: str,
    lineage_hash: str,
) -> tuple[str, str, str, str, str]:
    """
    Cache key for one step execution.

    lineage_hash is the rolling fingerprint of the upstream chain (raw input + prior steps).
    Including it makes cache entries safe under step reordering and upstream param changes.
    """
    return (namespace, spectrum_id, step_name, params_hash, lineage_hash)


def _step_input_from_raw(step: Any) -> str:
    if isinstance(step, dict):
        v = step.get("input_from", "previous")
    else:
        v = getattr(step, "input_from", None) or "previous"
    s = str(v).strip().lower()
    if s in ("initial", "after_step", "previous"):
        return s
    return "previous"


def _step_after_step_id_raw(step: Any) -> str | None:
    if isinstance(step, dict):
        aid = step.get("after_step_id")
    else:
        aid = getattr(step, "after_step_id", None)
    if aid is None:
        return None
    t = str(aid).strip()
    return t or None


def _step_name_raw(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("name", "") or "")
    return str(getattr(step, "name", "") or "")


def _step_params_raw(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        return dict(step.get("params") or {})
    return dict(getattr(step, "params", None) or {})


def _step_enabled_raw(step: Any) -> bool:
    if isinstance(step, dict):
        return bool(step.get("enabled", True))
    return bool(getattr(step, "enabled", True))


def _step_id_raw(step: Any) -> str | None:
    if isinstance(step, dict):
        sid = step.get("step_id")
    else:
        sid = getattr(step, "step_id", None)
    if sid is None:
        return None
    t = str(sid).strip()
    return t or None


def _input_tag(input_from: str, after_step_id: str | None) -> str:
    return sha256_hex(f"{input_from}|{after_step_id or ''}")


def _validate_baseline_point_references(steps_list: Sequence[Any]) -> None:
    id_to_index: dict[str, int] = {}
    for i, step in enumerate(steps_list):
        sid = _step_id_raw(step)
        if sid:
            id_to_index[sid] = i

    for j, step in enumerate(steps_list):
        if not _step_enabled_raw(step):
            continue
        if _step_name_raw(step) != "normalize":
            continue
        params = _step_params_raw(step)
        if str(params.get("method", "max")) != "baseline_point":
            continue
        baseline_step_id = str(params.get("baseline_step_id") or "").strip()
        if not baseline_step_id:
            raise ValueError("baseline_step_id must be provided for normalization method='baseline_point'")
        k = id_to_index.get(baseline_step_id)
        if k is None:
            raise ValueError(f"baseline_step_id {baseline_step_id!r} does not match any pipeline step")
        if k >= j:
            raise ValueError("baseline_step_id must refer to an earlier pipeline step")
        baseline_step = steps_list[k]
        if not _step_enabled_raw(baseline_step):
            raise ValueError("baseline_step_id must refer to an enabled baseline step")
        if _step_name_raw(baseline_step) != "baseline":
            raise ValueError("baseline_step_id must refer to a baseline step")


def _lineage_after_indexed_step(
    lineage_in: str,
    step_index: int,
    name: str,
    params_hash: str,
    impl_version: str,
    input_tag: str,
) -> str:
    return sha256_hex(f"{lineage_in}|idx={step_index}|{name}|{params_hash}|{impl_version}|in={input_tag}")


def _run_indexed_steps_for_spectrum(
    *,
    xy_initial: XY,
    input_hash: str,
    steps_list: Sequence[Any],
    spectrum_id: str,
    cache: CacheInterface[XY] | None,
    namespace: str,
    up_to_step: str | None,
    collect_steps: set[str] | None,
    step_nums: list[int] | None = None,
    collect_step_inputs: bool = False,
) -> tuple[XY, dict[str, XY], dict[int, XY]]:
    """
    Execute pipeline steps in list order with per-step input resolution (previous / initial / after_step).

    Disabled rows pass through the previous row's output without transforming.

    When collect_step_inputs is True, step_nums must have length n. For each enabled step j,
    the XY immediately before that step's transform is stored as per_step_input[step_nums[j]].
    Metric steps (fitting, spectral_intensities) should use that input spectrum (fitting refits raw data;
    spectral_intensities is a no-op on XY so input equals output).
    """
    n = len(steps_list)
    if n == 0:
        return xy_initial, {}, {}

    if collect_step_inputs:
        if step_nums is None or len(step_nums) != n:
            raise ValueError("collect_step_inputs requires step_nums with one entry per pipeline step")
    per_step_input: dict[int, XY] = {}

    final_xy: XY = xy_initial

    id_to_index: dict[str, int] = {}
    for i, s in enumerate(steps_list):
        sid = _step_id_raw(s)
        if sid:
            id_to_index[sid] = i

    outputs: list[XY | None] = [None] * n
    inputs_for_step: list[XY | None] = [None] * n
    lineage_after: list[str | None] = [None] * n
    per_spec: dict[str, XY] = {} if collect_steps is not None else {}

    want_by_name: dict[str, set[int | None]] = {}
    if collect_steps is not None:
        for t in collect_steps:
            nm, num = _parse_collect_token(str(t))
            if not nm:
                continue
            want_by_name.setdefault(nm, set()).add(num)

    for j in range(n):
        step = steps_list[j]
        en = _step_enabled_raw(step)
        if not en:
            if j == 0:
                outputs[0] = xy_initial
                lineage_after[0] = input_hash
            else:
                outputs[j] = outputs[j - 1]
                lineage_after[j] = lineage_after[j - 1]
            final_xy = outputs[j]  # type: ignore[assignment]
            continue

        name = _step_name_raw(step)
        impl = DEFAULT_STEPS.get(name)
        if impl is None:
            raise ValueError(f"Unknown pipeline step: {name}")
        impl_version = str(getattr(step, "impl_version", None) or (step.get("impl_version") if isinstance(step, dict) else None) or impl.impl_version)
        params = _step_params_raw(step)

        input_from = _step_input_from_raw(step)
        after_id = _step_after_step_id_raw(step)
        itag_decl = _input_tag(input_from, after_id if input_from == "after_step" else None)

        base_fp = params_fingerprint(name, params, impl_version)

        lineage_in_for_transform = input_hash
        inp_xy: XY

        if input_from == "initial":
            inp_xy = xy_initial
            lineage_in_for_transform = input_hash
        elif input_from == "after_step" and after_id:
            k = id_to_index.get(after_id)
            if k is None or k >= j or outputs[k] is None:
                if j > 0 and outputs[j - 1] is not None:
                    inp_xy = outputs[j - 1]  # type: ignore[assignment]
                    lineage_in_for_transform = lineage_after[j - 1] or input_hash
                else:
                    inp_xy = xy_initial
                    lineage_in_for_transform = input_hash
            else:
                inp_xy = outputs[k]  # type: ignore[assignment]
                lineage_in_for_transform = lineage_after[k] or input_hash
        else:
            if j > 0 and outputs[j - 1] is not None:
                inp_xy = outputs[j - 1]  # type: ignore[assignment]
                lineage_in_for_transform = lineage_after[j - 1] or input_hash
            else:
                inp_xy = xy_initial
                lineage_in_for_transform = input_hash

        if collect_step_inputs and step_nums is not None:
            per_step_input[step_nums[j]] = inp_xy
        inputs_for_step[j] = inp_xy

        baseline_ref_tag = ""
        baseline_reference: XY | None = None
        if name == "normalize" and str(params.get("method", "max")) == "baseline_point":
            baseline_step_id = str(params.get("baseline_step_id") or "").strip()
            if not baseline_step_id:
                raise ValueError("baseline_step_id must be provided for normalization method='baseline_point'")
            k = id_to_index.get(baseline_step_id)
            if k is None:
                raise ValueError(f"baseline_step_id {baseline_step_id!r} does not match any pipeline step")
            if k >= j:
                raise ValueError("baseline_step_id must refer to an earlier pipeline step")
            baseline_step = steps_list[k]
            if not _step_enabled_raw(baseline_step):
                raise ValueError("baseline_step_id must refer to an enabled baseline step")
            if _step_name_raw(baseline_step) != "baseline":
                raise ValueError("baseline_step_id must refer to a baseline step")
            baseline_input = inputs_for_step[k]
            baseline_output = outputs[k]
            if baseline_input is None or baseline_output is None:
                raise ValueError("selected baseline step has no available input/output")
            if (
                baseline_input.x.size != baseline_output.x.size
                or baseline_input.y.size != baseline_output.y.size
                or baseline_input.x.size != baseline_input.y.size
            ):
                raise ValueError("selected baseline step input/output arrays are incompatible")
            baseline_reference = XY(
                x=baseline_input.x,
                y=baseline_input.y.astype(float, copy=False) - baseline_output.y.astype(float, copy=False),
            )
            baseline_ref_tag = lineage_after[k] or ""

        params_hash = sha256_hex(f"{base_fp}|in={itag_decl}|baseline_ref={baseline_ref_tag}")

        step_key = f"{j}::{name}"
        key = _cache_key(
            namespace=namespace,
            spectrum_id=spectrum_id,
            step_name=step_key,
            params_hash=params_hash,
            lineage_hash=lineage_in_for_transform,
        )
        cached = cache.get(key) if cache is not None else None
        if cached is not None:
            xy_out = cached
        else:
            if baseline_reference is not None:
                point_x = normalization_point_x(params, method="baseline_point")
                xy_out = normalize_by_reference_point(
                    inp_xy,
                    reference_x=baseline_reference.x,
                    reference_y=baseline_reference.y,
                    point_x=point_x,
                    reference_label="baseline",
                )
            else:
                xy_out = impl.transform(inp_xy, params)
            if cache is not None:
                cache.set(key, xy_out)

        outputs[j] = xy_out
        lineage_after[j] = _lineage_after_indexed_step(
            lineage_in_for_transform,
            j,
            name,
            params_hash,
            impl_version,
            itag_decl,
        )

        if collect_steps is not None:
            wants = want_by_name.get(name)
            if wants:
                # Legacy: collect by step name (last enabled occurrence wins).
                if None in wants:
                    per_spec[name] = xy_out
                # New: collect by specific step_num token like "crop__3" (requires step_nums).
                if step_nums is not None and j < len(step_nums):
                    sn = step_nums[j]
                    if sn in wants:
                        per_spec[f"{name}__{sn}"] = xy_out

        final_xy = xy_out

        if up_to_step is not None:
            # Back-compat: allow selecting a stop point by step *name* (stops at first enabled occurrence).
            if name == up_to_step:
                break
            # New: allow disambiguating duplicate step names by selecting the specific step_id.
            sid_here = _step_id_raw(step)
            if sid_here and sid_here == up_to_step:
                break
            # New: allow selecting a specific occurrence via deterministic "name__<num>" token.
            # This matches the token scheme used for collect_steps (e.g. "crop__3").
            if step_nums is not None and j < len(step_nums):
                tok = f"{name}__{step_nums[j]}"
                if tok == up_to_step:
                    break

    return final_xy, per_spec, per_step_input if collect_step_inputs else {}


def _run_one_no_cache(
    ref: dict[str, Any],
    steps: list[dict[str, Any]],
    step_nums: list[int],
    *,
    namespace: str,
    up_to_step: str | None,
    collect_step_inputs: bool = False,
) -> tuple[XY, dict[int, XY]]:
    """
    Worker-safe implementation for ProcessPoolExecutor.

    IMPORTANT:
    - Does not use cross-process cache (InProcessLRUCache is not shared).
    - Uses only primitive ref/step specs to avoid pickling issues.
    - Missing uploads or unrecoverable per-spectrum failures return EMPTY_XY so batch runs do not abort.
    """
    sid = str(ref.get("spectrum_id") or "unknown")
    try:
        p = _resolve_ref_path(ref)
        ds = load_dataset(Path(p))
        xy_initial = extract_xy(ds, record_index=ref.get("record_index"))
        input_hash = _file_input_hash(Path(p))

        xy, _, per_in = _run_indexed_steps_for_spectrum(
            xy_initial=xy_initial,
            input_hash=input_hash,
            steps_list=steps,
            spectrum_id=sid,
            cache=None,
            namespace=namespace,
            up_to_step=up_to_step,
            collect_steps=None,
            step_nums=step_nums,
            collect_step_inputs=collect_step_inputs,
        )
        return xy, per_in
    except (FileNotFoundError, OSError, ValueError, IndexError) as e:
        logger.info("pipeline skip spectrum %s: %s", sid, e)
        return EMPTY_XY, {}


def run_pipeline_parallel_no_cache(
    *,
    inputs: Sequence[dict[str, Any]],
    pipeline_steps: Sequence[dict[str, Any]],
    config: EngineConfig | None = None,
    up_to_step: str | None = None,
    max_workers: int | None = None,
    step_nums: list[int] | None = None,
    collect_step_inputs: bool = False,
) -> dict[str, XY] | tuple[dict[str, XY], dict[str, dict[int, XY]]]:
    """
    Parallel pipeline execution for large batches (no shared cache).

    Notes:
    - Intended for Batch mode where we process many spectra once.
    - Uses ProcessPoolExecutor to speed up CPU-bound transforms.
    """
    cfg = config or EngineConfig()
    if not inputs:
        return {} if not collect_step_inputs else ({}, {})
    steps = [dict(s) for s in pipeline_steps]
    if collect_step_inputs:
        if not step_nums or len(step_nums) != len(steps):
            raise ValueError("collect_step_inputs requires step_nums matching pipeline_steps length")
    nums = step_nums or [0] * len(steps)
    _validate_baseline_point_references(steps)

    out: dict[str, XY] = {}
    per_in: dict[str, dict[int, XY]] = {} if collect_step_inputs else {}
    pool_broken = False

    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        fut_to_sid = {}
        for ref in inputs:
            sid = str(ref["spectrum_id"])
            ref_payload = dict(ref)
            fut = ex.submit(
                _run_one_no_cache,
                ref_payload,
                steps,
                nums,
                namespace=cfg.cache_namespace,
                up_to_step=up_to_step,
                collect_step_inputs=collect_step_inputs,
            )
            fut_to_sid[fut] = sid

        for fut in as_completed(fut_to_sid):
            sid = fut_to_sid[fut]
            try:
                xy_res, pin = fut.result()
                out[sid] = xy_res
                if collect_step_inputs:
                    per_in[sid] = pin
            except Exception as e:
                if isinstance(e, BrokenProcessPool):
                    pool_broken = True
                logger.warning("pipeline parallel worker failed for %s: %s", sid, e)
                out[sid] = EMPTY_XY
                if collect_step_inputs:
                    per_in[sid] = {}

    if pool_broken:
        logger.warning("pipeline process pool broke; rerunning workload sequentially")
        out = {}
        per_in = {} if collect_step_inputs else {}
        for ref in inputs:
            ref_payload = dict(ref)
            xy_res, pin = _run_one_no_cache(
                ref_payload,
                steps,
                nums,
                namespace=cfg.cache_namespace,
                up_to_step=up_to_step,
                collect_step_inputs=collect_step_inputs,
            )
            sid = str(ref["spectrum_id"])
            out[sid] = xy_res
            if collect_step_inputs:
                per_in[sid] = pin

    if collect_step_inputs:
        return out, per_in
    return out


def run_pipeline(
    *,
    inputs: Iterable[SpectrumRefLike],
    pipeline: PipelineLike,
    cache: CacheInterface[XY] | None = None,
    config: EngineConfig | None = None,
    up_to_step: str | None = None,
    strict: bool = False,
) -> dict[str, XY]:
    """
    Run the pipeline and return final XY per spectrum_id.

    Notes:
    - This is intentionally stateless; sessions wrap it.
    - Cache stores per-step XY keyed by (namespace, spectrum_id, step, params_hash, lineage_hash).
      lineage_hash encodes upstream step order and params so reordering cannot reuse stale entries.
    - Steps run in list order; each step can take input from previous row, initial spectrum, or after an
      earlier row (see PipelineStep.input_from).
    """
    cfg = config or EngineConfig()
    out: dict[str, XY] = {}
    steps_list = list(pipeline.steps)
    _validate_baseline_point_references(steps_list)

    for ref in inputs:
        sid = ref.spectrum_id
        try:
            p = _resolve_ref_path(ref)
            ds = load_dataset(Path(p))
            xy_initial = extract_xy(ds, record_index=ref.record_index)
            input_hash = _file_input_hash(Path(p))

            xy, _, _ = _run_indexed_steps_for_spectrum(
                xy_initial=xy_initial,
                input_hash=input_hash,
                steps_list=steps_list,
                spectrum_id=sid,
                cache=cache,
                namespace=cfg.cache_namespace,
                up_to_step=up_to_step,
                collect_steps=None,
            )
            out[sid] = xy
        except (FileNotFoundError, OSError, ValueError, IndexError) as e:
            if strict:
                raise
            logger.info("pipeline skip spectrum %s: %s", sid, e)
            out[sid] = EMPTY_XY

    return out


def run_pipeline_with_intermediates(
    *,
    inputs: Iterable[SpectrumRefLike],
    pipeline: PipelineLike,
    collect_steps: set[str],
    cache: CacheInterface[XY] | None = None,
    config: EngineConfig | None = None,
    up_to_step: str | None = None,
    strict: bool = False,
) -> tuple[dict[str, XY], dict[str, dict[str, XY]]]:
    """
    Run pipeline and also collect intermediates for selected step names.

    Returns:
        (final_by_spectrum_id, intermediates_by_spectrum_id[step_name] = XY)

    Duplicate step names: intermediates dict keeps one entry per name (last enabled occurrence).
    """
    cfg = config or EngineConfig()
    finals: dict[str, XY] = {}
    inter: dict[str, dict[str, XY]] = {}
    steps_list = list(pipeline.steps)
    _validate_baseline_point_references(steps_list)
    # Used for collecting specific occurrences via tokens like "crop__3".
    # Assigns numeric step ids deterministically from step_id (if numeric) or pipeline index (j+1).
    from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums

    step_nums = assign_pipeline_step_nums(steps_list)

    for ref in inputs:
        sid = ref.spectrum_id
        try:
            p = _resolve_ref_path(ref)
            ds = load_dataset(Path(p))
            xy_initial = extract_xy(ds, record_index=ref.record_index)
            input_hash = _file_input_hash(Path(p))

            xy, per_spec, _ = _run_indexed_steps_for_spectrum(
                xy_initial=xy_initial,
                input_hash=input_hash,
                steps_list=steps_list,
                spectrum_id=sid,
                cache=cache,
                namespace=cfg.cache_namespace,
                up_to_step=up_to_step,
                collect_steps=collect_steps,
                step_nums=step_nums,
            )
            finals[sid] = xy
            inter[sid] = per_spec
        except (FileNotFoundError, OSError, ValueError, IndexError) as e:
            if strict:
                raise
            logger.info("pipeline skip spectrum %s: %s", sid, e)
            finals[sid] = EMPTY_XY
            inter[sid] = {}

    return finals, inter
