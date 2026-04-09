import { fetchJson } from "/static/ui/api.js";

export async function listDatasets({ limit = 200, offset = 0 } = {}) {
  return await fetchJson(`/datasets?limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`);
}

export async function getDataset(datasetId) {
  return await fetchJson(`/datasets/${encodeURIComponent(String(datasetId))}`);
}

export async function createSession({ datasetId, pipeline, subset }) {
  return await fetchJson(`/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      dataset_id: datasetId,
      pipeline: pipeline ?? { steps: [] },
      subset: subset ?? { kind: "all" },
    }),
  });
}

export async function updateSessionSubset({ sessionId, subset }) {
  return await fetchJson(`/sessions/${encodeURIComponent(String(sessionId))}/subset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(subset),
  });
}

export async function updateSessionPipeline({ sessionId, pipeline }) {
  return await fetchJson(`/sessions/${encodeURIComponent(String(sessionId))}/pipeline`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pipeline }),
  });
}

export async function runSession({ sessionId, scope, returnSpec, upToStep }) {
  const payload = {
    scope: scope ?? "subset",
    return: returnSpec ?? { kind: "final" },
    up_to_step: upToStep ?? null,
  };
  return await fetchJson(`/sessions/${encodeURIComponent(String(sessionId))}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function sweepPipeline({ inputs, basePipeline, sweep, objective, cacheNamespace }) {
  return await fetchJson(`/pipeline/sweep`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      inputs,
      base_pipeline: basePipeline,
      sweep,
      objective,
      cache_namespace: cacheNamespace ?? null,
    }),
  });
}

