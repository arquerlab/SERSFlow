from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.upload_registry import resolve_uploaded_path, upload_root
from sersflow.core.pipeline.cache import CacheInterface
from sersflow.core.pipeline.hashing import sha256_hex
from sersflow.core.pipeline.steps import DEFAULT_STEPS, params_fingerprint
from sersflow.core.spectrum import XY, extract_xy


@dataclass(frozen=True)
class EngineConfig:
    cache_namespace: str = "default"

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
    input_hash: str,
) -> tuple[str, str, str, str, str]:
    return (namespace, spectrum_id, step_name, params_hash, input_hash)


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
    - Cache stores per-step XY intermediates keyed by (namespace,spectrum_id,step,params_hash,input_hash).
    """
    cfg = config or EngineConfig()
    out: dict[str, XY] = {}

    for ref in inputs:
        p = _resolve_existing_upload_path(ref.relative_path)
        ds = load_dataset(Path(p))
        xy = extract_xy(ds, record_index=ref.record_index)
        input_hash = _file_input_hash(Path(p))

        for step in pipeline.steps:
            if not step.enabled:
                continue
            impl = DEFAULT_STEPS.get(step.name)
            if impl is None:
                raise ValueError(f"Unknown pipeline step: {step.name}")
            impl_version = step.impl_version or impl.impl_version
            params_hash = sha256_hex(params_fingerprint(step.name, step.params, impl_version))

            key = _cache_key(
                namespace=cfg.cache_namespace,
                spectrum_id=ref.spectrum_id,
                step_name=step.name,
                params_hash=params_hash,
                input_hash=input_hash,
            )
            cached = cache.get(key) if cache is not None else None
            if cached is not None:
                xy = cached
            else:
                xy = impl.transform(xy, step.params)
                if cache is not None:
                    cache.set(key, xy)

            if up_to_step is not None and step.name == up_to_step:
                break

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
    """
    cfg = config or EngineConfig()
    finals: dict[str, XY] = {}
    inter: dict[str, dict[str, XY]] = {}

    for ref in inputs:
        p = _resolve_existing_upload_path(ref.relative_path)
        ds = load_dataset(Path(p))
        xy = extract_xy(ds, record_index=ref.record_index)
        input_hash = _file_input_hash(Path(p))

        per_spec: dict[str, XY] = {}
        for step in pipeline.steps:
            if not step.enabled:
                continue
            impl = DEFAULT_STEPS.get(step.name)
            if impl is None:
                raise ValueError(f"Unknown pipeline step: {step.name}")
            impl_version = step.impl_version or impl.impl_version
            params_hash = sha256_hex(params_fingerprint(step.name, step.params, impl_version))

            key = _cache_key(
                namespace=cfg.cache_namespace,
                spectrum_id=ref.spectrum_id,
                step_name=step.name,
                params_hash=params_hash,
                input_hash=input_hash,
            )
            cached = cache.get(key) if cache is not None else None
            if cached is not None:
                xy = cached
            else:
                xy = impl.transform(xy, step.params)
                if cache is not None:
                    cache.set(key, xy)

            if step.name in collect_steps:
                per_spec[step.name] = xy

            if up_to_step is not None and step.name == up_to_step:
                break

        finals[ref.spectrum_id] = xy
        inter[ref.spectrum_id] = per_spec

    return finals, inter

