/* Legacy CDN-based preprocess app (deprecated).
 *
 * This file is kept temporarily for reference while migrating to Vite.
 * The production `/preprocess` page should load assets from
 * `/static/preprocess-dist/...` (Vite build output) instead.
 */
import React from "https://esm.sh/react@18.3.1";
import { createRoot } from "https://esm.sh/react-dom@18.3.1/client";
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
} from "https://esm.sh/@tanstack/react-query@5.59.20";

import {
  createSession,
  getDataset,
  listDatasets,
  runSession,
  sweepPipeline,
  updateSessionPipeline,
  updateSessionSubset,
} from "./preprocess/api.js";
import { useAppStore } from "./preprocess/store.js";
import { PlotlyWrapper } from "./preprocess/plotly_wrapper.js";
import { SpectrumCheckboxListWrapper } from "./preprocess/spectrum_checkbox_list_wrapper.js";

const RAMAN_SHIFT_AXIS_TITLE = "Raman Shift (cm⁻¹)";

function Panel({ title, children }) {
  return React.createElement(
    "div",
    { className: "card" },
    React.createElement("div", { className: "section-title" }, title),
    children
  );
}

function Placeholder({ label }) {
  return React.createElement(
    "div",
    { style: { padding: "12px", color: "var(--muted, #666)" } },
    label
  );
}

function meanStd(arr) {
  const xs = (arr || []).map((x) => Number(x)).filter((x) => Number.isFinite(x));
  if (!xs.length) return { mean: null, std: null, n: 0 };
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  const var1 = xs.reduce((acc, x) => acc + (x - mean) * (x - mean), 0) / xs.length;
  return { mean, std: Math.sqrt(var1), n: xs.length };
}

function histogram(arr, binCount = 20) {
  const xs = (arr || []).map((x) => Number(x)).filter((x) => Number.isFinite(x));
  if (xs.length < 2) return null;
  const lo = Math.min(...xs);
  const hi = Math.max(...xs);
  if (!(hi > lo)) return null;
  const bins = Math.max(5, Math.min(80, Number(binCount) || 20));
  const step = (hi - lo) / bins;
  const counts = Array.from({ length: bins }, () => 0);
  for (const x of xs) {
    const i = Math.max(0, Math.min(bins - 1, Math.floor((x - lo) / step)));
    counts[i] += 1;
  }
  const centers = counts.map((_, i) => lo + (i + 0.5) * step);
  return { centers, counts, lo, hi };
}

function PreprocessingWorkspace() {
  const datasetId = useAppStore((s) => s.dataset.datasetId);
  const sessionId = useAppStore((s) => s.dataset.sessionId);
  const datasetMeta = useAppStore((s) => s.dataset.datasetMeta);
  const subsetSize = useAppStore((s) => s.subset.subsetSize);
  const subsetSeed = useAppStore((s) => s.subset.subsetSeed);
  const subsetLocked = useAppStore((s) => s.subset.subsetLocked);
  const subsetIds = useAppStore((s) => s.subset.subsetIds);
  const subsetMode = useAppStore((s) => s.subset.subsetMode);
  const mode = useAppStore((s) => s.view.mode);
  const plotView = useAppStore((s) => s.view.plotView);
  const autoRun = useAppStore((s) => s.view.autoRun);
  const execStatus = useAppStore((s) => s.execution.status);
  const lastError = useAppStore((s) => s.execution.lastError);
  const actions = useAppStore((s) => s.actions);

  const steps = useAppStore((s) => s.pipeline.steps);
  const selectedStepId = useAppStore((s) => s.pipeline.selectedStepId);
  const selectedStep = steps.find((st) => st.id === selectedStepId) || null;
  const pipelineVersion = useAppStore((s) => s.pipeline.pipelineVersion);
  const lastRunPipelineVersion = useAppStore((s) => s.pipeline.lastRunPipelineVersion);

  const datasetsQ = useQuery({
    queryKey: ["datasets", { limit: 200, offset: 0 }],
    queryFn: () => listDatasets({ limit: 200, offset: 0 }),
  });

  const datasetQ = useQuery({
    queryKey: ["dataset", datasetId],
    enabled: !!datasetId,
    queryFn: () => getDataset(datasetId),
  });

  const createSessionM = useMutation({
    mutationFn: async ({ datasetId, subset }) => {
      return await createSession({ datasetId, subset, pipeline: { steps: [] } });
    },
    onSuccess: (data) => {
      const s = data?.session;
      if (!s?.session_id) return;
      actions.setSession({
        sessionId: s.session_id,
        datasetMeta: { count: Number(s?.subset?.kind === "all" ? datasetQ.data?.dataset?.spectra?.length : datasetQ.data?.dataset?.spectra?.length) },
      });
    },
  });

  const updateSubsetM = useMutation({
    mutationFn: async ({ sessionId, subset }) => updateSessionSubset({ sessionId, subset }),
  });

  const updatePipelineM = useMutation({
    mutationFn: async ({ sessionId, pipeline }) => updateSessionPipeline({ sessionId, pipeline }),
  });

  const runExploreM = useMutation({
    mutationFn: async ({ sessionId }) => {
      return await runSession({
        sessionId,
        scope: "subset",
        returnSpec: { kind: "final" },
      });
    },
    onMutate: () => actions.runStarted(),
    onSuccess: (data) => actions.runSucceeded({ runId: data?.run_id ?? null }),
    onError: (e) => actions.runFailed(e),
  });

  const [currentFigure, setCurrentFigure] = React.useState(null);
  const [previousFigure, setPreviousFigure] = React.useState(null);
  const [currentMetrics, setCurrentMetrics] = React.useState(null);
  const [previousMetrics, setPreviousMetrics] = React.useState(null);

  const runMetricsM = useMutation({
    mutationFn: async ({ sessionId, scope }) => {
      return await runSession({
        sessionId,
        scope,
        returnSpec: { kind: "metrics_only", metrics: ["peak_height", "fwhm"] },
      });
    },
  });

  const sweepM = useMutation({
    mutationFn: async ({ inputs, basePipeline, sweep, objective, cacheNamespace }) =>
      sweepPipeline({ inputs, basePipeline, sweep, objective, cacheNamespace }),
  });

  function onSelectDataset(e) {
    const v = String(e.target.value || "");
    actions.selectDataset(v || null);
    if (!v) return;
    createSessionM.mutate({
      datasetId: v,
      subset: { kind: "random", n: subsetSize, seed: subsetSeed },
    });
  }

  const relPathToDatasetIndex = React.useMemo(() => {
    const spectra = datasetQ.data?.dataset?.spectra || [];
    const map = new Map();
    for (let i = 0; i < spectra.length; i++) {
      map.set(spectra[i].relative_path, i);
    }
    return map;
  }, [datasetQ.data]);

  async function persistManualSubsetFromRelativePaths(relativePaths) {
    if (!sessionId) return;
    const idxs = (relativePaths || [])
      .map((p) => relPathToDatasetIndex.get(p))
      .filter((x) => Number.isInteger(x))
      .slice(0, 30);
    const resp = await updateSubsetM.mutateAsync({
      sessionId,
      subset: { kind: "indices", indices: idxs },
    });
    const ids = resp?.resolved?.dataset_indices || [];
    useAppStore.setState((s) => ({
      subset: { ...s.subset, subsetIds: Array.isArray(ids) ? ids.slice(0, 30) : [], subsetLocked: true, subsetMode: "manual", subsetSource: "Manual" },
    }));
  }

  async function persistSubsetRandom() {
    if (!sessionId) return;
    const resp = await updateSubsetM.mutateAsync({
      sessionId,
      subset: { kind: "random", n: subsetSize, seed: subsetSeed },
    });
    const ids = resp?.resolved?.dataset_indices || [];
    useAppStore.setState((s) => ({ subset: { ...s.subset, subsetIds: Array.isArray(ids) ? ids.slice(0, 30) : [] } }));
  }

  async function onResample() {
    actions.resampleSubset();
    await persistSubsetRandom();
  }

  async function runAndBuildFigure({ upToStepName } = {}) {
    if (!sessionId) return null;
    if (mode === "batch") return null;

    await ensureSessionPipelineUpToDate();

    // Raw: run with up_to_step set to first step? For now, treat raw as up_to_step=null but still uses pipeline if saved.
    // To guarantee true raw, we will call session run up_to_step=null but with an empty pipeline in the session is not supported here.
    // So in UX we label raw as "Raw (session inputs)". Full raw wiring comes with explicit empty pipeline option later.

    if (plotView && String(plotView).startsWith("after:")) {
      const stepName = String(plotView).slice("after:".length);
      const out = await runSession({
        sessionId,
        scope: "subset",
        returnSpec: { kind: "intermediates", steps: [stepName] },
        upToStep: upToStepName ?? null,
      });
      const items = Array.isArray(out?.items) ? out.items : [];
      const traces = items.slice(0, 30).map((it) => {
        const xy = it?.steps?.[stepName];
        return {
          type: "scatter",
          mode: "lines",
          x: xy?.x || [],
          y: xy?.y || [],
          name: `${it.spectrum_id}`,
        };
      });
      return {
        data: traces,
        layout: {
          xaxis: { title: { text: RAMAN_SHIFT_AXIS_TITLE }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
          yaxis: { title: { text: "Intensity (counts)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
          legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
          margin: { l: 60, r: 20, t: 20, b: 95 },
        },
      };
    }

    const out = await runSession({
      sessionId,
      scope: "subset",
      returnSpec: { kind: "final" },
      upToStep: upToStepName ?? null,
    });
    const items = Array.isArray(out?.items) ? out.items : [];
    const traces = items.slice(0, 30).map((it) => ({
      type: "scatter",
      mode: "lines",
      x: it.x,
      y: it.y,
      name: it.spectrum_id,
    }));
    return {
      data: traces,
      layout: {
        xaxis: { title: { text: RAMAN_SHIFT_AXIS_TITLE }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
        yaxis: { title: { text: "Intensity (counts)" }, showline: true, mirror: true, showgrid: false, ticks: "outside" },
        legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
        margin: { l: 60, r: 20, t: 20, b: 95 },
      },
    };
  }

  // Debounced auto-run (explore only).
  React.useEffect(() => {
    if (!autoRun) return;
    if (mode !== "explore") return;
    if (!sessionId) return;
    if (execStatus === "running") return;
    // Only auto-run when pipeline has unsaved changes (modified).
    if (pipelineVersion === lastRunPipelineVersion) return;

    const t = setTimeout(() => {
      onRun().catch(() => {});
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, mode, sessionId, pipelineVersion, lastRunPipelineVersion, plotView]);

  async function onRun() {
    if (!sessionId) return;
    if (mode === "batch") {
      await onComputeMetrics();
      return;
    }

    actions.runStarted();
    let fig = null;
    try {
      fig = await runAndBuildFigure();
      actions.runSucceeded({ runId: null });
    } catch (e) {
      actions.runFailed(e);
      throw e;
    }
    setPreviousFigure(currentFigure);
    setCurrentFigure(fig);
  }

  async function onRunUpToSelected() {
    if (!sessionId || !selectedStep) return;
    if (mode === "batch") {
      await onComputeMetrics();
      return;
    }
    actions.runStarted();
    let fig = null;
    try {
      fig = await runAndBuildFigure({ upToStepName: selectedStep.name });
      actions.runSucceeded({ runId: null });
    } catch (e) {
      actions.runFailed(e);
      throw e;
    }
    setPreviousFigure(currentFigure);
    setCurrentFigure(fig);
  }

  async function onComputeMetrics() {
    if (!sessionId) return;
    await ensureSessionPipelineUpToDate();
    const scope = mode === "batch" ? "all" : "subset";
    const out = await runMetricsM.mutateAsync({ sessionId, scope });
    setPreviousMetrics(currentMetrics);
    setCurrentMetrics(out);
  }

  async function selectOutliers() {
    if (!sessionId) return;
    const resp = await updateSubsetM.mutateAsync({
      sessionId,
      subset: { kind: "outliers", metric: "peak_height", zscore_threshold: 3.0 },
    });
    const ids = resp?.resolved?.dataset_indices || [];
    actions.setSubsetIds(ids, "Outliers: peak_height (z>3)");
    actions.setMode("explore");
    actions.lockSubset(true);
  }

  async function selectTopN() {
    if (!sessionId) return;
    const resp = await updateSubsetM.mutateAsync({
      sessionId,
      subset: { kind: "top_n", metric: "peak_height", direction: "max", n: subsetSize },
    });
    const ids = resp?.resolved?.dataset_indices || [];
    actions.setSubsetIds(ids, `Top ${subsetSize}: peak_height`);
    actions.setMode("explore");
    actions.lockSubset(true);
  }

  async function onSavePipeline() {
    if (!sessionId) return;
    const pipeline = { steps: (steps || []).map((s) => ({ name: s.name, params: s.params || {}, enabled: s.enabled !== false })) };
    await updatePipelineM.mutateAsync({ sessionId, pipeline });
  }

  function exportPipelineJson() {
    const pipeline = { steps: (steps || []).map((s) => ({ name: s.name, params: s.params || {}, enabled: s.enabled !== false })) };
    const blob = new Blob([JSON.stringify(pipeline, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `sersflow-pipeline-${new Date().toISOString().slice(0, 19).replaceAll(":", "")}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2500);
  }

  async function importPipelineJson(file) {
    if (!file) return;
    const text = await file.text();
    const obj = JSON.parse(text);
    const stepsIn = Array.isArray(obj?.steps) ? obj.steps : [];
    // Replace pipeline steps in Zustand (new ids).
    const nextSteps = stepsIn
      .filter((s) => s && typeof s.name === "string")
      .map((s) => ({ id: crypto.randomUUID(), name: s.name, enabled: s.enabled !== false, params: s.params && typeof s.params === "object" ? s.params : {} }));
    useAppStore.setState((prev) => ({
      pipeline: { ...prev.pipeline, steps: nextSteps, selectedStepId: nextSteps[0]?.id || null, pipelineVersion: prev.pipeline.pipelineVersion + 1, dirtyFromStepIndex: 0 },
      execution: { ...prev.execution, status: "modified" },
    }));
    if (sessionId) {
      await onSavePipeline();
    }
  }

  async function ensureSessionPipelineUpToDate() {
    if (!sessionId) return;
    const s = useAppStore.getState();
    if (s.pipeline.pipelineVersion === s.pipeline.lastRunPipelineVersion) return;
    const pipeline = { steps: (s.pipeline.steps || []).map((st) => ({ name: st.name, params: st.params || {}, enabled: st.enabled !== false })) };
    await updatePipelineM.mutateAsync({ sessionId, pipeline });
    // Treat successful persistence as the pipeline version used for the next run.
    useAppStore.setState((prev) => ({
      pipeline: { ...prev.pipeline, lastRunPipelineVersion: prev.pipeline.pipelineVersion },
    }));
  }

  function addStepTemplate(name) {
    const templates = {
      cosmic_ray_removal: { name: "cosmic_ray_removal", enabled: true, params: { z_threshold: 6.0 } },
      crop: { name: "crop", enabled: true, params: { min_x: 400, max_x: 2000 } },
      align_resample: {
        name: "align_resample",
        enabled: true,
        params: { min_x: 400, max_x: 2000, grid_mode: "step", step: 1.0, n_points: 512, interp: "linear" },
      },
      normalization: { name: "normalization", enabled: true, params: { method: "vector" } },
      baseline_subtraction: { name: "baseline_subtraction", enabled: true, params: { method: "als", lam: 1e5, p: 0.01 } },
    };
    actions.addPipelineStep(templates[name] || { name: name || "step", enabled: true, params: {} });
  }

  async function onSweepSelectedParam() {
    if (!datasetQ.data?.dataset?.spectra || !selectedStep || !sessionId) return;
    // Minimal sweep: pick the first numeric param on the selected step.
    const params = selectedStep.params || {};
    const key = Object.keys(params).find((k) => Number.isFinite(Number(params[k])));
    if (!key) {
      alert("No numeric parameter found on the selected step to sweep.");
      return;
    }
    const base = Number(params[key]);
    const grid = {};
    grid[key] = [base * 0.5, base, base * 2].map((v) => Number.isFinite(v) ? v : base);

    const spectra = datasetQ.data.dataset.spectra;
    const idxs = Array.isArray(subsetIds) && subsetIds.length ? subsetIds : [];
    const inputs = (idxs.length ? idxs : spectra.map((_, i) => i).slice(0, Math.min(10, spectra.length)))
      .slice(0, 200)
      .map((i) => spectra[i])
      .filter(Boolean);

    const basePipeline = { steps: (steps || []).map((s) => ({ name: s.name, params: s.params || {}, enabled: s.enabled !== false })) };
    const out = await sweepM.mutateAsync({
      inputs,
      basePipeline,
      sweep: { step: selectedStep.name, grid },
      objective: { metric: "peak_height", aggregate: "median" },
      cacheNamespace: sessionId,
    });
    console.debug("Sweep result", out);
    alert("Sweep complete. (Results currently logged to console; UI comes next.)");
  }

  const statusText = actions.statusStripText() + (pipelineVersion !== lastRunPipelineVersion ? " (modified)" : " (up-to-date)");

  return React.createElement(
    "div",
    { className: "preprocess-grid" },
    React.createElement(
      "div",
      { className: "preprocess-top" },
      React.createElement(
        Panel,
        { title: "TopBar" },
        React.createElement(
          "div",
          { className: "row" },
          React.createElement(
            "label",
            { className: "inline" },
            "Dataset",
            React.createElement(
              "select",
              {
                value: datasetId || "",
                onChange: onSelectDataset,
                style: { padding: "8px", borderRadius: "10px", border: "1px solid var(--border)", background: "rgba(0,0,0,0.18)", color: "var(--text)" },
              },
              React.createElement("option", { value: "" }, datasetsQ.isLoading ? "Loading…" : "Select…"),
              ...(datasetsQ.data?.items || []).map((d) =>
                React.createElement(
                  "option",
                  { key: d.dataset_id, value: d.dataset_id },
                  `${d.dataset_id} (${d.count})`
                )
              )
            )
          ),
          React.createElement(
            "label",
            { className: "inline" },
            "Mode",
            React.createElement(
              "select",
              {
                value: mode,
                onChange: (e) => actions.setMode(String(e.target.value) === "batch" ? "batch" : "explore"),
                style: { padding: "8px", borderRadius: "10px", border: "1px solid var(--border)", background: "rgba(0,0,0,0.18)", color: "var(--text)" },
              },
              React.createElement("option", { value: "explore" }, "Explore"),
              React.createElement("option", { value: "batch" }, "Batch")
            )
          ),
          React.createElement(
            "label",
            { className: "inline" },
            "Subset mode",
            React.createElement(
              "select",
              {
                value: subsetMode,
                onChange: (e) => actions.setSubsetMode(String(e.target.value)),
                style: { padding: "8px", borderRadius: "10px", border: "1px solid var(--border)", background: "rgba(0,0,0,0.18)", color: "var(--text)" },
              },
              React.createElement("option", { value: "random" }, "Random"),
              React.createElement("option", { value: "manual" }, "Manual"),
              React.createElement("option", { value: "metrics" }, "Metrics")
            )
          ),
          React.createElement(
            "label",
            { className: "inline" },
            "Subset size",
            React.createElement("input", {
              type: "number",
              value: subsetSize,
              min: 1,
              max: 30,
              onChange: (e) => actions.setSubsetSize(e.target.value),
              onBlur: () => persistSubsetRandom(),
              disabled: subsetMode !== "random",
            })
          ),
          React.createElement(
            "label",
            { className: "inline" },
            "Seed",
            React.createElement("input", {
              type: "number",
              value: subsetSeed,
              onChange: (e) => useAppStore.setState((s) => ({ subset: { ...s.subset, subsetSeed: Number(e.target.value || 0) } })),
              onBlur: () => persistSubsetRandom(),
              disabled: subsetMode !== "random",
            })
          ),
          React.createElement(
            "button",
            { type: "button", onClick: onResample, disabled: !sessionId || subsetLocked || subsetMode !== "random" },
            "Resample"
          ),
          React.createElement(
            "button",
            { type: "button", onClick: () => actions.lockSubset(!subsetLocked), className: subsetLocked ? "danger" : "" },
            subsetLocked ? "Unlock subset" : "Lock subset"
          ),
          React.createElement(
            "button",
            { type: "button", onClick: onRun, disabled: !sessionId || runExploreM.isPending || runMetricsM.isPending },
            mode === "batch"
              ? runMetricsM.isPending
                ? "Running batch…"
                : "Run (batch)"
              : runExploreM.isPending
                ? "Running…"
                : "Run (subset)"
          )
        ),
        React.createElement("div", { className: "status", style: { marginTop: "8px" } }, statusText),
        datasetQ.data?.dataset?.spectra
          ? React.createElement(
              "div",
              { className: "hint", style: { marginTop: "6px" } },
              `Active: ${Math.min(30, (subsetIds || []).length || subsetSize)} / ${datasetQ.data.dataset.spectra.length} spectra`,
              mode === "batch" ? " (preview subset only)" : ""
            )
          : null,
        lastError ? React.createElement("div", { className: "err", style: { marginTop: "10px" } }, lastError) : null,
        React.createElement(
          Panel,
          { title: "Spectra (legacy checkbox list wrapper)" },
          React.createElement(SpectrumCheckboxListWrapper, {
            onSelectionChange: (paths) => {
              if (subsetMode !== "manual") return;
              // Manual selection persists subset by dataset indices.
              persistManualSubsetFromRelativePaths(paths);
            },
          })
        )
      )
    ),
    React.createElement(
      "div",
      { className: "preprocess-left" },
      React.createElement(
        React.Fragment,
        null,
        React.createElement(
          Panel,
          { title: "Pipeline" },
          React.createElement(
            "div",
            { className: "row" },
            React.createElement("button", { type: "button", className: "mini", onClick: () => addStepTemplate("cosmic_ray_removal") }, "+ cosmic"),
            React.createElement("button", { type: "button", className: "mini", onClick: () => addStepTemplate("crop") }, "+ crop"),
            React.createElement(
              "button",
              {
                type: "button",
                className: "mini",
                onClick: () => addStepTemplate("align_resample"),
                title: "Resample onto a uniform Raman shift grid (use after crop for matrix export / spectrum PCA)",
              },
              "+ resample"
            ),
            React.createElement("button", { type: "button", className: "mini", onClick: () => addStepTemplate("normalization") }, "+ norm"),
            React.createElement("button", { type: "button", className: "mini", onClick: () => addStepTemplate("baseline_subtraction") }, "+ baseline")
          ),
          React.createElement(
            "div",
            { style: { marginTop: "10px", display: "grid", gap: "8px" } },
            ...(steps || []).map((st, idx) =>
              React.createElement(
                "div",
                { key: st.id, className: "card-inner", style: { display: "grid", gap: "8px" } },
                React.createElement(
                  "div",
                  { className: "row", style: { justifyContent: "space-between" } },
                  React.createElement(
                    "button",
                    {
                      type: "button",
                      className: "mini",
                      onClick: () => actions.selectPipelineStep(st.id),
                      style: { fontWeight: st.id === selectedStepId ? 900 : 700 },
                    },
                    `${idx + 1}. ${st.name}`
                  ),
                  React.createElement(
                    "div",
                    { className: "row", style: { gap: "6px" } },
                    React.createElement(
                      "button",
                      { type: "button", className: "mini", onClick: () => actions.movePipelineStep(st.id, "up"), disabled: idx === 0 },
                      "↑"
                    ),
                    React.createElement(
                      "button",
                      { type: "button", className: "mini", onClick: () => actions.movePipelineStep(st.id, "down"), disabled: idx === (steps.length - 1) },
                      "↓"
                    ),
                    React.createElement(
                      "button",
                      { type: "button", className: "mini", onClick: () => actions.togglePipelineStep(st.id) },
                      st.enabled === false ? "OFF" : "ON"
                    ),
                    React.createElement("button", { type: "button", className: "mini", onClick: () => actions.duplicatePipelineStep(st.id) }, "Dup"),
                    React.createElement("button", { type: "button", className: "mini danger", onClick: () => actions.deletePipelineStep(st.id) }, "Del")
                  )
                )
              )
            )
          ),
          React.createElement(
            "div",
            { className: "row", style: { marginTop: "10px" } },
            React.createElement(
              "button",
              { type: "button", onClick: onSavePipeline, disabled: !sessionId || updatePipelineM.isPending },
              updatePipelineM.isPending ? "Saving…" : "Save to session"
            ),
            React.createElement("button", { type: "button", onClick: exportPipelineJson }, "Export JSON"),
            React.createElement("input", {
              type: "file",
              accept: "application/json",
              onChange: (e) => importPipelineJson(e.target.files && e.target.files[0]),
            }),
            React.createElement(
              "button",
              { type: "button", onClick: onRunUpToSelected, disabled: !sessionId || !selectedStep },
              selectedStep ? `Run up to: ${selectedStep.name}` : "Run up to selected"
            )
          )
        ),
        React.createElement(
          Panel,
          { title: "Parameters" },
          selectedStep
            ? React.createElement(
                React.Fragment,
                null,
                React.createElement("div", { className: "hint" }, `Selected: ${selectedStep.name}`),
                React.createElement(
                  "div",
                  { style: { marginTop: "10px", display: "grid", gap: "8px" } },
                  ...Object.keys(selectedStep.params || {}).map((k) => {
                    const v = selectedStep.params[k];
                    const isNum = Number.isFinite(Number(v));
                    return React.createElement(
                      "label",
                      { key: k, className: "inline", style: { justifyContent: "space-between" } },
                      k,
                      React.createElement("input", {
                        type: isNum ? "number" : "text",
                        value: String(v),
                        onChange: (e) => {
                          const raw = e.target.value;
                          const next = isNum ? Number(raw) : raw;
                          actions.updatePipelineStepParam(selectedStep.id, k, next);
                        },
                        style: isNum ? undefined : { width: "160px" },
                      })
                    );
                  })
                ),
                React.createElement(
                  "div",
                  { className: "row", style: { marginTop: "10px" } },
                  React.createElement(
                    "button",
                    { type: "button", onClick: onSweepSelectedParam, disabled: sweepM.isPending || !sessionId },
                    sweepM.isPending ? "Sweeping…" : "Sweep parameter"
                  )
                )
              )
            : React.createElement(Placeholder, { label: "Select a step to edit parameters." })
        )
      )
    ),
    React.createElement(
      "div",
      { className: "preprocess-center" },
      React.createElement(
        Panel,
        { title: "Plot" },
        React.createElement(
          "div",
          { className: "row" },
          React.createElement(
            "label",
            { className: "inline" },
            "View",
            React.createElement(
              "select",
              {
                value: plotView,
                onChange: (e) => actions.setPlotView(String(e.target.value)),
                style: { padding: "8px", borderRadius: "10px", border: "1px solid var(--border)", background: "rgba(0,0,0,0.18)", color: "var(--text)" },
              },
              React.createElement("option", { value: "raw" }, "Raw"),
              ...(steps || []).map((st) =>
                React.createElement("option", { key: st.id, value: `after:${st.name}` }, `After: ${st.name}`)
              ),
              React.createElement("option", { value: "final" }, "Final")
            )
          ),
          React.createElement(
            "label",
            { className: "inline" },
            "Plot mode",
            React.createElement(
              "select",
              {
                value: useAppStore((s) => s.view.plotStyle.mode),
                onChange: (e) =>
                  useAppStore.setState((s) => ({ view: { ...s.view, plotStyle: { ...s.view.plotStyle, mode: String(e.target.value) } } })),
                style: { padding: "8px", borderRadius: "10px", border: "1px solid var(--border)", background: "rgba(0,0,0,0.18)", color: "var(--text)" },
              },
              React.createElement("option", { value: "overlay" }, "Overlay"),
              React.createElement("option", { value: "stack" }, "Stack")
            )
          ),
          React.createElement(
            "label",
            { className: "inline" },
            "Stack sep",
            React.createElement("input", {
              type: "number",
              value: useAppStore((s) => s.view.plotStyle.stackSep),
              onChange: (e) =>
                useAppStore.setState((s) => ({
                  view: { ...s.view, plotStyle: { ...s.view.plotStyle, stackSep: Number(e.target.value || 0) } },
                })),
            })
          ),
          React.createElement(
            "label",
            { className: "inline" },
            React.createElement("input", {
              type: "checkbox",
              checked: useAppStore((s) => s.view.ghostOverlayEnabled),
              onChange: (e) => useAppStore.setState((s) => ({ view: { ...s.view, ghostOverlayEnabled: !!e.target.checked } })),
            }),
            "Ghost overlay"
          ),
          React.createElement(
            "label",
            { className: "inline" },
            React.createElement("input", {
              type: "checkbox",
              checked: autoRun,
              onChange: (e) => actions.setAutoRun(!!e.target.checked),
              disabled: mode !== "explore",
            }),
            "Auto-run"
          )
        ),
        React.createElement(
          "div",
          { style: { marginTop: "10px" } },
          React.createElement(PlotlyWrapper, {
            figure: currentFigure,
            previousFigure,
            plotStyle: useAppStore((s) => s.view.plotStyle),
            ghostOverlayEnabled: useAppStore((s) => s.view.ghostOverlayEnabled),
          })
        )
      )
    ),
    React.createElement(
      "div",
      { className: "preprocess-bottom" },
      React.createElement(
        Panel,
        { title: "Metrics" },
        React.createElement(
          "div",
          { className: "row" },
          React.createElement(
            "button",
            { type: "button", onClick: onComputeMetrics, disabled: !sessionId || runMetricsM.isPending },
            runMetricsM.isPending ? "Computing…" : mode === "batch" ? "Compute batch metrics" : "Compute subset metrics"
          ),
          mode === "batch"
            ? React.createElement(
                React.Fragment,
                null,
                React.createElement("button", { type: "button", onClick: selectOutliers, disabled: !sessionId }, "Outliers"),
                React.createElement("button", { type: "button", onClick: selectTopN, disabled: !sessionId }, `Top ${subsetSize}`)
              )
            : null
        ),
        React.createElement(
          "div",
          { style: { marginTop: "10px", display: "grid", gap: "10px" } },
          currentMetrics
            ? React.createElement(MetricsView, {
                mode,
                metricsResponse: currentMetrics,
                previousMetricsResponse: previousMetrics,
              })
            : React.createElement(Placeholder, { label: "No metrics yet. Compute metrics to populate this panel." })
        )
      )
    )
  );
}

function MetricsView({ mode, metricsResponse, previousMetricsResponse }) {
  const rows = Array.isArray(metricsResponse?.items) ? metricsResponse.items : [];
  const byName = new Map();
  for (const r of rows) {
    for (const m of r.metrics || []) {
      if (!byName.has(m.name)) byName.set(m.name, []);
      byName.get(m.name).push(m.value);
    }
  }

  const prevRows = Array.isArray(previousMetricsResponse?.items) ? previousMetricsResponse.items : [];
  const prevByName = new Map();
  for (const r of prevRows) {
    for (const m of r.metrics || []) {
      if (!prevByName.has(m.name)) prevByName.set(m.name, []);
      prevByName.get(m.name).push(m.value);
    }
  }

  const cards = ["peak_height", "fwhm"].map((name) => {
    const cur = meanStd(byName.get(name) || []);
    const prev = meanStd(prevByName.get(name) || []);
    const deltaMean = cur.mean != null && prev.mean != null ? cur.mean - prev.mean : null;
    const deltaStd = cur.std != null && prev.std != null ? cur.std - prev.std : null;
    return React.createElement(
      "div",
      { key: name, className: "card-inner" },
      React.createElement("div", { className: "section-title" }, `${name} (${mode})`),
      React.createElement(
        "div",
        { className: "row", style: { gap: "16px" } },
        React.createElement("div", null, React.createElement("div", { className: "hint" }, "Mean"), React.createElement("div", null, cur.mean == null ? "—" : cur.mean.toFixed(4))),
        React.createElement("div", null, React.createElement("div", { className: "hint" }, "Std"), React.createElement("div", null, cur.std == null ? "—" : cur.std.toFixed(4))),
        React.createElement(
          "div",
          null,
          React.createElement("div", { className: "hint" }, "Δ mean / Δ std"),
          React.createElement(
            "div",
            null,
            deltaMean == null ? "—" : deltaMean.toFixed(4),
            " / ",
            deltaStd == null ? "—" : deltaStd.toFixed(4)
          )
        )
      )
    );
  });

  const peakHist = histogram(byName.get("peak_height") || [], 24);
  const fwhmHist = histogram(byName.get("fwhm") || [], 24);

  const peakVals = (byName.get("peak_height") || []).map((x) => Number(x)).filter((x) => Number.isFinite(x));
  const peakStats = meanStd(peakVals);
  const outlierThreshold = 3.0;
  const outlierCount = (() => {
    if (mode !== "batch") return null;
    if (!peakVals.length || peakStats.std == null || peakStats.std === 0 || peakStats.mean == null) return 0;
    let c = 0;
    for (const v of peakVals) {
      const z = Math.abs((v - peakStats.mean) / peakStats.std);
      if (z > outlierThreshold) c += 1;
    }
    return c;
  })();
  const [distMetric, setDistMetric] = React.useState("peak_height");
  const dist = distMetric === "fwhm" ? fwhmHist : peakHist;
  const histFig =
    mode === "batch" && dist
      ? {
          data: [{ type: "bar", x: dist.centers, y: dist.counts, name: distMetric }],
          layout: { margin: { l: 50, r: 20, t: 10, b: 40 }, xaxis: { title: { text: distMetric } }, yaxis: { title: { text: "count" } } },
        }
      : null;

  return React.createElement(
    React.Fragment,
    null,
    React.createElement("div", { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "10px" } }, ...cards),
    mode === "batch"
      ? React.createElement(
          "div",
          { className: "card-inner" },
          React.createElement("div", { className: "section-title" }, "Outliers (batch)"),
          React.createElement(
            "div",
            { className: "hint" },
            outlierCount == null ? "—" : `${outlierCount} spectra with |z| > ${outlierThreshold} (peak_height)`
          )
        )
      : null,
    mode === "explore"
      ? React.createElement(
          "div",
          { className: "card-inner" },
          React.createElement("div", { className: "section-title" }, "Per-spectrum values (subset)"),
          React.createElement(
            "div",
            { className: "scrollbox", style: { maxHeight: "220px" } },
            React.createElement(
              "table",
              { style: { width: "100%", borderCollapse: "collapse", fontFamily: "var(--mono)", fontSize: "12px", color: "var(--muted)" } },
              React.createElement(
                "thead",
                null,
                React.createElement(
                  "tr",
                  null,
                  React.createElement("th", { style: { textAlign: "left", padding: "6px" } }, "spectrum_id"),
                  React.createElement("th", { style: { textAlign: "left", padding: "6px" } }, "peak_height"),
                  React.createElement("th", { style: { textAlign: "left", padding: "6px" } }, "fwhm")
                )
              ),
              React.createElement(
                "tbody",
                null,
                ...rows.slice(0, 200).map((r) => {
                  const pm = (r.metrics || []).find((m) => m.name === "peak_height");
                  const fm = (r.metrics || []).find((m) => m.name === "fwhm");
                  return React.createElement(
                    "tr",
                    { key: r.spectrum_id },
                    React.createElement("td", { style: { padding: "6px" } }, r.spectrum_id),
                    React.createElement("td", { style: { padding: "6px" } }, pm?.value == null ? "—" : Number(pm.value).toFixed(4)),
                    React.createElement("td", { style: { padding: "6px" } }, fm?.value == null ? "—" : Number(fm.value).toFixed(4))
                  );
                })
              )
            )
          )
        )
      : null,
    mode === "batch" && histFig
      ? React.createElement(
          "div",
          { className: "card-inner" },
          React.createElement("div", { className: "section-title" }, "Distribution (batch)"),
          React.createElement(
            "div",
            { className: "row" },
            React.createElement(
              "button",
              {
                type: "button",
                className: distMetric === "peak_height" ? "" : "mini",
                onClick: () => setDistMetric("peak_height"),
              },
              "peak_height"
            ),
            React.createElement(
              "button",
              {
                type: "button",
                className: distMetric === "fwhm" ? "" : "mini",
                onClick: () => setDistMetric("fwhm"),
              },
              "fwhm"
            )
          ),
          React.createElement(PlotlyWrapper, { figure: histFig, previousFigure: null, plotStyle: { mode: "overlay", stackSep: 0 }, ghostOverlayEnabled: false })
        )
      : null
  );
}

function main() {
  try {
    const el = document.getElementById("preprocess-root");
    if (!el) throw new Error("Missing preprocess root element");
    const qc = new QueryClient();
    createRoot(el).render(
      React.createElement(QueryClientProvider, { client: qc }, React.createElement(PreprocessingWorkspace))
    );
  } catch (e) {
    if (typeof window !== "undefined" && typeof window.__SERSFLOW_PREPROCESS_SHOW_ERROR__ === "function") {
      window.__SERSFLOW_PREPROCESS_SHOW_ERROR__(e && e.message ? e.message : String(e));
    }
    throw e;
  }
}

main();

