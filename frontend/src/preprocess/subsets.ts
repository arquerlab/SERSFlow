export type SavedSubset = {
  id: string;
  label: string;
  indices: number[];
  size: number;
  seed?: number;
  createdAt: number;
};

const MAX_SUBSETS_DEFAULT = 15;

export function storageKey(datasetId: string): string {
  return `sersflow.preprocess.savedSubsets.v1.dataset:${datasetId}`;
}

function safeParseArray(raw: string | null): any[] {
  if (!raw) return [];
  try {
    const obj = JSON.parse(raw);
    return Array.isArray(obj) ? obj : [];
  } catch {
    return [];
  }
}

function normalizeSubset(x: any): SavedSubset | null {
  if (!x || typeof x !== "object") return null;
  const id = String((x as any).id || "");
  const label = String((x as any).label || "");
  const indicesRaw = (x as any).indices;
  const indices = Array.isArray(indicesRaw)
    ? indicesRaw.map((v: any) => Number(v)).filter((n: any) => Number.isInteger(n) && n >= 0)
    : [];
  const size = Number((x as any).size);
  const seed = (x as any).seed == null ? undefined : Number((x as any).seed);
  const createdAt = Number((x as any).createdAt);
  if (!id || !label) return null;
  if (!Number.isFinite(size) || size <= 0) return null;
  if (!Number.isFinite(createdAt) || createdAt <= 0) return null;
  if (!indices.length) return null;
  return { id, label, indices, size, seed: Number.isFinite(seed) ? seed : undefined, createdAt };
}

export function loadSavedSubsets(datasetId: string): SavedSubset[] {
  const key = storageKey(datasetId);
  const arr = safeParseArray(localStorage.getItem(key));
  const out: SavedSubset[] = [];
  for (const it of arr) {
    const n = normalizeSubset(it);
    if (n) out.push(n);
  }
  // Oldest-first ordering is convenient for FIFO eviction.
  out.sort((a, b) => a.createdAt - b.createdAt);
  return out;
}

export function saveSavedSubsets(datasetId: string, subsets: SavedSubset[]): void {
  const key = storageKey(datasetId);
  localStorage.setItem(key, JSON.stringify(subsets));
}

export function addSavedSubset(datasetId: string, subset: SavedSubset, limit = MAX_SUBSETS_DEFAULT): SavedSubset[] {
  const cur = loadSavedSubsets(datasetId);
  const next = [...cur, subset].sort((a, b) => a.createdAt - b.createdAt);
  const lim = Math.max(1, Math.min(100, Number(limit) || MAX_SUBSETS_DEFAULT));
  const trimmed = next.length > lim ? next.slice(next.length - lim) : next;
  saveSavedSubsets(datasetId, trimmed);
  return trimmed;
}

export function deleteSavedSubset(datasetId: string, id: string): SavedSubset[] {
  const cur = loadSavedSubsets(datasetId);
  const next = cur.filter((s) => s.id !== id);
  saveSavedSubsets(datasetId, next);
  return next;
}

export function clearSavedSubsets(datasetId: string): void {
  localStorage.removeItem(storageKey(datasetId));
}

