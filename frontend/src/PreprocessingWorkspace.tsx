import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PlotlyWrapper } from "./legacy-wrappers/PlotlyWrapper";
import { SpectrumCheckboxListWrapper } from "./legacy-wrappers/SpectrumCheckboxListWrapper";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearAllDatasets,
  createDatasetFromUploads,
  createPipelineLibraryEntry,
  createSession,
  getDataset,
  getPipelineLibraryEntry,
  listDatasets,
  listPipelines,
  runPipeline,
  runSession,
  updateSessionPipeline,
  updateSessionSubset,
  type Pipeline,
  type SessionRunFinalResponse,
  type SessionRunIntermediatesResponse,
  type SessionRunMetricsResponse,
  type SpectrumRef,
} from "./preprocess/api";
import { buildSafeRunRequest, capTraceCount, DEFAULT_GUARDRAILS, type Mode, type PlotView } from "./preprocess/runController";
import { addSavedSubset, clearSavedSubsets, deleteSavedSubset, loadSavedSubsets, type SavedSubset } from "./preprocess/subsets";

function datasetOptionLabel(d: { dataset_id: string; count: number; metadata?: { name?: string | null } }) {
  const n = d.metadata?.name?.trim();
  if (n) return `${n} (${d.dataset_id}) — ${d.count}`;
  return `${d.dataset_id} (${d.count})`;
}

export default function PreprocessingWorkspace() {
  const queryClient = useQueryClient();
  const [selectedUploads, setSelectedUploads] = useState<string[]>([]);
  const [newDatasetName, setNewDatasetName] = useState("");
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("explore");

  // subset (explore)
  const [subsetMode] = useState<"random">("random");
  const [subsetSize, setSubsetSize] = useState(15);
  const [subsetSeed, setSubsetSeed] = useState(1337);
  const [subsetLocked, setSubsetLocked] = useState(false);
  const [subsetIndices, setSubsetIndices] = useState<number[]>([]);
  const [subsetSource, setSubsetSource] = useState<string>("—");
  const [savedSubsets, setSavedSubsets] = useState<SavedSubset[]>([]);
  const [activeSubsetId, setActiveSubsetId] = useState<string | null>(null);

  // pipeline
  const [steps, setSteps] = useState<
    { id: string; name: string; enabled: boolean; params: Record<string, any> }[]
  >([]);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [pipelineVersion, setPipelineVersion] = useState(0);
  const [lastSavedPipelineVersion, setLastSavedPipelineVersion] = useState(0);

  // view
  const [plotView, setPlotView] = useState<PlotView>("final");
  const [ghost, setGhost] = useState(true);
  const [plotMode, setPlotMode] = useState<"overlay" | "stack">("overlay");
  const [sep, setSep] = useState(1000);
  const [autoRun, setAutoRun] = useState(true);

  // results
  const [currentFigure, setCurrentFigure] = useState<any | null>(null);
  const [previousFigure, setPreviousFigure] = useState<any | null>(null);
  const [currentMetrics, setCurrentMetrics] = useState<SessionRunMetricsResponse | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const runSeq = useRef(0);

  const [libraryPipelineName, setLibraryPipelineName] = useState("");
  const [selectedLibraryPipelineId, setSelectedLibraryPipelineId] = useState("");

  const datasetsQ = useQuery({
    queryKey: ["datasets", { limit: 200, offset: 0 }],
    queryFn: () => listDatasets(200, 0),
  });

  const pipelinesLibraryQ = useQuery({
    queryKey: ["pipelines", { limit: 200, offset: 0 }],
    queryFn: () => listPipelines(200, 0),
  });

  const clearDatasetsM = useMutation({
    mutationFn: async () => clearAllDatasets(),
    onSuccess: () => {
      setDatasetId(null);
      setSessionId(null);
      setSubsetIndices([]);
      setSubsetSource("—");
      setActiveSubsetId(null);
      datasetsQ.refetch();
    },
  });

  const datasetQ = useQuery({
    queryKey: ["dataset", datasetId],
    enabled: !!datasetId,
    queryFn: () => getDataset(String(datasetId)),
  });

  const createFromUploadsM = useMutation({
    mutationFn: async (args: { paths: string[]; name?: string | null }) =>
      createDatasetFromUploads(args.paths, args.name?.trim() ? { name: args.name.trim() } : undefined),
    onSuccess: async (data) => {
      const nextDatasetId = data?.dataset?.dataset_id;
      if (!nextDatasetId) return;
      setNewDatasetName("");
      setDatasetId(nextDatasetId);
      // Create a session (subsets are explicit; user creates/applies subset next).
      const s = await createSession(nextDatasetId, { kind: "random", n: subsetSize, seed: subsetSeed }, { steps: [] });
      const sid = s?.session?.session_id ?? null;
      setSessionId(sid);
      setSteps([]);
      setSelectedStepId(null);
      setPipelineVersion(0);
      setLastSavedPipelineVersion(0);
      setSubsetLocked(false);
      setSubsetIndices([]);
      setSubsetSource("—");
      setActiveSubsetId(null);
      datasetsQ.refetch();
    },
  });

  const createSessionM = useMutation({
    mutationFn: async (nextDatasetId: string) => createSession(nextDatasetId, { kind: "random", n: subsetSize, seed: subsetSeed }, { steps: [] }),
    onSuccess: (data) => {
      const sid = data?.session?.session_id ?? null;
      setSessionId(sid);
      setSubsetIndices([]);
      setSubsetSource("—");
      setActiveSubsetId(null);
    },
  });

  const selectedStep = steps.find((s) => s.id === selectedStepId) ?? null;

  const METHOD_STEP_SPECS: Record<
    string,
    {
      methodLabel: string;
      methods: { id: string; label: string; defaults: Record<string, any>; fields: FieldSpec[] }[];
      // Fields that are always shown (in addition to method-specific).
      commonFields?: FieldSpec[];
    }
  > = {
    cosmic_ray_removal: {
      methodLabel: "method",
      methods: [
        { id: "zscore", label: "zscore", defaults: { threshold: 5.0, window: 5, interpolation: "median", max_width: 10, min_intensity_ratio: 2.0, n_iterations: 3 }, fields: [] },
        { id: "derivative", label: "derivative", defaults: { threshold: 3.0, window: 3, interpolation: "median", max_width: 10, min_intensity_ratio: 2.0, n_iterations: 3 }, fields: [] },
      ],
      commonFields: [
        { key: "threshold", kind: "number", label: "threshold" },
        { key: "window", kind: "int", label: "window" },
        { key: "interpolation", kind: "select", label: "interpolation", options: ["median", "linear", "cubic"] },
        { key: "max_width", kind: "int", label: "max_width" },
        { key: "min_intensity_ratio", kind: "number", label: "min_intensity_ratio" },
        { key: "n_iterations", kind: "int", label: "n_iterations" },
      ],
    },
    baseline: {
      methodLabel: "method",
      methods: [
        { id: "derpsalsa", label: "derpsalsa", defaults: { lam: 3e5, p: 0.001 }, fields: [{ key: "lam", kind: "number", label: "lam" }, { key: "p", kind: "number", label: "p" }] },
        { id: "asls", label: "asls", defaults: { lam: 1e6, p: 0.01 }, fields: [{ key: "lam", kind: "number", label: "lam" }, { key: "p", kind: "number", label: "p" }] },
        { id: "arpls", label: "arpls", defaults: { lam: 1e5 }, fields: [{ key: "lam", kind: "number", label: "lam" }] },
        { id: "mor", label: "mor", defaults: { half_window: 30 }, fields: [{ key: "half_window", kind: "int", label: "half_window" }] },
        { id: "mormol", label: "mormol", defaults: { half_window: 30 }, fields: [{ key: "half_window", kind: "int", label: "half_window" }] },
        { id: "snip", label: "snip", defaults: { max_half_window: 40 }, fields: [{ key: "max_half_window", kind: "int", label: "max_half_window" }] },
      ],
    },
    normalize: {
      methodLabel: "method",
      methods: [
        { id: "max", label: "max", defaults: {}, fields: [] },
        { id: "min", label: "min", defaults: {}, fields: [] },
        { id: "mean", label: "mean", defaults: {}, fields: [] },
        { id: "median", label: "median", defaults: {}, fields: [] },
        { id: "baseline", label: "baseline_point", defaults: { baseline_point: 1000 }, fields: [{ key: "baseline_point", kind: "number", label: "baseline_point" }] },
      ],
    },
  };

  type FieldSpec =
    | { key: string; kind: "number" | "int"; label: string }
    | { key: string; kind: "select"; label: string; options: string[] };

  function setSelectedStepParams(nextParams: Record<string, any>) {
    if (!selectedStep) return;
    setSteps((prev) => prev.map((p) => (p.id === selectedStep.id ? { ...p, params: nextParams } : p)));
    setPipelineVersion((vv) => vv + 1);
  }

  function updateSelectedStepParam(key: string, value: any) {
    if (!selectedStep) return;
    setSteps((prev) => prev.map((p) => (p.id === selectedStep.id ? { ...p, params: { ...(p.params ?? {}), [key]: value } } : p)));
    setPipelineVersion((vv) => vv + 1);
  }

  function normalizeMethodParams(stepName: string, params: Record<string, any> | null | undefined): Record<string, any> {
    const spec = METHOD_STEP_SPECS[stepName];
    if (!spec) return params ?? {};
    const p = { ...(params ?? {}) };
    const method = String(p.method || spec.methods[0]?.id || "");
    const def = spec.methods.find((m) => m.id === method) ?? spec.methods[0];
    if (!def) return p;
    // Ensure method exists and required defaults are present.
    return { method: def.id, ...def.defaults, ...Object.fromEntries(Object.entries(p).filter(([k]) => k !== "method")) };
  }

  const buildPipeline = useCallback((): Pipeline => {
    return {
      steps: steps.map((s) => ({
        name: s.name,
        params: normalizeMethodParams(s.name, s.params),
        enabled: s.enabled !== false,
      })),
    };
  }, [steps]);

  // Load saved subsets when dataset changes.
  useEffect(() => {
    if (!datasetId) {
      setSavedSubsets([]);
      return;
    }
    setSavedSubsets(loadSavedSubsets(datasetId));
  }, [datasetId]);

  async function createRandomSubset({ labelPrefix }: { labelPrefix: string }) {
    if (!sessionId || !datasetId) return;
    if (subsetLocked) return;
    const seed = Date.now() % 1_000_000_000;
    setSubsetSeed(seed);
    const resp = await updateSessionSubset(sessionId, { kind: "random", n: subsetSize, seed });
    const indices = resp?.resolved?.dataset_indices ?? [];
    setSubsetIndices(indices);
    const createdAt = Date.now();
    const subset: SavedSubset = {
      id: crypto.randomUUID(),
      label: `${labelPrefix} (${subsetSize})`,
      indices,
      size: subsetSize,
      seed,
      createdAt,
    };
    const next = addSavedSubset(datasetId, subset, 15);
    setSavedSubsets(next);
    setActiveSubsetId(subset.id);
    setSubsetSource(subset.label);
  }

  async function applySavedSubset(s: SavedSubset) {
    if (!sessionId) return;
    await updateSessionSubset(sessionId, { kind: "indices", indices: s.indices });
    setSubsetIndices(s.indices);
    setActiveSubsetId(s.id);
    setSubsetSource(s.label);
  }

  const savePipelineM = useMutation({
    mutationFn: async (pipeline: Pipeline) => {
      if (!sessionId) throw new Error("No session");
      return await updateSessionPipeline(sessionId, pipeline);
    },
    onSuccess: () => setLastSavedPipelineVersion(pipelineVersion),
  });

  const savePipelineLibraryM = useMutation({
    mutationFn: async () => {
      const name = libraryPipelineName.trim();
      if (!name) throw new Error("Enter a pipeline name");
      return createPipelineLibraryEntry(name, buildPipeline());
    },
    onSuccess: () => {
      setLastError(null);
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
    onError: (e: any) => setLastError(String(e?.message ?? e)),
  });

  async function applyLibraryPipeline() {
    if (!sessionId || !selectedLibraryPipelineId) return;
    setLastError(null);
    try {
      const { item } = await getPipelineLibraryEntry(selectedLibraryPipelineId);
      const next = item.pipeline.steps.map((st) => ({
        id: crypto.randomUUID(),
        name: st.name,
        enabled: st.enabled !== false,
        params: { ...((st.params as Record<string, any>) ?? {}) },
      }));
      setSteps(next);
      setSelectedStepId(null);
      setPipelineVersion((v) => v + 1);
    } catch (e: any) {
      setLastError(String(e?.message ?? e));
    }
  }

  async function ensurePipelineSaved() {
    if (!sessionId) return;
    if (pipelineVersion === lastSavedPipelineVersion) return;
    await savePipelineM.mutateAsync(buildPipeline());
  }

  function subsetInputsFromIndices(indices: number[]): SpectrumRef[] {
    const spectra = datasetQ.data?.dataset?.spectra ?? [];
    return indices
      .map((i) => spectra[i])
      .filter(Boolean)
      .slice(0, DEFAULT_GUARDRAILS.maxPlotSpectraHardCap);
  }

  async function runExplorePlot() {
    if (!sessionId) return;
    setLastError(null);
    await ensurePipelineSaved();
    if (!subsetIndices.length) {
      throw new Error("No active subset. Create or apply a saved subset to start plotting.");
    }

    const afterStep = plotView.startsWith("after:") ? plotView.slice("after:".length) : null;
    const payload = buildSafeRunRequest({
      mode,
      subsetCount: subsetIndices.length || subsetSize,
      plotView,
      upToStep: null,
      collectSteps: afterStep ? [afterStep] : [],
      batchMetrics: ["peak_height", "fwhm"],
    });

    const seq = ++runSeq.current;

    // Raw view uses /pipeline/run with empty pipeline (subset only), so we don't mutate the session pipeline.
    if (plotView === "raw") {
      const inputs = subsetInputsFromIndices(subsetIndices);
      const out = await runPipeline({
        inputs,
        pipeline: { steps: [] },
        return: { kind: "final" },
        cache_namespace: sessionId,
      });
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
          xaxis: { title: { text: "Raman Shift (cm$^{-1}$)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
          yaxis: { title: { text: "Intensity (counts)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      });
      return;
    }

    // Baseline inspection: overlay baseline curve on the uncorrected input to baseline.
    // We do this with /pipeline/run (no session mutation) by:
    // - Running the pipeline up to the step immediately before baseline (uncorrected input)
    // - Running the same, plus `baseline_curve` (estimated baseline)
    if (afterStep === "baseline") {
      const baselineIdx = steps.findIndex((s) => s.enabled !== false && s.name === "baseline");
      const baselineParams = baselineIdx >= 0 ? (steps[baselineIdx]?.params ?? {}) : {};

      // Find the last enabled step before baseline in the user-defined pipeline order.
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

      const pipelineToInput: Pipeline = {
        steps: steps
          .slice(0, prevEnabledIdx >= 0 ? prevEnabledIdx + 1 : 0)
          .map((s) => ({ name: s.name, params: s.params ?? {}, enabled: s.enabled !== false })),
      };

      const pipelineToBaselineCurve: Pipeline = {
        steps: [
          ...pipelineToInput.steps,
          { name: "baseline_curve", params: baselineParams, enabled: true },
        ],
      };

      const [rawIn, baseOut] = await Promise.all([
        runPipeline({ inputs, pipeline: pipelineToInput, return: { kind: "final" }, cache_namespace: sessionId }),
        runPipeline({ inputs, pipeline: pipelineToBaselineCurve, return: { kind: "final" }, cache_namespace: sessionId }),
      ]);
      if (seq !== runSeq.current) return;

      const rawItems = capTraceCount(rawIn.items ?? [], subsetSize);
      const baseById = new Map((baseOut.items ?? []).map((it) => [it.spectrum_id, it] as const));

      const traces = rawItems.flatMap((it) => {
        const base = baseById.get(it.spectrum_id);
        const out = [{ type: "scatter", mode: "lines", x: it.x, y: it.y, name: `${it.spectrum_id}` }] as any[];
        if (base) {
          out.push({ type: "scatter", mode: "lines", x: base.x, y: base.y, name: `${it.spectrum_id} baseline` });
        }
        return out;
      });

      setPreviousFigure(currentFigure);
      setCurrentFigure({
        data: traces,
        layout: {
          xaxis: { title: { text: "Raman Shift (cm$^{-1}$)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
          yaxis: { title: { text: "Intensity (counts)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      });
      return;
    }

    const out = await runSession(sessionId, payload);
    if (seq !== runSeq.current) return;

    if ((payload.return as any).kind === "intermediates") {
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
          xaxis: { title: { text: "Raman Shift (cm$^{-1}$)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
          yaxis: { title: { text: "Intensity (counts)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
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
        xaxis: { title: { text: "Raman Shift (cm$^{-1}$)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
        yaxis: { title: { text: "Intensity (counts)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
        legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
        margin: { l: 60, r: 20, t: 20, b: 95 },
      },
    });
  }

  const runMetricsM = useMutation({
    mutationFn: async (scope: "subset" | "all") => {
      if (!sessionId) throw new Error("No session");
      await ensurePipelineSaved();
      return (await runSession(sessionId, { scope, return: { kind: "metrics_only", metrics: ["peak_height", "fwhm"] }, up_to_step: null })) as SessionRunMetricsResponse;
    },
    onSuccess: (data) => {
      setCurrentMetrics(data);
    },
    onError: (e: any) => setLastError(String(e?.message ?? e)),
  });

  // Auto-run in Explore when pipeline changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const fig = useMemo(() => currentFigure, [currentFigure]);

  // Debounced auto-run (Explore only). This is a side-effect; useEffect is required.
  useEffect(() => {
    if (!autoRun) return;
    if (mode !== "explore") return;
    if (!sessionId) return;
    if (!subsetIndices.length) return;
    const t = setTimeout(() => {
      runExplorePlot().catch((e) => setLastError(String(e?.message ?? e)));
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, mode, sessionId, pipelineVersion, plotView, subsetIndices.join(",")]);

  function addStepTemplate(name: string) {
    const templates: Record<string, any> = {
      noise_savgol: { name: "noise_savgol", enabled: true, params: { window_length: 11, polyorder: 3 } },
      cosmic_ray_removal: {
        name: "cosmic_ray_removal",
        enabled: true,
        params: { method: "zscore", threshold: 5.0, window: 5, interpolation: "median", max_width: 10, min_intensity_ratio: 2.0, n_iterations: 3 },
      },
      baseline: { name: "baseline", enabled: true, params: { method: "derpsalsa", lam: 3e5, p: 0.001 } },
      crop: { name: "crop", enabled: true, params: { min_x: 400, max_x: 2000 } },
      // Backend supports: max/min/mean/median/baseline_point (see METHOD_STEP_SPECS).
      normalize: { name: "normalize", enabled: true, params: { method: "max" } },
    };
    const t = templates[name] ?? { name, enabled: true, params: {} };
    const id = crypto.randomUUID();
    setSteps((prev) => [...prev, { id, name: t.name, enabled: t.enabled, params: t.params }]);
    setSelectedStepId(id);
    setPipelineVersion((v) => v + 1);
  }

  return (
    <div className="preprocess-grid">
      <div className="preprocess-top card">
        <div className="section-title">Workspace</div>
        <div className="row">
          <label className="inline">
            Dataset
            <select
              value={datasetId ?? ""}
              onChange={(e) => {
                const v = String(e.target.value || "");
                setDatasetId(v || null);
                setSessionId(null);
                if (v) createSessionM.mutate(v);
              }}
            >
              <option value="">{datasetsQ.isLoading ? "Loading…" : "Select…"}</option>
              {(datasetsQ.data?.items ?? []).map((d) => (
                <option key={d.dataset_id} value={d.dataset_id}>
                  {datasetOptionLabel(d)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="danger"
            onClick={() => clearDatasetsM.mutate()}
            disabled={clearDatasetsM.isPending}
            title="Deletes all datasets and sessions from the backend DB"
          >
            {clearDatasetsM.isPending ? "Clearing datasets…" : "Clear datasets"}
          </button>
          <div className="hint" style={{ marginLeft: "8px" }}>
            Session: {sessionId ?? "—"}
          </div>
          <div className="hint" style={{ marginLeft: "8px" }}>
            Subset: {subsetSource} | Seed: {subsetSeed} {subsetLocked ? "| Locked" : ""}
          </div>
          <label className="inline">
            Mode
            <select value={mode} onChange={(e) => setMode(String(e.target.value) === "batch" ? "batch" : "explore")}>
              <option value="explore">Explore</option>
              <option value="batch">Batch</option>
            </select>
          </label>
          <label className="inline">
            Plot mode
            <select value={plotMode} onChange={(e) => setPlotMode(e.target.value as any)}>
              <option value="overlay">Overlay</option>
              <option value="stack">Stack</option>
            </select>
          </label>
          <label className="inline">
            Stack separation
            <input type="number" value={sep} onChange={(e) => setSep(Number(e.target.value || 0))} />
          </label>
          <label className="inline">
            <input type="checkbox" checked={ghost} onChange={(e) => setGhost(e.target.checked)} />
            Ghost overlay
          </label>
          <label className="inline">
            <input type="checkbox" checked={autoRun} onChange={(e) => setAutoRun(e.target.checked)} disabled={mode !== "explore"} />
            Auto-run
          </label>
          <button
            type="button"
            onClick={() => {
              if (mode === "batch") runMetricsM.mutate("all");
              else runExplorePlot().catch((e) => setLastError(String(e?.message ?? e)));
            }}
            disabled={!sessionId || runMetricsM.isPending || savePipelineM.isPending}
          >
            {mode === "batch" ? (runMetricsM.isPending ? "Running batch…" : "Run (batch metrics)") : "Run (subset plot)"}
          </button>
          {mode === "explore" ? (
            <button
              type="button"
              onClick={() => createRandomSubset({ labelPrefix: "Random" })}
              disabled={!sessionId || !datasetId || subsetLocked}
            >
              Create subset
            </button>
          ) : null}
          {mode === "explore" ? (
            <button
              type="button"
              onClick={() => createRandomSubset({ labelPrefix: "Random" })}
              disabled={!sessionId || !datasetId || subsetLocked}
            >
              Resample
            </button>
          ) : null}
          {mode === "explore" ? (
            <button type="button" onClick={() => setSubsetLocked((x) => !x)} className={subsetLocked ? "danger" : ""}>
              {subsetLocked ? "Unlock subset" : "Lock subset"}
            </button>
          ) : null}
        </div>
        {lastError ? (
          <div className="err" style={{ marginTop: "10px" }}>
            {lastError}
          </div>
        ) : null}
      </div>

      <div className="preprocess-left card">
        <div className="section-title">Uploads → Dataset</div>
        <SpectrumCheckboxListWrapper onSelectionChange={setSelectedUploads} />
        <div className="hint">Selected uploads: {selectedUploads.length}</div>
        <label className="inline" style={{ marginTop: "8px", display: "flex", width: "100%", maxWidth: "420px" }}>
          Dataset name (optional)
          <input
            type="text"
            value={newDatasetName}
            onChange={(e) => setNewDatasetName(e.target.value)}
            placeholder="Leave empty for auto id only"
            style={{ flex: 1, minWidth: "120px" }}
          />
        </label>
        <div className="row" style={{ marginTop: "10px" }}>
          <button
            type="button"
            onClick={() => createFromUploadsM.mutate({ paths: selectedUploads, name: newDatasetName.trim() || null })}
            disabled={selectedUploads.length === 0 || createFromUploadsM.isPending}
          >
            {createFromUploadsM.isPending ? "Creating…" : "Create dataset from selected"}
          </button>
        </div>
        {datasetId && datasetQ.data?.dataset ? (
          <div className="hint" style={{ marginTop: "8px" }}>
            Dataset spectra: {datasetQ.data.dataset.spectra?.length ?? 0}
          </div>
        ) : null}

        <div className="section-title" style={{ marginTop: "12px" }}>
          Subsets
        </div>
        <div className="row" style={{ marginBottom: "8px" }}>
          <button
            type="button"
            className="mini danger"
            onClick={() => {
              if (!datasetId) return;
              clearSavedSubsets(datasetId);
              setSavedSubsets([]);
              setActiveSubsetId(null);
              setSubsetIndices([]);
              setSubsetSource("—");
            }}
            disabled={!datasetId || savedSubsets.length === 0}
          >
            Clear all subsets
          </button>
        </div>
        <div style={{ display: "grid", gap: "6px" }}>
          {savedSubsets.length ? (
            savedSubsets
              .slice()
              .sort((a, b) => b.createdAt - a.createdAt)
              .map((s) => (
                <div key={s.id} className="card-inner" style={{ display: "grid", gap: "6px" }}>
                  <div className="row" style={{ justifyContent: "space-between" }}>
                    <button
                      type="button"
                      className="mini"
                      onClick={() => applySavedSubset(s)}
                      style={{ fontWeight: s.id === activeSubsetId ? 900 : 700 }}
                      disabled={!sessionId}
                    >
                      {s.label}
                    </button>
                    <button
                      type="button"
                      className="mini danger"
                      onClick={() => {
                        if (!datasetId) return;
                        const next = deleteSavedSubset(datasetId, s.id);
                        setSavedSubsets(next);
                        if (activeSubsetId === s.id) {
                          setActiveSubsetId(null);
                          setSubsetSource("—");
                          setSubsetIndices([]);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </div>
                  <div className="hint">
                    size={s.size} seed={s.seed ?? "—"}
                  </div>
                </div>
              ))
          ) : (
            <div className="hint">No saved subsets yet. Create one to start plotting.</div>
          )}
        </div>
      </div>

      <div className="preprocess-center card">
        <div className="section-title">Plot</div>
        <div className="row" style={{ marginBottom: "10px" }}>
          <label className="inline">
            View
            <select
              value={plotView}
              onChange={(e) => setPlotView(String(e.target.value) as PlotView)}
              disabled={mode === "batch"}
              title={mode === "batch" ? "Batch mode never requests intermediates; plot uses subset preview only." : undefined}
            >
              <option value="raw">Raw (subset)</option>
              <option value="final">Final</option>
              {/* Intermediate views are keyed by step name on the backend; duplicate step types share one "After:" slot (last wins). */}
              {steps.map((s) => (
                <option key={s.id} value={`after:${s.name}` as any}>
                  After: {s.name}
                </option>
              ))}
            </select>
          </label>
          {mode === "explore" ? (
            <label className="inline">
              Subset size
              <input
                type="number"
                min={1}
                max={30}
                value={subsetSize}
                onChange={(e) => setSubsetSize(Number(e.target.value || 1))}
                disabled={subsetMode !== "random" || subsetLocked}
              />
            </label>
          ) : null}
        </div>
        <PlotlyWrapper
          figure={fig}
          previousFigure={previousFigure}
          plotStyle={{ mode: plotMode, stackSep: sep }}
          ghostOverlayEnabled={ghost}
          className="plot"
        />
      </div>

      <div className="preprocess-bottom card">
        <div className="section-title">Pipeline</div>
        <div className="row">
          <button type="button" className="mini" onClick={() => addStepTemplate("noise_savgol")}>
            + noise
          </button>
          <button type="button" className="mini" onClick={() => addStepTemplate("cosmic_ray_removal")}>
            + cosmic
          </button>
          <button type="button" className="mini" onClick={() => addStepTemplate("baseline")}>
            + baseline
          </button>
          <button type="button" className="mini" onClick={() => addStepTemplate("crop")}>
            + crop
          </button>
          <button type="button" className="mini" onClick={() => addStepTemplate("normalize")}>
            + norm
          </button>
          <button type="button" onClick={() => savePipelineM.mutate(buildPipeline())} disabled={!sessionId || savePipelineM.isPending}>
            {savePipelineM.isPending ? "Saving…" : "Save pipeline"}
          </button>
        </div>

        <div className="section-title" style={{ marginTop: "14px" }}>
          Pipeline library
        </div>
        <div className="row" style={{ alignItems: "center", flexWrap: "wrap" }}>
          <label className="inline">
            Name
            <input
              type="text"
              value={libraryPipelineName}
              onChange={(e) => setLibraryPipelineName(e.target.value)}
              placeholder="e.g. Cu300 default"
              style={{ width: "180px" }}
            />
          </label>
          <button
            type="button"
            onClick={() => savePipelineLibraryM.mutate()}
            disabled={!libraryPipelineName.trim() || savePipelineLibraryM.isPending}
          >
            {savePipelineLibraryM.isPending ? "Saving…" : "Save to library"}
          </button>
          <label className="inline">
            Saved
            <select
              value={selectedLibraryPipelineId}
              onChange={(e) => setSelectedLibraryPipelineId(e.target.value)}
              style={{ minWidth: "200px" }}
            >
              <option value="">{pipelinesLibraryQ.isLoading ? "Loading…" : "Select saved pipeline…"}</option>
              {(pipelinesLibraryQ.data?.items ?? []).map((it) => (
                <option key={it.pipeline_id} value={it.pipeline_id}>
                  {it.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={() => applyLibraryPipeline()} disabled={!sessionId || !selectedLibraryPipelineId}>
            Apply
          </button>
          <button
            type="button"
            className="mini"
            onClick={() => pipelinesLibraryQ.refetch()}
            disabled={pipelinesLibraryQ.isFetching}
          >
            Refresh list
          </button>
        </div>
        <div className="hint" style={{ marginTop: "6px" }}>
          Save stores the current step list globally. Apply loads it into this session (then auto-save / run as usual). Duplicate names return an error.
        </div>

        <div style={{ marginTop: "10px", display: "grid", gap: "8px" }}>
          {steps.map((st, idx) => (
            <div key={st.id} className="card-inner" style={{ display: "grid", gap: "8px" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <button type="button" className="mini" onClick={() => setSelectedStepId(st.id)} style={{ fontWeight: st.id === selectedStepId ? 900 : 700 }}>
                  {idx + 1}. {st.name}
                </button>
                <div className="row" style={{ gap: "6px" }}>
                  <button
                    type="button"
                    className="mini"
                    onClick={() => {
                      setSteps((prev) => {
                        const i = prev.findIndex((p) => p.id === st.id);
                        if (i <= 0) return prev;
                        const next = prev.slice();
                        const [it] = next.splice(i, 1);
                        next.splice(i - 1, 0, it);
                        return next;
                      });
                      setPipelineVersion((v) => v + 1);
                    }}
                    disabled={idx === 0}
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="mini"
                    onClick={() => {
                      setSteps((prev) => {
                        const i = prev.findIndex((p) => p.id === st.id);
                        if (i < 0 || i === prev.length - 1) return prev;
                        const next = prev.slice();
                        const [it] = next.splice(i, 1);
                        next.splice(i + 1, 0, it);
                        return next;
                      });
                      setPipelineVersion((v) => v + 1);
                    }}
                    disabled={idx === steps.length - 1}
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="mini"
                    onClick={() => {
                      setSteps((prev) => prev.map((p) => (p.id === st.id ? { ...p, enabled: !p.enabled } : p)));
                      setPipelineVersion((v) => v + 1);
                    }}
                  >
                    {st.enabled ? "ON" : "OFF"}
                  </button>
                  <button
                    type="button"
                    className="mini danger"
                    onClick={() => {
                      setSteps((prev) => prev.filter((p) => p.id !== st.id));
                      if (selectedStepId === st.id) setSelectedStepId(null);
                      setPipelineVersion((v) => v + 1);
                    }}
                  >
                    Del
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="section-title" style={{ marginTop: "12px" }}>
          Parameters
        </div>
        {selectedStep ? (
          <div className="card-inner" style={{ display: "grid", gap: "8px" }}>
            <div className="hint">Selected: {selectedStep.name}</div>
            <div style={{ display: "grid", gap: "8px" }}>
              {(() => {
                const spec = METHOD_STEP_SPECS[selectedStep.name];
                if (!spec) {
                  return Object.keys(selectedStep.params || {}).map((k) => {
                    const v = (selectedStep.params as any)[k];
                    const isNum = Number.isFinite(Number(v));
                    return (
                      <label key={k} className="inline" style={{ justifyContent: "space-between" }}>
                        {k}
                        <input
                          type={isNum ? "number" : "text"}
                          value={String(v)}
                          onChange={(e) => {
                            const raw = e.target.value;
                            const next = isNum ? Number(raw) : raw;
                            updateSelectedStepParam(k, next);
                          }}
                          style={isNum ? undefined : { width: "180px" }}
                        />
                      </label>
                    );
                  });
                }

                const p = normalizeMethodParams(selectedStep.name, selectedStep.params);
                const method = String(p.method || spec.methods[0]?.id || "");
                const m = spec.methods.find((x) => x.id === method) ?? spec.methods[0];
                const fields: FieldSpec[] = [...(spec.commonFields ?? []), ...(m?.fields ?? [])];

                return (
                  <>
                    <label className="inline" style={{ justifyContent: "space-between" }}>
                      method
                      <select
                        value={method}
                        onChange={(e) => {
                          const nextMethod = String(e.target.value || "");
                          const mm = spec.methods.find((x) => x.id === nextMethod) ?? spec.methods[0];
                          setSelectedStepParams({ method: nextMethod, ...(mm?.defaults ?? {}) });
                        }}
                      >
                        {spec.methods.map((opt) => (
                          <option key={opt.id} value={opt.id}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    {fields.map((f) => {
                      const v = (p as any)[f.key];
                      if (f.kind === "select") {
                        return (
                          <label key={f.key} className="inline" style={{ justifyContent: "space-between" }}>
                            {f.label}
                            <select value={String(v ?? f.options[0] ?? "")} onChange={(e) => updateSelectedStepParam(f.key, String(e.target.value || ""))}>
                              {f.options.map((o) => (
                                <option key={o} value={o}>
                                  {o}
                                </option>
                              ))}
                            </select>
                          </label>
                        );
                      }

                      const isInt = f.kind === "int";
                      return (
                        <label key={f.key} className="inline" style={{ justifyContent: "space-between" }}>
                          {f.label}
                          <input
                            type="number"
                            value={String(v ?? (isInt ? 0 : 0))}
                            onChange={(e) => {
                              const raw = e.target.value;
                              const n = raw === "" ? NaN : Number(raw);
                              updateSelectedStepParam(f.key, isInt ? Math.trunc(n) : n);
                            }}
                          />
                        </label>
                      );
                    })}
                  </>
                );
              })()}
            </div>
          </div>
        ) : (
          <div className="hint">Select a step to edit parameters.</div>
        )}

        <div className="section-title" style={{ marginTop: "12px" }}>
          Metrics
        </div>
        <div className="row">
          <button type="button" onClick={() => runMetricsM.mutate(mode === "batch" ? "all" : "subset")} disabled={!sessionId || runMetricsM.isPending}>
            {runMetricsM.isPending ? "Computing…" : mode === "batch" ? "Compute batch metrics" : "Compute subset metrics"}
          </button>
          {mode === "batch" ? (
            <button
              type="button"
              onClick={async () => {
                if (!sessionId) return;
                const resp = await updateSessionSubset(sessionId, { kind: "outliers", metric: "peak_height", n: subsetSize, zscore_threshold: 3.0 });
                setSubsetIndices(resp?.resolved?.dataset_indices ?? []);
                setMode("explore");
                setSubsetLocked(true);
                setSubsetSource(`Outliers (${subsetSize})`);
              }}
              disabled={!sessionId}
            >
              Outliers → Explore
            </button>
          ) : (
            <div className="hint">Explore subset controls are in the top bar.</div>
          )}
        </div>
        {currentMetrics ? (
          <div className="hint" style={{ marginTop: "8px" }}>
            Metrics rows: {currentMetrics.items?.length ?? 0}
          </div>
        ) : (
          <div className="hint" style={{ marginTop: "8px" }}>
            No metrics yet.
          </div>
        )}
      </div>
    </div>
  );
}

