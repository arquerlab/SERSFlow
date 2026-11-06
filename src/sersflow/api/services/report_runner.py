"""Async job producing the R1 publication fit report (zip: report.html, report.md, report.json, figures/*.png)."""

from __future__ import annotations

import json
import logging
import os
import zipfile

from sersflow.api.services.fit_report import build_fit_report
from sersflow.core.report.render import render_html, render_markdown
from sersflow.infra.analysis_store import get_fit_curve_job, update_fit_curve_job
from sersflow.infra.explore_store import artifacts_root

logger = logging.getLogger(__name__)

REPORT_CONTENT = "report"
REPORT_JSON = "report.json"


def execute_report_job(job_id: str) -> None:
    rec = get_fit_curve_job(job_id)
    if rec is None:
        logger.error("report job not found: %s", job_id)
        return
    try:
        update_fit_curve_job(job_id=job_id, status="running", finished=False)
        opts = json.loads(rec.params_json or "{}")

        def progress(done: int, total: int) -> None:
            if done % 5 == 0 or done == total:
                update_fit_curve_job(job_id=job_id, progress_done=done, progress_total=total)

        report, figures = build_fit_report(
            rec.run_id,
            spectrum_ids=opts.get("spectrum_ids") or None,
            fitting_step_nums=opts.get("fitting_step_nums") or None,
            include_figures=bool(opts.get("include_figures", True)),
            progress=progress,
        )
        out_dir = os.path.join(artifacts_root(), "fit_curve_jobs", job_id)
        os.makedirs(out_dir, exist_ok=True)
        js = json.dumps(report, indent=1, allow_nan=False)
        with open(os.path.join(out_dir, REPORT_JSON), "w", encoding="utf-8") as f:
            f.write(js)
        zip_path = os.path.join(out_dir, "export.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("report.html", render_html(report, figures))
            zf.writestr("report.md", render_markdown(report))
            zf.writestr(REPORT_JSON, js)
            for name, data in figures.items():
                zf.writestr(name, data)
        n = sum(len(s.get("fits") or []) for s in report.get("spectra") or [])
        update_fit_curve_job(
            job_id=job_id, status="completed", progress_done=n, progress_total=n, artifact_path=zip_path, finished=True
        )
    except Exception as e:
        logger.exception("report job failed: %s", job_id)
        update_fit_curve_job(job_id=job_id, status="failed", error=str(e), finished=True)


def read_report_json(artifact_path: str) -> dict:
    with open(os.path.join(os.path.dirname(artifact_path), REPORT_JSON), encoding="utf-8") as f:
        return json.load(f)
