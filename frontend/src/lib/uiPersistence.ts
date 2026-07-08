/** Shared keys so Prepare and Analyze stay in sync when switching tabs. */
export const LS_ANALYZE_DATASET = "sersflow_analyze_dataset_id";
export const LS_ANALYZE_SESSION = "sersflow_analyze_session_id";
export const LS_ANALYZE_RUN = "sersflow_analyze_run_id";
export const LS_ANALYZE_PIPELINE = "sersflow_analyze_pipeline_id";

export const LS_PREPARE_UI = "sersflow_prepare_ui";
export const LS_ANALYZE_UI = "sersflow_analyze_ui";

export function safeJsonParse<T>(raw: string | null, fallback: T): T {
  if (raw == null || raw === "") return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export type PrepareUiPrefsV1 = {
  v: 1;
  mode?: "explore" | "batch";
  plotView?: string;
  ghost?: boolean;
  plotMode?: "overlay" | "stack";
  sep?: number;
  autoRun?: boolean;
  subsetSize?: number;
  subsetSeed?: number;
  libraryPipelineName?: string;
  selectedLibraryPipelineId?: string;
  libraryOverwrite?: boolean;
};

export function loadPrepareUiPrefs(): Partial<PrepareUiPrefsV1> {
  const raw = localStorage.getItem(LS_PREPARE_UI);
  const o = safeJsonParse<Partial<PrepareUiPrefsV1> | null>(raw, null);
  if (!o || o.v !== 1) return {};
  return o;
}

export function savePrepareUiPrefs(prefs: PrepareUiPrefsV1): void {
  try {
    localStorage.setItem(LS_PREPARE_UI, JSON.stringify(prefs));
  } catch {
    /* ignore quota */
  }
}

export type AnalyzeUiPrefsV1 = {
  v: 1;
  section?: string;
  corrCols?: string[];
  vifCols?: string[];
  pcaN?: number | "";
  pcaCols?: string[];
  clusterK?: number;
  clusterCols?: string[];
  clusterSeed?: number;
  matrixUpTo?: string;
  selectedMatrixJobId?: string;
  fpcaN?: number | "";
  pcaScaler?: "none" | "standard";
  discreteScaler?: "none" | "standard";
  // Plot selector + plot settings (PCA/FPCA + cluster overlays)
  scoresXpc?: number;
  scoresYpc?: number;
  scoresXMeta?: string;
  scoresYMeta?: string;
  scoresColorMeta?: string;
  pcVsMetaPcs?: number[];
  pcVsMetaX?: string;
  pairplotPcs?: number[];
  loadingsPc?: number;
  loadingsTopN?: number;
  selectedPcaPlots?: string[];
  selectedClusterPlots?: string[];
};

export function loadAnalyzeUiPrefs(): Partial<AnalyzeUiPrefsV1> {
  const raw = localStorage.getItem(LS_ANALYZE_UI);
  const o = safeJsonParse<Partial<AnalyzeUiPrefsV1> | null>(raw, null);
  if (!o || o.v !== 1) return {};
  return o;
}

export function saveAnalyzeUiPrefs(prefs: AnalyzeUiPrefsV1): void {
  try {
    localStorage.setItem(LS_ANALYZE_UI, JSON.stringify(prefs));
  } catch {
    /* ignore */
  }
}
