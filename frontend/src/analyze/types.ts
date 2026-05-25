import type { PlotlyFigure } from "../legacy-wrappers/PlotlyWrapper";
import type { CsvRow } from "./export";

export type PcaScaler = "none" | "standard";

export type PcaLikeResult = {
  kind?: string;
  method?: "pca" | "spca";
  scaler?: PcaScaler;
  pca_preprocessing?: {
    scaler?: PcaScaler;
    mean?: number[];
    scale?: number[];
    var?: number[];
    [k: string]: unknown;
  };
  n_components?: number;
  explained_variance_ratio?: number[];
  scores?: number[][];
  components?: number[][];
  feature_names?: string[];
  x_cm1?: number[];
  mean_spectrum?: number[];
  spectrum_ids?: string[];
  plots?: Record<string, string>;
  // Back-compat / extra fields from backend are allowed.
  [k: string]: unknown;
};

export type ClusterResult = {
  n_clusters?: number;
  labels?: Record<string, number>;
  inertia?: number;
  embedding?: string;
  n_pc_embedding?: number;
  spectrum_ids?: string[];
  [k: string]: unknown;
};

export type PlotSource = "pca" | "fpca_discrete" | "fpca_fda";
export type ClusterSource = "cluster" | "spectrum_cluster";

export type PlotKind =
  | "scores_scatter"
  | "scores_pairplot"
  | "scree"
  | "cumulative_evr"
  | "loadings_topn"
  | "loadings_heatmap";

export type ClusterPlotKind = "cluster_on_scores_scatter" | "cluster_sizes";

export type PlotCardModel = {
  id: string;
  title: string;
  source: PlotSource | ClusterSource;
  figure: PlotlyFigure;
  csvRows: CsvRow[];
  defaultPngName: string;
  defaultCsvName: string;
  zipFolder: string;
};

