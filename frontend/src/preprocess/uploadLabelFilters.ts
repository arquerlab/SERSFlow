import { effectiveLabelRows } from "./uploadBlockSpectra";

export type LabelFilterOp = "eq" | "contains" | "exists";

export type LabelFilter = {
  id: string;
  key: string;
  op: LabelFilterOp;
  value?: string;
};

export type LabelSelections = Record<string, string[]>;

export const FILTER_KEYS = [
  "xps_region",
  "sample",
  "gas",
  "ph",
  "electrolyte",
  "potential_V",
  "potential_ref",
  "current_density_A_cm2",
  "laser_nm",
  "laser_power_pct",
  "concentration_M",
] as const;

export type FilterKey = (typeof FILTER_KEYS)[number];

const LASER_KEYS = new Set(["laser_nm", "laser_power_pct"]);
const OPTIONAL_APP_KEYS = new Set(["gas", "ph"]);
const ELECTROCHEM_TRIO = ["current_density_A_cm2", "potential_V", "potential_ref"] as const;
const XPS_STRUCTURAL_KEYS = new Set(["xps_region"]);

/**
 * Which Prepare upload filter columns to show for the current item set / technique.
 * Mirrors backend `select_experimental_filter_keys`.
 */
export function visibleFilterKeys(
  items: { labels?: Record<string, unknown> | null; technique_family?: string | null }[],
  techniqueFamily?: string | null
): FilterKey[] {
  const present = new Set<string>();
  for (const item of items) {
    for (const row of effectiveLabelRows(item.labels)) {
      for (const [k, v] of Object.entries(row)) {
        if (v != null && v !== "") present.add(k);
      }
    }
  }
  const family = String(techniqueFamily || "").toLowerCase();
  const out: FilterKey[] = [];
  for (const key of FILTER_KEYS) {
    if (XPS_STRUCTURAL_KEYS.has(key)) {
      if (family === "xps" && present.has(key)) out.push(key);
      continue;
    }
    if (LASER_KEYS.has(key)) {
      if (family === "xps") continue;
      if (!present.has(key)) continue;
      out.push(key);
      continue;
    }
    if (OPTIONAL_APP_KEYS.has(key)) {
      if (!present.has(key)) continue;
      out.push(key);
      continue;
    }
    if ((ELECTROCHEM_TRIO as readonly string[]).includes(key)) {
      continue; // handled as a group below
    }
    if (!present.has(key)) continue;
    out.push(key);
  }
  if (ELECTROCHEM_TRIO.some((k) => present.has(k))) {
    for (const k of ELECTROCHEM_TRIO) out.push(k);
  }
  return out;
}

export function labelValueAsString(labels: Record<string, unknown> | undefined | null, key: string): string {
  if (!labels || typeof labels !== "object") return "";
  const v = labels[key];
  if (v == null || v === "") return "";
  return String(v);
}

function rowMatchesSelections(labels: Record<string, unknown>, selections: LabelSelections): boolean {
  for (const [key, allowed] of Object.entries(selections)) {
    if (!Array.isArray(allowed) || allowed.length === 0) continue;
    const raw = labelValueAsString(labels, key);
    if (!allowed.includes(raw)) return false;
  }
  return true;
}

/** True when a single path/block label row matches Excel-style selections. */
export function labelsMatchSelections(
  labels: Record<string, unknown> | undefined | null,
  selections: LabelSelections
): boolean {
  if (!selections || typeof selections !== "object") return true;
  const hasAny = Object.values(selections).some((a) => Array.isArray(a) && a.length > 0);
  if (!hasAny) return true;
  return rowMatchesSelections(labels || {}, selections);
}

function rowMatchesFilters(labels: Record<string, unknown>, filters: LabelFilter[]): boolean {
  return filters.every((f) => {
    const raw = labelValueAsString(labels, f.key);
    if (f.op === "exists") return raw !== "";
    if (f.op === "eq") return raw === String(f.value ?? "");
    if (f.op === "contains") {
      const needle = String(f.value ?? "").toLowerCase();
      if (!needle) return true;
      return raw.toLowerCase().includes(needle);
    }
    return true;
  });
}

export function matchesLabelFilters(
  labels: Record<string, unknown> | undefined | null,
  filters: LabelFilter[]
): boolean {
  if (!filters.length) return true;
  // OR across path + block rows: file matches if any spectrum matches all filters.
  return effectiveLabelRows(labels).some((row) => rowMatchesFilters(row, filters));
}

/**
 * Excel-style column filters: AND across keys, OR within a key.
 * Multi-spectrum: file matches if ANY path/block row matches (OR across spectra).
 * If a key has an empty selection list (or missing key), it does not filter.
 */
export function matchesLabelSelections(
  labels: Record<string, unknown> | undefined | null,
  selections: LabelSelections
): boolean {
  if (!selections || typeof selections !== "object") return true;
  const hasAny = Object.values(selections).some((a) => Array.isArray(a) && a.length > 0);
  if (!hasAny) return true;
  return effectiveLabelRows(labels).some((row) => rowMatchesSelections(row, selections));
}

export function distinctLabelValues(
  items: { labels?: Record<string, unknown> | null }[],
  key: string
): string[] {
  const seen = new Set<string>();
  for (const item of items) {
    for (const row of effectiveLabelRows(item.labels)) {
      const s = labelValueAsString(row, key);
      if (s) seen.add(s);
    }
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}

export function newFilterId(): string {
  return `lf_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
