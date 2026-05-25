import type { PipelineLibraryItem } from "./api";

export function datasetOptionLabel(d: { dataset_id: string; count: number; metadata?: { name?: string | null } }) {
  const n = d.metadata?.name?.trim();
  if (n) return `${n} (${d.dataset_id}) — ${d.count}`;
  return `${d.dataset_id} (${d.count})`;
}

export function pipelineOptionLabel(it: PipelineLibraryItem) {
  const n = it.name?.trim();
  if (n) return `${n} (${it.pipeline_id})`;
  return it.pipeline_id;
}
