"""
Pieces shared by the background fit jobs (parameter sweep, Monte Carlo, ...).

Every such job does the same things around its own computation: mark the job running, load the run and the
pipeline it used, find the fitting step, collect each spectrum's input to that step, keep the spectra that belong
to the step's XPS region, and mark the job failed if anything raises. They used to be copied into each runner.
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Iterator

from sersflow.api.services.fit_curve_export_runner import _max_spectra
from sersflow.api.services.fitting_preview import _collect_fit_input_xy, _find_fitting_step, _resolved_refs_for_run
from sersflow.api.services.observation_export import _labels_for_spectrum
from sersflow.core.pipeline.engine import fitting_region_applies
from sersflow.infra.analysis_store import get_fit_curve_job, get_run, update_fit_curve_job
from sersflow.infra.explore_store import artifacts_root
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection


def fit_job_dir(job_id: str) -> str:
    """Artifact folder of a fit-curve-style job (not created here)."""
    return os.path.join(artifacts_root(), "fit_curve_jobs", job_id)


@contextlib.contextmanager
def fit_job_lifecycle(job_id: str, label: str, logger: logging.Logger) -> Iterator[Any]:
    """
    Yield the job record with the job marked ``running``; mark it ``failed`` (with the message) if the block raises.

    Yields None when the job does not exist. The block itself marks the job ``completed`` with its artifact.
    """
    rec = get_fit_curve_job(job_id)
    if rec is None:
        logger.error("%s job not found: %s", label, job_id)
        yield None
        return
    try:
        update_fit_curve_job(job_id=job_id, status="running", finished=False)
        yield rec
    except Exception as e:  # noqa: BLE001 - a job must always end in a recorded state
        logger.exception("%s job failed: %s", label, job_id)
        update_fit_curve_job(job_id=job_id, status="failed", error=str(e), finished=True)


@dataclass
class FitJobContext:
    rec: Any
    run: Any
    pipeline: Any
    refs: list[Any]
    ns: str
    fitting_idx: int
    step_params: dict[str, Any]


def load_fit_job_context(rec: Any, *, spectrum_ids: Any = None) -> FitJobContext:
    """Run, pipeline, cohort refs and fitting-step params of a job (the technique defaults to the pipeline's)."""
    run = get_run(rec.run_id)
    if run is None:
        raise ValueError("analysis run not found")
    if run.status != "completed":
        raise ValueError("analysis run is not completed")
    pipeline, _ds, refs, ns = _resolved_refs_for_run(run, list(spectrum_ids) if spectrum_ids else None)
    if len(refs) > _max_spectra():
        raise ValueError(f"too many spectra (max {_max_spectra()})")
    fitting_idx, fitting_step = _find_fitting_step(pipeline, rec.fitting_step_num)
    step_params = dict(fitting_step.params or {})
    tech = getattr(pipeline, "technique_family", None)
    if tech and "technique_family" not in step_params:
        step_params["technique_family"] = tech
    return FitJobContext(
        rec=rec, run=run, pipeline=pipeline, refs=refs, ns=ns, fitting_idx=fitting_idx, step_params=step_params
    )


def applicable_spectra(ctx: FitJobContext) -> list[tuple[Any, Any, dict[str, Any]]]:
    """
    ``(ref, input XY of the fitting step, label row)`` for every cohort spectrum the step applies to.

    Spectra with no data at that step, or whose ``xps_region`` label does not match the step's region, are left out.
    """
    xy_by_id = _collect_fit_input_xy(
        pipeline=ctx.pipeline,
        refs=ctx.refs,
        ns=ctx.ns,
        fitting_idx=ctx.fitting_idx,
        fitting_step_num=ctx.rec.fitting_step_num,
    )
    paths = sorted({str(r.relative_path) for r in ctx.refs if r.relative_path})
    con = with_connection()
    try:
        labels_by_path = fetch_upload_labels_for_paths(con, paths)
    finally:
        con.close()

    applicable: list[tuple[Any, Any, dict[str, Any]]] = []
    for r in ctx.refs:
        xy = xy_by_id.get(str(r.spectrum_id))
        if xy is None or xy.x.size == 0:
            continue
        ri = r.record_index if isinstance(r.record_index, int) else None
        row = _labels_for_spectrum(labels_by_path.get(str(r.relative_path)) or {}, record_index=ri)
        raw_region = row.get("xps_region")
        region = str(raw_region).strip() if raw_region is not None and str(raw_region).strip() else None
        if not fitting_region_applies(step_params=ctx.step_params, spectrum_xps_region=region):
            continue
        applicable.append((r, xy, row))
    return applicable
