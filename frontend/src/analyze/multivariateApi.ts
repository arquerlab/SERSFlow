import { fetchJson } from "../lib/http";

export type MatrixPreprocess = {
  crop?: [number, number] | null;
  exclude?: [number, number][] | null;
  bin?: number;
  smooth_window?: number;
  smooth_poly?: number;
  derivative?: 0 | 1 | 2;
  row_norm?: "none" | "area" | "max" | "l2" | "snv" | "ref_band";
  ref_band?: [number, number] | null;
  transform?: "none" | "sqrt" | "log";
  nonneg?: "none" | "clip" | "shift";
  center?: "none" | "mean" | "median";
  scale?: "none" | "autoscale" | "pareto" | "range" | "poisson";
};

export type MvJobResponse<R = Record<string, unknown>> = {
  explore_id: string;
  artifact_dir: string;
  results: R;
};

export type MatrixPreprocessingMeta = {
  steps?: string[];
  warnings?: string[];
  n_channels_in?: number;
  n_channels_out?: number;
};

export type CorrelationMatrixResult = {
  method: "pearson" | "spearman";
  axis: "channels" | "samples";
  labels: string[];
  R: number[][];
  reordered: boolean;
  order?: number[];
  linkage?: string;
  n_constant_variables?: number;
  matrix_preprocessing?: MatrixPreprocessingMeta;
};

/** PCA / NMF / MCR-ALS results share this PCA-like shape. */
export type FactorResult = {
  kind?: string;
  method?: string;
  n_components: number;
  scores: number[][];
  components: number[][];
  explained_variance_ratio?: number[];
  x_cm1: number[];
  spectrum_ids: string[];
  lack_of_fit_pct?: number;
  r2?: number;
  reconstruction_error?: number;
  start_error_spread_pct?: number;
  scan?: { k: number; reconstruction_error: number; lack_of_fit_pct: number }[];
  iterations?: number;
  converged?: boolean;
  rotation?: { method: string; applied: boolean; reason?: string };
  note?: string;
  matrix_preprocessing?: MatrixPreprocessingMeta;
};

export type Cos2dResult = {
  x_cm1: number[];
  synchronous: number[][];
  asynchronous: number[][];
  autopower: number[];
  reference_spectrum: number[];
  perturbation: number[];
  perturbation_label: string;
  n_spectra: number;
  resampled: boolean;
  n_spectra_without_perturbation?: number;
  note?: string;
  matrix_preprocessing?: MatrixPreprocessingMeta;
};

function post<R>(path: string, body: unknown) {
  return fetchJson<MvJobResponse<R>>(`/explore/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function postSpectrumCorrelation(body: {
  matrix_job_id: string;
  axis: "channels" | "samples";
  method: "pearson" | "spearman";
  reorder: boolean;
  linkage: "average" | "complete" | "single" | "ward";
  preprocess?: MatrixPreprocess | null;
}) {
  return post<CorrelationMatrixResult>("spectrum-correlation", body);
}

export function postSpectrumPca(body: {
  matrix_job_id: string;
  n_components: number | null;
  scaler: "none" | "standard";
  rotation: "none" | "varimax";
  preprocess?: MatrixPreprocess | null;
}) {
  return post<FactorResult>("fpca-discrete", { ...body, method: "pca" });
}

export function postSpectrumNmf(body: {
  matrix_job_id: string;
  n_components: number;
  n_starts: number;
  scan_k?: number[] | null;
  preprocess?: MatrixPreprocess | null;
}) {
  return post<FactorResult>("spectrum-nmf", body);
}

export function postSpectrumMcr(body: {
  matrix_job_id: string;
  n_components: number;
  nonneg_conc: boolean;
  nonneg_spec: boolean;
  closure: boolean;
  unimodal_spec: boolean;
  normalise_spec: boolean;
  fixed_spectrum_ids?: string[] | null;
  preprocess?: MatrixPreprocess | null;
}) {
  return post<FactorResult>("spectrum-mcr", body);
}

export function postSpectrum2dcos(body: {
  matrix_job_id: string;
  perturbation: "sample_order" | "observation_column";
  analysis_run_id?: string | null;
  perturbation_column?: string | null;
  reference: "mean" | "first" | "last";
  preprocess?: MatrixPreprocess | null;
}) {
  return post<Cos2dResult>("spectrum-2dcos", body);
}
