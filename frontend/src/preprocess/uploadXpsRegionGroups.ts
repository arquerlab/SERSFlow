/** Group uploads by XPS region token for the upload picker. */

import { blockSelectionKey, sortedBlockEntries } from "./uploadBlockSpectra";

export type UploadXpsRow = {
  relative_path: string;
  xps_regions?: string[] | null;
  spectrum_count?: number | null;
  technique_family?: string | null;
  filename?: string;
  labels?: Record<string, unknown> | null;
};

export type XpsRegionGroupOption = {
  key: string;
  label: string;
  /** Parent file paths (may include multi-region files). */
  paths: string[];
  /**
   * Selection keys for this region: `path#recordIndex` when block metadata exists,
   * otherwise the bare file path.
   */
  selectionKeys: string[];
  spectrumCount: number;
};

function num(v: unknown): number | null {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function regionKeyFromMeta(meta: Record<string, unknown> | null | undefined): string {
  const r = typeof meta?.xps_region === "string" ? meta.xps_region.trim() : "";
  return r || "__unknown__";
}

/**
 * Group uploads by XPS region. Files without regions go under "Unknown region".
 * Multi-spectrum files contribute per-block selection keys when `labels.vms_spectra` is present.
 */
export function buildXpsRegionGroupOptions(items: UploadXpsRow[]): XpsRegionGroupOption[] {
  const buckets = new Map<string, { paths: string[]; selectionKeys: string[]; spectrumCount: number }>();

  function add(key: string, path: string, selectionKey: string, spectrumDelta: number) {
    const cur = buckets.get(key);
    if (cur) {
      if (!cur.paths.includes(path)) cur.paths.push(path);
      if (!cur.selectionKeys.includes(selectionKey)) cur.selectionKeys.push(selectionKey);
      cur.spectrumCount += spectrumDelta;
    } else {
      buckets.set(key, { paths: [path], selectionKeys: [selectionKey], spectrumCount: spectrumDelta });
    }
  }

  for (const it of items) {
    const path = String(it.relative_path || "");
    if (!path) continue;
    const blocks = sortedBlockEntries(it.labels);
    if (blocks.length) {
      for (const b of blocks) {
        const key = regionKeyFromMeta(b.meta);
        add(key, path, blockSelectionKey(path, b.index), 1);
      }
      continue;
    }
    const regions = Array.isArray(it.xps_regions)
      ? it.xps_regions.map((r) => String(r || "").trim()).filter(Boolean)
      : [];
    const nSpec = Math.max(1, Math.trunc(num(it.spectrum_count) ?? 1));
    const keys = regions.length ? regions : ["__unknown__"];
    for (const key of keys) {
      // Whole-file select when we lack per-block maps; count spectra once per file, not per region tag.
      add(key, path, path, key === keys[0] ? nSpec : 0);
    }
  }

  const out: XpsRegionGroupOption[] = [];
  for (const [key, v] of buckets) {
    if (key === "__unknown__") {
      out.push({
        key,
        label: `Unknown region (${v.paths.length} file(s), ${v.spectrumCount} spectra)`,
        paths: v.paths,
        selectionKeys: v.selectionKeys,
        spectrumCount: v.spectrumCount,
      });
    } else {
      out.push({
        key,
        label: `${key} (${v.paths.length} file(s), ${v.spectrumCount} spectra)`,
        paths: v.paths,
        selectionKeys: v.selectionKeys,
        spectrumCount: v.spectrumCount,
      });
    }
  }

  out.sort((a, b) => {
    if (a.key === "__unknown__") return 1;
    if (b.key === "__unknown__") return -1;
    return a.key.localeCompare(b.key);
  });
  return out;
}

import type { FormatCatalogItem } from "./hooks/useFormatsCatalog";
import { inferTechniqueFromFormatsCatalog } from "./hooks/useFormatsCatalog";

export type TechniqueCountedItem = {
  relative_path?: string;
  technique_family?: string | null;
  filename?: string;
};

/**
 * Infer technique from path when technique_family is missing.
 * Prefer upload.technique_family from the server. When a formats catalog is provided,
 * resolve via registered suffixes; otherwise default to vibrational.
 */
export function inferTechniqueFromPath(
  path: string,
  formatsCatalog?: FormatCatalogItem[]
): "vibrational" | "xps" {
  if (formatsCatalog?.length) {
    return inferTechniqueFromFormatsCatalog(path, formatsCatalog);
  }
  return "vibrational";
}

/** Count XPS vs vibrational among items (path-inferred when family missing). */
export function countTechniqueFamilies(
  items: TechniqueCountedItem[],
  formatsCatalog?: FormatCatalogItem[]
): { xps: number; vibrational: number } {
  let xps = 0;
  let vibrational = 0;
  for (const it of items) {
    const fam =
      it.technique_family === "xps" || it.technique_family === "vibrational"
        ? it.technique_family
        : inferTechniqueFromPath(String(it.relative_path || it.filename || ""), formatsCatalog);
    if (fam === "xps") xps += 1;
    else vibrational += 1;
  }
  return { xps, vibrational };
}

/**
 * Majority technique among items. Tie → vibrational.
 */
export function majorityTechniqueFamily(
  items: TechniqueCountedItem[],
  formatsCatalog?: FormatCatalogItem[]
): "vibrational" | "xps" {
  const { xps, vibrational } = countTechniqueFamilies(items, formatsCatalog);
  if (xps > vibrational) return "xps";
  return "vibrational";
}

/** True when XPS and vibrational counts are equal and both non-zero. */
export function isTechniqueFamilyTie(
  items: TechniqueCountedItem[],
  formatsCatalog?: FormatCatalogItem[]
): boolean {
  const { xps, vibrational } = countTechniqueFamilies(items, formatsCatalog);
  return xps > 0 && xps === vibrational;
}

/** True when selection contains both XPS and vibrational files. */
export function selectionMixesTechniques(
  paths: string[],
  itemsByPath: Map<string, TechniqueCountedItem> | TechniqueCountedItem[]
): boolean {
  const map =
    itemsByPath instanceof Map
      ? itemsByPath
      : new Map(itemsByPath.map((it) => [String(it.relative_path || ""), it]));
  let hasXps = false;
  let hasVib = false;
  for (const p of paths) {
    const it = map.get(p);
    const fam =
      it?.technique_family === "xps" || it?.technique_family === "vibrational"
        ? it.technique_family
        : inferTechniqueFromPath(p);
    if (fam === "xps") hasXps = true;
    else hasVib = true;
    if (hasXps && hasVib) return true;
  }
  return false;
}
