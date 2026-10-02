import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchJson } from "../../lib/http";

export type FormatUiTreatment = {
  show_block_picker: boolean;
  show_spectrum_mode: boolean;
  show_region_filter: boolean;
  show_skip_summary: boolean;
  plot_mode: "xy" | "multi_overlay" | "map";
  default_x_label: string | null;
  default_y_label: string | null;
  create_dataset_hints: string[];
};

export type FormatCatalogItem = {
  id: string;
  label: string;
  suffixes: string[];
  technique_family: string | null;
  technique_sniff?: boolean;
  capabilities: string[];
  ui: FormatUiTreatment;
  filter_fields: { key: string; label: string; kind: string; source: string }[];
  docs: string;
};

export type FormatsCatalogResponse = { items: FormatCatalogItem[] };

async function fetchFormatsCatalog(): Promise<FormatsCatalogResponse> {
  return fetchJson<FormatsCatalogResponse>("/meta/formats");
}

export function useFormatsCatalog() {
  return useQuery({
    queryKey: ["meta", "formats"],
    queryFn: fetchFormatsCatalog,
    staleTime: 60 * 60_000,
  });
}

/** Union of all registered suffixes for file inputs. */
export function acceptFromFormats(items: FormatCatalogItem[] | undefined): string {
  const suffixes = new Set<string>();
  for (const it of items ?? []) {
    for (const s of it.suffixes) suffixes.add(s.toLowerCase());
  }
  if (!suffixes.size) return ".txt,.wdf,.vms,.nxs,.nx5";
  return Array.from(suffixes).sort().join(",");
}

export function formatForPath(
  path: string,
  items: FormatCatalogItem[] | undefined
): FormatCatalogItem | undefined {
  const lower = path.toLowerCase();
  const dot = lower.lastIndexOf(".");
  if (dot < 0) return undefined;
  const suffix = lower.slice(dot);
  return (items ?? []).find((f) => f.suffixes.some((s) => s.toLowerCase() === suffix));
}

/** Infer technique from formats catalog when available; else vibrational. */
export function inferTechniqueFromFormatsCatalog(
  path: string,
  items: FormatCatalogItem[] | undefined
): "vibrational" | "xps" {
  const fmt = formatForPath(path, items);
  if (fmt?.technique_family === "xps" || fmt?.technique_family === "vibrational") {
    return fmt.technique_family;
  }
  // sniff formats (.txt): leave vibrational as safe default for client-side counting
  return "vibrational";
}

/** OR-merge UI treatments for selected upload paths. */
export function mergedUiForPaths(
  paths: string[],
  items: FormatCatalogItem[] | undefined
): FormatUiTreatment {
  const base: FormatUiTreatment = {
    show_block_picker: false,
    show_spectrum_mode: false,
    show_region_filter: false,
    show_skip_summary: false,
    plot_mode: "xy",
    default_x_label: null,
    default_y_label: null,
    create_dataset_hints: [],
  };
  const hints: string[] = [];
  for (const p of paths) {
    const fmt = formatForPath(p, items);
    if (!fmt) continue;
    const ui = fmt.ui;
    base.show_block_picker = base.show_block_picker || ui.show_block_picker;
    base.show_spectrum_mode = base.show_spectrum_mode || ui.show_spectrum_mode;
    base.show_region_filter = base.show_region_filter || ui.show_region_filter;
    base.show_skip_summary = base.show_skip_summary || ui.show_skip_summary;
    if (ui.plot_mode !== "xy") base.plot_mode = ui.plot_mode;
    if (!base.default_x_label && ui.default_x_label) base.default_x_label = ui.default_x_label;
    if (!base.default_y_label && ui.default_y_label) base.default_y_label = ui.default_y_label;
    hints.push(...(ui.create_dataset_hints ?? []));
  }
  base.create_dataset_hints = hints;
  return base;
}

export function useMergedFormatUi(paths: string[]) {
  const q = useFormatsCatalog();
  const ui = useMemo(() => mergedUiForPaths(paths, q.data?.items), [paths, q.data?.items]);
  return { ...q, ui };
}
