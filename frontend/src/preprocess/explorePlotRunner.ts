import type { MutableRefObject } from "react";
import {
  postFittingFit,
  runPipeline,
  runSession,
  type FittingComponentSpecPublic,
  type FitRequest,
  type Pipeline,
  type SessionRunFinalResponse,
  type SessionRunIntermediatesResponse,
  type SpectrumRef,
  type TechniqueFamily,
} from "./api";
import type { EditorStep } from "./editorTypes";
import { flattenFittingForPipeline, migrateFittingParamsToEditor } from "./fittingUtils";
import { buildFitResidualFigure } from "./fitResidualPlot";
import { buildSafeRunRequest, capTraceCount, type Mode, type PlotView } from "./runController";
import { fetchUploadsList } from "./hooks/useUploadsList";

const RAMAN_SHIFT_AXIS_TITLE = "Raman Shift (cm⁻¹)";
/** Session cohort QC only (shrink working set). metadata_filter is an engine mask step. */
const QC_STEP_NAMES = new Set(["low_signal_filter", "outlier_detection"]);
/** Steps that do not transform plot XY (features/metrics only). */
const METRIC_STEP_NAMES = new Set([
  "fitting",
  "spectral_intensities",
  "spectral_integrations",
  "feature_operations",
]);

function hasPlottableXy(it: { x?: unknown[]; y?: unknown[] } | null | undefined): boolean {
  return Array.isArray(it?.x) && it!.x!.length > 0;
}

/**
 * Parse View tokens like `fitting` or `fitting__3`.
 * Must split on the last `__<digits>` — a greedy `[A-Za-z0-9_]+` regex would swallow
 * `fitting__3` as the name and skip the fit/baseline special plot paths.
 */
export function parseAfterPlotToken(t: string | null): { name: string | null; stepNum: number | null } {
  if (!t) return { name: null, stepNum: null };
  const s = String(t);
  const sep = s.lastIndexOf("__");
  if (sep > 0) {
    const numPart = s.slice(sep + 2);
    if (/^\d+$/.test(numPart)) {
      return { name: s.slice(0, sep) || null, stepNum: Number(numPart) };
    }
  }
  return { name: s || null, stepNum: null };
}

function resolveEnabledStepIndex(
  steps: EditorStep[],
  name: string,
  stepNum: number | null,
  opts?: { preferLast?: boolean }
): number {
  if (typeof stepNum === "number" && stepNum > 0) {
    const cand = stepNum - 1;
    if (cand >= 0 && cand < steps.length && steps[cand]?.enabled !== false && steps[cand]?.name === name) {
      return cand;
    }
  }
  if (opts?.preferLast) {
    for (let i = steps.length - 1; i >= 0; i--) {
      if (steps[i]?.enabled !== false && steps[i]?.name === name) return i;
    }
    return -1;
  }
  return steps.findIndex((s) => s.enabled !== false && s.name === name);
}

export type FitStackFigure = {
  kind: "fit_stack";
  figures: Array<{ data: Record<string, unknown>[]; layout: Record<string, unknown>; spectrum_id?: string }>;
};

export type ExplorePlotRunnerDeps = {
  sessionId: string;
  explorePlotAbortRef: MutableRefObject<AbortController | null>;
  setLastError: (s: string | null) => void;
  setExplorePlotStatus: (s: string | null) => void;
  ensurePipelineSaved: () => Promise<void>;
  subsetIndices: number[];
  plotView: PlotView;
  mode: Mode;
  runSeq: MutableRefObject<number>;
  subsetSize: number;
  steps: EditorStep[];
  setPreviousFigure: (f: unknown) => void;
  currentFigure: unknown;
  setCurrentFigure: (f: unknown) => void;
  subsetInputsFromIndices: (indices: number[]) => SpectrumRef[];
  editorStepsToApiSteps: (slice: EditorStep[]) => Pipeline["steps"];
  fittingCatalog: FittingComponentSpecPublic[] | undefined;
  techniqueFamily?: TechniqueFamily;
  /** Format-driven plot kind from /meta/formats (xy | multi_overlay | map). */
  formatPlotMode?: "xy" | "multi_overlay" | "map";
  defaultXLabel?: string | null;
};

/**
 * Explore-mode plot refresh: saves pipeline, then runs session or /pipeline/run / /fitting/fit as needed.
 * Preserves abort handling and `runSeq` stale-run suppression.
 */
export async function runExplorePlot(deps: ExplorePlotRunnerDeps): Promise<void> {
  const {
    sessionId,
    explorePlotAbortRef,
    setLastError,
    setExplorePlotStatus,
    ensurePipelineSaved,
    subsetIndices,
    plotView,
    mode,
    runSeq,
    subsetSize,
    steps,
    setPreviousFigure,
    currentFigure,
    setCurrentFigure,
    subsetInputsFromIndices,
    editorStepsToApiSteps,
    fittingCatalog,
    techniqueFamily = "vibrational",
    formatPlotMode = "xy",
    defaultXLabel = null,
  } = deps;
  // Format plot_mode is a format hint (map markers etc.); overlay/stack + subset size remain user prefs.
  const xAxisTitle =
    (defaultXLabel && String(defaultXLabel).trim()) ||
    (techniqueFamily === "xps" ? "Binding energy (eV)" : RAMAN_SHIFT_AXIS_TITLE);

  explorePlotAbortRef.current?.abort();
  const ac = new AbortController();
  explorePlotAbortRef.current = ac;
  const signal = ac.signal;
  // Claim this run immediately so overlapping starts cannot both pass stale-seq checks.
  const seq = ++runSeq.current;

  const aborted = () => signal.aborted;
  const isAbortErr = (e: unknown) =>
    aborted() ||
    (e instanceof DOMException && e.name === "AbortError") ||
    (e as Error)?.name === "AbortError";
  const isStale = () => aborted() || seq !== runSeq.current;
  const commitFigure = (next: unknown) => {
    if (isStale()) return;
    setPreviousFigure(currentFigure);
    setCurrentFigure(next);
  };

  try {
    setLastError(null);
    setExplorePlotStatus("Saving pipeline…");
    await ensurePipelineSaved();
    if (isStale()) return;
    if (!subsetIndices.length) {
      throw new Error("No active subset. Create or apply a saved subset to start plotting.");
    }

    const afterToken = plotView.startsWith("after:") ? plotView.slice("after:".length) : null;
    const after = parseAfterPlotToken(afterToken);
    const afterStep = afterToken; // keep full token for intermediates lookup and request
    // Raw (subset) = true source spectra (no QC, no XY).
    // After a QC step = apply QC through that pipeline step only, then plot remaining raw XY.
    // Final with only QC + metric steps: apply all QC, then plot remaining raw XY.
    const wantsTrueRaw = plotView === "raw";
    const enabledNonQc = steps.filter((s) => s.enabled !== false && !QC_STEP_NAMES.has(s.name));
    const lastEnabledNonQc = [...enabledNonQc].reverse()[0] ?? null;
    const finalEndsWithFitting = plotView === "final" && lastEnabledNonQc?.name === "fitting";
    const finalIsQcCohortOnly =
      plotView === "final" &&
      !finalEndsWithFitting &&
      (enabledNonQc.length === 0 || enabledNonQc.every((s) => METRIC_STEP_NAMES.has(s.name)));
    const wantsQcRaw =
      finalIsQcCohortOnly || (after.name != null && QC_STEP_NAMES.has(after.name));
    const wantsSourceOrQcRaw = wantsTrueRaw || wantsQcRaw;

    let qcRawUpTo: string = "__raw__";
    if (wantsQcRaw && after.name != null && QC_STEP_NAMES.has(after.name)) {
      const through =
        typeof after.stepNum === "number" && after.stepNum > 0
          ? after.stepNum
          : steps.findIndex((s) => s.enabled !== false && s.name === after.name) + 1;
      if (through > 0) qcRawUpTo = `__raw__:${through}`;
    }

    const payload = buildSafeRunRequest({
      mode,
      subsetCount: subsetIndices.length || subsetSize,
      // QC steps have no XY intermediates; use final + sentinel via session run below.
      plotView: wantsSourceOrQcRaw ? "final" : plotView,
      upToStep: wantsTrueRaw ? "__source__" : wantsQcRaw ? qcRawUpTo : null,
      collectSteps: afterStep && !wantsSourceOrQcRaw ? [afterStep] : [],
      batchMetrics: ["peak_height", "fwhm"],
    });

    async function inputsAfterQc(): Promise<SpectrumRef[]> {
      const all = subsetInputsFromIndices(subsetIndices);
      const hasQc = steps.some((s) => s.enabled !== false && QC_STEP_NAMES.has(s.name));
      if (!hasQc) return all;
      const filtered = await runSession(
        sessionId,
        { scope: "subset", return: { kind: "final" }, up_to_step: "__raw__" },
        { signal }
      );
      if (isStale()) return [];
      const keep = new Set(((filtered as SessionRunFinalResponse).items ?? []).map((it) => it.spectrum_id));
      return all.filter((r) => keep.has(r.spectrum_id));
    }

    if (wantsSourceOrQcRaw) {
      setExplorePlotStatus(wantsTrueRaw ? "Loading subset spectra…" : "Applying filters…");
      const out = await runSession(sessionId, payload, { signal });
      if (isStale()) return;
      const items = ((out as SessionRunFinalResponse).items ?? []).filter(hasPlottableXy);
      const traces = capTraceCount(items, subsetSize).map((it) => ({
        type: "scatter",
        mode: formatPlotMode === "map" ? "lines+markers" : "lines",
        x: it.x,
        y: it.y,
        name: it.spectrum_id,
      }));
      if (items.length === 0) {
        setExplorePlotStatus(
          wantsTrueRaw
            ? "No spectra in the active subset."
            : "No spectra remain after cohort QC for this subset."
        );
        commitFigure({
          data: [],
          layout: {
            xaxis: { title: { text: xAxisTitle } },
            yaxis: { title: { text: "Intensity (counts)" } },
            annotations: [
              {
                text: wantsTrueRaw ? "Empty subset" : "Empty after QC filters",
                xref: "paper",
                yref: "paper",
                x: 0.5,
                y: 0.5,
                showarrow: false,
              },
            ],
            margin: { l: 60, r: 20, t: 20, b: 95 },
          },
        });
        return;
      }
      commitFigure({
        data: traces,
        layout: {
          xaxis: { title: { text: xAxisTitle } },
          yaxis: { title: { text: "Intensity (counts)" } },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      });
      return;
    }

    if (after.name === "baseline") {
      setExplorePlotStatus("Baseline preview: running pipeline…");
      const baselineIdx = resolveEnabledStepIndex(steps, "baseline", after.stepNum);
      const baselineParams = baselineIdx >= 0 ? (steps[baselineIdx]?.params ?? {}) : {};

      let prevEnabledIdx = -1;
      if (baselineIdx > 0) {
        for (let i = baselineIdx - 1; i >= 0; i--) {
          if (steps[i]?.enabled !== false) {
            prevEnabledIdx = i;
            break;
          }
        }
      }

      const inputs = await inputsAfterQc();
      if (isStale()) return;

      const slice = steps.slice(0, prevEnabledIdx >= 0 ? prevEnabledIdx + 1 : 0);
      const pipelineToInput: Pipeline = {
        steps: editorStepsToApiSteps(slice).filter((s) => !QC_STEP_NAMES.has(s.name)),
        technique_family: techniqueFamily,
      };

      const pipelineToBaselineCurve: Pipeline = {
        steps: [
          ...pipelineToInput.steps,
          {
            name: "baseline_curve",
            params: baselineParams as Record<string, unknown>,
            enabled: true,
            step_id: crypto.randomUUID(),
            input_from: "previous" as const,
          },
        ],
        technique_family: techniqueFamily,
      };


      let rawIn: Awaited<ReturnType<typeof runPipeline>>;
      let baseOut: Awaited<ReturnType<typeof runPipeline>>;
      try {
        [rawIn, baseOut] = await Promise.all([
          runPipeline({ inputs, pipeline: pipelineToInput, return: { kind: "final" }, cache_namespace: sessionId }, { signal }),
          runPipeline({ inputs, pipeline: pipelineToBaselineCurve, return: { kind: "final" }, cache_namespace: sessionId }, { signal }),
        ]);
      } catch (err) {
        throw err;
      }
      if (isStale()) return;

      const rawItems = capTraceCount(rawIn.items ?? [], subsetSize);
      const baseById = new Map((baseOut.items ?? []).map((it) => [it.spectrum_id, it] as const));

      const traces = rawItems.flatMap((it) => {
        const base = baseById.get(it.spectrum_id);
        const out = [{ type: "scatter", mode: "lines", x: it.x, y: it.y, name: `${it.spectrum_id}` }] as Record<string, unknown>[];
        if (base) {
          out.push({ type: "scatter", mode: "lines", x: base.x, y: base.y, name: `${it.spectrum_id} baseline` });
        }
        return out;
      });

      commitFigure({
        data: traces,
        layout: {
          xaxis: { title: { text: xAxisTitle } },
          yaxis: { title: { text: "Intensity (counts)" } },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      });
      return;
    }

    if (after.name === "fitting" || finalEndsWithFitting) {
      setExplorePlotStatus("Fitting: computing pipeline input…");
      const fittingIdx = resolveEnabledStepIndex(
        steps,
        "fitting",
        finalEndsWithFitting ? null : after.stepNum,
        { preferLast: finalEndsWithFitting }
      );
      const fittingStep = fittingIdx >= 0 ? steps[fittingIdx] : null;
      if (!fittingStep) {
        throw new Error("No enabled fitting step in pipeline");
      }
      const fp = migrateFittingParamsToEditor(fittingStep.params ?? {}, fittingCatalog);
      const flat = flattenFittingForPipeline(fp);
      const compsApi = (flat.components as { component_id: string; component_type: string; degree?: number }[]) ?? [];
      const p0 = flat.p0 as number[];
      const lo = flat.bounds_lower as (number | null)[];
      const hi = flat.bounds_upper as (number | null)[];

      let prevEnabledIdx = -1;
      if (fittingIdx > 0) {
        for (let i = fittingIdx - 1; i >= 0; i--) {
          if (steps[i]?.enabled !== false) {
            prevEnabledIdx = i;
            break;
          }
        }
      }

      const inputs = await inputsAfterQc();
      if (isStale()) return;

      const wantedRegion =
        typeof flat.xps_region === "string" && flat.xps_region.trim() ? flat.xps_region.trim() : "";
      let gatedInputs = inputs;
      if (wantedRegion) {
        try {
          const labJson = await fetchUploadsList(5000);
          const byPath = new Map<string, Record<string, unknown>>(
            (labJson.items ?? []).map((it: { relative_path?: string; labels?: Record<string, unknown> }) => [
              String(it.relative_path || ""),
              (it.labels || {}) as Record<string, unknown>,
            ])
          );
          gatedInputs = inputs.filter((r) => {
            const labels = byPath.get(String(r.relative_path || "")) || {};
            const blocks = (labels as { vms_spectra?: Record<string, { xps_region?: string }> }).vms_spectra;
            let region = "";
            if (blocks && typeof blocks === "object" && r.record_index != null) {
              const b = blocks[String(r.record_index)];
              if (b) region = String(b.xps_region || "");
            } else if (typeof (labels as { xps_region?: string }).xps_region === "string") {
              region = String((labels as { xps_region?: string }).xps_region);
            }
            return region.toLowerCase() === wantedRegion.toLowerCase();
          });
        } catch (e) {
          if (isAbortErr(e)) return;
          // Fall back to ungated inputs if label lookup fails.
        }
      }
      if (wantedRegion && gatedInputs.length === 0) {
        setExplorePlotStatus(`No spectra match fitting region ${wantedRegion} in the QC cohort.`);
        commitFigure({
          data: [],
          layout: {
            xaxis: { title: { text: xAxisTitle } },
            yaxis: { title: { text: "Intensity (counts)" } },
            annotations: [
              {
                text: `No spectra for region ${wantedRegion}`,
                xref: "paper",
                yref: "paper",
                x: 0.5,
                y: 0.5,
                showarrow: false,
              },
            ],
            margin: { l: 60, r: 20, t: 20, b: 95 },
          },
        });
        return;
      }

      const slice = steps.slice(0, prevEnabledIdx >= 0 ? prevEnabledIdx + 1 : 0);
      const pipelineToInput: Pipeline = {
        steps: editorStepsToApiSteps(slice).filter((s) => !QC_STEP_NAMES.has(s.name)),
        technique_family: techniqueFamily,
      };

      const rawIn = await runPipeline(
        {
          inputs: gatedInputs,
          pipeline: pipelineToInput,
          return: { kind: "final" },
          cache_namespace: sessionId,
        },
        { signal }
      );
      if (isStale()) return;

      const rawItems = capTraceCount(rawIn.items ?? [], subsetSize);
      const fillOpacity = Math.max(0, Math.min(1, typeof fp.fill_opacity === "number" ? fp.fill_opacity : 0.15));
      const nSpectra = rawItems.length;

      const figures: FitStackFigure["figures"] = [];
      for (let si = 0; si < rawItems.length; si++) {
        const it = rawItems[si]!;
        if (isStale()) return;
        setExplorePlotStatus(`Fitting: spectrum ${si + 1}/${nSpectra} (${it.spectrum_id.slice(0, 14)}…) — calling /fitting/fit`);
        let fitResp;
        try {
          fitResp = await postFittingFit(
            {
              target: { kind: "inline", x: it.x, y: it.y },
              components: compsApi.map((c) => ({
                component_id: c.component_id,
                component_type: c.component_type,
                degree: c.degree,
              })),
              p0,
              bounds: { lower: lo, upper: hi },
              return_curve: true,
              initial_guess_mode: fp.initial_guess_mode === "auto" ? "auto" : "default",
              technique_family: techniqueFamily,
              vary: Array.isArray(flat.vary) ? (flat.vary as boolean[]) : undefined,
              param_links: Array.isArray(flat.param_links)
                ? (flat.param_links as FitRequest["param_links"])
                : undefined,
              xps_region: typeof flat.xps_region === "string" ? flat.xps_region : undefined,
            },
            { signal }
          );
        } catch (e) {
          if (isAbortErr(e)) return;
          throw new Error(`Fitting failed for ${it.spectrum_id}: ${(e as Error)?.message ?? e}`);
        }
        const residual =
          fitResp.residual ??
          it.y.map((yv, i) => Number(yv) - Number(fitResp.y_hat?.[i] ?? 0));
        const built = buildFitResidualFigure({
          x: it.x,
          y: it.y,
          yHat: fitResp.y_hat ?? [],
          residual,
          components: fitResp.components ?? [],
          diagnostics: fitResp.diagnostics,
          title: it.spectrum_id,
          xAxisTitle,
          fillOpacity,
        });
        figures.push({ ...built, spectrum_id: it.spectrum_id });
      }

      setExplorePlotStatus(`Fitting preview: ${figures.length} spectra (stacked)`);
      commitFigure({ kind: "fit_stack", figures } satisfies FitStackFigure);
      return;
    }

    setExplorePlotStatus("Rendering plot…");
    const out = await runSession(sessionId, payload, { signal });
    if (isStale()) return;

    if ((payload.return as { kind?: string }).kind === "intermediates") {
      const stepName = afterStep ?? "";
      const items = ((out as SessionRunIntermediatesResponse).items ?? []).filter((it) =>
        hasPlottableXy(it.steps?.[stepName])
      );
      const traces = capTraceCount(items, subsetSize).map((it) => {
        const xy = it.steps?.[stepName];
        return { type: "scatter", mode: "lines", x: xy?.x ?? [], y: xy?.y ?? [], name: it.spectrum_id };
      });
      if (items.length === 0) {
        setExplorePlotStatus(
          after.name === "metadata_filter"
            ? "No spectra match this metadata filter on the active subset (non-matches are emptied on this branch)."
            : "No plottable spectra after this step."
        );
      }
      commitFigure({
        data: traces,
        layout: {
          xaxis: { title: { text: xAxisTitle } },
          yaxis: { title: { text: "Intensity (counts)" } },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      });
      return;
    }

    const finalItems = ((out as SessionRunFinalResponse).items ?? []).filter(hasPlottableXy);
    const traces = capTraceCount(finalItems, subsetSize).map((it) => ({
      type: "scatter",
      mode: "lines",
      x: it.x,
      y: it.y,
      name: it.spectrum_id,
    }));
    commitFigure({
      data: traces,
      layout: {
        xaxis: { title: { text: xAxisTitle } },
        yaxis: { title: { text: "Intensity (counts)" } },
        legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
        margin: { l: 60, r: 20, t: 20, b: 95 },
      },
    });
  } catch (e) {
    if (isAbortErr(e) || isStale()) return;
    setLastError(String((e as Error)?.message ?? e));
  } finally {
    // Only the latest run owns the status line (aborted/stale runs must not clear a newer run's status).
    if (seq === runSeq.current && explorePlotAbortRef.current === ac) {
      setExplorePlotStatus(null);
    }
  }
}
