import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  LS_ANALYZE_DATASET,
  LS_ANALYZE_RUN,
  LS_ANALYZE_SESSION,
  loadPrepareUiPrefs,
  savePrepareUiPrefs,
} from "./lib/uiPersistence";
import { PlotlyWrapper } from "./legacy-wrappers/PlotlyWrapper";
import { SpectrumCheckboxListWrapper, type SpectrumCheckboxListHandle } from "./legacy-wrappers/SpectrumCheckboxListWrapper";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearAllDatasets,
  createDatasetFromUploads,
  createPipelineLibraryEntry,
  createSession,
  deleteDataset,
  deletePipelineLibraryEntry,
  exportDatasetPackage,
  exportPipelineLibraryEntry,
  getDataset,
  getPipelineLibraryEntry,
  importDatasetPackage,
  importPipelineLibraryEntry,
  listBaselineMethods,
  listDatasets,
  listFittingModels,
  listPipelines,
  restoreDatasetUploads,
  runSession,
  updatePipelineLibraryEntry,
  updateSessionPipeline,
  updateSessionSubset,
  type BaselineMethodSpecPublic,
  type BaselineMethodsResponse,
  type BaselineParamSpecPublic,
  type FittingComponentSpecPublic,
  type Pipeline,
  type PipelineExportPackage,
  type PipelineInputFrom,
  type SessionRunMetricsResponse,
  type SpectrumRef,
} from "./preprocess/api";
import {
  additionalParams,
  defaultMethodForCategory,
  defaultsForPrimaryParams,
  fallbackBaselineCatalog,
  methodCategoryFor,
  methodSpec,
  methodsForCategory,
  normalizeBaselineParams,
  paramsByKey,
  primaryParams,
} from "./preprocess/baselineMethodCatalog";
import {
  defaultFittingEditorParams,
  defaultRowsForComponent,
  migrateFittingParamsToEditor,
  type FittingEditorParams,
} from "./preprocess/fittingUtils";
import { DEFAULT_GUARDRAILS, type Mode, type PlotView } from "./preprocess/runController";

function normalizePlotView(s: unknown): PlotView {
  if (s === "raw" || s === "final") return s;
  if (typeof s === "string" && s.startsWith("after:")) return s as PlotView;
  return "final";
}

function safeDownloadName(name: string, fallback: string): string {
  const base = String(name || fallback).trim() || fallback;
  return base.replace(/[^a-zA-Z0-9._-]+/g, "_");
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function notifyUploadsChanged() {
  try {
    const channel = new BroadcastChannel("sersflow:uploads-changed");
    channel.postMessage({ type: "uploads-changed" });
    channel.close();
  } catch {
    // ignore
  }
}
import { addSavedSubset, clearSavedSubsets, deleteSavedSubset, loadSavedSubsets, type SavedSubset } from "./preprocess/subsets";
import {
  type EditorStep,
  type FieldSpec,
  inputSelectValue,
  parseInputSelectValue,
  sanitizeStepInputs,
} from "./preprocess/editorTypes";
import { pipelineOptionLabel } from "./preprocess/labels";
import { pipelineStepSpecs } from "./preprocess/pipelineStepSpecs";
import { buildPipelineFromEditor, editorStepsToApiSteps, normalizeMethodParams } from "./preprocess/pipelineEditor";
import { SpectralIntensitiesProbeEditor } from "./preprocess/SpectralIntensitiesProbeEditor";
import { defaultSpectralIntensitiesParams, probesFromParams, probesToApiParams } from "./preprocess/spectralIntensitiesUtils";
import { runExplorePlot as runExplorePlotCore } from "./preprocess/explorePlotRunner";
import { AnalyzeContextBanner } from "./preprocess/components/AnalyzeContextBanner";
import { DatasetPicker } from "./components/DatasetPicker";

function ParamLabel({ label, description }: { label: string; description?: string }) {
  return (
    <span className="param-label">
      <span>{label}</span>
      {description ? (
        <button type="button" className="param-help" title={description} aria-label={`${label}: ${description}`}>
          ?
        </button>
      ) : null}
    </span>
  );
}

function baselineParamInputValue(value: unknown): string {
  return value == null ? "" : String(value);
}

function parseBaselineParamInput(param: BaselineParamSpecPublic, raw: string): unknown {
  if (raw === "") return param.nullable ? null : undefined;
  if (param.kind === "int") return Math.trunc(Number(raw));
  if (param.kind === "number") return Number(raw);
  return raw;
}

export default function PreprocessingWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams();
  const preparePrefs = useMemo(() => loadPrepareUiPrefs(), []);
  const queryClient = useQueryClient();
  const uploadsListRef = useRef<SpectrumCheckboxListHandle>(null);
  const datasetImportInputRef = useRef<HTMLInputElement | null>(null);
  const pipelineImportInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedUploads, setSelectedUploads] = useState<string[]>([]);
  const [newDatasetName, setNewDatasetName] = useState("");
  const [datasetId, setDatasetId] = useState<string | null>(() => {
    const u = searchParams.get("dataset_id");
    if (u) return u;
    const ls = localStorage.getItem(LS_ANALYZE_DATASET);
    return ls || null;
  });
  const [sessionId, setSessionId] = useState<string | null>(() => {
    const u = searchParams.get("session_id");
    if (u) return u;
    const ls = localStorage.getItem(LS_ANALYZE_SESSION);
    return ls || null;
  });
  const [mode, setMode] = useState<Mode>(() =>
    preparePrefs.mode === "batch" || preparePrefs.mode === "explore" ? preparePrefs.mode : "explore"
  );

  // subset (explore)
  const [subsetMode] = useState<"random">("random");
  const [subsetSize, setSubsetSize] = useState(() => {
    const n = preparePrefs.subsetSize;
    return typeof n === "number" && Number.isFinite(n) && n >= 1 ? Math.floor(n) : 15;
  });
  const [subsetSeed, setSubsetSeed] = useState(() => {
    const n = preparePrefs.subsetSeed;
    return typeof n === "number" && Number.isFinite(n) ? Math.floor(n) : 1337;
  });
  const [subsetLocked, setSubsetLocked] = useState(false);
  const [subsetIndices, setSubsetIndices] = useState<number[]>([]);
  const [subsetSource, setSubsetSource] = useState<string>("—");
  const [savedSubsets, setSavedSubsets] = useState<SavedSubset[]>([]);
  const [activeSubsetId, setActiveSubsetId] = useState<string | null>(null);

  // pipeline
  const [steps, setSteps] = useState<EditorStep[]>([]);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [pipelineVersion, setPipelineVersion] = useState(0);
  const [lastSavedPipelineVersion, setLastSavedPipelineVersion] = useState(0);

  // view
  const [plotView, setPlotView] = useState<PlotView>(() => normalizePlotView(preparePrefs.plotView));
  const [ghost, setGhost] = useState(() => (typeof preparePrefs.ghost === "boolean" ? preparePrefs.ghost : true));
  const [plotMode, setPlotMode] = useState<"overlay" | "stack">(() =>
    preparePrefs.plotMode === "stack" || preparePrefs.plotMode === "overlay" ? preparePrefs.plotMode : "overlay"
  );
  const [sep, setSep] = useState(() => {
    const n = preparePrefs.sep;
    return typeof n === "number" && Number.isFinite(n) ? n : 1000;
  });
  const [autoRun, setAutoRun] = useState(() => (typeof preparePrefs.autoRun === "boolean" ? preparePrefs.autoRun : true));

  // results
  const [currentFigure, setCurrentFigure] = useState<any | null>(null);
  const [previousFigure, setPreviousFigure] = useState<any | null>(null);
  const [currentMetrics, setCurrentMetrics] = useState<SessionRunMetricsResponse | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [workspaceInfo, setWorkspaceInfo] = useState<string | null>(null);
  /** Non-null while Explore plot is updating (save / pipeline / per-spectrum fit). */
  const [explorePlotStatus, setExplorePlotStatus] = useState<string | null>(null);
  const runSeq = useRef(0);
  /** Cancels in-flight HTTP from a previous Explore plot run (prevents backlog when params change fast). */
  const explorePlotAbortRef = useRef<AbortController | null>(null);

  const [libraryPipelineName, setLibraryPipelineName] = useState(() => preparePrefs.libraryPipelineName ?? "");
  const [selectedLibraryPipelineId, setSelectedLibraryPipelineId] = useState(
    () => preparePrefs.selectedLibraryPipelineId ?? ""
  );
  const [libraryOverwrite, setLibraryOverwrite] = useState(
    () => typeof preparePrefs.libraryOverwrite === "boolean" && preparePrefs.libraryOverwrite
  );

  const patchParams = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === undefined || v === "") n.delete(k);
            else n.set(k, v);
          }
          return n;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  useEffect(() => {
    if (datasetId) localStorage.setItem(LS_ANALYZE_DATASET, datasetId);
    else localStorage.removeItem(LS_ANALYZE_DATASET);
    patchParams({ dataset_id: datasetId || null });
  }, [datasetId, patchParams]);

  useEffect(() => {
    if (sessionId) localStorage.setItem(LS_ANALYZE_SESSION, sessionId);
    else localStorage.removeItem(LS_ANALYZE_SESSION);
    patchParams({ session_id: sessionId || null });
  }, [sessionId, patchParams]);

  const datasetsQ = useQuery({
    queryKey: ["datasets", { limit: 200, offset: 0 }],
    queryFn: () => listDatasets(200, 0),
  });

  useEffect(() => {
    const rn = searchParams.get("run_id");
    if (rn) localStorage.setItem(LS_ANALYZE_RUN, rn);
  }, [searchParams]);

  useEffect(() => {
    savePrepareUiPrefs({
      v: 1,
      mode,
      plotView,
      ghost,
      plotMode,
      sep,
      autoRun,
      subsetSize,
      subsetSeed,
      libraryPipelineName,
      selectedLibraryPipelineId,
      libraryOverwrite,
    });
  }, [
    mode,
    plotView,
    ghost,
    plotMode,
    sep,
    autoRun,
    subsetSize,
    subsetSeed,
    libraryPipelineName,
    selectedLibraryPipelineId,
    libraryOverwrite,
  ]);

  const pipelinesLibraryQ = useQuery({
    queryKey: ["pipelines", { limit: 200, offset: 0 }],
    queryFn: () => listPipelines(200, 0),
  });

  const fittingModelsQ = useQuery({
    queryKey: ["fitting", "models"],
    queryFn: () => listFittingModels(),
    staleTime: 10 * 60 * 1000,
  });
  const fittingCatalog: FittingComponentSpecPublic[] | undefined = fittingModelsQ.data?.components;
  const baselineMethodsQ = useQuery({
    queryKey: ["pipeline", "baseline-methods"],
    queryFn: () => listBaselineMethods(),
    staleTime: 10 * 60 * 1000,
  });
  const baselineCatalog: BaselineMethodsResponse = baselineMethodsQ.data ?? fallbackBaselineCatalog;

  const clearDatasetsM = useMutation({
    mutationFn: async () => clearAllDatasets(),
    onSuccess: async () => {
      setDatasetId(null);
      setSessionId(null);
      setSubsetIndices([]);
      setSubsetSource("—");
      setActiveSubsetId(null);
      setSteps([]);
      setSelectedStepId(null);
      setPipelineVersion(0);
      setLastSavedPipelineVersion(0);
      await queryClient.invalidateQueries({ queryKey: ["datasets"] });
    },
  });

  const deleteCurrentDatasetM = useMutation({
    mutationFn: async (id: string) => deleteDataset(id),
    onSuccess: async () => {
      setLastError(null);
      setDatasetId(null);
      setSessionId(null);
      setSubsetIndices([]);
      setSubsetSource("—");
      setActiveSubsetId(null);
      setSteps([]);
      setSelectedStepId(null);
      setPipelineVersion(0);
      setLastSavedPipelineVersion(0);
      await queryClient.invalidateQueries({ queryKey: ["datasets"] });
    },
    onError: (e: unknown) => setLastError(String((e as Error)?.message ?? e)),
  });

  const datasetQ = useQuery({
    queryKey: ["dataset", datasetId],
    enabled: !!datasetId,
    queryFn: () => getDataset(String(datasetId)),
  });

  const createFromUploadsM = useMutation({
    mutationFn: async (args: { paths: string[]; name?: string }) =>
      createDatasetFromUploads(
        args.paths,
        args.name?.trim() ? { name: args.name.trim() } : undefined
      ),
    onSuccess: async (data) => {
      const nextDatasetId = data?.dataset?.dataset_id;
      if (!nextDatasetId) return;
      const skipped = data?.skipped_files ?? [];
      if (skipped.length) {
        const preview = skipped
          .slice(0, 5)
          .map((s) => `${s.relative_path}: ${s.reason}`)
          .join("; ");
        const more = skipped.length > 5 ? ` … (+${skipped.length - 5} more)` : "";
        setLastError(
          `Dataset created, but ${skipped.length} file(s) could not be loaded: ${preview}${more}`
        );
      } else {
        setLastError(null);
      }
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
      await queryClient.invalidateQueries({ queryKey: ["datasets"] });
      await queryClient.refetchQueries({ queryKey: ["datasets"] });
    },
  });

  const restoreDatasetUploadsM = useMutation({
    mutationFn: async (id: string) => restoreDatasetUploads(id),
    onSuccess: async (data) => {
      const restored = data.restored.length;
      const reactivated = data.reactivated.length;
      const already = data.already_active.length;
      const missing = data.missing.length;
      setLastError(missing ? `${missing} dataset file(s) could not be restored. Files that still have blobs remain usable for plotting.` : null);
      setWorkspaceInfo(`Uploads restored: ${restored} copied from blobs, ${reactivated} reactivated, ${already} already active.`);
      notifyUploadsChanged();
      await uploadsListRef.current?.refresh();
    },
    onError: (e: unknown) => setLastError(String((e as Error)?.message ?? e)),
  });

  const importDatasetM = useMutation({
    mutationFn: async (file: File) => importDatasetPackage(file),
    onSuccess: async (data) => {
      const nextDatasetId = data.dataset.dataset_id;
      setDatasetId(nextDatasetId);
      const s = await createSession(nextDatasetId, { kind: "random", n: subsetSize, seed: subsetSeed }, { steps: [] });
      setSessionId(s?.session?.session_id ?? null);
      setWorkspaceInfo(`Imported dataset with ${data.imported_spectra} spectra and ${data.imported_blobs} new blob file(s).`);
      setLastError(null);
      await queryClient.invalidateQueries({ queryKey: ["datasets"] });
      await queryClient.refetchQueries({ queryKey: ["datasets"] });
    },
    onError: (e: unknown) => setLastError(String((e as Error)?.message ?? e)),
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

  function removeSelectedStepParam(key: string) {
    if (!selectedStep) return;
    setSteps((prev) =>
      prev.map((p) => {
        if (p.id !== selectedStep.id) return p;
        const next = { ...(p.params ?? {}) };
        delete next[key];
        return { ...p, params: next };
      })
    );
    setPipelineVersion((vv) => vv + 1);
  }

  function updateSelectedFittingParams(next: FittingEditorParams) {
    if (!selectedStep || selectedStep.name !== "fitting") return;
    setSteps((prev) =>
      prev.map((p) => (p.id === selectedStep.id ? { ...p, params: next as unknown as Record<string, any> } : p))
    );
    setPipelineVersion((vv) => vv + 1);
  }

  const buildPipeline = useCallback(
    (): Pipeline => buildPipelineFromEditor(steps, fittingCatalog, baselineCatalog),
    [steps, fittingCatalog, baselineCatalog]
  );

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
    mutationFn: async () =>
      createPipelineLibraryEntry(libraryPipelineName.trim(), buildPipeline(), { overwrite: libraryOverwrite }),
    onSuccess: (data) => {
      setLastError(null);
      if (data?.item?.name) setLibraryPipelineName(data.item.name);
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
    onError: (e: any) => setLastError(String(e?.message ?? e)),
  });

  const updatePipelineLibraryM = useMutation({
    mutationFn: async () => {
      if (!selectedLibraryPipelineId) throw new Error("Select a saved pipeline");
      const trimmed = libraryPipelineName.trim();
      const fallback = (pipelinesLibraryQ.data?.items ?? []).find((x) => x.pipeline_id === selectedLibraryPipelineId)?.name ?? "";
      const name = trimmed || fallback;
      if (!name) throw new Error("Enter a pipeline name");
      return updatePipelineLibraryEntry(selectedLibraryPipelineId, { name, pipeline: buildPipeline() });
    },
    onSuccess: () => {
      setLastError(null);
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
    onError: (e: any) => setLastError(String(e?.message ?? e)),
  });

  const deletePipelineLibraryM = useMutation({
    mutationFn: async () => {
      if (!selectedLibraryPipelineId) throw new Error("Select a saved pipeline");
      return deletePipelineLibraryEntry(selectedLibraryPipelineId);
    },
    onSuccess: () => {
      setLastError(null);
      setSelectedLibraryPipelineId("");
      queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
    onError: (e: any) => setLastError(String(e?.message ?? e)),
  });

  const importPipelineLibraryM = useMutation({
    mutationFn: async (pkg: PipelineExportPackage | { name?: string | null; pipeline: Pipeline }) => importPipelineLibraryEntry(pkg),
    onSuccess: async (data) => {
      setLastError(null);
      setWorkspaceInfo(`Imported pipeline "${data.item.name}".`);
      setSelectedLibraryPipelineId(data.item.pipeline_id);
      setLibraryPipelineName(data.item.name);
      await queryClient.invalidateQueries({ queryKey: ["pipelines"] });
    },
    onError: (e: any) => setLastError(String(e?.message ?? e)),
  });

  async function loadLibraryPipelineById(pipelineId: string) {
    if (!pipelineId) return;
    setLastError(null);
    try {
      const { item } = await getPipelineLibraryEntry(pipelineId);
      setLibraryPipelineName(item.name);
      const next: EditorStep[] = item.pipeline.steps.map((st) => {
        const sid = (st.step_id != null && String(st.step_id).trim() !== "" ? String(st.step_id).trim() : null) ?? null;
        const input_from = (st.input_from as PipelineInputFrom | undefined) ?? "previous";
        const after = st.after_step_id != null && String(st.after_step_id).trim() !== "" ? String(st.after_step_id).trim() : null;
        const rawParams = (st.params as Record<string, any>) ?? {};
        const params =
          st.name === "fitting"
            ? (migrateFittingParamsToEditor(rawParams, fittingCatalog) as unknown as Record<string, any>)
            : st.name === "spectral_intensities"
              ? (probesToApiParams(probesFromParams(rawParams)) as Record<string, any>)
              : { ...rawParams };
        return {
          id: sid ?? crypto.randomUUID(),
          name: st.name,
          enabled: st.enabled !== false,
          params,
          input_from: input_from === "after_step" && !after ? "previous" : input_from,
          after_step_id: input_from === "after_step" && after ? after : null,
        };
      });
      setSteps(sanitizeStepInputs(next));
      setSelectedStepId(null);
      setPipelineVersion((v) => v + 1);
    } catch (e: any) {
      setLastError(String(e?.message ?? e));
    }
  }

  async function applyLibraryPipeline() {
    if (!selectedLibraryPipelineId) return;
    await loadLibraryPipelineById(selectedLibraryPipelineId);
  }

  async function exportCurrentDataset() {
    if (!datasetId) return;
    try {
      const blob = await exportDatasetPackage(datasetId);
      const name = datasetQ.data?.dataset?.metadata?.name || datasetId;
      downloadBlob(blob, `${safeDownloadName(name, datasetId)}.sersflow-dataset.zip`);
      setWorkspaceInfo("Dataset export downloaded.");
      setLastError(null);
    } catch (e: any) {
      setLastError(String(e?.message ?? e));
    }
  }

  async function exportSelectedPipeline() {
    if (!selectedLibraryPipelineId) return;
    try {
      const blob = await exportPipelineLibraryEntry(selectedLibraryPipelineId);
      const name =
        (pipelinesLibraryQ.data?.items ?? []).find((x) => x.pipeline_id === selectedLibraryPipelineId)?.name ||
        libraryPipelineName ||
        selectedLibraryPipelineId;
      downloadBlob(blob, `${safeDownloadName(name, selectedLibraryPipelineId)}.sersflow-pipeline.json`);
      setWorkspaceInfo("Pipeline export downloaded.");
      setLastError(null);
    } catch (e: any) {
      setLastError(String(e?.message ?? e));
    }
  }

  async function exportEditorPipeline() {
    const name = libraryPipelineName.trim() || "current_pipeline";
    const pkg: PipelineExportPackage = {
      schema_version: "sersflow.pipeline.v1",
      created_by: "SERSFlow",
      exported_at: new Date().toISOString(),
      name,
      pipeline: buildPipeline(),
      source_pipeline_id: selectedLibraryPipelineId || null,
    };
    downloadBlob(
      new Blob([JSON.stringify(pkg, null, 2)], { type: "application/json" }),
      `${safeDownloadName(name, "current_pipeline")}.sersflow-pipeline.json`
    );
    setWorkspaceInfo("Current editor pipeline export downloaded.");
    setLastError(null);
  }

  async function handleDatasetImportFile(file: File | null | undefined) {
    if (!file) return;
    await importDatasetM.mutateAsync(file);
    if (datasetImportInputRef.current) datasetImportInputRef.current.value = "";
  }

  async function handlePipelineImportFile(file: File | null | undefined) {
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as PipelineExportPackage;
      await importPipelineLibraryM.mutateAsync(parsed);
    } catch (e: any) {
      setLastError(String(e?.message ?? e));
    } finally {
      if (pipelineImportInputRef.current) pipelineImportInputRef.current.value = "";
    }
  }

  async function ensurePipelineSaved() {
    if (!sessionId) return;
    if (pipelineVersion === lastSavedPipelineVersion) return;
    await savePipelineM.mutateAsync(buildPipeline());
  }

  function subsetInputsFromIndices(indices: number[]): SpectrumRef[] {
    const spectra = datasetQ.data?.dataset?.spectra ?? [];
    const inputs = indices
      .map((i) => spectra[i])
      .filter(Boolean)
      .slice(0, DEFAULT_GUARDRAILS.maxPlotSpectraHardCap);
    return inputs;
  }

  async function runExplorePlot() {
    if (!sessionId) return;
    await runExplorePlotCore({
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
      editorStepsToApiSteps: (slice) => editorStepsToApiSteps(slice, fittingCatalog, baselineCatalog),
      fittingCatalog,
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

  // For "After: <step>" plot views, do not tie auto-run to pipelineVersion — editing step params
  // would queue many expensive runs (especially fitting). Refresh those views via plot/subset changes or Run.
  const pipelineDepForAutoRun = typeof plotView === "string" && plotView.startsWith("after:") ? 0 : pipelineVersion;

  // Debounced auto-run (Explore only). This is a side-effect; useEffect is required.
  useEffect(() => {
    if (!autoRun) return;
    if (mode !== "explore") return;
    if (!sessionId) return;
    if (!subsetIndices.length) return;
    const t = setTimeout(() => {
      runExplorePlot().catch((e) => setLastError(String(e?.message ?? e)));
    }, plotView.startsWith("after:") ? 500 : 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, mode, sessionId, pipelineDepForAutoRun, plotView, subsetIndices.join(",")]);

  function addStepTemplate(name: string) {
    const defaultBaseline = defaultMethodForCategory(baselineCatalog, "whittaker") ?? baselineCatalog.methods[0];
    const templates: Record<string, any> = {
      noise_savgol: { name: "noise_savgol", enabled: true, params: { window_length: 11, polyorder: 3 } },
      cosmic_ray_removal: {
        name: "cosmic_ray_removal",
        enabled: true,
        params: { method: "zscore", threshold: 5.0, window: 5, interpolation: "median", max_width: 10, min_intensity_ratio: 2.0, n_iterations: 3 },
      },
      baseline: {
        name: "baseline",
        enabled: true,
        params: { method: defaultBaseline?.id ?? "asls", ...defaultsForPrimaryParams(defaultBaseline) },
      },
      crop: { name: "crop", enabled: true, params: { min_x: 400, max_x: 2000 } },
      align_resample: {
        name: "align_resample",
        enabled: true,
        params: {
          method: "uniform",
          min_x: 400,
          max_x: 2000,
          grid_mode: "step",
          step: 1.0,
          n_points: 512,
          interp: "linear",
        },
      },
      // Backend supports: max/min/mean/median/vector/spectrum_point/baseline_point.
      normalize: { name: "normalize", enabled: true, params: { method: "max" } },
      fitting: {
        name: "fitting",
        enabled: true,
        params: defaultFittingEditorParams(undefined) as unknown as Record<string, any>,
      },
      spectral_intensities: {
        name: "spectral_intensities",
        enabled: true,
        params: defaultSpectralIntensitiesParams() as unknown as Record<string, any>,
      },
    };
    const t = templates[name] ?? { name, enabled: true, params: {} };
    const id = crypto.randomUUID();
    setSteps((prev) => [...prev, { id, name: t.name, enabled: t.enabled, params: t.params, input_from: "previous", after_step_id: null }]);
    setSelectedStepId(id);
    setPipelineVersion((v) => v + 1);
  }

  return (
    <div className="preprocess-grid">
      <div className="preprocess-top card">
        <div className="section-title">Pipeline &amp; preview</div>
        <p className="hint" style={{ margin: "0 0 10px" }}>
          Choose a <b>Dataset</b> below. The random subset here is only for <b>preview plots</b>. Batch feature extraction and
          multivariate stats use the <b>full dataset</b> from <b>Features &amp; statistics</b> after you save the pipeline.
        </p>
        <AnalyzeContextBanner
          show={
            !!(searchParams.get("dataset_id") || searchParams.get("session_id") || searchParams.get("run_id"))
          }
        />
        <div className="row preprocess-workspace-loadout">
          <DatasetPicker
            items={datasetsQ.data?.items ?? []}
            value={datasetId ?? ""}
            loading={datasetsQ.isLoading}
            onChange={(v) => {
              setDatasetId(v || null);
              setSessionId(null);
              if (v) createSessionM.mutate(v);
            }}
          />
          <button
            type="button"
            className="danger"
            onClick={() => datasetId && deleteCurrentDatasetM.mutate(datasetId)}
            disabled={!datasetId || deleteCurrentDatasetM.isPending || clearDatasetsM.isPending}
            title="Delete only the dataset selected above (and its sessions)"
          >
            {deleteCurrentDatasetM.isPending ? "Deleting…" : "Delete current dataset"}
          </button>
          <button
            type="button"
            className="danger"
            onClick={() => clearDatasetsM.mutate()}
            disabled={clearDatasetsM.isPending || deleteCurrentDatasetM.isPending}
            title="Deletes all datasets and sessions from the backend DB"
          >
            {clearDatasetsM.isPending ? "Clearing…" : "Clear all datasets"}
          </button>
          <button
            type="button"
            onClick={() => datasetId && restoreDatasetUploadsM.mutate(datasetId)}
            disabled={!datasetId || restoreDatasetUploadsM.isPending}
            title="Make this dataset's source files visible in the active upload list again"
          >
            {restoreDatasetUploadsM.isPending ? "Restoring…" : "Restore files to uploads"}
          </button>
          <button type="button" onClick={exportCurrentDataset} disabled={!datasetId}>
            Export dataset
          </button>
          <button type="button" onClick={() => datasetImportInputRef.current?.click()} disabled={importDatasetM.isPending}>
            {importDatasetM.isPending ? "Importing…" : "Import dataset"}
          </button>
          <input
            ref={datasetImportInputRef}
            type="file"
            accept=".zip,.sersflow-dataset.zip,application/zip"
            style={{ display: "none" }}
            onChange={(e) => handleDatasetImportFile(e.currentTarget.files?.[0]).catch((err) => setLastError(String(err?.message ?? err)))}
          />
        </div>
        <div className="row">
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
        {workspaceInfo ? (
          <div className="hint" style={{ marginTop: "10px" }}>
            {workspaceInfo}
          </div>
        ) : null}
      </div>

      <div className="preprocess-left card">
        <div className="section-title">Uploads → Dataset</div>
        <SpectrumCheckboxListWrapper ref={uploadsListRef} onSelectionChange={setSelectedUploads} />
        <div className="hint">
          Selected uploads: {selectedUploads.length}. You can create a dataset from a single file or many.
        </div>
        {selectedUploads.length === 1 ? (
          <div className="hint" style={{ marginTop: "4px" }}>
            One file is enough. Series or map files expand to multiple spectra inside the dataset.
          </div>
        ) : null}
        <label className="inline" style={{ marginTop: "8px", display: "flex", width: "100%", maxWidth: "420px" }}>
          Dataset name (optional)
          <input
            type="text"
            value={newDatasetName}
            onChange={(e) => setNewDatasetName(e.target.value)}
            placeholder="Leave empty for an auto name (Unnamed dataset …)"
            style={{ flex: 1, minWidth: "120px" }}
          />
        </label>
        <div className="hint" style={{ marginTop: "4px" }}>
          Shown in the dataset list. If you leave this blank, the server picks a default name.
        </div>
        <div className="row" style={{ marginTop: "10px" }}>
          <button
            type="button"
            onClick={() => createFromUploadsM.mutate({ paths: selectedUploads, name: newDatasetName })}
            disabled={selectedUploads.length === 0 || createFromUploadsM.isPending}
          >
            {createFromUploadsM.isPending ? "Creating…" : "Create dataset from selected (1+ files)"}
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
        {explorePlotStatus ? (
          <div
            className="hint"
            style={{
              marginBottom: "10px",
              padding: "8px 10px",
              borderRadius: "6px",
              background: "rgba(80, 120, 200, 0.12)",
              border: "1px solid rgba(80, 120, 200, 0.35)",
            }}
          >
            {explorePlotStatus}
          </div>
        ) : null}
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
              {/* Intermediate views: if a step name appears multiple times, disambiguate by a short numeric suffix (index+1). */}
              {(() => {
                const enabled = steps.filter((s) => s.enabled !== false);
                const counts = new Map<string, number>();
                for (const s of enabled) counts.set(s.name, (counts.get(s.name) || 0) + 1);
                return steps.map((s, idx) => {
                  if (s.enabled === false) return null;
                  const c = counts.get(s.name) || 0;
                  const stepNum = idx + 1; // must match backend's default step_num assignment (j+1)
                  const token = c > 1 ? `${s.name}__${stepNum}` : s.name;
                  const label = c > 1 ? `${s.name} (${stepNum})` : s.name;
                  return (
                    <option key={s.id} value={`after:${token}` as any}>
                      After: {label}
                    </option>
                  );
                });
              })()}
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

      <div className="preprocess-bottom card" id="pipeline-library-section">
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
          <button
            type="button"
            className="mini"
            onClick={() => addStepTemplate("align_resample")}
            title="Resample onto a uniform Raman shift grid (use after crop for matrix export / spectrum PCA)"
          >
            + resample
          </button>
          <button type="button" className="mini" onClick={() => addStepTemplate("normalize")}>
            + norm
          </button>
          <button type="button" className="mini" onClick={() => addStepTemplate("fitting")}>
            + fit
          </button>
          <button type="button" className="mini" onClick={() => addStepTemplate("spectral_intensities")} title="Intensity probes for analysis (I_* columns)">
            + intensities
          </button>
          <button type="button" onClick={() => savePipelineM.mutate(buildPipeline())} disabled={!sessionId || savePipelineM.isPending}>
            {savePipelineM.isPending ? "Saving…" : "Save pipeline"}
          </button>
          <button type="button" onClick={exportEditorPipeline}>
            Export current pipeline
          </button>
        </div>
        {steps.some((s) => s.name === "fitting" && s.enabled !== false) && explorePlotStatus ? (
          <div
            className="hint"
            style={{
              marginTop: "8px",
              padding: "8px 10px",
              borderRadius: "6px",
              background: "rgba(80, 120, 200, 0.1)",
              border: "1px solid rgba(80, 120, 200, 0.3)",
            }}
          >
            <b>Fitting step:</b> {explorePlotStatus}
          </div>
        ) : null}

        <div className="section-title" style={{ marginTop: "14px" }}>
          Saved pipelines (library)
        </div>
        {pipelinesLibraryQ.isError ? (
          <div className="err" style={{ marginBottom: "8px" }}>
            Could not load saved pipelines: {String((pipelinesLibraryQ.error as Error)?.message ?? pipelinesLibraryQ.error)}. Check
            that the API is running and try Refresh list.
          </div>
        ) : null}
        <div className="row" style={{ alignItems: "center", flexWrap: "wrap" }}>
          <label className="inline">
            Name (optional)
            <input
              type="text"
              value={libraryPipelineName}
              onChange={(e) => setLibraryPipelineName(e.target.value)}
              placeholder="Leave empty for an auto name (Unnamed pipeline …)"
              style={{ width: "220px" }}
            />
          </label>
          <label className="inline" title="If checked, saving uses the same name and replaces the stored steps">
            <input
              type="checkbox"
              checked={libraryOverwrite}
              onChange={(e) => setLibraryOverwrite(e.target.checked)}
            />{" "}
            Overwrite if name exists
          </label>
          <button
            type="button"
            onClick={() => savePipelineLibraryM.mutate()}
            disabled={savePipelineLibraryM.isPending}
          >
            {savePipelineLibraryM.isPending ? "Saving…" : "Save to library"}
          </button>
          <label className="inline">
            Saved
            <select
              value={selectedLibraryPipelineId}
              onChange={(e) => {
                const id = String(e.target.value || "");
                setSelectedLibraryPipelineId(id);
                const it = (pipelinesLibraryQ.data?.items ?? []).find((x) => x.pipeline_id === id);
                if (it) setLibraryPipelineName(it.name);
                else setLibraryPipelineName("");
                if (id) void loadLibraryPipelineById(id);
              }}
              style={{ minWidth: "200px" }}
            >
              <option value="">{pipelinesLibraryQ.isLoading ? "Loading…" : "None"}</option>
              {(pipelinesLibraryQ.data?.items ?? []).map((it) => (
                <option key={it.pipeline_id} value={it.pipeline_id}>
                  {pipelineOptionLabel(it)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            onClick={() => applyLibraryPipeline()}
            disabled={!selectedLibraryPipelineId}
            title="Fetch this pipeline again from the server (discards unsaved editor edits)"
          >
            Reload
          </button>
          <button
            type="button"
            onClick={() => updatePipelineLibraryM.mutate()}
            disabled={!selectedLibraryPipelineId || updatePipelineLibraryM.isPending}
            title="Rename and/or replace steps for the selected library entry"
          >
            {updatePipelineLibraryM.isPending ? "Updating…" : "Update selected"}
          </button>
          <button
            type="button"
            className="mini"
            onClick={() => deletePipelineLibraryM.mutate()}
            disabled={!selectedLibraryPipelineId || deletePipelineLibraryM.isPending}
          >
            {deletePipelineLibraryM.isPending ? "Deleting…" : "Delete selected"}
          </button>
          <button
            type="button"
            className="mini"
            onClick={exportSelectedPipeline}
            disabled={!selectedLibraryPipelineId}
          >
            Export selected
          </button>
          <button
            type="button"
            className="mini"
            onClick={() => pipelineImportInputRef.current?.click()}
            disabled={importPipelineLibraryM.isPending}
          >
            {importPipelineLibraryM.isPending ? "Importing…" : "Import pipeline"}
          </button>
          <input
            ref={pipelineImportInputRef}
            type="file"
            accept=".json,.sersflow-pipeline.json,application/json"
            style={{ display: "none" }}
            onChange={(e) => handlePipelineImportFile(e.currentTarget.files?.[0])}
          />
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
          Choosing a pipeline in the workspace or here loads its steps into the editor immediately. Use <b>Save pipeline</b> in
          the row above to persist the editor into the active session before running. Use <b>Overwrite if name exists</b> when
          saving to the library, or <b>Update selected</b> to change an existing library entry.
        </div>

        <div style={{ marginTop: "10px", display: "grid", gap: "8px" }}>
          {steps.map((st, idx) => (
            <div key={st.id} className="card-inner" style={{ display: "grid", gap: "8px" }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <button type="button" className="mini" onClick={() => setSelectedStepId(st.id)} style={{ fontWeight: st.id === selectedStepId ? 900 : 700 }}>
                  {idx + 1}. {st.name}
                </button>
                <div className="row" style={{ gap: "6px" }}>
                  <select
                    className="mini"
                    title="Input XY for this step"
                    value={inputSelectValue(st)}
                    onChange={(e) => {
                      const v = String(e.target.value || "");
                      const parsed = parseInputSelectValue(v);
                      setSteps((prev) =>
                        sanitizeStepInputs(
                          prev.map((p) => (p.id === st.id ? { ...p, ...parsed } : p))
                        )
                      );
                      setPipelineVersion((vv) => vv + 1);
                    }}
                  >
                    <option value="previous">Previous</option>
                    <option value="initial">Initial</option>
                    {steps.slice(0, idx).map((prev, i) => (
                      <option key={prev.id} value={`after:${prev.id}`}>
                        After step {i + 1}: {prev.name}
                      </option>
                    ))}
                  </select>
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
                        return sanitizeStepInputs(next);
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
                        return sanitizeStepInputs(next);
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
                      setSteps((prev) => sanitizeStepInputs(prev.filter((p) => p.id !== st.id)));
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
            {selectedStep.name === "fitting" ? (
              <div className="hint" style={{ marginTop: "-2px" }}>
                Fitting preview for <b>View → After: fitting</b> refreshes when you change the view, subset, or click{" "}
                <b>Run (subset plot)</b> — not on every parameter edit (avoids freezing the UI).
              </div>
            ) : null}
            <div style={{ display: "grid", gap: "8px" }}>
              {(() => {
                if (selectedStep.name === "fitting") {
                  const fp = migrateFittingParamsToEditor(selectedStep.params ?? {}, fittingCatalog);
                  return (
                    <>
                      <label className="inline" style={{ justifyContent: "space-between" }}>
                        Output mode
                        <select
                          value={fp.output_mode}
                          onChange={(e) => {
                            const output_mode = e.target.value === "residual" ? "residual" : "fit";
                            updateSelectedFittingParams({ ...fp, output_mode });
                          }}
                        >
                          <option value="fit">Replace y with fitted curve (fit)</option>
                          <option value="residual">Residual (y − fit)</option>
                        </select>
                      </label>
                      <label className="inline" style={{ justifyContent: "space-between" }}>
                        Gaussian amplitude (initial guess)
                        <select
                          value={fp.initial_guess_mode}
                          onChange={(e) => {
                            const initial_guess_mode = e.target.value === "auto" ? "auto" : "default";
                            updateSelectedFittingParams({ ...fp, initial_guess_mode });
                          }}
                        >
                          <option value="default">Default — use Initial Guess column (amplitude)</option>
                          <option value="auto">
                            Auto — amplitude = spectrum intensity at center position (backend, per spectrum)
                          </option>
                        </select>
                      </label>
                      <label className="inline" style={{ justifyContent: "space-between" }}>
                        Gaussian fill opacity (area from peak down to y = 0)
                        <input
                          type="number"
                          min={0}
                          max={1}
                          step={0.05}
                          value={fp.fill_opacity}
                          onChange={(e) => {
                            const v = Number(e.target.value);
                            updateSelectedFittingParams({ ...fp, fill_opacity: Number.isFinite(v) ? v : 0.15 });
                          }}
                        />
                      </label>
                      {fittingModelsQ.isLoading ? <div className="hint">Loading model catalog…</div> : null}
                      {fittingModelsQ.isError ? (
                        <div className="err">Could not load /fitting/models: {String((fittingModelsQ.error as Error)?.message ?? fittingModelsQ.error)}</div>
                      ) : null}
                      {fp.components.map((comp, ci) => (
                        <div
                          key={`fitting-comp-${ci}`}
                          className="card-inner"
                          style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: "12px", alignItems: "start" }}
                        >
                          <div style={{ display: "grid", gap: "8px" }}>
                            <div className="row" style={{ justifyContent: "space-between" }}>
                              <div className="hint" style={{ fontWeight: 800 }}>
                                Model
                              </div>
                              <button
                                type="button"
                                className="mini danger"
                                onClick={() => {
                                  const next = fp.components.filter((_, j) => j !== ci);
                                  updateSelectedFittingParams({
                                    ...fp,
                                    components: next.length ? next : defaultFittingEditorParams(fittingCatalog).components,
                                  });
                                }}
                              >
                                Remove
                              </button>
                            </div>

                            <label className="inline" style={{ justifyContent: "space-between", alignItems: "center" }}>
                              <span className="hint" style={{ flex: "1 1 auto", minWidth: 0 }}>
                                Peak name
                              </span>
                              <input
                                type="text"
                                placeholder="auto if empty"
                                value={comp.component_id}
                                onChange={(e) => {
                                  const next = fp.components.slice();
                                  next[ci] = { ...comp, component_id: e.target.value };
                                  updateSelectedFittingParams({ ...fp, components: next });
                                }}
                                style={{ width: "140px" }}
                                title="Used in plots and analysis column prefixes. Leave empty for p1, p2, …"
                              />
                            </label>

                            <label className="inline" style={{ justifyContent: "space-between" }}>
                              Type
                              <select
                                value={comp.component_type}
                                onChange={(e) => {
                                  const component_type = e.target.value === "polynomial_background" ? "polynomial_background" : "gaussian";
                                  const degree = component_type === "polynomial_background" ? 2 : 0;
                                  const rows = defaultRowsForComponent(component_type, degree, fittingCatalog);
                                  const next = fp.components.slice();
                                  next[ci] = { ...comp, component_type, degree, rows };
                                  updateSelectedFittingParams({ ...fp, components: next });
                                }}
                              >
                                <option value="gaussian">Gaussian</option>
                                <option value="polynomial_background">Polynomial</option>
                              </select>
                            </label>

                            {comp.component_type === "polynomial_background" ? (
                              <label className="inline" style={{ justifyContent: "space-between" }}>
                                Degree
                                <input
                                  type="number"
                                  min={0}
                                  max={12}
                                  value={comp.degree}
                                  onChange={(e) => {
                                    const degree = Math.max(0, Math.min(12, Math.floor(Number(e.target.value || 0))));
                                    const rows = defaultRowsForComponent("polynomial_background", degree, fittingCatalog);
                                    const next = fp.components.slice();
                                    next[ci] = { ...comp, degree, rows };
                                    updateSelectedFittingParams({ ...fp, components: next });
                                  }}
                                  style={{ width: "100px" }}
                                />
                              </label>
                            ) : null}
                          </div>

                          <div style={{ display: "grid", gap: "6px" }}>
                            <div
                              className="hint"
                              style={{
                                display: "grid",
                                gridTemplateColumns: "minmax(120px, 1fr) 140px 170px",
                                gap: "8px",
                                fontWeight: 800,
                              }}
                            >
                              <span>Parameter</span>
                              <span>Initial Guess</span>
                              <span>Bounds</span>
                            </div>
                            {comp.rows.map((row, ri) => (
                              <div
                                key={row.key}
                                style={{
                                  display: "grid",
                                  gridTemplateColumns: "minmax(120px, 1fr) 140px 170px",
                                  gap: "8px",
                                  alignItems: "center",
                                }}
                              >
                                <span>{row.label}</span>
                                <input
                                  type="number"
                                  step="any"
                                  disabled={
                                    fp.initial_guess_mode === "auto" &&
                                    comp.component_type === "gaussian" &&
                                    row.key === "amp"
                                  }
                                  title={
                                    fp.initial_guess_mode === "auto" &&
                                    comp.component_type === "gaussian" &&
                                    row.key === "amp"
                                      ? "Auto mode: backend uses intensity at the center (pos) as initial amplitude."
                                      : undefined
                                  }
                                  value={row.p0}
                                  onChange={(e) => {
                                    const v = Number(e.target.value);
                                    const next = fp.components.slice();
                                    const rows = next[ci]!.rows.slice();
                                    rows[ri] = { ...row, p0: Number.isFinite(v) ? v : 0 };
                                    next[ci] = { ...next[ci]!, rows };
                                    updateSelectedFittingParams({ ...fp, components: next });
                                  }}
                                />
                                <div className="row" style={{ gap: "6px", justifyContent: "flex-start" }}>
                                  <input
                                    type="number"
                                    step="any"
                                    placeholder="lower"
                                    value={row.lower === null ? "" : String(row.lower)}
                                    onChange={(e) => {
                                      const raw = e.target.value.trim();
                                      const lower = raw === "" ? null : Number(raw);
                                      const next = fp.components.slice();
                                      const rows = next[ci]!.rows.slice();
                                      rows[ri] = { ...row, lower: lower !== null && Number.isFinite(lower) ? lower : null };
                                      next[ci] = { ...next[ci]!, rows };
                                      updateSelectedFittingParams({ ...fp, components: next });
                                    }}
                                    style={{ width: "78px" }}
                                  />
                                  <input
                                    type="number"
                                    step="any"
                                    placeholder="upper"
                                    value={row.upper === null ? "" : String(row.upper)}
                                    onChange={(e) => {
                                      const raw = e.target.value.trim();
                                      const upper = raw === "" ? null : Number(raw);
                                      const next = fp.components.slice();
                                      const rows = next[ci]!.rows.slice();
                                      rows[ri] = { ...row, upper: upper !== null && Number.isFinite(upper) ? upper : null };
                                      next[ci] = { ...next[ci]!, rows };
                                      updateSelectedFittingParams({ ...fp, components: next });
                                    }}
                                    style={{ width: "78px" }}
                                  />
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ))}
                      <button
                        type="button"
                        className="mini"
                        onClick={() => {
                          const rows = defaultRowsForComponent("gaussian", 0, fittingCatalog);
                          updateSelectedFittingParams({
                            ...fp,
                            components: [
                              ...fp.components,
                              { component_id: "", component_type: "gaussian", degree: 0, rows },
                            ],
                          });
                        }}
                      >
                        + Add model
                      </button>
                    </>
                  );
                }

                if (selectedStep.name === "spectral_intensities") {
                  return (
                    <SpectralIntensitiesProbeEditor
                      probes={probesFromParams(selectedStep.params ?? {})}
                      onChange={(next) => setSelectedStepParams(probesToApiParams(next))}
                    />
                  );
                }

                if (selectedStep.name === "baseline") {
                  const rawMethod = String((selectedStep.params as any)?.method || "");
                  const p = normalizeBaselineParams(selectedStep.params, baselineCatalog);
                  const method = String(p.method || baselineCatalog.methods[0]?.id || "");
                  const m = methodSpec(baselineCatalog, method) ?? baselineCatalog.methods.find((x) => x.ui_enabled !== false);
                  const category = m ? m.category : methodCategoryFor(baselineCatalog, method);
                  const categoryOptions = baselineCatalog.categories.filter((cat) => methodsForCategory(baselineCatalog, cat.id).length);
                  const categoryMethods = methodsForCategory(baselineCatalog, category);
                  const paramMap = paramsByKey(m);
                  const primary = primaryParams(m);
                  const primaryKeys = new Set(primary.map((x) => x.key));
                  const additional = additionalParams(m);
                  const selectedAdditionalKeys = Object.keys(selectedStep.params ?? {}).filter((key) => {
                    const spec = paramMap.get(key);
                    return key !== "method" && spec?.ui_role === "advanced" && !primaryKeys.has(key);
                  });
                  const availableAdditional = additional.filter((param) => !selectedAdditionalKeys.includes(param.key));
                  const unknownBaselineMethod = rawMethod !== "" && !methodSpec(baselineCatalog, rawMethod);

                  const applyBaselineMethod = (nextMethod: BaselineMethodSpecPublic | undefined) => {
                    if (!nextMethod) return;
                    setSelectedStepParams({ method: nextMethod.id, ...defaultsForPrimaryParams(nextMethod) });
                  };

                  const renderBaselineParam = (param: BaselineParamSpecPublic, value: unknown, removable: boolean) => {
                    const onParsedValue = (next: unknown) => {
                      if (next === undefined) {
                        removeSelectedStepParam(param.key);
                      } else {
                        updateSelectedStepParam(param.key, next);
                      }
                    };

                    let control;
                    if (param.options?.length) {
                      control = (
                        <select
                          value={value == null ? "" : String(value)}
                          onChange={(e) => onParsedValue(e.target.value === "" && param.nullable ? null : String(e.target.value))}
                        >
                          {param.nullable ? <option value="">None</option> : null}
                          {param.options.map((o) => (
                            <option key={o} value={o}>
                              {o}
                            </option>
                          ))}
                        </select>
                      );
                    } else if (param.kind === "boolean") {
                      control = (
                        <input
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(e) => onParsedValue(e.target.checked)}
                        />
                      );
                    } else {
                      const isNumber = param.kind === "number" || param.kind === "int";
                      control = (
                        <input
                          type={isNumber ? "number" : "text"}
                          value={baselineParamInputValue(value)}
                          placeholder={param.nullable ? "None" : undefined}
                          onChange={(e) => onParsedValue(parseBaselineParamInput(param, e.target.value))}
                        />
                      );
                    }

                    return (
                      <label key={param.key} className="inline baseline-param-row" style={{ justifyContent: "space-between" }}>
                        <ParamLabel label={param.key} description={param.description} />
                        <span className="baseline-param-control">
                          {control}
                          {removable ? (
                            <button type="button" className="mini" onClick={() => removeSelectedStepParam(param.key)} title={`Remove ${param.key}`}>
                              remove
                            </button>
                          ) : null}
                        </span>
                      </label>
                    );
                  };

                  return (
                    <>
                      {unknownBaselineMethod ? (
                        <div className="err">Unknown baseline method {rawMethod}; using the first available method for editing.</div>
                      ) : null}
                      <label className="inline" style={{ justifyContent: "space-between" }}>
                        category
                        <select
                          value={category}
                          onChange={(e) => applyBaselineMethod(defaultMethodForCategory(baselineCatalog, String(e.target.value)))}
                        >
                          {categoryOptions.map((cat) => (
                            <option key={cat.id} value={cat.id}>
                              {cat.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="inline" style={{ justifyContent: "space-between" }}>
                        method
                        <select
                          value={m?.id ?? ""}
                          onChange={(e) => applyBaselineMethod(methodSpec(baselineCatalog, String(e.target.value)))}
                        >
                          {categoryMethods.map((opt) => (
                            <option key={opt.id} value={opt.id}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      {primary.map((param) => renderBaselineParam(param, (p as any)[param.key], false))}
                      {selectedAdditionalKeys.length ? <div className="hint">Additional arguments</div> : null}
                      {selectedAdditionalKeys.map((key) => {
                        const param = paramMap.get(key);
                        return param ? renderBaselineParam(param, (selectedStep.params as any)[key], true) : null;
                      })}
                      {availableAdditional.length ? (
                        <label className="inline" style={{ justifyContent: "space-between" }}>
                          add argument
                          <select
                            value=""
                            onChange={(e) => {
                              const key = String(e.target.value || "");
                              if (!key) return;
                              const param = paramMap.get(key);
                              if (param) updateSelectedStepParam(key, param.default);
                            }}
                          >
                            <option value="">Select argument…</option>
                            {availableAdditional.map((param) => (
                              <option key={param.key} value={param.key}>
                                {param.key}
                              </option>
                            ))}
                          </select>
                        </label>
                      ) : null}
                      {baselineMethodsQ.isError ? (
                        <div className="hint">Using fallback baseline method metadata; backend metadata could not be loaded.</div>
                      ) : null}
                    </>
                  );
                }

                const spec = pipelineStepSpecs[selectedStep.name];
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

                const p = normalizeMethodParams(selectedStep.name, selectedStep.params, fittingCatalog);
                const method = String(p.method || spec.methods[0]?.id || "");
                const m = spec.methods.find((x) => x.id === method) ?? spec.methods[0];
                const fields: FieldSpec[] = [...(spec.commonFields ?? []), ...(m?.fields ?? [])];
                const selectedStepIndex = steps.findIndex((s) => s.id === selectedStep.id);
                const baselineStepOptions =
                  selectedStep.name === "normalize" && method === "baseline_point"
                    ? steps
                        .slice(0, Math.max(selectedStepIndex, 0))
                        .map((step, index) => ({ step, index }))
                        .filter(({ step }) => step.enabled !== false && step.name === "baseline")
                    : [];
                const selectedBaselineStepId = String((p as any).baseline_step_id ?? "");
                const baselineStepIsInvalid =
                  selectedStep.name === "normalize" &&
                  method === "baseline_point" &&
                  selectedBaselineStepId !== "" &&
                  !baselineStepOptions.some(({ step }) => step.id === selectedBaselineStepId);

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

                    {selectedStep.name === "normalize" && method === "baseline_point" ? (
                      <>
                        <label className="inline" style={{ justifyContent: "space-between" }}>
                          baseline step
                          <select
                            value={selectedBaselineStepId}
                            onChange={(e) => updateSelectedStepParam("baseline_step_id", String(e.target.value || ""))}
                          >
                            <option value="">Select baseline step…</option>
                            {baselineStepOptions.map(({ step, index }) => {
                              const baselineMethod = String((step.params as any)?.method || "derpsalsa");
                              return (
                                <option key={step.id} value={step.id}>
                                  Step {index + 1}: baseline ({baselineMethod})
                                </option>
                              );
                            })}
                          </select>
                        </label>
                        {!baselineStepOptions.length ? (
                          <div className="hint">Add or move an enabled baseline step before this normalize step.</div>
                        ) : null}
                        {baselineStepIsInvalid ? (
                          <div className="err">Selected baseline step is no longer an earlier enabled baseline step.</div>
                        ) : null}
                      </>
                    ) : null}

                    {fields.map((f) => {
                      const v = (p as any)[f.key];
                      if (f.kind === "select") {
                        return (
                          <label key={f.key} className="inline" style={{ justifyContent: "space-between" }}>
                            <ParamLabel label={f.label} description={f.description} />
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

                      if (f.kind === "boolean") {
                        return (
                          <label key={f.key} className="inline" style={{ justifyContent: "space-between" }}>
                            <ParamLabel label={f.label} description={f.description} />
                            <input type="checkbox" checked={Boolean(v)} onChange={(e) => updateSelectedStepParam(f.key, e.target.checked)} />
                          </label>
                        );
                      }

                      if (f.kind === "string") {
                        return (
                          <label key={f.key} className="inline" style={{ justifyContent: "space-between" }}>
                            <ParamLabel label={f.label} description={f.description} />
                            <input
                              type="text"
                              value={String(v ?? "")}
                              onChange={(e) => updateSelectedStepParam(f.key, e.target.value)}
                            />
                          </label>
                        );
                      }

                      const isInt = f.kind === "int";
                      return (
                        <label key={f.key} className="inline" style={{ justifyContent: "space-between" }}>
                          <ParamLabel label={f.label} description={f.description} />
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
          Run
        </div>
        <div className="row">
          <button
            type="button"
            onClick={() => {
              if (mode === "batch") runMetricsM.mutate("all");
              else runExplorePlot().catch((e) => setLastError(String(e?.message ?? e)));
            }}
            disabled={!sessionId || runMetricsM.isPending || savePipelineM.isPending}
          >
            {mode === "batch"
              ? runMetricsM.isPending
                ? "Running…"
                : "Quick metrics (all spectra, peak / FWHM)"
              : "Run preview plot (subset)"}
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
        {mode === "batch" ? (
          currentMetrics ? (
            <div className="hint" style={{ marginTop: "8px" }}>
              Metrics rows: {currentMetrics.items?.length ?? 0}
            </div>
          ) : (
            <div className="hint" style={{ marginTop: "8px" }}>
              No metrics yet.
            </div>
          )
        ) : null}
      </div>
    </div>
  );
}

