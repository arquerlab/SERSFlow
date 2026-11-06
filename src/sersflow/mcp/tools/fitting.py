"""Fitting catalog and interactive fit."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sersflow.api.schemas.fitting import FitRequest
from sersflow.mcp import summarize
from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="get_fitting_models")
    async def get_fitting_models() -> str:
        """GET /fitting/models — fitting component catalog (vibrational + XPS types mixed).

        Prefer /meta/pipeline-steps and XPS recipe apply when building technique-specific pipelines.
        """

        def _run():
            resp = ctx.get_client().fitting.models()
            return {"ok": True, "data": resp.model_dump() if hasattr(resp, "model_dump") else resp}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_fitting_validate_links")
    async def post_fitting_validate_links(
        components: list[dict[str, Any]],
        param_links: list[dict[str, Any]],
    ) -> str:
        """
        POST /fitting/validate-links — check a fitting step's param_links before running (F4).

        Link modes: equal / scale / offset / area_ratio (one target), or expr (free expression):
        {"source_component_id": "C", "source_key": "pos", "mode": "expr",
         "expr": "{A.pos} + 0.5*({B.pos} - {A.pos})"}. References are {peak.param}; {A.area} is the peak area;
        "defines": "area" on an amp link makes the expression the peak AREA. Allowed: numbers, + - * / **,
        abs sqrt exp log min max. A linked parameter ignores its own bounds. Returns {ok, errors, drivers};
        errors name unknown peaks/keys, parameters defined twice and cycles (C.pos -> B.pos -> C.pos).
        """

        def _run():
            data = ctx.get_client().fitting.validate_links(components, param_links)
            return {"ok": True, "data": data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_fitting_test_peak_model")
    async def post_fitting_test_peak_model(
        fit_request: dict[str, Any],
        mode: str = "scan",
        key: str | None = None,
        component_id: str | None = None,
        component_type: str | None = None,
        values: list[float] | None = None,
        n_replicates: int = 50,
        seed: int = 0,
    ) -> str:
        """
        POST /fitting/test-peak-model — S1 "Test peak model" (CasaXPS) on ONE spectrum.

        fit_request: the same body as post_fitting_fit (target, components, p0, bounds, vary, param_links, ...).
        mode="scan": fix `key` (pos, fwhm, m, ...) of `component_id` — or of every component (optionally only
        `component_type`, e.g. all GL m) — at each of `values` (<=101) and refit: per value chi2, redchi, rmse, bic,
        area and %area per component; best_value = chi2 minimum. A flat chi2 with moving %area = unstable component.
        mode="noise": refit n_replicates noisy copies of the best fit (F2 Monte Carlo): %area distribution and
        parameter spread per component (overlay curves are dropped from this compact answer).
        """

        def _run():
            body: dict[str, Any] = {"fit": fit_request, "mode": mode, "n_replicates": n_replicates, "seed": seed}
            for k, v in (("key", key), ("component_id", component_id), ("component_type", component_type)):
                if v is not None:
                    body[k] = v
            if values is not None:
                body["values"] = values
            data = ctx.get_client().fitting.test_peak_model(body)
            data.pop("overlay", None)
            for k in ("x", "y", "best_y_hat"):
                data.pop(k, None)
            return {"ok": True, "data": data}

        return await tool_call(ctx, _run)

    @mcp.tool(name="get_references")
    async def get_references(q: str | None = None) -> str:
        """GET /references — your reference-spectrum library (M1): id, name, range, area, sha256, provenance."""

        def _run():
            return {"ok": True, "data": ctx.get_client().fitting.list_references(q)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_references")
    async def post_references(
        name: str,
        x: list[float] | None = None,
        y: list[float] | None = None,
        dataset_id: str | None = None,
        spectrum_id: str | None = None,
        text: str | None = None,
        x_min: float | None = None,
        x_max: float | None = None,
        notes: str = "",
        source: dict[str, Any] | None = None,
    ) -> str:
        """
        Save a reference spectrum (M1) for `reference_spectrum` fit components. Give ONE of:
        x+y (a processed spectrum, e.g. after calibration and background subtraction; put the pipeline/provenance in
        `source`), dataset_id+spectrum_id (raw spectrum as loaded), or `text` (two-column energy/intensity file
        content). The stored copy is normalised to unit area, so a fitted reference amplitude is its area. Use in a
        fitting step as {"component_id": "CoO", "component_type": "reference_spectrum", "reference_id": ...,
        "reference_sha256": ...} with p0 [area, shift]; shift is fixed (vary false) by default. Models made only of
        references with fixed shifts are solved exactly by NNLS.
        """

        def _run():
            client = ctx.get_client().fitting
            if x is not None and y is not None:
                body = {"name": name, "x": x, "y": y, "notes": notes, "source": source or {}, "x_min": x_min, "x_max": x_max}
                return {"ok": True, "data": _summary(client.create_reference(body))}
            if dataset_id and spectrum_id:
                body = {"name": name, "dataset_id": dataset_id, "spectrum_id": spectrum_id, "notes": notes, "x_min": x_min, "x_max": x_max}
                return {"ok": True, "data": _summary(client.create_reference_from_dataset(body))}
            if text:
                return {"ok": True, "data": _summary(client.import_reference({"name": name, "content": text, "notes": notes}))}
            return {"ok": False, "error": "give x+y, dataset_id+spectrum_id, or text"}

        return await tool_call(ctx, _run)

    @mcp.tool(name="delete_references")
    async def delete_references(reference_id: str) -> str:
        """DELETE /references/{reference_id} — remove one of your reference spectra."""

        def _run():
            return {"ok": True, "data": ctx.get_client().fitting.delete_reference(reference_id)}

        return await tool_call(ctx, _run)

    @mcp.tool(name="post_fitting_fit")
    async def post_fitting_fit(
        request: dict[str, Any],
        return_curve: bool = False,
        output_path: str | None = None,
        confirm: bool = False,
    ) -> str:
        """POST /fitting/fit — compact diagnostics; optional curve JSON path when return_curve=true."""

        def _run():
            req = FitRequest.model_validate(request)
            resp = ctx.get_client().fitting.fit(req)
            data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
            curve_keys = {"x", "y", "y_fit", "y_hat", "residual", "residual_normalised", "components", "curve"}
            compact = {
                k: v
                for k, v in (data.items() if isinstance(data, dict) else [])
                if k not in curve_keys
            }
            out: dict[str, Any] = {"ok": True, "diagnostics": compact}
            if return_curve:
                dest = ctx.resolve_export_path(
                    output_path, "fitting_fit_curve.json", confirm=confirm
                )
                dest.write_text(json.dumps(data, default=str), encoding="utf-8")
                ctx.record_export("fitting:fit", dest)
                out["curve_path"] = str(dest.resolve())
            return out

        return await tool_call(ctx, _run)


def _summary(ref: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in ref.items() if k not in ("x", "y")}
