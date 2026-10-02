import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  LS_ANALYZE_DATASET,
  LS_ANALYZE_RUN,
  LS_ANALYZE_SESSION,
  loadPrepareUiPrefs,
  savePrepareUiPrefs,
} from "./lib/uiPersistence";
import { DraftNumberInput } from "./lib/draftInputs";
import { PlotlyWrapper } from "./legacy-wrappers/PlotlyWrapper";
import { UploadDatasetPicker, type UploadDatasetPickerHandle } from "./legacy-wrappers/UploadDatasetPicker";
import { ResizableSplit } from "./components/ResizableSplit";
import { ResizableVerticalSplit } from "./components/ResizableVerticalSplit";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { acceptFromFormats, useFormatsCatalog, useMergedFormatUi } from "./preprocess/hooks/useFormatsCatalog";
import { usePipelineStepsCatalog, stepSpecsFromCatalog } from "./preprocess/hooks/usePipelineStepsCatalog";
import { fetchUploadsList, UPLOADS_LIST_QUERY_KEY, useUploadsList } from "./preprocess/hooks/useUploadsList";
import {
  clearAllDatasets,
  createDatasetFromUploads,
  createPipelineLibraryEntry,
  createSession,
  deleteDataset,
  deletePipelineLibraryEntry,
  exportDatasetPackage,
  exportPipelineLibraryEntry,
  fetchDatasetXpsRegions,
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
  type TechniqueFamily,
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
  PEAK_COMPONENT_TYPES,
  PEAK_TYPE_LABELS,
  XPS_REGION_PRESETS,
  defaultFittingEditorParams,
  defaultRowsForComponent,
  findParamLink,
  isPeakComponentType,
  migrateFittingParamsToEditor,
  parseFittingComponentType,
  upsertParamLink,
  xpsBgComponentTypesFromCatalog,
  xpsBgTypeLabel,
  type FittingEditorParams,
  type FittingParamLink,
} from "./preprocess/fittingUtils";
import { FittingRecipePicker } from "./preprocess/FittingRecipePicker";
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
  migrateMetadataFilterStepsOnLoad,
  sanitizeStepInputs,
} from "./preprocess/editorTypes";
import { pipelineOptionLabel } from "./preprocess/labels";
import { buildPipelineFromEditor, editorStepsToApiSteps, normalizeMethodParams } from "./preprocess/pipelineEditor";
import { SpectralIntensitiesProbeEditor } from "./preprocess/SpectralIntensitiesProbeEditor";
import { defaultSpectralIntensitiesParams, probesFromParams, probesToApiParams } from "./preprocess/spectralIntensitiesUtils";
import { SpectralIntegrationsEditor } from "./preprocess/SpectralIntegrationsEditor";
import {
  defaultSpectralIntegrationsParams,
  integrationWindowsFromParams,
  integrationWindowsToApiParams,
} from "./preprocess/spectralIntegrationsUtils";
import { FeatureOperationsEditor } from "./preprocess/FeatureOperationsEditor";
import {
  defaultFeatureOperationsParams,
  featureOperationsFromParams,
  featureOperationsToApiParams,
  featureVariablesBeforeStep,
} from "./preprocess/featureOperationsUtils";
import { ReferenceTransformEditor } from "./preprocess/ReferenceTransformEditor";
import {
  defaultReferenceTransformParams,
  referenceTransformFromParams,
  referenceTransformToApiParams,
} from "./preprocess/referenceTransformUtils";
import {
  defaultXAxisCalibrationParams,
  earlierFittingStepOptions,
  fittingPosKeysForStep,
  multiFittingInPipeline,
  normalizeXAxisCalibrationParams,
} from "./preprocess/xAxisCalibrationUtils";
import { runExplorePlot as runExplorePlotCore } from "./preprocess/explorePlotRunner";
import { LowSignalFilterEditor } from "./preprocess/LowSignalFilterEditor";
import { OutlierDetectionEditor } from "./preprocess/OutlierDetectionEditor";
import { MetadataFilterEditor } from "./preprocess/MetadataFilterEditor";
import { TickDropdown } from "./preprocess/TickDropdown";
import { getBlockSpectra } from "./preprocess/uploadBlockSpectra";
import { selectionMixesTechniques } from "./preprocess/uploadXpsRegionGroups";
import { dualXpsBackgroundConflict } from "./preprocess/xpsBackgroundGuard";
import { AnalyzeContextBanner } from "./preprocess/components/AnalyzeContextBanner";
import { PipelineCard } from "./preprocess/components/PipelineCard";
import { PipelineStepList } from "./preprocess/components/PipelineStepList";
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

export default function PreprocessingWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams();
  const preparePrefs = useMemo(() => loadPrepareUiPrefs(), []);
  const queryClient = useQueryClient();
  const uploadsListRef = useRef<UploadDatasetPickerHandle>(null);
  const datasetImportInputRef = useRef<HTMLInputElement | null>(null);
  const pipelineImportInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedUploads, setSelectedUploads] = useState<string[]>([]);
  const [selectedRecordIndices, setSelectedRecordIndices] = useState<Record<string, number[]>>({});
  const [newDatasetName, setNewDatasetName] = useState("");
  const [vmsSpectrumMode, setVmsSpectrumMode] = useState<"averages" | "individuals" | "all">("averages");
  const [createXpsRegions, setCreateXpsRegions] = useState<string[]>([]);
  const [regionSubsetPicks, setRegionSubsetPicks] = useState<string[]>([]);
  const formatsQ = useFormatsCatalog();
  const { ui: selectedFormatUi } = useMergedFormatUi(selectedUploads);
  const uploadAccept = acceptFromFormats(formatsQ.data?.items);
  const selectedHasMulti =
    selectedFormatUi.show_spectrum_mode || selectedFormatUi.show_region_filter;
  // Block picker lives in the uploads list; do not OR show_block_picker into Prepare mode/region UI.
  const selectedHasExplicitBlocks = Object.keys(selectedRecordIndices).length > 0;
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
  const dualBgConflict = useMemo(() => dualXpsBackgroundConflict(steps), [steps]);

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
  const [pipelineTechniqueFamily, setPipelineTechniqueFamily] = useState<TechniqueFamily>("vibrational");
  const isXpsPipeline = pipelineTechniqueFamily === "xps";

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
    const input = document.getElementById("files");
    if (input instanceof HTMLInputElement && uploadAccept) {
      input.accept = uploadAccept;
    }
  }, [uploadAccept]);

  useEffect(() => {
    const channel = new BroadcastChannel("sersflow:uploads-changed");
    const onMsg = () => {
      void queryClient.invalidateQueries({ queryKey: UPLOADS_LIST_QUERY_KEY });
    };
    channel.addEventListener("message", onMsg);
    return () => {
      channel.removeEventListener("message", onMsg);
      channel.close();
    };
  }, [queryClient]);

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
    queryKey: ["pipelines", { limit: 200, offset: 0, technique_family: pipelineTechniqueFamily }],
    queryFn: () => listPipelines(200, 0, null, pipelineTechniqueFamily),
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

  useEffect(() => {
    const fam = datasetQ.data?.dataset?.metadata?.technique_family;
    if (fam === "xps" || fam === "vibrational") {
      setPipelineTechniqueFamily(fam);
    }
  }, [datasetId, datasetQ.data?.dataset?.metadata?.technique_family]);

  const datasetCapabilities = datasetQ.data?.dataset?.metadata?.capabilities ?? [];
  const pipelineStepsQ = usePipelineStepsCatalog({
    techniqueFamily: pipelineTechniqueFamily,
    capabilities: datasetCapabilities,
  });
  const pipelineStepSpecsFromApi = useMemo(
    () => stepSpecsFromCatalog(pipelineStepsQ.data?.items),
    [pipelineStepsQ.data?.items]
  );
  const stepsCatalogReady = Boolean(pipelineStepsQ.data?.items?.length);

  const uploadsMetaQ = useUploadsList({ limit: 5000 });

  const preferredPassEnergy = useMemo(() => {
    const items = uploadsMetaQ.data?.items ?? [];
    const paths =
      selectedUploads.length > 0
        ? selectedUploads
        : (datasetQ.data?.dataset?.spectra ?? [])
            .map((s: { relative_path?: string }) => s.relative_path)
            .filter((p): p is string => Boolean(p));
    const seen = new Set(paths);
    for (const it of items) {
      if (!seen.has(it.relative_path)) continue;
      const labels = it.labels;
      if (!labels || typeof labels !== "object") continue;
      const top = Number((labels as { pass_energy_eV?: unknown }).pass_energy_eV);
      if (Number.isFinite(top) && top > 0) return Math.round(top);
      const blocks = (labels as { vms_spectra?: Record<string, { pass_energy_eV?: unknown }> }).vms_spectra;
      if (blocks && typeof blocks === "object") {
        for (const b of Object.values(blocks)) {
          const pe = Number(b?.pass_energy_eV);
          if (Number.isFinite(pe) && pe > 0) return Math.round(pe);
        }
      }
    }
    return null;
  }, [selectedUploads, uploadsMetaQ.data?.items, datasetQ.data?.dataset?.spectra]);

  const selectionMixedTechniques = useMemo(() => {
    const items = uploadsMetaQ.data?.items ?? [];
    return selectionMixesTechniques(selectedUploads, items);
  }, [selectedUploads, uploadsMetaQ.data?.items]);

  const createRegionOptions = useMemo(() => {
    const items = uploadsMetaQ.data?.items ?? [];
    const set = new Set<string>();
    for (const p of selectedUploads) {
      const it = items.find((x) => x.relative_path === p);
      for (const r of it?.xps_regions ?? []) {
        const t = String(r || "").trim();
        if (t) set.add(t);
      }
    }
    return [...set].sort();
  }, [selectedUploads, uploadsMetaQ.data?.items]);

  const xpsRegionsQ = useQuery({
    queryKey: ["dataset-xps-regions", datasetId],
    queryFn: () => fetchDatasetXpsRegions(datasetId!),
    enabled: Boolean(datasetId) && pipelineTechniqueFamily === "xps",
  });

  const createFromUploadsM = useMutation({
    mutationFn: async (args: {
      paths: string[];
      name?: string;
      vms_spectrum_mode?: "averages" | "individuals" | "all";
      xps_regions?: string[];
      record_indices?: Record<string, number[]>;
    }) => {
      if (selectionMixedTechniques) {
        throw new Error("Cannot mix vibrational and XPS files in one dataset. Deselect one technique first.");
      }
      return createDatasetFromUploads(
        args.paths,
        args.name?.trim() ? { name: args.name.trim() } : undefined,
        {
          ...(args.vms_spectrum_mode ? { vms_spectrum_mode: args.vms_spectrum_mode } : {}),
          ...(args.xps_regions?.length ? { xps_regions: args.xps_regions } : {}),
          ...(args.record_indices && Object.keys(args.record_indices).length
            ? { record_indices: args.record_indices }
            : {}),
        }
      );
    },
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
      const fam = data?.dataset?.metadata?.technique_family;
      if (fam === "xps" || fam === "vibrational") setPipelineTechniqueFamily(fam);
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
    onError: (e: unknown) => setLastError(String((e as Error)?.message ?? e)),
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

  useEffect(() => {
    if (!selectedStepId && steps.length > 0) {
      setSelectedStepId(steps[0]!.id);
    }
  }, [steps, selectedStepId]);

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
    (): Pipeline =>
      buildPipelineFromEditor(steps, fittingCatalog, baselineCatalog, pipelineTechniqueFamily, pipelineStepSpecsFromApi),
    [steps, fittingCatalog, baselineCatalog, pipelineTechniqueFamily, pipelineStepSpecsFromApi]
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
    try {
      await updateSessionSubset(sessionId, { kind: "indices", indices: s.indices });
      setSubsetIndices(s.indices);
      setActiveSubsetId(s.id);
      setSubsetSource(s.label);
    } catch (e) {
      setLastError(String((e as Error)?.message ?? e));
    }
  }

  const savePipelineM = useMutation({
    mutationFn: async (pipeline: Pipeline) => {
      if (!sessionId) throw new Error("No session");
      const conflict = dualXpsBackgroundConflict(pipeline.steps ?? []);
      if (conflict) throw new Error(conflict);
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
              : st.name === "spectral_integrations"
                ? (integrationWindowsToApiParams(integrationWindowsFromParams(rawParams)) as Record<string, unknown>)
                : st.name === "feature_operations"
                  ? (featureOperationsToApiParams(featureOperationsFromParams(rawParams)) as Record<string, unknown>)
                  : st.name === "reference_transform"
                    ? (referenceTransformToApiParams(referenceTransformFromParams(rawParams)) as Record<string, unknown>)
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
      const migrated = migrateMetadataFilterStepsOnLoad(sanitizeStepInputs(next));
      setSteps(migrated);
      setSelectedStepId(null);
      const fam =
        item.technique_family ??
        item.pipeline.technique_family ??
        null;
      if (fam === "xps" || fam === "vibrational") setPipelineTechniqueFamily(fam);
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
      editorStepsToApiSteps: (slice) =>
        editorStepsToApiSteps(slice, fittingCatalog, baselineCatalog, pipelineStepSpecsFromApi),
      fittingCatalog,
      techniqueFamily: pipelineTechniqueFamily,
      formatPlotMode: selectedFormatUi.plot_mode,
      defaultXLabel: selectedFormatUi.default_x_label,
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

  type StepCategory = "Data Preparation" | "Preprocessing" | "Transformation" | "Feature Extraction";
  type StepPickerItem = {
    category: StepCategory;
    name: string;
    label: string;
    description: string;
  };

  const stepPicker: StepPickerItem[] = useMemo(() => {
    const items = pipelineStepsQ.data?.items;
    if (!items?.length) return [];
    const groups: StepCategory[] = ["Data Preparation", "Preprocessing", "Transformation", "Feature Extraction"];
    return items
      .filter((it) => groups.includes(it.palette_group as StepCategory))
      .map((it) => ({
        category: it.palette_group as StepCategory,
        name: it.id,
        label: it.label,
        description: it.description || "",
      }));
  }, [pipelineStepsQ.data?.items]);

  function addStepTemplate(name: string) {
    const defaultBaseline = defaultMethodForCategory(baselineCatalog, "whittaker") ?? baselineCatalog.methods[0];
    const catalogItem = pipelineStepsQ.data?.items?.find((it) => it.id === name);
    const catalogMethod = catalogItem?.ui?.methods?.[0];
    const catalogDefaults =
      catalogMethod != null
        ? {
            ...(catalogItem?.ui?.method_param_key
              ? { [catalogItem.ui.method_param_key]: catalogMethod.id }
              : {}),
            ...(catalogMethod.defaults ?? {}),
          }
        : null;

    const templates: Record<string, any> = {
      noise_savgol: {
        name: "noise_savgol",
        enabled: true,
        params: catalogDefaults ?? { window_length: 11, polyorder: 3 },
      },
      cosmic_ray_removal: {
        name: "cosmic_ray_removal",
        enabled: true,
        params: catalogDefaults ?? {
          method: "zscore",
          threshold: 5.0,
          window: 5,
          interpolation: "median",
          max_width: 10,
          min_intensity_ratio: 2.0,
          n_iterations: 3,
        },
      },
      baseline: {
        name: "baseline",
        enabled: true,
        params: { method: defaultBaseline?.id ?? "asls", ...defaultsForPrimaryParams(defaultBaseline) },
      },
      crop: {
        name: "crop",
        enabled: true,
        params: catalogDefaults ?? { min_x: 400, max_x: 2000 },
      },
      align_resample: {
        name: "align_resample",
        enabled: true,
        params: catalogDefaults ?? {
          method: "uniform",
          min_x: 400,
          max_x: 2000,
          grid_mode: "step",
          step: 1.0,
          n_points: 512,
          interp: "linear",
        },
      },
      x_axis_calibration: {
        name: "x_axis_calibration",
        enabled: true,
        params: defaultXAxisCalibrationParams(pipelineTechniqueFamily) as unknown as Record<string, unknown>,
      },
      normalize: {
        name: "normalize",
        enabled: true,
        params: catalogDefaults ?? { method: "max" },
      },
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
      spectral_integrations: {
        name: "spectral_integrations",
        enabled: true,
        params: defaultSpectralIntegrationsParams() as unknown as Record<string, unknown>,
      },
      feature_operations: {
        name: "feature_operations",
        enabled: true,
        params: defaultFeatureOperationsParams() as unknown as Record<string, unknown>,
      },
      spectrum_derivative: {
        name: "spectrum_derivative",
        enabled: true,
        params: catalogDefaults ?? { method: "gradient", order: 1 },
      },
      reference_transform: {
        name: "reference_transform",
        enabled: true,
        params: defaultReferenceTransformParams() as unknown as Record<string, unknown>,
      },
      low_signal_filter: {
        name: "low_signal_filter",
        enabled: true,
        params: { metric: "median", threshold: 0, divisor: 10, action: "exclude" },
      },
      metadata_filter: {
        name: "metadata_filter",
        enabled: true,
        params: { filters: [], action: "keep" },
      },
      outlier_detection: {
        name: "outlier_detection",
        enabled: true,
        params: {
          method: "correlation_to_median",
          threshold: 0.98,
          action: "exclude",
          pca_scaler: "none",
          n_components: 8,
        },
      },
    };
    const t = templates[name] ?? {
      name,
      enabled: true,
      params: catalogDefaults ?? {},
    };
    const id = crypto.randomUUID();
    setSteps((prev) => [
      ...prev,
      { id, name: t.name, enabled: t.enabled, params: t.params, input_from: "previous", after_step_id: null },
    ]);
    setSelectedStepId(id);
    setPipelineVersion((v) => v + 1);
  }

  return (
    <div className="preprocess-grid">
      <div className="preprocess-top card">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: "10px" }}>
          <div className="section-title" style={{ margin: 0 }}>
            Pipeline &amp; preview
          </div>
          <button
            type="button"
            className="param-help"
            aria-label="Pipeline and preview help"
            title={
              "Manage your datasets\n" +
              "- Select you active dataset from the database\n" +
              "- Restore files from old dataset to active uploaded files to edit metadata\n" +
              "- Import new dataset one or export your active one"
            }
          >
            ?
          </button>
        </div>
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
        <div className="row" style={{ alignItems: "flex-start", justifyContent: "space-between", gap: "12px", flexWrap: "wrap" }}>
          <div className="row" style={{ flexWrap: "wrap", gap: "10px", alignItems: "center" }}>
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
            {mode === "explore" && pipelineTechniqueFamily === "xps" ? (
              <>
                <TickDropdown
                  label="Regions"
                  appearance="select"
                  options={(xpsRegionsQ.data?.regions ?? []).map((r) => r.region)}
                  selected={regionSubsetPicks}
                  emptySummary="Select regions…"
                  title="Select one or more XPS regions for the subset"
                  disabled={!sessionId || !datasetId || subsetLocked}
                  onChange={setRegionSubsetPicks}
                />
                <button
                  type="button"
                  disabled={!sessionId || !datasetId || subsetLocked || !regionSubsetPicks.length}
                  onClick={async () => {
                    if (!sessionId || !datasetId) return;
                    const spectra = datasetQ.data?.dataset?.spectra ?? [];
                    const wanted = new Set(regionSubsetPicks);
                    const labJson = await fetchUploadsList(5000);
                    const byPath = new Map<string, any>(
                      (labJson.items ?? []).map((it: any) => [String(it.relative_path), it.labels || {}])
                    );
                    const indices: number[] = [];
                    spectra.forEach((s, i) => {
                      const labels = byPath.get(s.relative_path) || {};
                      const blocks = getBlockSpectra(labels);
                      let region: string | undefined;
                      if (Object.keys(blocks).length && s.record_index != null) {
                        const b = blocks[String(s.record_index)];
                        if (b) region = String(b.xps_region || "");
                      } else if (typeof labels.xps_region === "string") {
                        region = labels.xps_region;
                      }
                      if (region && wanted.has(region)) indices.push(i);
                    });
                    if (!indices.length) {
                      setLastError("No spectra match the selected XPS regions.");
                      return;
                    }
                    await updateSessionSubset(sessionId, { kind: "indices", indices });
                    setSubsetIndices(indices);
                    const names = [...wanted].sort().join(", ");
                    const label =
                      wanted.size === 1 ? `Region ${names} (${indices.length})` : `Regions ${names} (${indices.length})`;
                    const subset = {
                      id: crypto.randomUUID(),
                      label,
                      indices,
                      size: indices.length,
                      createdAt: Date.now(),
                    };
                    const next = addSavedSubset(datasetId, subset, 15);
                    setSavedSubsets(next);
                    setActiveSubsetId(subset.id);
                    setSubsetSource(subset.label);
                    setLastError(null);
                  }}
                >
                  Create region subset
                </button>
              </>
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

          <button
            type="button"
            className="param-help"
            aria-label="Preview options help"
            title={"Preview options\n- Select plotting style\n- Create subset to preview your data"}
          >
            ?
          </button>
        </div>
        {lastError ? (
          <div className="err" style={{ marginTop: "10px" }}>
            {lastError}
          </div>
        ) : null}
        {dualBgConflict ? (
          <div className="err" style={{ marginTop: "10px" }} title="Dual Shirley/Tougaard not allowed">
            {dualBgConflict}
          </div>
        ) : null}
        {workspaceInfo ? (
          <div className="hint" style={{ marginTop: "10px" }}>
            {workspaceInfo}
          </div>
        ) : null}
      </div>

      <div className="preprocess-body">
        <ResizableVerticalSplit
          storageKey="sersflow:prepare-body-h"
          defaultHeight={560}
          minHeight={260}
          maxHeight={1400}
          allowPageScroll
          top={
            <div className="preprocess-split-row">
              <ResizableSplit
                storageKey="sersflow:prepare-sidebar-w"
                defaultWidth={400}
                minWidth={280}
                maxWidth={720}
                left={
      <div className="preprocess-left card">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: "10px" }}>
          <div className="section-title" style={{ margin: 0 }}>
            Create new dataset
          </div>
          <button
            type="button"
            className="param-help"
            aria-label="Create new dataset help"
            title={
              "Create new dataset\n" +
              "- Select within your active uploaded files (add filters if needed) and create your own dataset for latter analysis"
            }
          >
            ?
          </button>
        </div>
        <div className="row" style={{ marginTop: "8px", alignItems: "flex-end", flexWrap: "wrap", gap: "10px" }}>
          <button
            type="button"
            onClick={() =>
              createFromUploadsM.mutate({
                paths: selectedUploads,
                name: newDatasetName,
                vms_spectrum_mode: selectedHasMulti ? (selectedHasExplicitBlocks ? "all" : vmsSpectrumMode) : undefined,
                xps_regions: selectedHasMulti && createXpsRegions.length ? createXpsRegions : undefined,
                record_indices: selectedHasExplicitBlocks ? selectedRecordIndices : undefined,
              })
            }
            disabled={selectedUploads.length === 0 || createFromUploadsM.isPending || selectionMixedTechniques}
          >
            {createFromUploadsM.isPending ? "Creating…" : "Create dataset"}
          </button>
          {selectedHasMulti ? (
            <>
              {selectedFormatUi.show_spectrum_mode ? (
              <label
                className="inline"
                style={{ margin: 0, opacity: selectedHasExplicitBlocks ? 0.55 : 1 }}
                title={
                  selectedHasExplicitBlocks
                    ? "Specific spectra are ticked — those blocks are used (mode ignored)"
                    : "Multi-spectrum files may contain averaged and individual replicate blocks per region"
                }
              >
                Multi-spectrum blocks
                <select
                  value={vmsSpectrumMode}
                  disabled={selectedHasExplicitBlocks}
                  onChange={(e) => {
                    const v = e.target.value;
                    setVmsSpectrumMode(v === "individuals" ? "individuals" : v === "all" ? "all" : "averages");
                  }}
                >
                  <option value="averages">Averaged</option>
                  <option value="individuals">Individual</option>
                  <option value="all">All</option>
                </select>
              </label>
              ) : null}
              {selectedFormatUi.show_region_filter ? (
              <TickDropdown
                label="Regions"
                options={createRegionOptions}
                selected={createXpsRegions}
                emptySummary="All regions"
                title="Optional: keep only selected XPS regions when creating the dataset"
                onChange={setCreateXpsRegions}
              />
              ) : null}
            </>
          ) : null}
          <label className="inline" style={{ margin: 0, display: "flex", width: "100%", maxWidth: "420px" }}>
            Dataset name (optional)
            <input
              type="text"
              value={newDatasetName}
              onChange={(e) => setNewDatasetName(e.target.value)}
              placeholder="Leave empty for an auto name (Unnamed dataset …)"
              style={{ flex: 1, minWidth: "120px" }}
            />
          </label>
        </div>
        <UploadDatasetPicker
          ref={uploadsListRef}
          onSelectionChange={(paths, recordIndices) => {
            setSelectedUploads(paths);
            setSelectedRecordIndices(recordIndices || {});
          }}
        />
        <div className="hint">
          Selected uploads: {selectedUploads.length}. You can create a dataset from a single file or many.
          {selectedFormatUi.create_dataset_hints.length ? (
            <>
              {" "}
              {selectedFormatUi.create_dataset_hints[0]}
            </>
          ) : null}
        </div>
        {selectedFormatUi.show_skip_summary &&
        uploadsMetaQ.data?.items?.some((it) => {
          if (!selectedUploads.includes(it.relative_path)) return false;
          const n = Number((it.labels as { nxs_skipped_count?: unknown } | undefined)?.nxs_skipped_count);
          return Number.isFinite(n) && n > 0;
        }) ? (
          <div className="hint" style={{ marginTop: "4px" }}>
            Some NeXus regions were skipped (non–binding-energy axes). Check upload labels for details.
          </div>
        ) : null}
        {selectionMixedTechniques ? (
          <div className="hint" style={{ color: "var(--danger, #b00020)", marginTop: "4px" }}>
            Selection mixes XPS and vibrational files. Deselect one technique before creating a dataset.
          </div>
        ) : null}
        {selectedUploads.length === 1 ? (
          <div className="hint" style={{ marginTop: "4px" }}>
            One file is enough. Series or map files expand to multiple spectra inside the dataset.
          </div>
        ) : null}
        <div className="hint" style={{ marginTop: "4px" }}>
          Shown in the dataset list. If you leave this blank, the server picks a default name.
        </div>
        {datasetId && datasetQ.data?.dataset ? (
          <div className="hint" style={{ marginTop: "8px" }}>
            Dataset spectra: {datasetQ.data.dataset.spectra?.length ?? 0}
          </div>
        ) : null}
      </div>
                }
                right={
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
        {fig && typeof fig === "object" && (fig as { kind?: string }).kind === "fit_stack" ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {((fig as { figures?: unknown[] }).figures ?? []).map((f, i) => (
              <PlotlyWrapper
                key={(f as { spectrum_id?: string })?.spectrum_id ?? i}
                figure={f as any}
                previousFigure={null}
                plotStyle={{ mode: "overlay", stackSep: 0 }}
                ghostOverlayEnabled={false}
                className="plot"
              />
            ))}
          </div>
        ) : (
          <PlotlyWrapper
            figure={fig}
            previousFigure={previousFigure}
            plotStyle={{ mode: plotMode, stackSep: sep }}
            ghostOverlayEnabled={ghost}
            className="plot"
          />
        )}

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
        <div className="subset-tiles">
          {savedSubsets.length ? (
            savedSubsets
              .slice()
              .sort((a, b) => b.createdAt - a.createdAt)
              .map((s) => (
                <div key={s.id} className="card-inner subset-tile">
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                    <button
                      type="button"
                      className="mini"
                      onClick={() => applySavedSubset(s)}
                      style={{ fontWeight: s.id === activeSubsetId ? 900 : 700, maxWidth: "100%" }}
                      disabled={!sessionId}
                      title={s.label}
                    >
                      <span style={{ display: "inline-block", maxWidth: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {s.label}
                      </span>
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
                }
              />
            </div>
          }
          bottom={
            <div className="preprocess-bottom card" id="pipeline-library-section">
        <div className="section-title">Pipeline</div>
        <div className="row" style={{ marginBottom: "10px", alignItems: "center" }}>
          <label className="inline" style={{ justifyContent: "space-between", minWidth: "280px" }}>
            Pipeline type
            <select
              value={pipelineTechniqueFamily}
              onChange={(e) => {
                const v = e.target.value === "xps" ? "xps" : "vibrational";
                setPipelineTechniqueFamily(v);
                setSelectedLibraryPipelineId("");
              }}
              title="Required for save-to-library; selects fit engine (XPS→lmfit, vibrational→curve_fit)"
            >
              <option value="vibrational">Vibrational (Raman / SERS / FTIR)</option>
              <option value="xps">XPS</option>
            </select>
          </label>
          <span className="hint">
            {isXpsPipeline ? "Fitting uses lmfit (constraints + XPS backgrounds)." : "Fitting uses SciPy curve_fit."}
          </span>
        </div>
        <div className="pipeline-step-picker" role="group" aria-label="Add pipeline step">
          {!stepsCatalogReady ? <div className="hint">Loading step catalog…</div> : null}
          {(["Data Preparation", "Preprocessing", "Transformation", "Feature Extraction"] as StepCategory[]).map((cat) => {
            const items = stepPicker.filter((x) => x.category === cat);
            return (
              <div key={cat} className="pipeline-step-picker-col">
                <div className="pipeline-step-picker-title">{cat}</div>
                <div className="pipeline-step-picker-items">
                  {items.map((it) => (
                    <button
                      key={`${cat}:${it.name}`}
                      type="button"
                      className="mini pipeline-step-picker-btn"
                      onClick={() => addStepTemplate(it.name)}
                      title={it.description}
                      disabled={!stepsCatalogReady}
                    >
                      + {it.label}
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
        <div className="row" style={{ marginTop: "10px" }}>
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

        <PipelineCard
          stepList={
            <PipelineStepList
              steps={steps}
              selectedStepId={selectedStepId}
              onSelectStep={setSelectedStepId}
              onStepsChange={setSteps}
              onPipelineVersionBump={() => setPipelineVersion((v) => v + 1)}
              onSelectedStepCleared={() => setSelectedStepId(null)}
            />
          }
          paramsPanel={
            selectedStep ? (
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
                  const linkTargets = fp.components.flatMap((c) =>
                    c.rows.map((r) => ({
                      component_id: c.component_id || "(unnamed)",
                      key: r.key,
                      label: `${c.component_id || "peak"}.${r.label}`,
                    }))
                  );
                  return (
                    <>
                      {isXpsPipeline ? (
                        <FittingRecipePicker
                          fittingParams={fp}
                          fittingCatalog={fittingCatalog}
                          enabled={isXpsPipeline}
                          preferredPassEnergy={preferredPassEnergy}
                          onApply={(next) => updateSelectedFittingParams(next)}
                        />
                      ) : null}
                      {isXpsPipeline ? (
                        <label className="inline" style={{ justifyContent: "space-between", alignItems: "center" }}>
                          Region / band
                          <span style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                            <select
                              value={(() => {
                                const opts = [
                                  ...(xpsRegionsQ.data?.regions?.map((r) => r.region) ?? []),
                                  ...(fp.xps_region ? [fp.xps_region] : []),
                                  ...XPS_REGION_PRESETS,
                                ].filter(Boolean);
                                const uniq = [...new Set(opts.map(String))];
                                return uniq.includes(fp.xps_region ?? "") ? fp.xps_region : "";
                              })()}
                              onChange={(e) => {
                                const v = e.target.value;
                                updateSelectedFittingParams({ ...fp, xps_region: v });
                              }}
                              style={{ width: "100px" }}
                              title="Dataset XPS regions (fallback: presets)"
                            >
                              <option value="">Custom…</option>
                              {(xpsRegionsQ.data?.regions?.length
                                ? xpsRegionsQ.data.regions.map((r) => r.region)
                                : [...XPS_REGION_PRESETS]
                              ).map((r) => (
                                <option key={r} value={r}>
                                  {r}
                                </option>
                              ))}
                              {fp.xps_region &&
                              !(xpsRegionsQ.data?.regions ?? []).some((r) => r.region === fp.xps_region) &&
                              !(XPS_REGION_PRESETS as readonly string[]).includes(fp.xps_region) ? (
                                <option value={fp.xps_region}>{fp.xps_region}</option>
                              ) : null}
                            </select>
                            <input
                              type="text"
                              list="xps-region-presets"
                              placeholder="e.g. O1s, Ir4f"
                              value={fp.xps_region ?? ""}
                              onChange={(e) => updateSelectedFittingParams({ ...fp, xps_region: e.target.value })}
                              style={{ width: "120px" }}
                              title="Core-level / region label for feature column prefixes"
                            />
                            <datalist id="xps-region-presets">
                              {(xpsRegionsQ.data?.regions?.length
                                ? xpsRegionsQ.data.regions.map((r) => r.region)
                                : [...XPS_REGION_PRESETS]
                              ).map((r) => (
                                <option key={r} value={r} />
                              ))}
                            </datalist>
                          </span>
                        </label>
                      ) : null}
                      <label className="inline" style={{ justifyContent: "space-between" }}>
                        Peak amplitude (initial guess)
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
                        Peak fill opacity (area from peak down to y = 0)
                        <DraftNumberInput
                          min={0}
                          max={1}
                          value={fp.fill_opacity}
                          onChange={(n) => {
                            if (n != null) updateSelectedFittingParams({ ...fp, fill_opacity: n });
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
                                  const component_type = parseFittingComponentType(e.target.value);
                                  const degree = component_type === "polynomial_background" ? 2 : 0;
                                  const rows = defaultRowsForComponent(component_type, degree, fittingCatalog);
                                  const next = fp.components.slice();
                                  next[ci] = { ...comp, component_type, degree, rows };
                                  updateSelectedFittingParams({ ...fp, components: next });
                                }}
                              >
                                {PEAK_COMPONENT_TYPES.map((t) => (
                                  <option key={t} value={t}>
                                    {PEAK_TYPE_LABELS[t]}
                                  </option>
                                ))}
                                <option value="polynomial_background">Polynomial</option>
                                {isXpsPipeline
                                  ? xpsBgComponentTypesFromCatalog(fittingCatalog).map((t) => (
                                      <option key={t} value={t}>
                                        {xpsBgTypeLabel(t, fittingCatalog)}
                                      </option>
                                    ))
                                  : null}
                              </select>
                            </label>

                            {comp.component_type === "polynomial_background" ? (
                              <label className="inline" style={{ justifyContent: "space-between" }}>
                                Degree
                                <DraftNumberInput
                                  integer
                                  min={0}
                                  max={12}
                                  value={comp.degree}
                                  onChange={(n) => {
                                    if (n == null) return;
                                    const degree = n;
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
                                gridTemplateColumns: isXpsPipeline
                                  ? "minmax(100px, 1fr) 110px 150px 56px minmax(140px, 1.2fr)"
                                  : "minmax(120px, 1fr) 140px 170px",
                                gap: "8px",
                                fontWeight: 800,
                              }}
                            >
                              <span>Parameter</span>
                              <span>Initial Guess</span>
                              <span>Bounds</span>
                              {isXpsPipeline ? <span>Vary</span> : null}
                              {isXpsPipeline ? <span>Link</span> : null}
                            </div>
                            {comp.rows.map((row, ri) => {
                              const existingLink = findParamLink(fp.param_links, comp.component_id, row.key);
                              return (
                              <div
                                key={row.key}
                                style={{
                                  display: "grid",
                                  gridTemplateColumns: isXpsPipeline
                                    ? "minmax(100px, 1fr) 110px 150px 56px minmax(140px, 1.2fr)"
                                    : "minmax(120px, 1fr) 140px 170px",
                                  gap: "8px",
                                  alignItems: "center",
                                }}
                              >
                                <span>{row.label}</span>
                                <DraftNumberInput
                                  disabled={
                                    fp.initial_guess_mode === "auto" &&
                                    isPeakComponentType(comp.component_type) &&
                                    row.key === "amp"
                                  }
                                  title={
                                    fp.initial_guess_mode === "auto" &&
                                    isPeakComponentType(comp.component_type) &&
                                    row.key === "amp"
                                      ? "Auto mode: backend uses intensity at the center (pos) as initial amplitude."
                                      : undefined
                                  }
                                  value={row.p0}
                                  onChange={(n) => {
                                    if (n == null) return;
                                    const next = fp.components.slice();
                                    const rows = next[ci]!.rows.slice();
                                    rows[ri] = { ...row, p0: n };
                                    next[ci] = { ...next[ci]!, rows };
                                    updateSelectedFittingParams({ ...fp, components: next });
                                  }}
                                />
                                <div className="row" style={{ gap: "6px", justifyContent: "flex-start" }}>
                                  <DraftNumberInput
                                    nullable
                                    placeholder="lower"
                                    value={row.lower}
                                    onChange={(lower) => {
                                      const next = fp.components.slice();
                                      const rows = next[ci]!.rows.slice();
                                      rows[ri] = { ...row, lower };
                                      next[ci] = { ...next[ci]!, rows };
                                      updateSelectedFittingParams({ ...fp, components: next });
                                    }}
                                    style={{ width: "68px" }}
                                  />
                                  <DraftNumberInput
                                    nullable
                                    placeholder="upper"
                                    value={row.upper}
                                    onChange={(upper) => {
                                      const next = fp.components.slice();
                                      const rows = next[ci]!.rows.slice();
                                      rows[ri] = { ...row, upper };
                                      next[ci] = { ...next[ci]!, rows };
                                      updateSelectedFittingParams({ ...fp, components: next });
                                    }}
                                    style={{ width: "68px" }}
                                  />
                                </div>
                                {isXpsPipeline ? (
                                  <input
                                    type="checkbox"
                                    checked={row.vary !== false}
                                    onChange={(e) => {
                                      const next = fp.components.slice();
                                      const rows = next[ci]!.rows.slice();
                                      rows[ri] = { ...row, vary: e.target.checked };
                                      next[ci] = { ...next[ci]!, rows };
                                      updateSelectedFittingParams({ ...fp, components: next });
                                    }}
                                    title="When unchecked, parameter is held fixed during the fit"
                                  />
                                ) : null}
                                {isXpsPipeline ? (
                                  <div className="row" style={{ gap: "4px", flexWrap: "wrap" }}>
                                    <select
                                      value={
                                        existingLink
                                          ? `${existingLink.target_component_id}::${existingLink.target_key}`
                                          : ""
                                      }
                                      onChange={(e) => {
                                        const v = e.target.value;
                                        if (!v) {
                                          updateSelectedFittingParams({
                                            ...fp,
                                            param_links: upsertParamLink(fp.param_links, null, comp.component_id, row.key),
                                          });
                                          return;
                                        }
                                        const [tid, tkey] = v.split("::");
                                        const link: FittingParamLink = {
                                          source_component_id: comp.component_id,
                                          source_key: row.key,
                                          target_component_id: tid || "",
                                          target_key: tkey || "",
                                          mode: existingLink?.mode ?? "equal",
                                          scale: existingLink?.scale,
                                        };
                                        updateSelectedFittingParams({
                                          ...fp,
                                          param_links: upsertParamLink(fp.param_links, link, comp.component_id, row.key),
                                        });
                                      }}
                                      style={{ maxWidth: "120px" }}
                                      title="Link this parameter to another component parameter"
                                    >
                                      <option value="">None</option>
                                      {linkTargets
                                        .filter(
                                          (t) =>
                                            !(t.component_id === (comp.component_id || "(unnamed)") && t.key === row.key)
                                        )
                                        .map((t) => (
                                          <option key={`${t.component_id}::${t.key}`} value={`${t.component_id}::${t.key}`}>
                                            {t.label}
                                          </option>
                                        ))}
                                    </select>
                                    {existingLink ? (
                                      <>
                                        <select
                                          value={existingLink.mode}
                                          onChange={(e) => {
                                            const v = e.target.value;
                                            const mode =
                                              v === "scale" ? "scale" : v === "offset" ? "offset" : "equal";
                                            const link: FittingParamLink = {
                                              ...existingLink,
                                              mode,
                                              scale: mode === "scale" ? existingLink.scale ?? 1 : undefined,
                                              offset: mode === "offset" ? existingLink.offset ?? 0 : undefined,
                                            };
                                            updateSelectedFittingParams({
                                              ...fp,
                                              param_links: upsertParamLink(
                                                fp.param_links,
                                                link,
                                                comp.component_id,
                                                row.key
                                              ),
                                            });
                                          }}
                                          style={{ width: "72px" }}
                                        >
                                          <option value="equal">equal</option>
                                          <option value="scale">scale</option>
                                          <option value="offset">offset</option>
                                        </select>
                                        {existingLink.mode === "scale" ? (
                                          <DraftNumberInput
                                            value={existingLink.scale ?? 1}
                                            onChange={(n) => {
                                              if (n == null) return;
                                              const link: FittingParamLink = { ...existingLink, scale: n };
                                              updateSelectedFittingParams({
                                                ...fp,
                                                param_links: upsertParamLink(
                                                  fp.param_links,
                                                  link,
                                                  comp.component_id,
                                                  row.key
                                                ),
                                              });
                                            }}
                                            style={{ width: "56px" }}
                                          />
                                        ) : null}
                                        {existingLink.mode === "offset" ? (
                                          <DraftNumberInput
                                            value={existingLink.offset ?? 0}
                                            onChange={(n) => {
                                              if (n == null) return;
                                              const link: FittingParamLink = { ...existingLink, offset: n };
                                              updateSelectedFittingParams({
                                                ...fp,
                                                param_links: upsertParamLink(
                                                  fp.param_links,
                                                  link,
                                                  comp.component_id,
                                                  row.key
                                                ),
                                              });
                                            }}
                                            style={{ width: "56px" }}
                                          />
                                        ) : null}
                                      </>
                                    ) : null}
                                  </div>
                                ) : null}
                              </div>
                            );
                            })}
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
                      steps={steps}
                      selectedStepId={selectedStep.id}
                      onChange={(next) => setSelectedStepParams(probesToApiParams(next))}
                    />
                  );
                }

                if (selectedStep.name === "spectral_integrations") {
                  return (
                    <SpectralIntegrationsEditor
                      windows={integrationWindowsFromParams(selectedStep.params ?? {})}
                      onChange={(next) => setSelectedStepParams(integrationWindowsToApiParams(next))}
                    />
                  );
                }

                if (selectedStep.name === "feature_operations") {
                  return (
                    <FeatureOperationsEditor
                      operations={featureOperationsFromParams(selectedStep.params ?? {})}
                      variables={featureVariablesBeforeStep(steps, selectedStep.id)}
                      onChange={(next) => setSelectedStepParams(featureOperationsToApiParams(next))}
                    />
                  );
                }

                if (selectedStep.name === "reference_transform") {
                  const selectedStepIndex = steps.findIndex((s) => s.id === selectedStep.id);
                  return (
                    <ReferenceTransformEditor
                      params={referenceTransformFromParams(selectedStep.params ?? {})}
                      spectra={datasetQ.data?.dataset?.spectra ?? []}
                      previousSteps={steps.slice(0, Math.max(selectedStepIndex, 0)).filter((step) => step.enabled !== false)}
                      onChange={(next) => setSelectedStepParams(referenceTransformToApiParams(next))}
                    />
                  );
                }

                if (selectedStep.name === "low_signal_filter") {
                  return (
                    <LowSignalFilterEditor
                      sessionId={sessionId ?? ""}
                      stepId={selectedStep.id}
                      params={selectedStep.params ?? {}}
                      onChange={(next) => setSelectedStepParams(next)}
                      ensurePipelineSaved={ensurePipelineSaved}
                      datasetSpectra={datasetQ.data?.dataset?.spectra ?? []}
                    />
                  );
                }

                if (selectedStep.name === "metadata_filter") {
                  return (
                    <MetadataFilterEditor
                      datasetId={datasetId}
                      params={selectedStep.params ?? {}}
                      onChange={(next) => setSelectedStepParams(next)}
                    />
                  );
                }

                if (selectedStep.name === "outlier_detection") {
                  return (
                    <OutlierDetectionEditor
                      sessionId={sessionId ?? ""}
                      stepId={selectedStep.id}
                      params={selectedStep.params ?? {}}
                      onChange={(next) => setSelectedStepParams(next)}
                      ensurePipelineSaved={ensurePipelineSaved}
                      datasetSpectra={datasetQ.data?.dataset?.spectra ?? []}
                    />
                  );
                }

                if (selectedStep.name === "baseline") {
                  const rawMethod = String((selectedStep.params as any)?.method || "");
                  const p = normalizeBaselineParams(selectedStep.params, baselineCatalog);
                  const method = String(p.method || baselineCatalog.methods[0]?.id || "");
                  const m = methodSpec(baselineCatalog, method) ?? baselineCatalog.methods.find((x) => x.ui_enabled !== false);
                  const category = m ? m.category : methodCategoryFor(baselineCatalog, method);
                  const categoryOptions = baselineCatalog.categories.filter((cat) => {
                    if (!isXpsPipeline && cat.id === "lmfitxps") return false;
                    return methodsForCategory(baselineCatalog, cat.id).length > 0;
                  });
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
                    } else if (param.kind === "number" || param.kind === "int") {
                      control = (
                        <DraftNumberInput
                          value={value}
                          integer={param.kind === "int"}
                          nullable={param.nullable}
                          placeholder={param.nullable ? "None" : undefined}
                          onChange={(next) => onParsedValue(next === null ? null : next)}
                        />
                      );
                    } else {
                      control = (
                        <input
                          type="text"
                          value={value == null ? "" : String(value)}
                          placeholder={param.nullable ? "None" : undefined}
                          onChange={(e) => onParsedValue(e.target.value === "" && param.nullable ? null : String(e.target.value))}
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

                const spec = pipelineStepSpecsFromApi[selectedStep.name];
                if (!spec) {
                  return Object.keys(selectedStep.params || {}).map((k) => {
                    const v = (selectedStep.params as any)[k];
                    const isNum = Number.isFinite(Number(v));
                    return (
                      <label key={k} className="inline" style={{ justifyContent: "space-between" }}>
                        {k}
                        {isNum ? (
                          <DraftNumberInput
                            value={v}
                            onChange={(n) => {
                              if (n != null) updateSelectedStepParam(k, n);
                            }}
                          />
                        ) : (
                          <input
                            type="text"
                            value={String(v)}
                            onChange={(e) => updateSelectedStepParam(k, e.target.value)}
                            style={{ width: "180px" }}
                          />
                        )}
                      </label>
                    );
                  });
                }

                const p =
                  selectedStep.name === "x_axis_calibration"
                    ? (normalizeXAxisCalibrationParams(
                        selectedStep.params as Record<string, unknown>,
                        pipelineTechniqueFamily
                      ) as unknown as Record<string, unknown>)
                    : normalizeMethodParams(
                        selectedStep.name,
                        selectedStep.params,
                        fittingCatalog,
                        baselineCatalog,
                        pipelineStepSpecsFromApi
                      );
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

                const fittingStepOptions =
                  selectedStep.name === "x_axis_calibration" && method === "reference_peak"
                    ? earlierFittingStepOptions(steps, selectedStep.id)
                    : [];
                const selectedFittingStepId = String((p as any).fitting_step_id ?? "");
                const fittingStepIsInvalid =
                  selectedStep.name === "x_axis_calibration" &&
                  method === "reference_peak" &&
                  selectedFittingStepId !== "" &&
                  !fittingStepOptions.some(({ step }) => step.id === selectedFittingStepId);
                const multiFit = multiFittingInPipeline(steps);
                const selectedFittingOpt = fittingStepOptions.find(({ step }) => step.id === selectedFittingStepId);
                const posKeyOptions = selectedFittingOpt
                  ? fittingPosKeysForStep(selectedFittingOpt.step, {
                      stepIndex: selectedFittingOpt.index,
                      multiFitting: multiFit,
                    })
                  : [];
                const selectedPosKey = String((p as any).pos_key ?? "");
                const posKeyIsInvalid =
                  selectedStep.name === "x_axis_calibration" &&
                  method === "reference_peak" &&
                  selectedPosKey !== "" &&
                  !posKeyOptions.includes(selectedPosKey);

                return (
                  <>
                    <label className="inline" style={{ justifyContent: "space-between" }}>
                      <ParamLabel label={spec.methodLabel || "method"} description={`Select the ${spec.methodLabel || "method"} variant for this step.`} />
                      <select
                        value={method}
                        onChange={(e) => {
                          const nextMethod = String(e.target.value || "");
                          const mm = spec.methods.find((x) => x.id === nextMethod) ?? spec.methods[0];
                          if (selectedStep.name === "x_axis_calibration") {
                            const base = defaultXAxisCalibrationParams(pipelineTechniqueFamily);
                            setSelectedStepParams({
                              ...base,
                              ...(mm?.defaults ?? {}),
                              method: nextMethod,
                              target_x:
                                nextMethod === "reference_peak" && pipelineTechniqueFamily === "xps"
                                  ? 284.8
                                  : Number((mm?.defaults as any)?.target_x ?? base.target_x),
                            });
                            return;
                          }
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

                    {selectedStep.name === "x_axis_calibration" && method === "reference_peak" ? (
                      <>
                        <label className="inline" style={{ justifyContent: "space-between" }}>
                          fitting step
                          <select
                            value={selectedFittingStepId}
                            onChange={(e) => {
                              const nextId = String(e.target.value || "");
                              const opt = fittingStepOptions.find(({ step }) => step.id === nextId);
                              const nextKeys = opt
                                ? fittingPosKeysForStep(opt.step, { stepIndex: opt.index, multiFitting: multiFit })
                                : [];
                              setSelectedStepParams({
                                ...normalizeXAxisCalibrationParams(
                                  selectedStep.params as Record<string, unknown>,
                                  pipelineTechniqueFamily
                                ),
                                method: "reference_peak",
                                fitting_step_id: nextId,
                                pos_key: nextKeys.includes(selectedPosKey) ? selectedPosKey : nextKeys[0] ?? "",
                              });
                            }}
                          >
                            <option value="">Select fitting step…</option>
                            {fittingStepOptions.map(({ step, index }) => {
                              const region = String((step.params as any)?.xps_region || "").trim();
                              const nComp = Array.isArray((step.params as any)?.components)
                                ? (step.params as any).components.length
                                : 0;
                              const suffix = region ? ` (${region})` : nComp ? ` (${nComp} component${nComp === 1 ? "" : "s"})` : "";
                              return (
                                <option key={step.id} value={step.id}>
                                  Step {index + 1}: fitting{suffix}
                                </option>
                              );
                            })}
                          </select>
                        </label>
                        {!fittingStepOptions.length ? (
                          <div className="hint">Add or move an enabled fitting step before this calibration step.</div>
                        ) : null}
                        {fittingStepIsInvalid ? (
                          <div className="err">Selected fitting step is no longer an earlier enabled fitting step.</div>
                        ) : null}
                        <label className="inline" style={{ justifyContent: "space-between" }}>
                          position key
                          <select
                            value={selectedPosKey}
                            onChange={(e) => updateSelectedStepParam("pos_key", String(e.target.value || ""))}
                            disabled={!selectedFittingStepId || !posKeyOptions.length}
                          >
                            <option value="">Select pos key…</option>
                            {posKeyOptions.map((key) => (
                              <option key={key} value={key}>
                                {key}
                              </option>
                            ))}
                          </select>
                        </label>
                        {selectedFittingStepId && !posKeyOptions.length ? (
                          <div className="hint">Selected fitting step has no peak position parameters.</div>
                        ) : null}
                        {posKeyIsInvalid ? (
                          <div className="err">Selected position key is not available on the chosen fitting step.</div>
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
                          <DraftNumberInput
                            value={v}
                            integer={isInt}
                            onChange={(n) => {
                              if (n != null) updateSelectedStepParam(f.key, n);
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
              <div className="hint">Select a step on the left to edit parameters.</div>
            )
          }
          footer={
            <>
        <div className="section-title">Run</div>
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
            </>
          }
        />
            </div>
          }
        />
      </div>
    </div>
  );
}

