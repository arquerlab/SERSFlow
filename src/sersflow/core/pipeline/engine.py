from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence

from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.upload_registry import resolve_uploaded_path, upload_root
from sersflow.core.pipeline.cache import CacheInterface
from sersflow.core.pipeline.hashing import sha256_hex
from sersflow.core.pipeline.steps import DEFAULT_STEPS, StepImpl, params_fingerprint
from sersflow.core.spectrum import XY, extract_xy


@dataclass(frozen=True)
class EngineConfig:
    cache_namespace: str = "default"


@dataclass(frozen=True)
class EnabledStepDescriptor:
    """One enabled pipeline step with precomputed cache metadata (per request)."""

    name: str
    params: dict[str, Any]
    impl: StepImpl
    impl_version: str
    params_hash: str


class SpectrumRefLike(Protocol):
    spectrum_id: str
    relative_path: str
    record_index: int | None


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


def _lineage_after_step(lineage_in: str, desc: EnabledStepDescriptor) -> str:
    return sha256_hex(f"{lineage_in}|{desc.name}|{desc.params_hash}|{desc.impl_version}")


def build_enabled_step_descriptors(steps: Sequence[PipelineStepLike]) -> list[EnabledStepDescriptor]:
    """
    Resolve and fingerprint enabled steps once per pipeline run.

    Avoids repeated DEFAULT_STEPS lookups and params_fingerprint work inside per-spectrum loops.
    """
    out: list[EnabledStepDescriptor] = []
    for step in steps:
        if not step.enabled:
            continue
        impl = DEFAULT_STEPS.get(step.name)
        if impl is None:
            raise ValueError(f"Unknown pipeline step: {step.name}")
        impl_version = str(step.impl_version or impl.impl_version)
        params = dict(step.params or {})
        params_hash = sha256_hex(params_fingerprint(step.name, params, impl_version))
        out.append(
            EnabledStepDescriptor(
                name=step.name,
                params=params,
                impl=impl,
                impl_version=impl_version,
                params_hash=params_hash,
            )
        )
    return out


def _run_enabled_steps_for_spectrum(
    *,
    xy: XY,
    input_hash: str,
    enabled: list[EnabledStepDescriptor],
    spectrum_id: str,
    cache: CacheInterface[XY] | None,
    namespace: str,
    up_to_step: str | None,
    collect_steps: set[str] | None,
) -> tuple[XY, dict[str, XY]]:
    """
    Execute enabled steps in order, updating xy and optional intermediate collection.

    If collect_steps is not None, collects intermediates by step name. Duplicate step names
    in one pipeline overwrite the same dict key (last occurrence wins); callers should avoid
    duplicate names if they need distinct intermediate views.
    """
    lineage_in = input_hash
    per_spec: dict[str, XY] = {} if collect_steps is not None else {}

    for desc in enabled:
        key = _cache_key(
            namespace=namespace,
            spectrum_id=spectrum_id,
            step_name=desc.name,
            params_hash=desc.params_hash,
            lineage_hash=lineage_in,
        )
        cached = cache.get(key) if cache is not None else None
        if cached is not None:
            xy = cached
        else:
            xy = desc.impl.transform(xy, desc.params)
            if cache is not None:
                cache.set(key, xy)

        if collect_steps is not None and desc.name in collect_steps:
            per_spec[desc.name] = xy

        lineage_in = _lineage_after_step(lineage_in, desc)

        if up_to_step is not None and desc.name == up_to_step:
            break

    return xy, per_spec


class _StepSpec(Protocol):
    name: str
    params: dict[str, Any]
    enabled: bool
    impl_version: str | None


def _run_one_no_cache(
    ref: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    namespace: str,
    up_to_step: str | None,
) -> XY:
    """
    Worker-safe implementation for ProcessPoolExecutor.

    IMPORTANT:
    - Does not use cross-process cache (InProcessLRUCache is not shared).
    - Uses only primitive ref/step specs to avoid pickling issues.
    """
    _ = namespace
    p = _resolve_existing_upload_path(str(ref["relative_path"]))
    ds = load_dataset(Path(p))
    xy = extract_xy(ds, record_index=ref.get("record_index"))
    _ = _file_input_hash(Path(p))

    for step in steps:
        if not step.get("enabled", True):
            continue
        step_name = str(step["name"])
        impl = DEFAULT_STEPS.get(step_name)
        if impl is None:
            raise ValueError(f"Unknown pipeline step: {step_name}")
        xy = impl.transform(xy, dict(step.get("params") or {}))
        if up_to_step is not None and step_name == up_to_step:
            break
    return xy


def run_pipeline_parallel_no_cache(
    *,
    inputs: Sequence[dict[str, Any]],
    pipeline_steps: Sequence[dict[str, Any]],
    config: EngineConfig | None = None,
    up_to_step: str | None = None,
    max_workers: int | None = None,
) -> dict[str, XY]:
    """
    Parallel pipeline execution for large batches (no shared cache).

    Notes:
    - Intended for Batch mode where we process many spectra once.
    - Uses ProcessPoolExecutor to speed up CPU-bound transforms.
    """
    cfg = config or EngineConfig()
    if not inputs:
        return {}
    steps = [dict(s) for s in pipeline_steps]
    out: dict[str, XY] = {}

    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        fut_to_sid = {}
        for ref in inputs:
            sid = str(ref["spectrum_id"])
            fut = ex.submit(_run_one_no_cache, dict(ref), steps, namespace=cfg.cache_namespace, up_to_step=up_to_step)
            fut_to_sid[fut] = sid

        for fut in as_completed(fut_to_sid):
            sid = fut_to_sid[fut]
            out[sid] = fut.result()

    return out


def run_pipeline(
    *,
    inputs: Iterable[SpectrumRefLike],
    pipeline: PipelineLike,
    cache: CacheInterface[XY] | None = None,
    config: EngineConfig | None = None,
    up_to_step: str | None = None,
) -> dict[str, XY]:
    """
    Run the pipeline and return final XY per spectrum_id.

    Notes:
    - This is intentionally stateless; sessions wrap it.
    - Cache stores per-step XY keyed by (namespace, spectrum_id, step, params_hash, lineage_hash).
      lineage_hash encodes upstream step order and params so reordering cannot reuse stale entries.
    """
    cfg = config or EngineConfig()
    enabled = build_enabled_step_descriptors(pipeline.steps)
    out: dict[str, XY] = {}

    for ref in inputs:
        p = _resolve_existing_upload_path(ref.relative_path)
        ds = load_dataset(Path(p))
        xy = extract_xy(ds, record_index=ref.record_index)
        input_hash = _file_input_hash(Path(p))

        xy, _ = _run_enabled_steps_for_spectrum(
            xy=xy,
            input_hash=input_hash,
            enabled=enabled,
            spectrum_id=ref.spectrum_id,
            cache=cache,
            namespace=cfg.cache_namespace,
            up_to_step=up_to_step,
            collect_steps=None,
        )
        out[ref.spectrum_id] = xy

    return out


def run_pipeline_with_intermediates(
    *,
    inputs: Iterable[SpectrumRefLike],
    pipeline: PipelineLike,
    collect_steps: set[str],
    cache: CacheInterface[XY] | None = None,
    config: EngineConfig | None = None,
    up_to_step: str | None = None,
) -> tuple[dict[str, XY], dict[str, dict[str, XY]]]:
    """
    Run pipeline and also collect intermediates for selected step names.

    Returns:
        (final_by_spectrum_id, intermediates_by_spectrum_id[step_name] = XY)

    Duplicate step names: intermediates dict keeps one entry per name (last enabled occurrence).
    """
    cfg = config or EngineConfig()
    enabled = build_enabled_step_descriptors(pipeline.steps)
    finals: dict[str, XY] = {}
    inter: dict[str, dict[str, XY]] = {}

    for ref in inputs:
        p = _resolve_existing_upload_path(ref.relative_path)
        ds = load_dataset(Path(p))
        xy = extract_xy(ds, record_index=ref.record_index)
        input_hash = _file_input_hash(Path(p))

        xy, per_spec = _run_enabled_steps_for_spectrum(
            xy=xy,
            input_hash=input_hash,
            enabled=enabled,
            spectrum_id=ref.spectrum_id,
            cache=cache,
            namespace=cfg.cache_namespace,
            up_to_step=up_to_step,
            collect_steps=collect_steps,
        )
        finals[ref.spectrum_id] = xy
        inter[ref.spectrum_id] = per_spec

    return finals, inter
