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
  record_index?: number | null;
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

export type PipelineStep = { name: string; params?: Record<string, unknown>; enabled?: boolean };
export type Pipeline = { steps: PipelineStep[] };

export type SessionCreateResponse = { session: { session_id: string } };
export type SessionPipelineUpdateResponse = { pipeline: Pipeline; pipeline_hash: string };
export type SessionSubsetUpdateResponse = { subset: SubsetStrategy; resolved: { count: number; dataset_indices: number[] } };
export type DatasetCreateResponse = { dataset: Dataset };
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

function formatErrorDetail(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return JSON.stringify(detail);
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return `Request failed (${status})`;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = (data && typeof data === "object" && "detail" in data ? (data as any).detail : null) ?? text;
    throw new Error(formatErrorDetail(detail, res.status));
  }
  return data as T;
}

export function listDatasets(limit = 200, offset = 0) {
  return fetchJson<DatasetListResponse>(`/datasets?limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`);
}

export function getDataset(datasetId: string) {
  return fetchJson<DatasetGetResponse>(`/datasets/${encodeURIComponent(datasetId)}`);
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

export function runSession(sessionId: string, payload: SessionRunRequest) {
  return fetchJson<SessionRunFinalResponse | SessionRunMetricsResponse | SessionRunIntermediatesResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/run`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export type PipelineRunRequest = { inputs: SpectrumRef[]; pipeline: Pipeline; return: { kind: "final" } | { kind: "metrics_only"; metrics: string[] }; up_to_step?: string | null; cache_namespace?: string | null };
export type PipelineRunFinalResponse = { items: SpectrumSeries[] };

export function runPipeline(payload: PipelineRunRequest) {
  return fetchJson<PipelineRunFinalResponse>(`/pipeline/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listPipelines(limit = 100, offset = 0, q?: string | null) {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (q != null && String(q).trim() !== "") params.set("q", String(q).trim());
  return fetchJson<PipelineListResponse>(`/pipelines?${params.toString()}`);
}

export function createPipelineLibraryEntry(name: string, pipeline: Pipeline) {
  return fetchJson<PipelineCreateResponse>(`/pipelines`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, pipeline }),
  });
}

export function getPipelineLibraryEntry(pipelineId: string) {
  return fetchJson<PipelineGetResponse>(`/pipelines/${encodeURIComponent(pipelineId)}`);
}

