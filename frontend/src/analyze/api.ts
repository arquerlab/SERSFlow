import { fetchBlob, fetchJson } from "../lib/http";
import type { PcaScaler } from "./types";
import type { Pipeline, SubsetStrategy } from "../preprocess/api";

// --- Sessions (list) ---

export type SessionListItem = {
  session_id: string;
  dataset_id: string;
  created_at: string;
  updated_at: string;
};

export type SessionListResponse = { items: SessionListItem[]; count: number };

export function listSessions(datasetId: string, limit = 50) {
  const p = new URLSearchParams({ dataset_id: datasetId, limit: String(limit) });
  return fetchJson<SessionListResponse>(`/sessions?${p.toString()}`);
}

// --- Analysis ---

export type AnalysisRunSummary = {
  run_id: string;
  dataset_id: string;
  dataset_name: string | null;
  session_id: string | null;
  pipeline_id: string | null;
  pipeline_name: string | null;
  pipeline_hash: string;
  pipeline_summary: string | null;
  subset_hash: string;
  status: string;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  label: string | null;
  pinned: boolean;
  feature_columns: string[] | null;
};

export type AnalysisRunCreateBody = {
  dataset_id: string;
  session_id?: string | null;
  pipeline_id?: string | null;
  pipeline_name?: string | null;
  pipeline?: Pipeline | null;
  subset?: SubsetStrategy | null;
  /** Maps to JSON `async` (async analysis job). */
  async_job?: boolean;
  label?: string | null;
  pin?: boolean;
};

export function listAnalysisRuns(datasetId: string, limit = 50) {
  return fetchJson<AnalysisRunSummary[]>(
    `/analysis/runs?${new URLSearchParams({ dataset_id: datasetId, limit: String(limit) }).toString()}`
  );
}

export function getAnalysisRun(runId: string) {
  return fetchJson<{ run: AnalysisRunSummary }>(`/analysis/runs/${encodeURIComponent(runId)}`);
}

export type AnalysisRunCreateResponse = {
  run_id: string;
  job_id: string | null;
  status: string;
  message: string | null;
};

export function createAnalysisRun(body: AnalysisRunCreateBody) {
  const payload: Record<string, unknown> = {
    dataset_id: body.dataset_id,
    async: body.async_job ?? false,
  };
  if (body.session_id) payload.session_id = body.session_id;
  if (body.pipeline_id) payload.pipeline_id = body.pipeline_id;
  if (body.pipeline_name) payload.pipeline_name = body.pipeline_name;
  if (!body.session_id && body.pipeline) payload.pipeline = body.pipeline;
  if (!body.session_id && body.subset) payload.subset = body.subset;
  if (body.label != null) payload.label = body.label;
  if (body.pin) payload.pin = body.pin;
  return fetchJson<AnalysisRunCreateResponse>(`/analysis/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteAnalysisRun(runId: string) {
  return fetchJson<{ deleted: boolean }>(`/analysis/runs/${encodeURIComponent(runId)}`, {
    method: "DELETE",
  });
}

export function deleteAllAnalysisRuns(datasetId: string) {
  const p = new URLSearchParams({ dataset_id: datasetId });
  return fetchJson<{ deleted: boolean; runs_deleted: number }>(`/analysis/runs?${p.toString()}`, {
    method: "DELETE",
  });
}

export type AnalysisJobStatus = {
  job_id: string;
  run_id: string;
  status: string;
  progress_done: number;
  progress_total: number;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export function getAnalysisJob(jobId: string) {
  return fetchJson<AnalysisJobStatus>(`/analysis/jobs/${encodeURIComponent(jobId)}`);
}

export function getExportManifestUrl(runId: string) {
  return `/analysis/runs/${encodeURIComponent(runId)}/export/manifest`;
}

export type AnalysisExportManifestJson = Record<string, unknown>;

export function fetchExportManifest(runId: string) {
  return fetchJson<AnalysisExportManifestJson>(getExportManifestUrl(runId));
}

export function getExportBundleUrl(runId: string) {
  return `/analysis/runs/${encodeURIComponent(runId)}/export/bundle`;
}

export function getExportFeaturesUrl(runId: string, layout: "wide" | "long", maxRows?: number) {
  const p = new URLSearchParams({ layout });
  if (maxRows != null) p.set("max_rows", String(maxRows));
  return `/analysis/runs/${encodeURIComponent(runId)}/export?${p}`;
}

export function getObservationUrl(
  runId: string,
  opts: { layout: "wide" | "long"; format?: "csv" | "parquet"; join?: string; max_rows?: number }
) {
  const p = new URLSearchParams({ layout: opts.layout });
  if (opts.format) p.set("format", opts.format);
  if (opts.join) p.set("join", opts.join);
  if (opts.max_rows != null) p.set("max_rows", String(opts.max_rows));
  return `/analysis/runs/${encodeURIComponent(runId)}/observation?${p}`;
}

export type ObservationSchema = {
  feature_keys: string[];
  axis_keys: string[];
  meta_keys: string[];
};

export function fetchObservationSchema(runId: string) {
  return fetchJson<ObservationSchema>(`/analysis/runs/${encodeURIComponent(runId)}/observation-schema`);
}

export function getObservationColumnsUrl(runId: string, cols: string[], maxRows?: number) {
  const p = new URLSearchParams({ cols: cols.join(",") });
  if (maxRows != null) p.set("max_rows", String(maxRows));
  return `/analysis/runs/${encodeURIComponent(runId)}/observation-columns?${p}`;
}

export function fetchObservationColumns(runId: string, cols: string[], maxRows?: number) {
  return fetchJson<{ rows: Record<string, unknown>[] }>(getObservationColumnsUrl(runId, cols, maxRows));
}

export type AnalysisSpectrumResponse = {
  spectrum_id: string;
  relative_path: string | null;
  file_kind: string | null;
  axis_time_s: number | null;
  axis_map_x: number | null;
  axis_map_y: number | null;
  x: Array<number | null>;
  y: Array<number | null>;
};

export function fetchAnalysisSpectrum(runId: string, spectrumId: string) {
  return fetchJson<AnalysisSpectrumResponse>(
    `/analysis/runs/${encodeURIComponent(runId)}/spectra/${encodeURIComponent(spectrumId)}`
  );
}

// --- Explore ---

export type MatrixExportResponse = { matrix_job_id: string; status: string };

export function postMatrixJob(body: {
  dataset_id?: string | null;
  analysis_run_id?: string | null;
  session_id?: string | null;
  pipeline?: Pipeline | null;
  up_to_step?: string | null;
  async?: boolean;
}) {
  return fetchJson<MatrixExportResponse>(`/explore/matrix-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, async: body.async ?? false }),
  });
}

export type MatrixJobStatus = {
  matrix_job_id: string;
  status: string;
  dataset_id: string;
  npz_path: string | null;
  manifest: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

export function getMatrixJob(id: string) {
  return fetchJson<MatrixJobStatus>(`/explore/matrix-jobs/${encodeURIComponent(id)}`);
}

export function getMatrixJobExportUrl(id: string) {
  return `/explore/matrix-jobs/${encodeURIComponent(id)}/export.csv`;
}

export function getExplorePcaExportUrl(
  exploreId: string,
  kind: "scores" | "loadings" | "variance" | "mean"
) {
  return `/explore/runs/${encodeURIComponent(exploreId)}/export/${kind}.csv`;
}

export type ExploreJobResponse = {
  explore_id: string;
  artifact_dir: string;
  results: Record<string, unknown>;
};

export function postCorrelation(body: { analysis_run_id: string; feature_columns?: string[] | null }) {
  return fetchJson<ExploreJobResponse>(`/explore/correlation`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postVif(body: { analysis_run_id: string; feature_columns: string[] }) {
  return fetchJson<ExploreJobResponse>(`/explore/vif`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postPca(body: {
  analysis_run_id: string;
  n_components?: number | null;
  feature_columns?: string[] | null;
  method?: "pca" | "spca";
  scaler?: PcaScaler;
  spca_alpha?: number;
  spca_ridge_alpha?: number;
}) {
  return fetchJson<ExploreJobResponse>(`/explore/pca`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postCluster(body: {
  analysis_run_id: string;
  n_clusters?: number;
  feature_columns?: string[] | null;
  seed?: number;
}) {
  return fetchJson<ExploreJobResponse>(`/explore/cluster`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postFpcaDiscrete(body: {
  matrix_job_id: string;
  method?: "pca" | "spca";
  n_components?: number | null;
  scaler?: PcaScaler;
  spca_alpha?: number;
  spca_ridge_alpha?: number;
}) {
  return fetchJson<ExploreJobResponse>(`/explore/fpca-discrete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postSpectrumCluster(body: {
  matrix_job_id: string;
  n_clusters?: number;
  seed?: number;
  n_pc_embedding?: number;
}) {
  return fetchJson<ExploreJobResponse>(`/explore/spectrum-cluster`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postFpcaFda(body: { matrix_job_id: string; n_components?: number | null }) {
  return fetchJson<ExploreJobResponse>(`/explore/fpca-fda`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Download blob from same-origin URL (e.g. export CSV). */
export function downloadUrl(url: string) {
  return fetchBlob(url);
}

export type SpectrumAxesPage = {
  items: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
};

export function getSpectrumAxesPage(datasetId: string, limit = 50, offset = 0) {
  const p = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return fetchJson<SpectrumAxesPage>(
    `/datasets/${encodeURIComponent(datasetId)}/spectrum-axes?${p}`
  );
}
