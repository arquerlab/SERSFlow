export type DatasetMetadata = {
  name?: string | null;
  description?: string | null;
  tags?: string[];
  created_by?: string | null;
  created_at?: string | null;
};

export type DatasetListItem = { dataset_id: string; count: number; metadata?: DatasetMetadata };
export type SpectrumRef = {
  spectrum_id: string;
  relative_path: string;
  source?: string | null;
  record_index?: number | null;
  blob_id?: string | null;
  blob_relative_path?: string | null;
  original_relative_path?: string | null;
};

export type Dataset = {
  dataset_id: string;
  spectra: SpectrumRef[];
  metadata?: DatasetMetadata;
};

export type SubsetStrategy =
  | { kind: "all" }
  | { kind: "random"; n: number; seed?: number | null }
  | { kind: "indices"; indices: number[] }
  | { kind: "top_n"; metric: string; direction?: "min" | "max"; n: number }
  | { kind: "outliers"; metric: string; zscore_threshold?: number; n: number };

export type PipelineInputFrom = "previous" | "initial" | "after_step";

export type NormalizeScalarParams = {
  method?: "max" | "min" | "mean" | "median" | "vector" | "l2";
};

export type NormalizeSpectrumPointParams = {
  method: "spectrum_point";
  point_x: number;
};

export type NormalizeBaselinePointParams = {
  method: "baseline_point";
  baseline_step_id: string;
  point_x: number;
};

export type NormalizeLegacyBaselineParams = {
  method: "baseline";
  baseline_point: number;
};

export type NormalizeParams =
  | NormalizeScalarParams
  | NormalizeSpectrumPointParams
  | NormalizeBaselinePointParams
  | NormalizeLegacyBaselineParams;

export type PipelineStep = {
  name: string;
  params?: Record<string, unknown>;
  enabled?: boolean;
  impl_version?: string | null;
  step_id?: string | null;
  input_from?: PipelineInputFrom;
  after_step_id?: string | null;
};
export type Pipeline = { steps: PipelineStep[] };

export type SessionCreateResponse = { session: { session_id: string } };
export type SessionPipelineUpdateResponse = { pipeline: Pipeline; pipeline_hash: string };
export type SessionSubsetUpdateResponse = { subset: SubsetStrategy; resolved: { count: number; dataset_indices: number[] } };
export type SkippedUpload = { relative_path: string; reason: string };
export type DatasetCreateResponse = { dataset: Dataset; skipped_files?: SkippedUpload[] };
export type DatasetGetResponse = { dataset: Dataset };
export type DatasetListResponse = { items: DatasetListItem[]; count: number };

export type SessionRunReturnSpec =
  | { kind: "final" }
  | { kind: "metrics_only"; metrics: string[] }
  | { kind: "intermediates"; steps: string[] };

export type SessionRunRequest = { scope: "subset" | "all"; return: SessionRunReturnSpec; up_to_step: string | null };

export type SpectrumSeries = { spectrum_id: string; x: number[]; y: number[] };
export type MetricValue = { name: string; value: number | null; unit: string | null };
export type SpectrumMetrics = { spectrum_id: string; metrics: MetricValue[] };

export type SessionRunFinalResponse = { items: SpectrumSeries[] };
export type SessionRunMetricsResponse = { items: SpectrumMetrics[] };
export type SessionRunIntermediatesResponse = { items: { spectrum_id: string; steps: Record<string, { x: number[]; y: number[] }> }[] };

export type SessionQcPreviewRequest = {
  scope: "subset" | "all";
  step_id: string;
  step_params: Record<string, unknown>;
};

export type SessionQcScoreRow = { spectrum_id: string; score: number | null; flagged: boolean };
export type SessionQcPreviewResponse = {
  step_id: string;
  step_name: string;
  summary: { total: number; flagged_count: number; flagged_pct: number };
  histogram: { bins: number[]; counts: number[]; nonfinite: number };
  threshold: number;
  direction: "below" | "above";
  scores: SessionQcScoreRow[];
  meta: Record<string, unknown>;
};

export type PipelineLibraryItem = {
  pipeline_id: string;
  name: string;
  pipeline: Pipeline;
  created_at: string;
  updated_at: string;
};

export type PipelineListResponse = { items: PipelineLibraryItem[]; count: number };
export type PipelineGetResponse = { item: PipelineLibraryItem };
export type PipelineCreateResponse = { item: PipelineLibraryItem };
export type PipelineUpdateResponse = { item: PipelineLibraryItem };
export type DatasetRestoreUploadsItem = {
  original_relative_path: string;
  relative_path: string;
  filename: string;
  status: "restored" | "reactivated" | "already_active" | "missing";
  reason?: string | null;
};
export type DatasetRestoreUploadsResponse = {
  restored: DatasetRestoreUploadsItem[];
  reactivated: DatasetRestoreUploadsItem[];
  already_active: DatasetRestoreUploadsItem[];
  missing: DatasetRestoreUploadsItem[];
};
export type DatasetImportResponse = {
  dataset: Dataset;
  imported_spectra: number;
  imported_blobs: number;
  imported_labels: number;
};
export type PipelineExportPackage = {
  schema_version: "sersflow.pipeline.v1";
  created_by?: string;
  exported_at?: string;
  name: string;
  pipeline: Pipeline;
  source_pipeline_id?: string | null;
};
export type PipelineImportResponse = { item: PipelineLibraryItem };

import { fetchBlob, fetchJson } from "../lib/http";

export function listDatasets(limit = 200, offset = 0) {
  return fetchJson<DatasetListResponse>(`/datasets?limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`);
}

export function getDataset(datasetId: string) {
  return fetchJson<DatasetGetResponse>(`/datasets/${encodeURIComponent(datasetId)}`);
}

export function restoreDatasetUploads(datasetId: string, options?: { force_copy?: boolean }) {
  return fetchJson<DatasetRestoreUploadsResponse>(`/datasets/${encodeURIComponent(datasetId)}/restore-uploads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force_copy: !!options?.force_copy }),
  });
}

export function exportDatasetPackage(datasetId: string) {
  return fetchBlob(`/datasets/${encodeURIComponent(datasetId)}/export`);
}

export function importDatasetPackage(file: File) {
  const form = new FormData();
  form.append("file", file);
  return fetchJson<DatasetImportResponse>(`/datasets/import`, {
    method: "POST",
    body: form,
  });
}

export function createDatasetFromUploads(relativePaths: string[], metadata?: DatasetMetadata) {
  const md: Record<string, unknown> = {};
  if (metadata?.name != null && String(metadata.name).trim() !== "") md.name = String(metadata.name).trim();
  if (metadata?.description != null && String(metadata.description).trim() !== "") md.description = String(metadata.description).trim();
  if (metadata?.tags?.length) md.tags = metadata.tags;
  return fetchJson<DatasetCreateResponse>(`/datasets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ relative_paths: relativePaths, metadata: md }),
  });
}

export function createSession(datasetId: string, subset: SubsetStrategy, pipeline: Pipeline) {
  return fetchJson<SessionCreateResponse>(`/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ dataset_id: datasetId, subset, pipeline }),
  });
}

export function clearAllDatasets() {
  return fetchJson<{ deleted: boolean; datasets_deleted: number; sessions_deleted: number }>(`/datasets`, {
    method: "DELETE",
  });
}

export function deleteDataset(datasetId: string) {
  return fetchJson<{ deleted: boolean; sessions_deleted: number }>(`/datasets/${encodeURIComponent(datasetId)}`, {
    method: "DELETE",
  });
}

export function updateSessionPipeline(sessionId: string, pipeline: Pipeline) {
  return fetchJson<SessionPipelineUpdateResponse>(`/sessions/${encodeURIComponent(sessionId)}/pipeline`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pipeline }),
  });
}

export function updateSessionSubset(sessionId: string, subset: SubsetStrategy) {
  return fetchJson<SessionSubsetUpdateResponse>(`/sessions/${encodeURIComponent(sessionId)}/subset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subset),
  });
}

export function runSession(sessionId: string, payload: SessionRunRequest, init?: RequestInit) {
  return fetchJson<SessionRunFinalResponse | SessionRunMetricsResponse | SessionRunIntermediatesResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/run`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      ...init,
    }
  );
}

export function previewSessionQc(sessionId: string, payload: SessionQcPreviewRequest, init?: RequestInit) {
  return fetchJson<SessionQcPreviewResponse>(`/sessions/${encodeURIComponent(sessionId)}/qc/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    ...init,
  });
}

export type PipelineRunRequest = { inputs: SpectrumRef[]; pipeline: Pipeline; return: { kind: "final" } | { kind: "metrics_only"; metrics: string[] }; up_to_step?: string | null; cache_namespace?: string | null };
export type PipelineRunFinalResponse = { items: SpectrumSeries[] };

export function runPipeline(payload: PipelineRunRequest, init?: RequestInit) {
  return fetchJson<PipelineRunFinalResponse>(`/pipeline/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    ...init,
  });
}

export type BaselineParamKind = "number" | "int" | "boolean" | "string" | "json";
export type BaselineUiRole = "primary" | "advanced" | "hidden";

export type BaselineParamSpecPublic = {
  key: string;
  kind: BaselineParamKind;
  default: unknown;
  nullable: boolean;
  ui_role: BaselineUiRole;
  description: string;
  options?: string[];
};

export type BaselineMethodSpecPublic = {
  id: string;
  label: string;
  category: string;
  ui_enabled?: boolean;
  params: BaselineParamSpecPublic[];
};

export type BaselineCategorySpecPublic = {
  id: string;
  label: string;
};

export type BaselineMethodsResponse = {
  categories: BaselineCategorySpecPublic[];
  methods: BaselineMethodSpecPublic[];
};

export function listBaselineMethods() {
  return fetchJson<BaselineMethodsResponse>(`/pipeline/baseline-methods`);
}

export function listPipelines(limit = 100, offset = 0, q?: string | null) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (q != null && String(q).trim() !== "") params.set("q", String(q).trim());
  return fetchJson<PipelineListResponse>(`/pipelines?${params.toString()}`);
}

export function createPipelineLibraryEntry(name: string, pipeline: Pipeline, options?: { overwrite?: boolean }) {
  const params = new URLSearchParams();
  if (options?.overwrite) params.set("overwrite", "true");
  const qs = params.toString();
  const url = qs ? `/pipelines?${qs}` : `/pipelines`;
  return fetchJson<PipelineCreateResponse>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, pipeline }),
  });
}

export function getPipelineLibraryEntry(pipelineId: string) {
  return fetchJson<PipelineGetResponse>(`/pipelines/${encodeURIComponent(pipelineId)}`);
}

export function updatePipelineLibraryEntry(
  pipelineId: string,
  body: { name?: string; pipeline?: Pipeline }
) {
  return fetchJson<PipelineUpdateResponse>(`/pipelines/${encodeURIComponent(pipelineId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deletePipelineLibraryEntry(pipelineId: string) {
  return fetchJson<{ deleted: boolean }>(`/pipelines/${encodeURIComponent(pipelineId)}`, {
    method: "DELETE",
  });
}

export function exportPipelineLibraryEntry(pipelineId: string) {
  return fetchBlob(`/pipelines/${encodeURIComponent(pipelineId)}/export`);
}

export function importPipelineLibraryEntry(payload: PipelineExportPackage | { name?: string | null; pipeline: Pipeline }) {
  const body =
    "schema_version" in payload
      ? { schema_version: payload.schema_version, name: payload.name, pipeline: payload.pipeline }
      : { schema_version: "sersflow.pipeline.v1", name: payload.name ?? null, pipeline: payload.pipeline };
  return fetchJson<PipelineImportResponse>(`/pipelines/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** GET /fitting/models */
export type FittingParamSpecPublic = {
  key: string;
  label: string;
  default: number | null;
  bounds_default: { lower: number | null; upper: number | null };
  unit: string | null;
  ui: Record<string, unknown>;
};

export type FittingComponentSpecPublic = {
  component_type: string;
  display_name: string;
  kind: "fixed" | "parametric";
  params: FittingParamSpecPublic[];
};

export type FittingModelsResponse = { components: FittingComponentSpecPublic[] };

export function listFittingModels() {
  return fetchJson<FittingModelsResponse>(`/fitting/models`);
}

export type FitTarget =
  | { kind: "inline"; x: number[]; y: number[] }
  | { kind: "spectrum_ref"; spectrum: SpectrumRef };

export type FitComponentRequest = {
  component_id: string;
  component_type: string;
  degree?: number | null;
};

export type FitRequest = {
  target: FitTarget;
  components: FitComponentRequest[];
  p0: number[];
  bounds: { lower: (number | null)[]; upper: (number | null)[] };
  return_curve?: boolean;
  /** default: use p0; auto: Gaussian amp = intensity at initial pos (backend). */
  initial_guess_mode?: "default" | "auto";
};

export type FitComponentResult = {
  component_id: string;
  component_type: string;
  degree?: number | null;
  param_keys: string[];
  params: Record<string, number>;
  y_hat?: number[] | null;
};

export type FitResponse = {
  params_vector: number[];
  components: FitComponentResult[];
  y_hat: number[] | null;
};

export function postFittingFit(payload: FitRequest, init?: RequestInit) {
  return fetchJson<FitResponse>(`/fitting/fit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    ...init,
  });
}

