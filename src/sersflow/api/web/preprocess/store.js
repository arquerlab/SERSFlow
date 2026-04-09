import { create } from "https://esm.sh/zustand@4.5.5";

function nextSeed(prev) {
  const p = Number.isFinite(Number(prev)) ? Number(prev) : Date.now();
  // Simple, explicit: different each click, stable display.
  return (p * 9301 + 49297) % 233280;
}

export const useAppStore = create((set, get) => ({
  dataset: {
    datasetId: null,
    sessionId: null,
    datasetMeta: null, // {count, name...}
  },
  subset: {
    subsetMode: "random", // random | manual | metrics
    subsetSize: 5,
    subsetLocked: false,
    subsetIds: [],
    subsetSeed: 123,
    subsetSource: "Random",
  },
  pipeline: {
    steps: [],
    selectedStepId: null,
    pipelineVersion: 0,
    lastRunPipelineVersion: 0,
    dirtyFromStepIndex: null,
  },
  execution: {
    status: "idle", // idle | modified | running | error
    lastRunId: null,
    lastRunAt: null,
    lastError: null,
  },
  view: {
    mode: "explore", // explore | batch
    plotView: "raw", // raw | final | after:stepName
    plotStyle: { mode: "overlay", stackSep: 1000 },
    ghostOverlayEnabled: true,
    autoRun: false,
  },

  actions: {
    selectDataset(datasetId) {
      set((s) => ({
        dataset: { ...s.dataset, datasetId, sessionId: null, datasetMeta: null },
        execution: { ...s.execution, status: "idle", lastError: null },
      }));
    },
    setSession({ sessionId, datasetMeta }) {
      set((s) => ({
        dataset: { ...s.dataset, sessionId, datasetMeta: datasetMeta ?? s.dataset.datasetMeta },
      }));
    },

    setMode(mode) {
      set((s) => ({ view: { ...s.view, mode } }));
    },

    setPlotView(plotView) {
      set((s) => ({ view: { ...s.view, plotView } }));
    },
    setAutoRun(v) {
      set((s) => ({ view: { ...s.view, autoRun: !!v } }));
    },

    setSubsetSize(n) {
      const nn = Math.max(1, Math.min(30, Number(n) || 1));
      set((s) => ({ subset: { ...s.subset, subsetSize: nn } }));
    },
    resampleSubset() {
      set((s) => {
        if (s.subset.subsetLocked) return s;
        const seed2 = nextSeed(s.subset.subsetSeed);
        return { subset: { ...s.subset, subsetSeed: seed2, subsetSource: "Random" } };
      });
    },
    lockSubset(v) {
      set((s) => ({ subset: { ...s.subset, subsetLocked: !!v } }));
    },
    setSubsetIds(ids, source) {
      const arr = Array.isArray(ids) ? ids.map((x) => Number(x)).filter((x) => Number.isInteger(x)) : [];
      set((s) => ({
        subset: {
          ...s.subset,
          subsetIds: arr.slice(0, 30),
          subsetLocked: true,
          subsetMode: source ? "metrics" : s.subset.subsetMode,
          subsetSource: source ?? s.subset.subsetSource,
        },
      }));
    },

    setSubsetMode(mode) {
      set((s) => ({ subset: { ...s.subset, subsetMode: mode } }));
    },

    addPipelineStep(step) {
      const id = crypto.randomUUID();
      set((s) => ({
        pipeline: {
          ...s.pipeline,
          steps: [...s.pipeline.steps, { id, ...step }],
          selectedStepId: id,
          pipelineVersion: s.pipeline.pipelineVersion + 1,
          dirtyFromStepIndex: s.pipeline.steps.length,
        },
        execution: { ...s.execution, status: "modified" },
      }));
    },
    selectPipelineStep(stepId) {
      set((s) => ({ pipeline: { ...s.pipeline, selectedStepId: stepId } }));
    },
    togglePipelineStep(stepId) {
      set((s) => {
        const idx = s.pipeline.steps.findIndex((st) => st.id === stepId);
        if (idx < 0) return s;
        const steps = s.pipeline.steps.slice();
        steps[idx] = { ...steps[idx], enabled: !steps[idx].enabled };
        return {
          pipeline: { ...s.pipeline, steps, pipelineVersion: s.pipeline.pipelineVersion + 1, dirtyFromStepIndex: idx },
          execution: { ...s.execution, status: "modified" },
        };
      });
    },
    deletePipelineStep(stepId) {
      set((s) => {
        const idx = s.pipeline.steps.findIndex((st) => st.id === stepId);
        if (idx < 0) return s;
        const steps = s.pipeline.steps.filter((st) => st.id !== stepId);
        const selectedStepId = s.pipeline.selectedStepId === stepId ? (steps[idx]?.id || steps[idx - 1]?.id || null) : s.pipeline.selectedStepId;
        return {
          pipeline: { ...s.pipeline, steps, selectedStepId, pipelineVersion: s.pipeline.pipelineVersion + 1, dirtyFromStepIndex: idx },
          execution: { ...s.execution, status: "modified" },
        };
      });
    },
    duplicatePipelineStep(stepId) {
      set((s) => {
        const idx = s.pipeline.steps.findIndex((st) => st.id === stepId);
        if (idx < 0) return s;
        const src = s.pipeline.steps[idx];
        const copy = { ...src, id: crypto.randomUUID(), name: src.name, params: { ...(src.params || {}) } };
        const steps = s.pipeline.steps.slice();
        steps.splice(idx + 1, 0, copy);
        return {
          pipeline: { ...s.pipeline, steps, selectedStepId: copy.id, pipelineVersion: s.pipeline.pipelineVersion + 1, dirtyFromStepIndex: idx },
          execution: { ...s.execution, status: "modified" },
        };
      });
    },
    movePipelineStep(stepId, dir) {
      const d = dir === "up" ? -1 : 1;
      set((s) => {
        const idx = s.pipeline.steps.findIndex((st) => st.id === stepId);
        if (idx < 0) return s;
        const j = idx + d;
        if (j < 0 || j >= s.pipeline.steps.length) return s;
        const steps = s.pipeline.steps.slice();
        const tmp = steps[idx];
        steps[idx] = steps[j];
        steps[j] = tmp;
        return {
          pipeline: { ...s.pipeline, steps, pipelineVersion: s.pipeline.pipelineVersion + 1, dirtyFromStepIndex: Math.min(idx, j) },
          execution: { ...s.execution, status: "modified" },
        };
      });
    },
    updatePipelineStepParam(stepId, key, value) {
      set((s) => {
        const idx = s.pipeline.steps.findIndex((st) => st.id === stepId);
        if (idx < 0) return s;
        const steps = s.pipeline.steps.slice();
        const st = steps[idx];
        const params = { ...(st.params || {}) };
        params[key] = value;
        steps[idx] = { ...st, params };
        return {
          pipeline: { ...s.pipeline, steps, pipelineVersion: s.pipeline.pipelineVersion + 1, dirtyFromStepIndex: idx },
          execution: { ...s.execution, status: "modified" },
        };
      });
    },

    markModified() {
      set((s) => ({ execution: { ...s.execution, status: "modified" } }));
    },
    runStarted() {
      set((s) => ({ execution: { ...s.execution, status: "running", lastError: null } }));
    },
    runSucceeded({ runId }) {
      set((s) => ({
        execution: { ...s.execution, status: "idle", lastRunId: runId ?? s.execution.lastRunId, lastRunAt: new Date().toISOString() },
        pipeline: { ...s.pipeline, lastRunPipelineVersion: s.pipeline.pipelineVersion },
      }));
    },
    runFailed(err) {
      set((s) => ({ execution: { ...s.execution, status: "error", lastError: String(err?.message || err) } }));
    },

    statusStripText() {
      const s = get();
      const ds = s.dataset.datasetId ? `Dataset: ${s.dataset.datasetId}` : "Dataset: —";
      const sub = `Subset: ${s.subset.subsetMode}(${s.subset.subsetSize}) seed=${s.subset.subsetSeed}${s.subset.subsetLocked ? " locked" : ""}`;
      const pipe = `Pipeline: ${s.execution.status}`;
      return `${ds} | ${sub} | ${pipe}`;
    },
  },
}));

