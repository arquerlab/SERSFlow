/** Client helpers for multi-spectrum upload block maps (persisted as labels.vms_spectra). */

export type BlockSpectraMap = Record<string, Record<string, unknown>>;

export const INTERNAL_LABEL_KEYS = new Set(["vms_spectra", "vms_spectrum_mode", "xps_regions_filter"]);

export function getBlockSpectra(labels: Record<string, unknown> | null | undefined): BlockSpectraMap {
  if (!labels || typeof labels !== "object") return {};
  const raw = labels.vms_spectra;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: BlockSpectraMap = {};
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    if (v && typeof v === "object" && !Array.isArray(v)) out[String(k)] = v as Record<string, unknown>;
  }
  return out;
}

/** Technique a block declares (``meta.technique``), mirroring the backend's token mapping. */
export function blockTechnique(meta: Record<string, unknown> | null | undefined): "xps" | "xas" | null {
  const t = String(meta?.technique ?? "").trim().toLowerCase();
  if (t === "xps") return "xps";
  if (t === "xas" || t === "nexafs") return "xas";
  return null;
}

export type EffectiveTechnique = "vibrational" | "xps" | "xas";

export const TECHNIQUE_LABELS: Record<EffectiveTechnique, string> = {
  vibrational: "Vibrational",
  xps: "XPS",
  xas: "XAS",
};

/**
 * Techniques an upload contributes: those its blocks declare (multi-technique files such as .sle),
 * otherwise the file's own technique family (vibrational / XPS / XAS).
 */
export function effectiveTechniques(item: {
  labels?: Record<string, unknown> | null;
  technique_family?: string | null;
}): EffectiveTechnique[] {
  const fromBlocks = new Set<EffectiveTechnique>();
  for (const meta of Object.values(getBlockSpectra(item.labels))) {
    const t = blockTechnique(meta);
    if (t) fromBlocks.add(t);
  }
  if (fromBlocks.size) return (["vibrational", "xps", "xas"] as const).filter((t) => fromBlocks.has(t));
  const fam = item.technique_family;
  return fam === "vibrational" || fam === "xps" || fam === "xas" ? [fam] : [];
}

/**
 * Copy of an upload whose path-level labels carry ``technique`` when its blocks do not, so the
 * technique filter also separates vibrational files from XPS / XAS ones.
 */
export function withEffectiveTechnique<
  T extends { labels?: Record<string, unknown> | null; technique_family?: string | null },
>(item: T): T {
  const techs = effectiveTechniques(item);
  const hasBlockTechnique = Object.values(getBlockSpectra(item.labels)).some((m) => blockTechnique(m));
  if (hasBlockTechnique || techs.length !== 1) return item;
  return { ...item, labels: { ...(item.labels || {}), technique: TECHNIQUE_LABELS[techs[0]] } };
}

export function pathLabelsWithoutInternal(
  labels: Record<string, unknown> | null | undefined
): Record<string, unknown> {
  if (!labels || typeof labels !== "object") return {};
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(labels)) {
    if (INTERNAL_LABEL_KEYS.has(k)) continue;
    out[k] = v;
  }
  return out;
}

/** Path-level keys overlaid by block keys (block wins). Internal keys excluded. */
export function mergePathAndBlockLabels(
  pathLabels: Record<string, unknown> | null | undefined,
  blockLabels: Record<string, unknown> | null | undefined
): Record<string, unknown> {
  return { ...pathLabelsWithoutInternal(pathLabels), ...(blockLabels || {}) };
}

/**
 * Effective label rows for filtering: path-level (sans internal) plus each block.
 * A file matches a filter if ANY row matches (OR across spectra).
 */
export function effectiveLabelRows(
  labels: Record<string, unknown> | null | undefined
): Record<string, unknown>[] {
  const path = pathLabelsWithoutInternal(labels);
  const blocks = getBlockSpectra(labels);
  const entries = Object.keys(blocks)
    .map((k) => Number(k))
    .filter((n) => Number.isFinite(n))
    .sort((a, b) => a - b)
    .map((i) => mergePathAndBlockLabels(labels, blocks[String(i)]));
  if (!entries.length) return [path];
  // Include path row so path-only labels still match when blocks lack the key.
  return [path, ...entries];
}

export function sortedBlockEntries(labels: Record<string, unknown> | null | undefined): Array<{
  index: number;
  meta: Record<string, unknown>;
}> {
  const blocks = getBlockSpectra(labels);
  return Object.keys(blocks)
    .map((k) => ({ index: Number(k), meta: blocks[k] }))
    .filter((x) => Number.isFinite(x.index))
    .sort((a, b) => a.index - b.index);
}

export function blockDisplayName(meta: Record<string, unknown> | null | undefined): string {
  const m = meta || {};
  if (typeof m.block_name === "string" && m.block_name.trim()) return m.block_name;
  const region = typeof m.xps_region === "string" ? m.xps_region : "block";
  const role = typeof m.spectrum_role === "string" ? m.spectrum_role : "spectrum";
  return `${region} · ${role}`;
}

export function blockSelectionKey(relativePath: string, recordIndex: number): string {
  return `${relativePath}#${recordIndex}`;
}

export function parseSelectionKey(key: string): { relativePath: string; recordIndex: number | null } {
  const s = String(key || "");
  const i = s.lastIndexOf("#");
  if (i <= 0) return { relativePath: s, recordIndex: null };
  const tail = s.slice(i + 1);
  if (!/^\d+$/.test(tail)) return { relativePath: s, recordIndex: null };
  return { relativePath: s.slice(0, i), recordIndex: Number(tail) };
}

/** Unique parent file paths from a mix of path and path#index keys. */
export function parentPathsFromSelectionKeys(keys: Iterable<string>): string[] {
  const out = new Set<string>();
  for (const key of keys) {
    const { relativePath } = parseSelectionKey(key);
    if (relativePath) out.add(relativePath);
  }
  return [...out];
}

/**
 * When any block keys (path#idx) exist for a path, return those indices.
 * Paths selected only at file level are omitted (caller uses mode/regions).
 */
export function recordIndicesByPathFromSelectionKeys(keys: Iterable<string>): Record<string, number[]> {
  const byPath = new Map<string, number[]>();
  for (const key of keys) {
    const { relativePath, recordIndex } = parseSelectionKey(key);
    if (recordIndex == null || !relativePath) continue;
    const list = byPath.get(relativePath) || [];
    list.push(recordIndex);
    byPath.set(relativePath, list);
  }
  const out: Record<string, number[]> = {};
  for (const [p, idxs] of byPath) {
    out[p] = [...new Set(idxs)].sort((a, b) => a - b);
  }
  return out;
}
