import { fetchJson } from "../lib/http";

export type DepthAlignParams = {
  feature_column: string;
  position_columns?: string[];
  mode?: "edge" | "argmax";
  direction?: "down" | "up";
  smooth?: number;
  plateau_z_max?: number | null;
  plateau_n?: number;
  low_z_range?: [number, number] | null;
  search_z_min?: number | null;
  reference?: number[] | null;
};

export type SegmentsBody = {
  analysis_run_id: string;
  feature_columns: string[];
  order_column: string;
  method: "contiguous" | "kmeans";
  n_segments: number;
  k_max: number;
  bin_width: number;
  winsor_pct: number | null;
  robust_clip: number | null;
  standardize: boolean;
  seed: number;
  n_init: number;
  per_position_check: boolean;
  position_columns: string[];
  align: DepthAlignParams | null;
  zone_names?: string[] | null;
};

export type AlignmentPosition = { position: number[]; edge_z: number | null; shift: number | null };

export type AlignmentSummary = {
  reference: number[];
  reference_edge_z: number;
  n_positions: number;
  n_positions_without_edge: number;
  shift_min: number | null;
  shift_max: number | null;
  shift_mean: number | null;
  shift_std: number | null;
  positions: AlignmentPosition[];
};

export type SegmentRow = {
  segment: number;
  n: number;
  z_min: number;
  z_max: number;
  z_median: number;
  median_features?: Record<string, number>;
};

export type SegmentsResult = {
  method: "contiguous" | "kmeans";
  n_segments: number;
  n_rows: number;
  n_dropped_rows: number;
  order_column: string;
  feature_columns: string[];
  cuts?: number[];
  cuts_by_k?: Record<string, number[]>;
  cost_by_k: Record<string, number>;
  silhouette_by_k?: Record<string, number>;
  contiguity?: number;
  per_position_cuts?: { position: number[]; cuts: number[] }[];
  segments: SegmentRow[];
  zone_names: string[];
  spectrum_ids: string[];
  labels: number[];
  z_used: number[];
  z_original: number[];
  alignment?: AlignmentSummary;
};

export type DepthAlignResult = AlignmentSummary & {
  spectrum_ids: string[];
  z_original: number[];
  z_aligned: number[];
  order_column: string;
};

type Job<R> = { explore_id: string; artifact_dir: string; results: R };

export function postSegments(body: SegmentsBody) {
  return fetchJson<Job<SegmentsResult>>(`/explore/segments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postDepthAlign(body: DepthAlignParams & { analysis_run_id: string; order_column: string }) {
  return fetchJson<Job<DepthAlignResult>>(`/explore/depth-align`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
