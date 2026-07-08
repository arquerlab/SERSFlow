export type LabelFilterOp = "eq" | "contains" | "exists";

export type LabelFilter = {
  id: string;
  key: string;
  op: LabelFilterOp;
  value?: string;
};

export type LabelSelections = Record<string, string[]>;

export const FILTER_KEYS = [
  "sample",
  "gas",
  "ph",
  "electrolyte",
  "potential_V",
  "laser_nm",
  "laser_power_pct",
  "concentration_M",
] as const;

export type FilterKey = (typeof FILTER_KEYS)[number];

export function labelValueAsString(labels: Record<string, unknown> | undefined | null, key: string): string {
  if (!labels || typeof labels !== "object") return "";
  const v = labels[key];
  if (v == null || v === "") return "";
  return String(v);
}

export function matchesLabelFilters(
  labels: Record<string, unknown> | undefined | null,
  filters: LabelFilter[]
): boolean {
  if (!filters.length) return true;
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

/**
 * Excel-style column filters: AND across keys, OR within a key.
 * If a key has an empty selection list (or missing key), it does not filter.
 */
export function matchesLabelSelections(
  labels: Record<string, unknown> | undefined | null,
  selections: LabelSelections
): boolean {
  if (!selections || typeof selections !== "object") return true;
  for (const [key, allowed] of Object.entries(selections)) {
    if (!Array.isArray(allowed) || allowed.length === 0) continue;
    const raw = labelValueAsString(labels, key);
    if (!allowed.includes(raw)) return false;
  }
  return true;
}

export function distinctLabelValues(
  items: { labels?: Record<string, unknown> | null }[],
  key: string
): string[] {
  const seen = new Set<string>();
  for (const item of items) {
    const s = labelValueAsString(item.labels, key);
    if (s) seen.add(s);
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}

export function newFilterId(): string {
  return `lf_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
