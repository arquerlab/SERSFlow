import type { MutableRefObject } from "react";
import {
  postFittingFit,
  runPipeline,
  runSession,
  type FittingComponentSpecPublic,
  type Pipeline,
  type SessionRunFinalResponse,
  type SessionRunIntermediatesResponse,
  type SpectrumRef,
} from "./api";
import { flattenFittingForPipeline, migrateFittingParamsToEditor } from "./fittingUtils";
import { buildSafeRunRequest, capTraceCount, type Mode, type PlotView } from "./runController";
import type { EditorStep } from "./editorTypes";

const RAMAN_SHIFT_AXIS_TITLE = "Raman Shift (cm⁻¹)";

function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "").trim();
  if (h.length !== 6) return `rgba(128,128,128,${alpha})`;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

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
  } = deps;

  explorePlotAbortRef.current?.abort();
  const ac = new AbortController();
  explorePlotAbortRef.current = ac;
  const signal = ac.signal;

  const aborted = () => signal.aborted;
  const isAbortErr = (e: unknown) =>
    aborted() ||
    (e instanceof DOMException && e.name === "AbortError") ||
    (e as Error)?.name === "AbortError";

  try {
    setLastError(null);
    setExplorePlotStatus("Saving pipeline…");
    await ensurePipelineSaved();
    if (aborted()) return;
    if (!subsetIndices.length) {
      throw new Error("No active subset. Create or apply a saved subset to start plotting.");
    }

    const afterToken = plotView.startsWith("after:") ? plotView.slice("after:".length) : null;
    const parseAfterToken = (t: string | null): { name: string | null; stepNum: number | null } => {
      if (!t) return { name: null, stepNum: null };
      const m = String(t).match(/^([A-Za-z0-9_]+)(?:__(\d+))?$/);
      if (!m) return { name: String(t), stepNum: null };
      return { name: m[1] || null, stepNum: m[2] ? Number(m[2]) : null };
    };
    const after = parseAfterToken(afterToken);
    const afterStep = afterToken; // keep full token for intermediates lookup and request
    const payload = buildSafeRunRequest({
      mode,
      subsetCount: subsetIndices.length || subsetSize,
      plotView,
      upToStep: null,
      collectSteps: afterStep ? [afterStep] : [],
      batchMetrics: ["peak_height", "fwhm"],
    });

    const seq = ++runSeq.current;

    if (plotView === "raw") {
      setExplorePlotStatus("Loading subset spectra…");
      const inputs = subsetInputsFromIndices(subsetIndices);
      const out = await runPipeline(
        {
          inputs,
          pipeline: { steps: [] },
          return: { kind: "final" },
          cache_namespace: sessionId,
        },
        { signal }
      );
      if (seq !== runSeq.current) return;
      const traces = capTraceCount(out.items ?? [], subsetSize).map((it) => ({
        type: "scatter",
        mode: "lines",
        x: it.x,
        y: it.y,
        name: it.spectrum_id,
      }));
      setPreviousFigure(currentFigure);
      setCurrentFigure({
        data: traces,
        layout: {
          xaxis: { title: { text: RAMAN_SHIFT_AXIS_TITLE } },
          yaxis: { title: { text: "Intensity (counts)" } },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      });
      return;
    }

    if (after.name === "baseline") {
      setExplorePlotStatus("Baseline preview: running pipeline…");
      let baselineIdx =
        typeof after.stepNum === "number" && after.stepNum > 0 ? Math.min(steps.length - 1, after.stepNum - 1) : -1;
      if (!(baselineIdx >= 0 && steps[baselineIdx]?.enabled !== false && steps[baselineIdx]?.name === "baseline")) {
        baselineIdx = steps.findIndex((s) => s.enabled !== false && s.name === "baseline");
      }
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

      const inputs = subsetInputsFromIndices(subsetIndices);

      const slice = steps.slice(0, prevEnabledIdx >= 0 ? prevEnabledIdx + 1 : 0);
      const pipelineToInput: Pipeline = { steps: editorStepsToApiSteps(slice) };

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
      };

      const [rawIn, baseOut] = await Promise.all([
        runPipeline({ inputs, pipeline: pipelineToInput, return: { kind: "final" }, cache_namespace: sessionId }, { signal }),
        runPipeline({ inputs, pipeline: pipelineToBaselineCurve, return: { kind: "final" }, cache_namespace: sessionId }, { signal }),
      ]);
      if (seq !== runSeq.current) return;

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

      setPreviousFigure(currentFigure);
      setCurrentFigure({
        data: traces,
        layout: {
          xaxis: { title: { text: RAMAN_SHIFT_AXIS_TITLE } },
          yaxis: { title: { text: "Intensity (counts)" } },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      });
      return;
    }

    if (after.name === "fitting") {
      setExplorePlotStatus("Fitting: computing pipeline input…");
      let fittingIdx =
        typeof after.stepNum === "number" && after.stepNum > 0 ? Math.min(steps.length - 1, after.stepNum - 1) : -1;
      if (!(fittingIdx >= 0 && steps[fittingIdx]?.enabled !== false && steps[fittingIdx]?.name === "fitting")) {
        fittingIdx = steps.findIndex((s) => s.enabled !== false && s.name === "fitting");
      }
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

      const inputs = subsetInputsFromIndices(subsetIndices);
      const slice = steps.slice(0, prevEnabledIdx >= 0 ? prevEnabledIdx + 1 : 0);
      const pipelineToInput: Pipeline = { steps: editorStepsToApiSteps(slice) };

      const rawIn = await runPipeline(
        {
          inputs,
          pipeline: pipelineToInput,
          return: { kind: "final" },
          cache_namespace: sessionId,
        },
        { signal }
      );
      if (seq !== runSeq.current) return;

      const rawItems = capTraceCount(rawIn.items ?? [], subsetSize);
      const fillOpacity = Math.max(0, Math.min(1, typeof fp.fill_opacity === "number" ? fp.fill_opacity : 0.15));
      const fitColors = ["#e74c3c", "#3498db", "#2ecc71", "#9b59b6", "#f39c12", "#1abc9c"];
      const nSpectra = rawItems.length;

      const traces: Record<string, unknown>[] = [];
      for (let si = 0; si < rawItems.length; si++) {
        const it = rawItems[si]!;
        if (aborted()) return;
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
            },
            { signal }
          );
        } catch (e) {
          if (isAbortErr(e)) return;
          throw new Error(`Fitting failed for ${it.spectrum_id}: ${(e as Error)?.message ?? e}`);
        }
        traces.push({
          type: "scatter",
          mode: "lines",
          x: it.x,
          y: it.y,
          name: `${it.spectrum_id}`,
          line: { color: "#333" },
        });
        traces.push({
          type: "scatter",
          mode: "lines",
          x: it.x,
          y: fitResp.y_hat ?? [],
          line: { color: "rgba(231,76,60,0.95)", width: 2 },
          name: `${it.spectrum_id} fit (sum)`,
        });
        (fitResp.components ?? []).forEach((comp, j) => {
          if (!comp.y_hat?.length) return;
          const isGaussian = comp.component_type === "gaussian";
          traces.push({
            type: "scatter",
            mode: "lines",
            x: it.x,
            y: comp.y_hat,
            name: `${it.spectrum_id} ${comp.component_type} [${comp.component_id}]`,
            line: { color: fitColors[j % fitColors.length], dash: isGaussian ? "solid" : "dot" },
            ...(isGaussian
              ? {
                  fill: "tozeroy",
                  fillcolor: hexToRgba(fitColors[j % fitColors.length] ?? "#888888", fillOpacity),
                }
              : {}),
          });
        });
      }

      setExplorePlotStatus("Fitting: building plot…");
      setPreviousFigure(currentFigure);
      setCurrentFigure({
        data: traces,
        layout: {
          xaxis: { title: { text: RAMAN_SHIFT_AXIS_TITLE } },
          yaxis: { title: { text: "Intensity (counts)" } },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      });
      return;
    }

    setExplorePlotStatus("Rendering plot…");
    const out = await runSession(sessionId, payload, { signal });
    if (seq !== runSeq.current) return;

    if ((payload.return as { kind?: string }).kind === "intermediates") {
      const stepName = afterStep ?? "";
      const items = (out as SessionRunIntermediatesResponse).items ?? [];
      const traces = capTraceCount(items, subsetSize).map((it) => {
        const xy = it.steps?.[stepName];
        return { type: "scatter", mode: "lines", x: xy?.x ?? [], y: xy?.y ?? [], name: it.spectrum_id };
      });
      setPreviousFigure(currentFigure);
      setCurrentFigure({
        data: traces,
        layout: {
          xaxis: { title: { text: RAMAN_SHIFT_AXIS_TITLE } },
          yaxis: { title: { text: "Intensity (counts)" } },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      });
      return;
    }

    const items = (out as SessionRunFinalResponse).items ?? [];
    const traces = capTraceCount(items, subsetSize).map((it) => ({
      type: "scatter",
      mode: "lines",
      x: it.x,
      y: it.y,
      name: it.spectrum_id,
    }));
    setPreviousFigure(currentFigure);
    setCurrentFigure({
      data: traces,
      layout: {
        xaxis: { title: { text: RAMAN_SHIFT_AXIS_TITLE } },
        yaxis: { title: { text: "Intensity (counts)" } },
        legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
        margin: { l: 60, r: 20, t: 20, b: 95 },
      },
    });
  } catch (e) {
    if (isAbortErr(e)) return;
    setLastError(String((e as Error)?.message ?? e));
  } finally {
    setExplorePlotStatus(null);
  }
}
