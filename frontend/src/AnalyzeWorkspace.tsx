import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { useSearchParams } from "react-router-dom";
import {
  LS_ANALYZE_DATASET,
  LS_ANALYZE_PIPELINE,
  LS_ANALYZE_RUN,
  loadAnalyzeUiPrefs,
  saveAnalyzeUiPrefs,
} from "./lib/uiPersistence";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlotlyWrapper, type PlotlyFigure } from "./legacy-wrappers/PlotlyWrapper";
import Plotly from "plotly.js-dist-min";
import { DatasetPicker } from "./components/DatasetPicker";
import { listDatasets, listPipelines, type PipelineLibraryItem, type SubsetStrategy } from "./preprocess/api";
import { downloadBlob, downloadCsv, plotlyDivToPngBytes, rowsToCsv, zipFiles } from "./analyze/export";
import type { ClusterResult, PcaLikeResult, PcaScaler, PlotCardModel } from "./analyze/types";
import {
  buildCumulativeEvr,
  buildLoadingsHeatmap,
  buildLoadingsSpectrum,
  buildLoadingsTopN,
  buildScoresPairplot,
  buildScoresScatter,
  buildScree,
} from "./analyze/pcaPlots";
import { buildClusterOnScoresScatter, buildClusterSizesBar } from "./analyze/clusterPlots";
import {
  createAnalysisRun,
  deleteAnalysisRun,
  deleteAllAnalysisRuns,
  downloadUrl,
  fetchExportManifest,
  fetchObservationColumns,
  fetchObservationSchema,
  getAnalysisJob,
  getExportBundleUrl,
  getExportFeaturesUrl,
  getExplorePcaExportUrl,
  getMatrixJobExportUrl,
  getObservationUrl,
  getSpectrumAxesPage,
  getAnalysisRun,
  listAnalysisRuns,
  postCluster,
  postCorrelation,
  postFpcaDiscrete,
  postFpcaFda,
  postMatrixJob,
  postPca,
  postSpectrumCluster,
  postVif,
  getMatrixJob,
  type AnalysisRunSummary,
} from "./analyze/api";

type AnalyzeSection =
  | "overview"
  | "exports"
  | "correlation"
  | "pca_cluster"
  | "meta_plot"
  | "spectrum_matrix";

const SECTIONS: { id: AnalyzeSection; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "exports", label: "Exports" },
  { id: "correlation", label: "Correlation / VIF" },
  { id: "pca_cluster", label: "PCA / Cluster" },
  { id: "meta_plot", label: "Parameter scatter" },
  { id: "spectrum_matrix", label: "Spectrum matrix & PCA" },
];

function coercePcaScaler(value: unknown, fallback: PcaScaler = "none"): PcaScaler {
  return value === "standard" || value === "none" ? value : fallback;
}

function triggerBlobDownload(blob: Blob, filename: string) {
  const u = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = u;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(u);
}

async function safeDownload(url: string, filename: string, onErr: (msg: string) => void) {
  try {
    const blob = await downloadUrl(url);
    triggerBlobDownload(blob, filename);
  } catch (e) {
    onErr(String((e as Error)?.message ?? e));
  }
}

function cellToNumber(v: unknown): number | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "boolean") return null;
  if (typeof v === "string") {
    const t = v.trim();
    if (!t) return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function meanStd(values: number[]): { mean: number; std: number } {
  if (!values.length) return { mean: NaN, std: NaN };
  const n = values.length;
  const mean = values.reduce((a, b) => a + b, 0) / n;
  if (n < 2) return { mean, std: 0 };
  let acc = 0;
  for (const v of values) acc += (v - mean) ** 2;
  // sample std
  const std = Math.sqrt(acc / (n - 1));
  return { mean, std };
}

function stableNumberKey(v: number, decimals = 6): string {
  if (!Number.isFinite(v)) return "NaN";
  // Avoid 0.30000000000000004 style jitter; keep integers compact.
  const r = Math.round(v);
  if (Math.abs(v - r) < 1e-12) return String(r);
  return v.toFixed(decimals);
}

/**
 * Explains why exports / explore need a completed *batch analysis* run (POST /analysis/runs),
 * and surfaces failed-run errors (often pipeline: crop vs. wavenumbers, fitting with no points).
 */
function AnalysisRunGateNotice({
  runId,
  selectedRun,
  compact,
}: {
  runId: string;
  selectedRun: AnalysisRunSummary | undefined;
  compact?: boolean;
}) {
  if (!runId) {
    return compact ? (
      <div className="hint">Choose a completed run in Overview (Run analysis async).</div>
    ) : (
      <>
        <p className="hint">
          Open <b>Overview</b>, select dataset + pipeline, then click <b>Run feature extraction (async)</b>. It processes
          every spectrum in the dataset. Feature columns come from enabled <code>spectral_intensities</code> steps; if none
          are present, the server uses a default probe. This is <b>not</b> the same as <b>Run (subset plot)</b> in Pipeline
          &amp; preview.
        </p>
        <p className="hint">When the run status is <b>completed</b>, exports and statistics below are enabled.</p>
      </>
    );
  }
  if (!selectedRun) {
    return <div className="hint">Loading run…</div>;
  }
  if (selectedRun.status === "failed") {
    return (
      <div className="hint">
        <p>
          <b>This analysis run failed</b> — there are no features to export or explore.
          {selectedRun.error ? (
            <>
              {" "}
              Detail: <span className="err" style={{ whiteSpace: "pre-wrap" }}>{selectedRun.error}</span>
            </>
          ) : null}
        </p>
        {!compact ? (
          <p style={{ marginTop: "8px" }}>
            Typical fix in <b>Pipeline &amp; preview</b>: widen <b>crop</b> so it overlaps your data&apos;s wavenumbers;
            if you use <b>fitting</b>, ensure the cropped region still has points. Then save the pipeline and start a{" "}
            <b>new</b> feature extraction run from Overview.
          </p>
        ) : null}
      </div>
    );
  }
  return (
    <div className="hint">
      Current status: <b>{selectedRun.status}</b>. Wait until it is <b>completed</b> in Overview, or select another run.
    </div>
  );
}

function normalizeRunNameToken(s: string): string {
  return String(s ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function nextRunNameId(existingLabels: (string | null | undefined)[], base: string): string {
  const b = normalizeRunNameToken(base);
  if (!b) return "00";
  const re = new RegExp(`^${b.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s+(\\d{2})$`);
  let maxSeen = -1;
  for (const raw of existingLabels) {
    const t = normalizeRunNameToken(raw ?? "");
    const m = re.exec(t);
    if (!m) continue;
    const n = Number(m[1]);
    if (Number.isFinite(n)) maxSeen = Math.max(maxSeen, n);
  }
  const next = Math.min(99, maxSeen + 1);
  return String(next).padStart(2, "0");
}

export default function AnalyzeWorkspace() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const analyzeUiLoaded = useMemo(() => loadAnalyzeUiPrefs(), []);

  const [datasetId, setDatasetId] = useState(
    () => searchParams.get("dataset_id") || localStorage.getItem(LS_ANALYZE_DATASET) || ""
  );
  const [pipelineId, setPipelineId] = useState(
    () => searchParams.get("pipeline_id") || localStorage.getItem(LS_ANALYZE_PIPELINE) || ""
  );
  const [runId, setRunId] = useState(() => searchParams.get("run_id") || localStorage.getItem(LS_ANALYZE_RUN) || "");
  const [section, setSection] = useState<AnalyzeSection>(() => {
    const s = searchParams.get("section") as AnalyzeSection | null;
    if (s && SECTIONS.some((x) => x.id === s)) return s;
    const fromLs = analyzeUiLoaded.section as AnalyzeSection | undefined;
    if (fromLs && SECTIONS.some((x) => x.id === fromLs)) return fromLs;
    return "overview";
  });

  const [pendingJobId, setPendingJobId] = useState<string | null>(null);
  const [manifestJson, setManifestJson] = useState<string | null>(null);
  const [exportNote, setExportNote] = useState<string | null>(null);

  // Shared column selection for Correlation and VIF.
  // Back-compat: if corrCols missing but vifCols exists, start from vifCols.
  const [corrCols, setCorrCols] = useState<string[]>(() => analyzeUiLoaded.corrCols ?? analyzeUiLoaded.vifCols ?? []);
  const [pcaN, setPcaN] = useState<number | "">(() => {
    const n = analyzeUiLoaded.pcaN;
    if (n === "" || n === undefined) return "";
    const num = typeof n === "number" ? n : Number(n);
    return Number.isFinite(num) ? num : "";
  });
  const [pcaCols, setPcaCols] = useState<string[]>(() => analyzeUiLoaded.pcaCols ?? []);
  const [clusterK, setClusterK] = useState(() =>
    typeof analyzeUiLoaded.clusterK === "number" && Number.isFinite(analyzeUiLoaded.clusterK) ? analyzeUiLoaded.clusterK : 3
  );
  const [clusterCols, setClusterCols] = useState<string[]>(() => analyzeUiLoaded.clusterCols ?? []);
  const [clusterSeed, setClusterSeed] = useState(() =>
    typeof analyzeUiLoaded.clusterSeed === "number" && Number.isFinite(analyzeUiLoaded.clusterSeed)
      ? analyzeUiLoaded.clusterSeed
      : 0
  );

  const [matrixUpTo, setMatrixUpTo] = useState(() => analyzeUiLoaded.matrixUpTo ?? "");
  const [matrixJobId, setMatrixJobId] = useState<string | null>(null);
  const [fpcaN, setFpcaN] = useState<number | "">(() => {
    const n = analyzeUiLoaded.fpcaN;
    if (n === "" || n === undefined) return "";
    const num = typeof n === "number" ? n : Number(n);
    return Number.isFinite(num) ? num : "";
  });

  const [pcaMethod, setPcaMethod] = useState<"pca" | "spca">("pca");
  const [pcaScaler, setPcaScaler] = useState<PcaScaler>(() => coercePcaScaler(analyzeUiLoaded.pcaScaler));
  const [spcaAlpha, setSpcaAlpha] = useState(1);
  const [spcaRidge, setSpcaRidge] = useState(1e-5);
  const [discreteMethod, setDiscreteMethod] = useState<"pca" | "spca">("pca");
  const [discreteScaler, setDiscreteScaler] = useState<PcaScaler>(() => coercePcaScaler(analyzeUiLoaded.discreteScaler));
  const [spectrumClusterK, setSpectrumClusterK] = useState(3);
  const [spectrumClusterSeed, setSpectrumClusterSeed] = useState(0);
  const [spectrumClusterPcEmbedding, setSpectrumClusterPcEmbedding] = useState(10);
  const [metaX, setMetaX] = useState("");
  const [metaY, setMetaY] = useState("");
  const [metaColor, setMetaColor] = useState("");
  const [metaPlotStyle, setMetaPlotStyle] = useState<"scatter" | "errorbars" | "errorbars_line" | "boxplot">("scatter");
  const [metaXErr, setMetaXErr] = useState("");
  const [metaYErr, setMetaYErr] = useState("");
  const [metaScatterFig, setMetaScatterFig] = useState<PlotlyFigure | null>(null);
  const [metaScatterCsvRows, setMetaScatterCsvRows] = useState<
    { spectrum_id: string; x: number; y: number; color?: number | null; x_err?: number | null; y_err?: number | null }[]
  >([]);
  const metaPlotDivRef = useRef<HTMLDivElement | null>(null);
  const [spectrumClusterResult, setSpectrumClusterResult] = useState<Record<string, unknown> | null>(null);

  // Shared PCA/FPCA plotting preferences (used by the plot-card selector UI).
  const [scoresXpc, setScoresXpc] = useState(() =>
    typeof analyzeUiLoaded.scoresXpc === "number" && Number.isFinite(analyzeUiLoaded.scoresXpc) ? analyzeUiLoaded.scoresXpc : 2
  );
  const [scoresYpc, setScoresYpc] = useState(() =>
    typeof analyzeUiLoaded.scoresYpc === "number" && Number.isFinite(analyzeUiLoaded.scoresYpc) ? analyzeUiLoaded.scoresYpc : 3
  );
  const [pairplotPcs, setPairplotPcs] = useState<number[]>(() =>
    Array.isArray(analyzeUiLoaded.pairplotPcs) && analyzeUiLoaded.pairplotPcs.length ? analyzeUiLoaded.pairplotPcs : [2, 3, 4, 5, 6]
  );
  const [loadingsPc] = useState(() =>
    typeof analyzeUiLoaded.loadingsPc === "number" && Number.isFinite(analyzeUiLoaded.loadingsPc) ? analyzeUiLoaded.loadingsPc : 2
  );
  const [loadingsTopN, setLoadingsTopN] = useState(() =>
    typeof analyzeUiLoaded.loadingsTopN === "number" && Number.isFinite(analyzeUiLoaded.loadingsTopN) ? analyzeUiLoaded.loadingsTopN : 20
  );
  const [selectedPcaPlots, setSelectedPcaPlots] = useState<string[]>(() =>
    Array.isArray(analyzeUiLoaded.selectedPcaPlots) ? analyzeUiLoaded.selectedPcaPlots : ["scores_scatter", "scree", "cumulative_evr"]
  );
  const [selectedClusterPlots, setSelectedClusterPlots] = useState<string[]>(() =>
    Array.isArray(analyzeUiLoaded.selectedClusterPlots) ? analyzeUiLoaded.selectedClusterPlots : ["cluster_on_scores_scatter", "cluster_sizes"]
  );

  const [corrResult, setCorrResult] = useState<Record<string, unknown> | null>(null);
  const [vifResult, setVifResult] = useState<Record<string, unknown> | null>(null);
  const [pcaResult, setPcaResult] = useState<Record<string, unknown> | null>(null);
  const [clusterResult, setClusterResult] = useState<Record<string, unknown> | null>(null);
  const [fpcaDiscResult, setFpcaDiscResult] = useState<Record<string, unknown> | null>(null);
  const [fpcaDiscExploreId, setFpcaDiscExploreId] = useState<string | null>(null);
  const [fpcaFdaResult, setFpcaFdaResult] = useState<Record<string, unknown> | null>(null);
  const [fpcaFdaExploreId, setFpcaFdaExploreId] = useState<string | null>(null);

  const [exploreBusy, setExploreBusy] = useState<string | null>(null);
  const [exportBusy, setExportBusy] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const plotDivByIdRef = useRef<Record<string, HTMLDivElement | null>>({});

  const patchParams = useCallback(
    (patch: Record<string, string | null | undefined>) => {
      setSearchParams(
        (prev) => {
          const n = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(patch)) {
            if (v === null || v === undefined || v === "") n.delete(k);
            else n.set(k, v);
          }
          return n;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  useEffect(() => {
    if (datasetId) localStorage.setItem(LS_ANALYZE_DATASET, datasetId);
    else localStorage.removeItem(LS_ANALYZE_DATASET);
    patchParams({ dataset_id: datasetId || null });
  }, [datasetId, patchParams]);

  useEffect(() => {
    if (pipelineId) localStorage.setItem(LS_ANALYZE_PIPELINE, pipelineId);
    else localStorage.removeItem(LS_ANALYZE_PIPELINE);
    patchParams({ pipeline_id: pipelineId || null });
  }, [pipelineId, patchParams]);

  useEffect(() => {
    if (runId) localStorage.setItem(LS_ANALYZE_RUN, runId);
    else localStorage.removeItem(LS_ANALYZE_RUN);
    patchParams({ run_id: runId || null });
  }, [runId, patchParams]);

  useEffect(() => {
    saveAnalyzeUiPrefs({
      v: 1,
      section,
      corrCols,
      // Keep writing vifCols so older UIs / stored prefs remain usable.
      vifCols: corrCols,
      pcaN,
      pcaCols,
      clusterK,
      clusterCols,
      clusterSeed,
      matrixUpTo,
      fpcaN,
      pcaScaler,
      discreteScaler,
      scoresXpc,
      scoresYpc,
      pairplotPcs,
      loadingsPc,
      loadingsTopN,
      selectedPcaPlots,
      selectedClusterPlots,
    });
  }, [
    section,
    corrCols,
    pcaN,
    pcaCols,
    clusterK,
    clusterCols,
    clusterSeed,
    matrixUpTo,
    fpcaN,
    pcaScaler,
    discreteScaler,
    scoresXpc,
    scoresYpc,
    pairplotPcs,
    loadingsPc,
    loadingsTopN,
    selectedPcaPlots,
    selectedClusterPlots,
  ]);

  useEffect(() => {
    patchParams({ section });
  }, [section, patchParams]);

  const datasetsQ = useQuery({
    queryKey: ["datasets", { limit: 200, offset: 0 }],
    queryFn: () => listDatasets(200, 0),
  });

  const pipelinesQ = useQuery({
    queryKey: ["pipelines", { limit: 500, offset: 0 }],
    queryFn: () => listPipelines(500, 0),
  });

  const runsQ = useQuery({
    queryKey: ["analysisRuns", datasetId],
    queryFn: () => listAnalysisRuns(datasetId, 100),
    enabled: !!datasetId,
  });

  const runDetailQ = useQuery({
    queryKey: ["analysisRun", runId],
    queryFn: () => getAnalysisRun(runId),
    enabled: !!runId,
  });

  const selectedRun: AnalysisRunSummary | undefined = useMemo(() => {
    return (runsQ.data ?? []).find((r) => r.run_id === runId);
  }, [runsQ.data, runId]);

  const schemaQ = useQuery({
    queryKey: ["observationSchema", runId],
    queryFn: () => fetchObservationSchema(runId),
    enabled: !!runId && selectedRun?.status === "completed",
  });

  const jobQ = useQuery({
    queryKey: ["analysisJob", pendingJobId],
    queryFn: () => getAnalysisJob(pendingJobId!),
    enabled: !!pendingJobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (!pendingJobId) return false;
      if (s === "completed" || s === "failed") return false;
      return 1000;
    },
  });

  useEffect(() => {
    const st = jobQ.data?.status;
    if (st === "completed" || st === "failed") {
      setPendingJobId(null);
      void queryClient.invalidateQueries({ queryKey: ["analysisRuns", datasetId] });
    }
  }, [jobQ.data?.status, datasetId, queryClient]);

  const matrixPollQ = useQuery({
    queryKey: ["matrixJob", matrixJobId],
    queryFn: () => getMatrixJob(matrixJobId!),
    enabled: !!matrixJobId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      if (!matrixJobId) return false;
      if (s === "completed" || s === "failed") return false;
      return 1000;
    },
  });

  const effectiveMatrixId = matrixJobId ?? matrixPollQ.data?.matrix_job_id ?? null;

  const featureColumns = useMemo(
    () => runDetailQ.data?.run.feature_columns ?? [],
    [runDetailQ.data?.run.feature_columns]
  );

  const selectableColumns = useMemo(() => {
    const s = schemaQ.data;
    if (!s) return featureColumns;
    const merged = [...s.feature_keys, ...s.axis_keys, ...s.meta_keys];
    const seen = new Set<string>();
    const out: string[] = [];
    for (const c of merged) {
      if (!seen.has(c)) {
        seen.add(c);
        out.push(c);
      }
    }
    return out.length ? out : featureColumns;
  }, [schemaQ.data, featureColumns]);

  // Keep checkbox selections aligned with the *current* run. Persisted names from localStorage
  // or a previous run can be stale — unknown keys become NaN for every row and break /explore/*.
  useEffect(() => {
    if (!selectableColumns.length) return;
    const allowed = new Set(selectableColumns);

    setCorrCols((prev) => {
      const next = prev.filter((c) => allowed.has(c));
      return next.length ? next : [...featureColumns.filter((c) => allowed.has(c))];
    });
    // Ensure VIF always has at least 2 columns when possible (shares corrCols).
    setCorrCols((prev) => {
      const next = prev.filter((c) => allowed.has(c));
      if (next.length >= 2) return next;
      const fb = featureColumns.filter((c) => allowed.has(c));
      if (!fb.length) return next;
      return fb.slice(0, Math.min(2, fb.length));
    });
    setPcaCols((prev) => {
      const next = prev.filter((c) => allowed.has(c));
      return next.length ? next : [...featureColumns.filter((c) => allowed.has(c))];
    });
    setClusterCols((prev) => {
      const next = prev.filter((c) => allowed.has(c));
      return next.length ? next : [...featureColumns.filter((c) => allowed.has(c))];
    });
  }, [runId, selectableColumns, featureColumns]);

  const createRunM = useMutation({
    mutationFn: async () => {
      if (!datasetId) throw new Error("Select a dataset");
      if (!pipelineId || !selectedPipeline) throw new Error("Select a pipeline");
      const ds = (datasetsQ.data?.items ?? []).find((d) => d.dataset_id === datasetId);
      const datasetName = normalizeRunNameToken(ds?.metadata?.name ?? ds?.dataset_id ?? datasetId);
      const pipelineName = normalizeRunNameToken(selectedPipeline.name ?? pipelineId);
      const base = normalizeRunNameToken(`${datasetName} ${pipelineName}`);
      const id2 = nextRunNameId(
        (runsQ.data ?? []).map((r) => r.label),
        base
      );
      const runName = normalizeRunNameToken(`${base} ${id2}`);
      return createAnalysisRun({
        dataset_id: datasetId,
        pipeline_id: pipelineId,
        pipeline_name: selectedPipeline.name,
        pipeline: selectedPipeline.pipeline,
        subset: subsetAll,
        async_job: true,
        label: runName,
      });
    },
    onSuccess: (data) => {
      setLastError(null);
      if (data.job_id) setPendingJobId(data.job_id);
      setRunId(data.run_id);
      void queryClient.invalidateQueries({ queryKey: ["analysisRuns", datasetId] });
    },
    onError: (e: Error) => setLastError(e.message),
  });

  const deleteRunM = useMutation({
    mutationFn: async (rid: string) => deleteAnalysisRun(rid),
    onSuccess: async (_data, rid) => {
      if (runId === rid) setRunId("");
      await queryClient.invalidateQueries({ queryKey: ["analysisRuns", datasetId] });
    },
    onError: (e: Error) => setLastError(e.message),
  });

  const deleteAllRunsM = useMutation({
    mutationFn: async () => {
      if (!datasetId) throw new Error("Select a dataset");
      return deleteAllAnalysisRuns(datasetId);
    },
    onSuccess: async () => {
      setRunId("");
      await queryClient.invalidateQueries({ queryKey: ["analysisRuns", datasetId] });
    },
    onError: (e: Error) => setLastError(e.message),
  });

  const corrFigure = useMemo(() => {
    if (!corrResult) return null;
    const names = corrResult.feature_names as string[] | undefined;
    const R = corrResult.R as number[][] | undefined;
    if (!names?.length || !R?.length) return null;
    const n = names.length;
    const warn = n > 80;
    return {
      figure: {
        data: [
          {
            type: "heatmap",
            z: R,
            x: names,
            y: names,
            colorscale: "RdBu",
            zmid: 0,
            colorbar: { title: "r" },
          },
        ],
        layout: {
          title: warn ? "Correlation (large matrix — may be slow to render)" : "Pearson correlation",
          margin: { l: 120, r: 20, t: 44, b: 120 },
          // Provide ticktext so the wrapper can detect dense axes and hide tick labels.
          // This keeps the view clean for large matrices while preserving hover detail.
          xaxis: { ticktext: names },
          yaxis: { ticktext: names },
        },
      },
      warn,
    };
  }, [corrResult]);

  const vifFigure = useMemo(() => {
    if (!vifResult) return null;
    const names = vifResult.feature_names as string[] | undefined;
    const vifs = vifResult.vif as number[] | undefined;
    if (!names?.length || !vifs?.length) return null;
    return {
      data: [
        {
          type: "bar",
          x: names,
          y: vifs.map((v) => (Number.isFinite(v) ? v : null)),
        },
      ],
      layout: {
        title: "Variance inflation factor",
        margin: { l: 60, r: 20, t: 20, b: 120 },
        xaxis: { tickangle: -45 },
      },
    };
  }, [vifResult]);

  const plotCards: PlotCardModel[] = useMemo(() => {
    const cards: PlotCardModel[] = [];

    function pushBuilt(
      source: PlotCardModel["source"],
      zipFolder: string,
      built: { figure: PlotlyFigure; csvRows: any[]; title: string; defaultName: string } | null,
      titlePrefix: string
    ) {
      if (!built) return;
      const id = `${source}_${built.defaultName}`;
      cards.push({
        id,
        title: `${titlePrefix}: ${built.title}`,
        source,
        figure: built.figure,
        csvRows: built.csvRows,
        defaultPngName: `${id}.png`,
        defaultCsvName: `${id}.csv`,
        zipFolder,
      });
    }

    const pca = (pcaResult ?? null) as PcaLikeResult | null;
    const fpcaD = (fpcaDiscResult ?? null) as PcaLikeResult | null;
    const fpcaF = (fpcaFdaResult ?? null) as PcaLikeResult | null;
    const cl = (clusterResult ?? null) as ClusterResult | null;
    const specCl = (spectrumClusterResult ?? null) as ClusterResult | null;

    const wantP = new Set(selectedPcaPlots);
    const wantC = new Set(selectedClusterPlots);

    const includeFeaturePca = section === "pca_cluster";
    const includeSpectrumPca = section === "spectrum_matrix";

    if (includeFeaturePca && pca) {
      if (wantP.has("scores_scatter")) pushBuilt("pca", "pca", buildScoresScatter(pca, { xPc: scoresXpc, yPc: scoresYpc }), "PCA");
      if (wantP.has("scores_pairplot")) pushBuilt("pca", "pca", buildScoresPairplot(pca, { pcs: pairplotPcs, maxPcs: 8 }), "PCA");
      if (wantP.has("scree")) pushBuilt("pca", "pca", buildScree(pca), "PCA");
      if (wantP.has("cumulative_evr")) pushBuilt("pca", "pca", buildCumulativeEvr(pca), "PCA");
      if (wantP.has("loadings_topn")) {
        const pcs = Array.from(new Set(pairplotPcs.map((p) => Math.max(1, Math.floor(p))))).slice(0, 8);
        for (const pc of pcs) {
          pushBuilt("pca", "pca", buildLoadingsTopN(pca, { pc, topN: loadingsTopN }), "PCA");
        }
      }
      if (wantP.has("loadings_heatmap")) pushBuilt("pca", "pca", buildLoadingsHeatmap(pca, { pcs: pairplotPcs }), "PCA");
    }

    if (includeSpectrumPca && fpcaD) {
      if (wantP.has("scores_scatter")) pushBuilt("fpca_discrete", "fpca_discrete", buildScoresScatter(fpcaD, { xPc: scoresXpc, yPc: scoresYpc }), "FPCA discrete");
      if (wantP.has("scores_pairplot")) pushBuilt("fpca_discrete", "fpca_discrete", buildScoresPairplot(fpcaD, { pcs: pairplotPcs, maxPcs: 8 }), "FPCA discrete");
      if (wantP.has("scree")) pushBuilt("fpca_discrete", "fpca_discrete", buildScree(fpcaD), "FPCA discrete");
      if (wantP.has("cumulative_evr")) pushBuilt("fpca_discrete", "fpca_discrete", buildCumulativeEvr(fpcaD), "FPCA discrete");
      if (wantP.has("loadings_topn")) {
        // For spectrum PCA/FPCA, prefer spectrum-style loadings curves (PC loadings vs Raman shift).
        const built = buildLoadingsSpectrum(fpcaD, { pcs: pairplotPcs, maxPcs: 6 });
        if (built) pushBuilt("fpca_discrete", "fpca_discrete", built, "FPCA discrete");
        else {
          const pcs = Array.from(new Set(pairplotPcs.map((p) => Math.max(1, Math.floor(p))))).slice(0, 8);
          for (const pc of pcs) pushBuilt("fpca_discrete", "fpca_discrete", buildLoadingsTopN(fpcaD, { pc, topN: loadingsTopN }), "FPCA discrete");
        }
      }
      if (wantP.has("loadings_heatmap")) pushBuilt("fpca_discrete", "fpca_discrete", buildLoadingsHeatmap(fpcaD, { pcs: pairplotPcs }), "FPCA discrete");
    }

    if (includeSpectrumPca && fpcaF) {
      if (wantP.has("scores_scatter")) pushBuilt("fpca_fda", "fpca_fda", buildScoresScatter(fpcaF, { xPc: scoresXpc, yPc: scoresYpc }), "FPCA fda");
      if (wantP.has("scores_pairplot")) pushBuilt("fpca_fda", "fpca_fda", buildScoresPairplot(fpcaF, { pcs: pairplotPcs, maxPcs: 8 }), "FPCA fda");
      if (wantP.has("scree")) pushBuilt("fpca_fda", "fpca_fda", buildScree(fpcaF), "FPCA fda");
      if (wantP.has("cumulative_evr")) pushBuilt("fpca_fda", "fpca_fda", buildCumulativeEvr(fpcaF), "FPCA fda");
      if (wantP.has("loadings_topn")) {
        const built = buildLoadingsSpectrum(fpcaF, { pcs: pairplotPcs, maxPcs: 6 });
        if (built) pushBuilt("fpca_fda", "fpca_fda", built, "FPCA fda");
        else {
          const pcs = Array.from(new Set(pairplotPcs.map((p) => Math.max(1, Math.floor(p))))).slice(0, 8);
          for (const pc of pcs) pushBuilt("fpca_fda", "fpca_fda", buildLoadingsTopN(fpcaF, { pc, topN: loadingsTopN }), "FPCA fda");
        }
      }
      if (wantP.has("loadings_heatmap")) pushBuilt("fpca_fda", "fpca_fda", buildLoadingsHeatmap(fpcaF, { pcs: pairplotPcs }), "FPCA fda");
    }

    // Cluster plots
    if (includeFeaturePca && cl) {
      if (wantC.has("cluster_sizes")) pushBuilt("cluster", "cluster", buildClusterSizesBar(cl), "k-means");
      if (wantC.has("cluster_on_scores_scatter") && pca) {
        pushBuilt("cluster", "cluster", buildClusterOnScoresScatter(pca, cl, { xPc: scoresXpc, yPc: scoresYpc }), "k-means");
      }
    }
    if (includeSpectrumPca && specCl) {
      if (wantC.has("cluster_sizes")) pushBuilt("spectrum_cluster", "spectrum_cluster", buildClusterSizesBar(specCl), "Spectrum k-means");
      if (wantC.has("cluster_on_scores_scatter") && fpcaD) {
        pushBuilt(
          "spectrum_cluster",
          "spectrum_cluster",
          buildClusterOnScoresScatter(fpcaD, specCl, { xPc: scoresXpc, yPc: scoresYpc }),
          "Spectrum k-means"
        );
      }
    }

    return cards;
  }, [
    section,
    pcaResult,
    fpcaDiscResult,
    fpcaFdaResult,
    clusterResult,
    spectrumClusterResult,
    selectedPcaPlots,
    selectedClusterPlots,
    scoresXpc,
    scoresYpc,
    pairplotPcs,
    loadingsTopN,
  ]);

  function PlotCard({ card }: { card: PlotCardModel }) {
    return (
      <div className="card" style={{ marginTop: "10px" }}>
        <div className="row" style={{ justifyContent: "space-between", gap: "10px", alignItems: "center" }}>
          <div className="hint" style={{ margin: 0 }}>
            {card.title}
          </div>
          <div className="row" style={{ gap: "6px", flexWrap: "wrap" }}>
            <button
              type="button"
              className="mini"
              onClick={async () => {
                const div = plotDivByIdRef.current[card.id];
                if (!div) return;
                const bytes = await plotlyDivToPngBytes(div, { width: 1200, scale: 2 });
                downloadBlob(
                  card.defaultPngName,
                  new Blob([bytes as unknown as BlobPart], { type: "image/png" })
                );
              }}
            >
              Download PNG
            </button>
            <button type="button" className="mini" onClick={() => downloadCsv(card.defaultCsvName, card.csvRows)}>
              Download CSV
            </button>
          </div>
        </div>
        <PlotlyWrapper
          ref={(el) => {
            plotDivByIdRef.current[card.id] = el;
          }}
          figure={card.figure}
          previousFigure={null}
          plotStyle={{ mode: "overlay", stackSep: 0 }}
          ghostOverlayEnabled={false}
          className="plot-host"
        />
      </div>
    );
  }

  async function exportAllCsvZip() {
    setLastError(null);
    setExportBusy("csv");
    try {
      const files = plotCards.map((c) => ({
        path: `${c.zipFolder}/${c.defaultCsvName}`,
        bytes: rowsToCsv(c.csvRows),
      }));
      const zip = zipFiles(files);
      downloadBlob("plots_csv.zip", zip);
    } catch (e) {
      setLastError(String((e as Error)?.message ?? e));
    } finally {
      setExportBusy(null);
    }
  }

  async function exportAllPngZip() {
    setLastError(null);
    setExportBusy("png");
    try {
      const files: { path: string; bytes: Uint8Array }[] = [];
      for (const c of plotCards) {
        const div = plotDivByIdRef.current[c.id];
        if (!div) continue;
        const bytes = await plotlyDivToPngBytes(div, { width: 1200, scale: 2 });
        files.push({ path: `${c.zipFolder}/${c.defaultPngName}`, bytes });
      }
      if (!files.length) {
        throw new Error("No rendered plots were available for PNG export yet. Scroll until plots are visible, then retry.");
      }
      const zip = zipFiles(files);
      downloadBlob("plots_png.zip", zip);
    } catch (e) {
      setLastError(String((e as Error)?.message ?? e));
    } finally {
      setExportBusy(null);
    }
  }

  const axesQ = useQuery({
    queryKey: ["spectrumAxes", datasetId],
    queryFn: () => getSpectrumAxesPage(datasetId, 50, 0),
    enabled: !!datasetId && section === "spectrum_matrix",
  });

  function toggleCol(list: string[], col: string, on: boolean) {
    const set = new Set(list);
    if (on) set.add(col);
    else set.delete(col);
    return Array.from(set);
  }

  function updateSelection(
    selected: string[],
    keys: string[],
    mode: "select_all" | "clear",
  ): string[] {
    const set = new Set(selected);
    if (mode === "select_all") {
      for (const k of keys) set.add(k);
    } else {
      for (const k of keys) set.delete(k);
    }
    return Array.from(set);
  }

  function renderColumnGridWithSelectAll(
    title: string,
    keys: string[],
    selected: string[],
    setSelected: Dispatch<SetStateAction<string[]>>,
  ) {
    if (!keys.length) return null;

    const spectralFamilies =
      title === "Spectral features"
        ? (() => {
            const posKeys = keys.filter(
              (k) => /^(s\d+_)?fit_.+_pos$/.test(k) || /^(s\d+_)?peak_pos_cm1_/.test(k)
            );
            const ampKeys = keys.filter((k) => /^(s\d+_)?fit_.+_amp$/.test(k));
            const areaKeys = keys.filter((k) => /^(s\d+_)?fit_.+_area$/.test(k));
            const fwhmKeys = keys.filter((k) => /^(s\d+_)?fit_.+_fwhm$/.test(k));
            const intensityAtKeys = keys.filter((k) => /^(s\d+_)?I_/.test(k));
            return [
              { id: "pos", label: "pos", keys: posKeys },
              { id: "amp", label: "amp", keys: ampKeys },
              { id: "area", label: "area", keys: areaKeys },
              { id: "fwhm", label: "fwhm", keys: fwhmKeys },
              { id: "intensity_at", label: "intensity_at", keys: intensityAtKeys },
            ].filter((f) => f.keys.length);
          })()
        : null;

    return (
      <div style={{ marginTop: "10px" }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
          <div className="hint" style={{ margin: 0 }}>
            {title}
          </div>
          <div className="row" style={{ gap: "6px" }}>
            <button type="button" className="mini" onClick={() => setSelected((prev) => updateSelection(prev, keys, "select_all"))}>
              Select all
            </button>
            <button type="button" className="mini" onClick={() => setSelected((prev) => updateSelection(prev, keys, "clear"))}>
              Clear
            </button>
          </div>
        </div>
        {spectralFamilies?.length ? (
          <div className="row" style={{ gap: "6px", flexWrap: "wrap", marginTop: "6px" }}>
            {spectralFamilies.map((f) => (
              <div key={f.id} className="row" style={{ gap: "6px" }}>
                <button
                  type="button"
                  className="mini"
                  title={`Select all ${f.label} features`}
                  onClick={() => setSelected((prev) => updateSelection(prev, f.keys, "select_all"))}
                >
                  + {f.label}
                </button>
                <button
                  type="button"
                  className="mini"
                  title={`Deselect all ${f.label} features`}
                  onClick={() => setSelected((prev) => updateSelection(prev, f.keys, "clear"))}
                >
                  - {f.label}
                </button>
              </div>
            ))}
          </div>
        ) : null}
        <div
          style={{
            marginTop: "6px",
            maxHeight: 160,
            overflow: "auto",
            border: "1px solid rgba(255,255,255,0.08)",
            padding: "6px",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: "6px 10px",
          }}
        >
          {keys.map((c) => (
            <label key={c} className="inline" style={{ display: "block", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={c}>
              <input type="checkbox" checked={selected.includes(c)} onChange={(e) => setSelected(toggleCol(selected, c, e.target.checked))} />{" "}
              {c}
            </label>
          ))}
        </div>
      </div>
    );
  }

  const emptyDataset = !datasetId;
  const emptyPipeline = !pipelineId;
  const emptyRun = !runId;

  const selectedPipeline: PipelineLibraryItem | undefined = useMemo(() => {
    return (pipelinesQ.data?.items ?? []).find((p) => p.pipeline_id === pipelineId);
  }, [pipelinesQ.data?.items, pipelineId]);

  const subsetAll: SubsetStrategy = useMemo(() => ({ kind: "all" }), []);

  const matrixStepOptions = useMemo(() => {
    const p = selectedPipeline?.pipeline;
    const steps = (p?.steps ?? []).filter((s) => s.enabled !== false);
    const counts = new Map<string, number>();
    return steps
      .map((s, idx) => {
        const name = String(s.name || "").trim();
        if (!name) return null;
        const k = (counts.get(name) ?? 0) + 1;
        counts.set(name, k);

        // Prefer stable disambiguation by step_id; fall back to deterministic token.
        const stepId = (s.step_id ?? "").trim();
        const value = stepId ? stepId : `${name}__${idx + 1}`;
        const label = `${idx + 1}. ${name}${k > 1 ? ` (${k})` : ""}`;
        return { value, label, legacyName: name };
      })
      .filter((x): x is { value: string; label: string; legacyName: string } => !!x);
  }, [selectedPipeline]);

  // Back-compat: migrate previously stored "matrixUpTo" (often a step name like "normalize")
  // to the first matching option value when the pipeline changes.
  useEffect(() => {
    if (!matrixUpTo) return;
    const values = new Set(matrixStepOptions.map((o) => o.value));
    if (values.has(matrixUpTo)) return;
    const firstByName = matrixStepOptions.find((o) => o.legacyName === matrixUpTo);
    if (firstByName) setMatrixUpTo(firstByName.value);
  }, [matrixUpTo, matrixStepOptions]);

  return (
    <div className="preprocess-grid analyze-layout">
      <div className="preprocess-left card">
        <div className="section-title">Features &amp; statistics</div>
        <p className="hint" style={{ margin: "0 0 10px" }}>
          Use <b>Overview</b> first: choose dataset + pipeline, then <b>Run feature extraction (async)</b>. That job processes
          the <b>full dataset</b> (the random subset in Pipeline &amp; preview is only for plots). It must finish with status{" "}
          <b>completed</b> before exports and multivariate tools run.
        </p>

        <div className="row" style={{ flexWrap: "wrap", gap: "10px", alignItems: "flex-end" }}>
          <DatasetPicker
            items={datasetsQ.data?.items ?? []}
            value={datasetId}
            loading={datasetsQ.isLoading}
            onChange={(id) => {
              setDatasetId(id);
              setPipelineId("");
              setRunId("");
            }}
          />
          <label className="inline">
            Run
            <select value={runId} onChange={(e) => setRunId(e.target.value)} disabled={emptyDataset}>
              <option value="">{emptyDataset ? "—" : "Select run…"}</option>
              {(runsQ.data ?? []).map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {(r.label ?? r.run_id.slice(0, 14) + "…")} ({r.status})
                </option>
              ))}
            </select>
          </label>
          {section === "overview" || section === "spectrum_matrix" ? (
            <label className="inline">
              Pipeline
              <select
                value={pipelineId}
                disabled={pipelinesQ.isLoading}
                onChange={(e) => {
                  setPipelineId(e.target.value);
                }}
              >
                <option value="">{pipelinesQ.isLoading ? "Loading…" : "Select…"}</option>
                {(pipelinesQ.data?.items ?? []).map((p) => (
                  <option key={p.pipeline_id} value={p.pipeline_id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>

        <div className="row" style={{ marginTop: "10px", flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
          <label className="inline">
            Section
            <select value={section} onChange={(e) => setSection(e.target.value as AnalyzeSection)}>
              {SECTIONS.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {lastError ? (
          <div className="err" style={{ marginTop: "10px" }}>
            {lastError}
          </div>
        ) : null}

        {section === "overview" ? (
          <div style={{ marginTop: "14px" }}>
            <div className="section-title">Runs</div>
            {!emptyDataset && pipelineId ? (
              <p className="hint" style={{ margin: "0 0 10px" }}>
                Feature columns come from the selected pipeline (including <code>spectral_intensities</code> probes). Extraction
                covers <b>all spectra</b> in the dataset.
              </p>
            ) : null}
            {emptyDataset ? (
              <div className="hint">Select a dataset to list analysis runs.</div>
            ) : runsQ.isLoading ? (
              <div className="hint">Loading runs…</div>
            ) : (runsQ.data ?? []).length === 0 ? (
              <div className="hint">No analysis runs yet. Create one below (requires a pipeline).</div>
            ) : (
              <div style={{ maxHeight: 220, overflow: "auto", marginBottom: "10px" }}>
                <table className="mini-table" style={{ width: "100%", fontSize: "12px" }}>
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Status</th>
                      <th>Dataset</th>
                      <th>Pipeline</th>
                      <th></th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(runsQ.data ?? []).map((r) => (
                      <tr
                        key={r.run_id}
                        style={{ cursor: "pointer", background: r.run_id === runId ? "rgba(120,160,255,0.12)" : undefined }}
                        onClick={() => setRunId(r.run_id)}
                      >
                        <td title={r.label ?? r.run_id}>{(r.label ?? r.run_id).slice(0, 26)}{(r.label ?? r.run_id).length > 26 ? "…" : ""}</td>
                        <td>{r.status}</td>
                        <td>{r.dataset_name ?? "—"}</td>
                        <td>{r.pipeline_name ?? "—"}</td>
                        <td style={{ width: 1, whiteSpace: "nowrap" }} onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            className="mini"
                            disabled={deleteRunM.isPending}
                            onClick={() => {
                              const ok = window.confirm(`Delete run?\n\n${r.label ?? r.run_id}\n\nThis cannot be undone.`);
                              if (!ok) return;
                              deleteRunM.mutate(r.run_id);
                            }}
                          >
                            Delete
                          </button>
                        </td>
                        <td>{r.created_at?.slice(0, 19) ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "center" }}>
              <button
                type="button"
                disabled={!datasetId || !pipelineId || !selectedPipeline || createRunM.isPending}
                onClick={() => createRunM.mutate()}
              >
                {createRunM.isPending ? "Starting…" : "Run feature extraction (async)"}
              </button>
              <button
                type="button"
                className="mini"
                disabled={!datasetId || deleteAllRunsM.isPending || (runsQ.data ?? []).length === 0}
                onClick={() => {
                  const dsName =
                    (datasetsQ.data?.items ?? []).find((d) => d.dataset_id === datasetId)?.metadata?.name ?? datasetId;
                  const ok = window.confirm(
                    `Delete ALL analysis runs for this dataset?\n\nDataset: ${dsName}\n\nThis cannot be undone.`
                  );
                  if (!ok) return;
                  deleteAllRunsM.mutate();
                }}
              >
                {deleteAllRunsM.isPending ? "Deleting…" : "Delete all runs"}
              </button>
            </div>

            {pendingJobId || jobQ.data ? (
              <div className="hint" style={{ marginTop: "10px" }}>
                Job: {pendingJobId ?? jobQ.data?.job_id ?? "—"} — {jobQ.data?.status ?? "queued"} (
                {jobQ.data?.progress_done ?? 0}/{jobQ.data?.progress_total ?? 0})
                {jobQ.data?.error ? ` — ${jobQ.data.error}` : ""}
              </div>
            ) : null}

            {selectedRun ? (
              <div className="hint" style={{ marginTop: "10px" }}>
                <div>
                  <b>Status:</b> {selectedRun.status}
                  {selectedRun.error ? ` — ${selectedRun.error}` : ""}
                </div>
                <div>
                  <b>Finished:</b> {selectedRun.finished_at ?? "—"}
                </div>
              </div>
            ) : (
              <div className="hint" style={{ marginTop: "10px" }}>
                Select a run to drive exports and explore actions.
              </div>
            )}
          </div>
        ) : null}

        {section === "exports" ? (
          <div style={{ marginTop: "14px" }}>
            <div className="section-title">Exports</div>
            <p className="hint">
              CSV exports are UTF-8. <b>Primary download:</b> observation wide — features plus upload labels (<code>meta_*</code>)
              and map/time axes when available. Missing values show as empty cells. For sklearn-style matrices with numeric
              columns only, use features wide/long.
            </p>
            {emptyRun || selectedRun?.status !== "completed" ? (
              <AnalysisRunGateNotice runId={runId} selectedRun={selectedRun} />
            ) : (
              <>
                <div className="hint" style={{ marginBottom: "8px" }}>
                  Observation table (recommended)
                </div>
                <div className="row" style={{ flexWrap: "wrap", gap: "8px" }}>
                  <button
                    type="button"
                    className="mini"
                    style={{ fontWeight: 600 }}
                    onClick={() =>
                      safeDownload(
                        getObservationUrl(runId, { layout: "wide", format: "csv", join: "labels,axes" }),
                        `observation_wide_${runId}.csv`,
                        (m) => setExportNote(m)
                      )
                    }
                  >
                    Observation wide CSV (labels + axes)
                  </button>
                  <button
                    type="button"
                    className="mini"
                    onClick={() =>
                      safeDownload(
                        getObservationUrl(runId, { layout: "long", format: "csv", join: "labels,axes" }),
                        `observation_long_${runId}.csv`,
                        (m) => setExportNote(m)
                      )
                    }
                  >
                    Observation long CSV
                  </button>
                  <button
                    type="button"
                    className="mini"
                    onClick={() =>
                      safeDownload(
                        getObservationUrl(runId, { layout: "wide", format: "parquet", join: "labels,axes" }),
                        `observation_wide_${runId}.parquet`,
                        (m) => setExportNote(m)
                      )
                    }
                  >
                    Observation Parquet (wide)
                  </button>
                </div>
                <div className="hint" style={{ margin: "12px 0 8px" }}>
                  Features only (analysis run columns)
                </div>
                <div className="row" style={{ flexWrap: "wrap", gap: "8px" }}>
                  <button
                    type="button"
                    className="mini"
                    onClick={() =>
                      safeDownload(getExportFeaturesUrl(runId, "wide"), `features_wide_${runId}.csv`, (m) =>
                        setExportNote(m)
                      )
                    }
                  >
                    Features wide CSV
                  </button>
                  <button
                    type="button"
                    className="mini"
                    onClick={() =>
                      safeDownload(getExportFeaturesUrl(runId, "long"), `features_long_${runId}.csv`, (m) =>
                        setExportNote(m)
                      )
                    }
                  >
                    Features long CSV
                  </button>
                </div>
                <div className="hint" style={{ margin: "12px 0 8px" }}>
                  Manifest &amp; bundle
                </div>
                <div className="row" style={{ flexWrap: "wrap", gap: "8px" }}>
                  <button
                    type="button"
                    className="mini"
                    onClick={async () => {
                      setExportNote(null);
                      try {
                        const m = await fetchExportManifest(runId);
                        setManifestJson(JSON.stringify(m, null, 2));
                      } catch (e) {
                        setExportNote(String((e as Error).message));
                      }
                    }}
                  >
                    Load manifest (JSON)
                  </button>
                  <button
                    type="button"
                    className="mini"
                    onClick={() => safeDownload(getExportBundleUrl(runId), `analysis_${runId}_bundle.zip`, (m) => setExportNote(m))}
                  >
                    Bundle (ZIP, features only)
                  </button>
                </div>
                {exportNote ? <div className="err" style={{ marginTop: "8px" }}>{exportNote}</div> : null}
                {manifestJson ? (
                  <pre
                    style={{
                      marginTop: "10px",
                      maxHeight: 240,
                      overflow: "auto",
                      fontSize: "11px",
                      padding: "8px",
                      background: "rgba(0,0,0,0.2)",
                    }}
                  >
                    {manifestJson}
                  </pre>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {section === "correlation" ? (
          <div style={{ marginTop: "14px" }}>
            <div className="section-title">Correlation &amp; VIF</div>
            {emptyRun || selectedRun?.status !== "completed" ? (
              <AnalysisRunGateNotice runId={runId} selectedRun={selectedRun} />
            ) : (
              <>
                <div className="hint" style={{ marginBottom: "8px" }}>
                  Pick columns once and run any method. Correlation uses defaults if none selected; VIF typically needs ≥2
                  numeric columns.
                </div>
                <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
                  <button
                    type="button"
                    disabled={!!exploreBusy}
                    onClick={async () => {
                      setExploreBusy("correlation");
                      setLastError(null);
                      try {
                        const resp = await postCorrelation({
                          analysis_run_id: runId,
                          feature_columns: corrCols.length ? corrCols : null,
                        });
                        setCorrResult(resp.results as Record<string, unknown>);
                      } catch (e) {
                        setLastError(String((e as Error).message));
                      } finally {
                        setExploreBusy(null);
                      }
                    }}
                  >
                    {exploreBusy === "correlation" ? "Running…" : "Run correlation"}
                  </button>
                  <button
                    type="button"
                    disabled={corrCols.length < 2 || !!exploreBusy}
                    onClick={async () => {
                      setExploreBusy("vif");
                      setLastError(null);
                      try {
                        const resp = await postVif({ analysis_run_id: runId, feature_columns: corrCols });
                        setVifResult(resp.results as Record<string, unknown>);
                      } catch (e) {
                        setLastError(String((e as Error).message));
                      } finally {
                        setExploreBusy(null);
                      }
                    }}
                  >
                    {exploreBusy === "vif" ? "Running…" : "Run VIF"}
                  </button>
                </div>

                {schemaQ.data ? (
                  <>
                    <div className="row" style={{ gap: "6px", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="mini"
                        onClick={() => {
                          const all = [...schemaQ.data!.feature_keys, ...schemaQ.data!.axis_keys, ...schemaQ.data!.meta_keys];
                          setCorrCols((prev) => updateSelection(prev, all, "select_all"));
                        }}
                      >
                        Select all (all groups)
                      </button>
                      <button
                        type="button"
                        className="mini"
                        onClick={() => {
                          const all = [...schemaQ.data!.feature_keys, ...schemaQ.data!.axis_keys, ...schemaQ.data!.meta_keys];
                          setCorrCols((prev) => updateSelection(prev, all, "clear"));
                        }}
                      >
                        Clear all
                      </button>
                    </div>
                    {renderColumnGridWithSelectAll("Spectral features", schemaQ.data.feature_keys, corrCols, setCorrCols)}
                    {renderColumnGridWithSelectAll("Axes & grid", schemaQ.data.axis_keys, corrCols, setCorrCols)}
                    {renderColumnGridWithSelectAll("Experiment metadata (upload)", schemaQ.data.meta_keys, corrCols, setCorrCols)}
                  </>
                ) : (
                  <div style={{ maxHeight: 140, overflow: "auto", border: "1px solid rgba(255,255,255,0.08)", padding: "6px" }}>
                    {featureColumns.map((c) => (
                      <label key={c} className="inline" style={{ display: "block" }}>
                        <input
                          type="checkbox"
                          checked={corrCols.includes(c)}
                          onChange={(e) => setCorrCols(toggleCol(corrCols, c, e.target.checked))}
                        />{" "}
                        {c}
                      </label>
                    ))}
                  </div>
                )}
                {corrFigure?.warn ? (
                  <div className="hint" style={{ marginTop: "8px" }}>
                    Large correlation matrix: rendering may be slow; consider fewer columns.
                  </div>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {section === "pca_cluster" ? (
          <div style={{ marginTop: "14px" }}>
            <div className="section-title">PCA &amp; k-means</div>
            {emptyRun || selectedRun?.status !== "completed" ? (
              <AnalysisRunGateNotice runId={runId} selectedRun={selectedRun} />
            ) : (
              <>
                <div className="hint" style={{ marginBottom: "8px" }}>
                  Run PCA (or Sparse PCA) and k-means on the selected columns. Plots/export are controlled below.
                </div>

                <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
                  <button
                    type="button"
                    disabled={!!exploreBusy}
                    onClick={async () => {
                      setExploreBusy("pca");
                      setLastError(null);
                      try {
                        const resp = await postPca({
                          analysis_run_id: runId,
                          n_components: pcaN === "" ? null : pcaN,
                          feature_columns: corrCols.length ? corrCols : null,
                          method: pcaMethod,
                          scaler: pcaScaler,
                          spca_alpha: spcaAlpha,
                          spca_ridge_alpha: spcaRidge,
                        });
                        setPcaResult(resp.results as Record<string, unknown>);
                      } catch (e) {
                        setLastError(String((e as Error).message));
                      } finally {
                        setExploreBusy(null);
                      }
                    }}
                  >
                    {exploreBusy === "pca" ? "Running…" : pcaMethod === "spca" ? "Run sparse PCA" : "Run PCA"}
                  </button>
                  <button
                    type="button"
                    disabled={!!exploreBusy}
                    onClick={async () => {
                      setExploreBusy("cluster");
                      setLastError(null);
                      try {
                        const resp = await postCluster({
                          analysis_run_id: runId,
                          n_clusters: clusterK,
                          feature_columns: corrCols.length ? corrCols : null,
                          seed: clusterSeed,
                        });
                        setClusterResult(resp.results as Record<string, unknown>);
                      } catch (e) {
                        setLastError(String((e as Error).message));
                      } finally {
                        setExploreBusy(null);
                      }
                    }}
                  >
                    {exploreBusy === "cluster" ? "Running…" : "Run k-means"}
                  </button>
                </div>

                <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "flex-end", marginTop: "8px" }}>
                  <label className="inline">
                    PCA method
                    <select value={pcaMethod} onChange={(e) => setPcaMethod(e.target.value as "pca" | "spca")}>
                      <option value="pca">PCA</option>
                      <option value="spca">Sparse PCA</option>
                    </select>
                  </label>
                  <label className="inline" title="Feature PCA often benefits from unit-variance scaling when columns have different units or magnitudes.">
                    Scaling
                    <select value={pcaScaler} onChange={(e) => setPcaScaler(e.target.value as PcaScaler)}>
                      <option value="none">None / mean-center only</option>
                      <option value="standard">StandardScaler / unit variance</option>
                    </select>
                  </label>
                  <label className="inline">
                    n_components
                    <input
                      type="number"
                      min={1}
                      value={pcaN === "" ? "" : pcaN}
                      placeholder="default"
                      onChange={(e) => {
                        const v = e.target.value;
                        setPcaN(v === "" ? "" : Number(v));
                      }}
                    />
                  </label>
                  {pcaMethod === "spca" ? (
                    <>
                      <label className="inline">
                        spca_alpha
                        <input type="number" step="any" value={spcaAlpha} onChange={(e) => setSpcaAlpha(Number(e.target.value))} />
                      </label>
                      <label className="inline">
                        spca_ridge_alpha
                        <input type="number" step="any" value={spcaRidge} onChange={(e) => setSpcaRidge(Number(e.target.value))} />
                      </label>
                    </>
                  ) : null}
                  <label className="inline">
                    k (k-means)
                    <input type="number" min={2} max={200} value={clusterK} onChange={(e) => setClusterK(Number(e.target.value))} />
                  </label>
                  <label className="inline">
                    seed
                    <input type="number" value={clusterSeed} onChange={(e) => setClusterSeed(Number(e.target.value))} />
                  </label>
                </div>

                <div className="hint" style={{ marginTop: "6px" }}>
                  StandardScaler is usually helpful for feature PCA when selected columns use different units or intensity scales.
                </div>

                <div className="hint" style={{ marginTop: "10px" }}>
                  Plot settings
                </div>
                <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "flex-end" }}>
                  <label className="inline">
                    Scatter X PC
                    <input type="number" min={1} value={scoresXpc} onChange={(e) => setScoresXpc(Number(e.target.value))} />
                  </label>
                  <label className="inline">
                    Scatter Y PC
                    <input type="number" min={1} value={scoresYpc} onChange={(e) => setScoresYpc(Number(e.target.value))} />
                  </label>
                  <label className="inline" title="Comma-separated list, e.g. 2,3,4,5,6">
                    Pairplot PCs
                    <input
                      type="text"
                      value={pairplotPcs.join(",")}
                      onChange={(e) => {
                        const pcs = e.target.value
                          .split(",")
                          .map((x) => Number(x.trim()))
                          .filter((n) => Number.isFinite(n) && n >= 1)
                          .map((n) => Math.floor(n));
                        setPairplotPcs(pcs.length ? pcs : []);
                      }}
                    />
                  </label>
                  <label className="inline">
                    Loadings topN
                    <input type="number" min={1} max={200} value={loadingsTopN} onChange={(e) => setLoadingsTopN(Number(e.target.value))} />
                  </label>
                </div>

                <div className="row" style={{ gap: "14px", flexWrap: "wrap", alignItems: "center", marginTop: "8px" }}>
                  <div className="hint" style={{ margin: 0 }}>
                    Plots
                  </div>
                  {[
                    ["scores_scatter", "Scores scatter"],
                    ["scores_pairplot", "Scores pairplot"],
                    ["scree", "Scree"],
                    ["cumulative_evr", "Cumulative EVR"],
                    ["loadings_topn", "Loadings topN"],
                    ["loadings_heatmap", "Loadings heatmap"],
                  ].map(([id, label]) => (
                    <label key={id} className="inline">
                      <input
                        type="checkbox"
                        checked={selectedPcaPlots.includes(id)}
                        onChange={(e) => setSelectedPcaPlots(toggleCol(selectedPcaPlots, id, e.target.checked))}
                      />{" "}
                      {label}
                    </label>
                  ))}
                  {[
                    ["cluster_on_scores_scatter", "Cluster on scores"],
                    ["cluster_sizes", "Cluster sizes"],
                  ].map(([id, label]) => (
                    <label key={id} className="inline">
                      <input
                        type="checkbox"
                        checked={selectedClusterPlots.includes(id)}
                        onChange={(e) => setSelectedClusterPlots(toggleCol(selectedClusterPlots, id, e.target.checked))}
                      />{" "}
                      {label}
                    </label>
                  ))}
                </div>

                {schemaQ.data ? (
                  <>
                    <div className="row" style={{ gap: "6px", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="mini"
                        onClick={() => {
                          const all = [...schemaQ.data!.feature_keys, ...schemaQ.data!.axis_keys, ...schemaQ.data!.meta_keys];
                          setCorrCols((prev) => updateSelection(prev, all, "select_all"));
                        }}
                      >
                        Select all (all groups)
                      </button>
                      <button
                        type="button"
                        className="mini"
                        onClick={() => {
                          const all = [...schemaQ.data!.feature_keys, ...schemaQ.data!.axis_keys, ...schemaQ.data!.meta_keys];
                          setCorrCols((prev) => updateSelection(prev, all, "clear"));
                        }}
                      >
                        Clear all
                      </button>
                    </div>
                    {renderColumnGridWithSelectAll("Spectral features", schemaQ.data.feature_keys, corrCols, setCorrCols)}
                    {renderColumnGridWithSelectAll("Axes & grid", schemaQ.data.axis_keys, corrCols, setCorrCols)}
                    {renderColumnGridWithSelectAll("Experiment metadata (upload)", schemaQ.data.meta_keys, corrCols, setCorrCols)}
                  </>
                ) : (
                  <div style={{ maxHeight: 140, overflow: "auto", border: "1px solid rgba(255,255,255,0.08)", padding: "6px" }}>
                    {featureColumns.map((c) => (
                      <label key={c} className="inline" style={{ display: "block" }}>
                        <input
                          type="checkbox"
                          checked={corrCols.includes(c)}
                          onChange={(e) => setCorrCols(toggleCol(corrCols, c, e.target.checked))}
                        />{" "}
                        {c}
                      </label>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        ) : null}

        {section === "meta_plot" ? (
          <div style={{ marginTop: "14px" }}>
            <div className="section-title">Parameter vs parameter</div>
            {emptyRun || selectedRun?.status !== "completed" ? (
              <AnalysisRunGateNotice runId={runId} selectedRun={selectedRun} />
            ) : (
              <>
                <p className="hint">
                  Scatter plot of numeric columns from the merged observation row (features, <code>meta_*</code>, axes).
                  Pick X and Y; optional color uses a third numeric column.
                </p>
                <div className="row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "flex-end" }}>
                  <label className="inline">
                    Style
                    <select
                      value={metaPlotStyle}
                      onChange={(e) =>
                        setMetaPlotStyle(e.target.value as "scatter" | "errorbars" | "errorbars_line" | "boxplot")
                      }
                    >
                      <option value="scatter">Scatter</option>
                      <option value="errorbars">Mean ± error bars (group by X)</option>
                      <option value="errorbars_line">Line + error bars (group by X)</option>
                      <option value="boxplot">Boxplot (group by X)</option>
                    </select>
                  </label>
                  <label className="inline">
                    X
                    <select value={metaX} onChange={(e) => setMetaX(e.target.value)}>
                      <option value="">—</option>
                      {selectableColumns.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="inline">
                    Y
                    <select value={metaY} onChange={(e) => setMetaY(e.target.value)}>
                      <option value="">—</option>
                      {selectableColumns.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="inline">
                    Color (optional)
                    <select value={metaColor} onChange={(e) => setMetaColor(e.target.value)}>
                      <option value="">—</option>
                      {selectableColumns.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  </label>
                  {metaPlotStyle === "errorbars" || metaPlotStyle === "errorbars_line" ? (
                    <>
                      <label className="inline">
                        X error (optional)
                        <select value={metaXErr} onChange={(e) => setMetaXErr(e.target.value)}>
                          <option value="">—</option>
                          {selectableColumns.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="inline">
                        Y error (optional)
                        <select value={metaYErr} onChange={(e) => setMetaYErr(e.target.value)}>
                          <option value="">—</option>
                          {selectableColumns.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                      </label>
                    </>
                  ) : null}
                  <button
                    type="button"
                    disabled={!!exploreBusy || !metaX || !metaY}
                    onClick={async () => {
                      setExploreBusy("meta_scatter");
                      setLastError(null);
                      setMetaScatterFig(null);
                      setMetaScatterCsvRows([]);
                      try {
                        const cols = [metaX, metaY, metaColor, metaXErr, metaYErr].filter(Boolean);
                        const uniq = Array.from(new Set(cols));
                        const { rows } = await fetchObservationColumns(runId, uniq, 200_000);
                        type CsvRow = {
                          spectrum_id: string;
                          x: number;
                          y: number;
                          color?: number | null;
                          x_err?: number | null;
                          y_err?: number | null;
                        };

                        const raw: CsvRow[] = [];
                        for (const r of rows) {
                          const x = cellToNumber(r[metaX]);
                          const y = cellToNumber(r[metaY]);
                          if (x === null || y === null) continue;
                          const sid = String(r.spectrum_id ?? "");
                          const color = metaColor ? cellToNumber(r[metaColor]) : null;
                          const xErr = metaXErr ? cellToNumber(r[metaXErr]) : null;
                          const yErr = metaYErr ? cellToNumber(r[metaYErr]) : null;
                          raw.push({ spectrum_id: sid, x, y, color, x_err: xErr, y_err: yErr });
                        }

                        if (metaPlotStyle === "scatter") {
                          const xv = raw.map((r) => r.x);
                          const yv = raw.map((r) => r.y);
                          const text = raw.map((r) => r.spectrum_id);
                          const cv = metaColor ? raw.map((r) => r.color ?? null) : [];

                          const trace: Record<string, unknown> = {
                            type: "scatter",
                            mode: "markers",
                            x: xv,
                            y: yv,
                            text,
                            marker: { size: 7 },
                          };
                          if (metaColor && cv.length === xv.length && cv.some((v) => v !== null)) {
                            trace.marker = { size: 7, color: cv, colorscale: "Viridis", showscale: true };
                          }
                          setMetaScatterCsvRows(raw);
                          setMetaScatterFig({
                            data: [trace],
                            layout: {
                              title: `${metaY} vs ${metaX}`,
                              xaxis: { title: metaX },
                              yaxis: { title: metaY },
                            },
                          });
                          return;
                        }

                        // Aggregated modes: group by X (and optional discrete color).
                        // Intended for experiments where X represents a controllable parameter value.
                        type GroupKey = string;
                        type Group = {
                          xVals: number[];
                          yVals: number[];
                          colorVals: (number | null)[];
                          xErrVals: number[];
                          yErrVals: number[];
                        };
                        const groups = new Map<GroupKey, Group>();

                        function colorBucket(v: number | null): string {
                          if (v === null || !Number.isFinite(v)) return "—";
                          return stableNumberKey(v, 6);
                        }

                        const uniqueColorBuckets = new Set<string>();
                        for (const r of raw) {
                          if (!metaColor) break;
                          uniqueColorBuckets.add(colorBucket(r.color ?? null));
                          if (uniqueColorBuckets.size > 40) break;
                        }
                        // Only treat color as a grouping dimension when it behaves like a discrete factor.
                        const useColorGrouping = !!metaColor && uniqueColorBuckets.size > 1 && uniqueColorBuckets.size <= 12;

                        for (const r of raw) {
                          const xKey = stableNumberKey(r.x, 6);
                          const cKey = useColorGrouping ? colorBucket(r.color ?? null) : "";
                          const key = useColorGrouping ? `${cKey}||${xKey}` : xKey;
                          const g =
                            groups.get(key) ?? { xVals: [], yVals: [], colorVals: [], xErrVals: [], yErrVals: [] };
                          g.xVals.push(r.x);
                          g.yVals.push(r.y);
                          if (useColorGrouping) g.colorVals.push(r.color ?? null);
                          if (typeof r.x_err === "number" && Number.isFinite(r.x_err)) g.xErrVals.push(r.x_err);
                          if (typeof r.y_err === "number" && Number.isFinite(r.y_err)) g.yErrVals.push(r.y_err);
                          groups.set(key, g);
                        }

                        // Build series: if metaColor present and seems discrete, make one trace per color bucket.
                        const byColor = new Map<
                          string,
                          { x: number[]; y: number[]; xerr: number[]; yerr: number[]; n: number[] }
                        >();
                        for (const [key, g] of groups.entries()) {
                          const [cKey] = useColorGrouping ? key.split("||") : [""];
                          const xStats = meanStd(g.xVals);
                          const yStats = meanStd(g.yVals);
                          const xMean = xStats.mean;
                          const yMean = yStats.mean;
                          const yStd = yStats.std;
                          const xErrMean = g.xErrVals.length ? meanStd(g.xErrVals).mean : 0;
                          const yErrMean = g.yErrVals.length ? meanStd(g.yErrVals).mean : NaN;
                          const yErrFinal = Number.isFinite(yErrMean) ? yErrMean : yStd;
                          if (!Number.isFinite(xMean) || !Number.isFinite(yMean) || !Number.isFinite(yErrFinal)) continue;
                          const seriesKey = useColorGrouping ? cKey : "__all__";
                          const s = byColor.get(seriesKey) ?? { x: [], y: [], xerr: [], yerr: [], n: [] };
                          s.x.push(xMean);
                          s.y.push(yMean);
                          s.xerr.push(Number.isFinite(xErrMean) ? xErrMean : 0);
                          s.yerr.push(yErrFinal);
                          s.n.push(g.yVals.length);
                          byColor.set(seriesKey, s);
                        }

                        const traces: Record<string, unknown>[] = [];
                        const seriesKeys = Array.from(byColor.keys());
                        // If too many unique colors, collapse to one trace.
                        const collapseColor = useColorGrouping && seriesKeys.length > 12;
                        const finalSeries = collapseColor ? new Map([["__all__", {
                          x: seriesKeys.flatMap((k) => byColor.get(k)!.x),
                          y: seriesKeys.flatMap((k) => byColor.get(k)!.y),
                          xerr: seriesKeys.flatMap((k) => byColor.get(k)!.xerr),
                          yerr: seriesKeys.flatMap((k) => byColor.get(k)!.yerr),
                          n: seriesKeys.flatMap((k) => byColor.get(k)!.n),
                        }]]) : byColor;

                        for (const [k, s] of finalSeries.entries()) {
                          // Sort by X so lineplot is meaningful.
                          const idx = s.x.map((v, i) => [v, i] as const).sort((a, b) => a[0] - b[0]).map((t) => t[1]);
                          const xs = idx.map((i) => s.x[i]);
                          const ys = idx.map((i) => s.y[i]);
                          const xerrs = idx.map((i) => (s as any).xerr?.[i] ?? 0);
                          const yerrs = idx.map((i) => s.yerr[i]);
                          const ns = idx.map((i) => s.n[i]);
                          const label = useColorGrouping && !collapseColor ? `${metaColor}=${k}` : undefined;
                          const mode = metaPlotStyle === "errorbars_line" ? "lines+markers" : "markers";
                          const tr: Record<string, unknown> = {
                            type: "scatter",
                            mode,
                            name: label,
                            x: xs,
                            y: ys,
                            text: ns.map((n) => `n=${n}`),
                            marker: { size: 8 },
                            error_y: { type: "data", array: yerrs, visible: true },
                          };
                          if (metaXErr) tr.error_x = { type: "data", array: xerrs, visible: true };
                          traces.push(tr);
                        }

                        setMetaScatterCsvRows(raw);
                        if (metaPlotStyle === "boxplot") {
                          // Boxplot: one box per unique X (and per discrete color bucket if applicable).
                          const orderedX = Array.from(new Set(raw.map((r) => r.x).sort((a, b) => a - b)));
                          const boxTraces: Record<string, unknown>[] = [];
                          if (useColorGrouping && !collapseColor) {
                            const byBucket = new Map<string, { x: number[]; y: number[] }>();
                            for (const r of raw) {
                              const cKey = colorBucket(r.color ?? null);
                              const b = byBucket.get(cKey) ?? { x: [], y: [] };
                              b.x.push(r.x);
                              b.y.push(r.y);
                              byBucket.set(cKey, b);
                            }
                            for (const [cKey, s] of Array.from(byBucket.entries()).sort((a, b) => a[0].localeCompare(b[0]))) {
                              boxTraces.push({
                                type: "box",
                                name: `${metaColor}=${cKey}`,
                                x: s.x.map((v) => stableNumberKey(v, 6)),
                                y: s.y,
                                boxpoints: false,
                              });
                            }
                          } else {
                            boxTraces.push({
                              type: "box",
                              x: raw.map((r) => stableNumberKey(r.x, 6)),
                              y: raw.map((r) => r.y),
                              boxpoints: false,
                            });
                          }
                          setMetaScatterFig({
                            data: boxTraces.length ? boxTraces : [{ type: "box", x: [], y: [] }],
                            layout: {
                              title: `${metaY} vs ${metaX} (boxplot grouped by X)`,
                              xaxis: {
                                title: metaX,
                                categoryorder: "array",
                                categoryarray: orderedX.map((v) => stableNumberKey(v, 6)),
                              },
                              yaxis: { title: metaY },
                              boxmode: "group",
                              margin: { l: 60, r: 20, t: 40, b: 70 },
                            },
                          });
                          return;
                        }

                        setMetaScatterFig({
                          data: traces.length ? traces : [{ type: "scatter", mode: "markers", x: [], y: [] }],
                          layout: {
                            title: `${metaY} vs ${metaX} (grouped by X)`,
                            xaxis: { title: metaX },
                            yaxis: { title: metaY },
                          },
                        });
                      } catch (e) {
                        setLastError(String((e as Error).message));
                      } finally {
                        setExploreBusy(null);
                      }
                    }}
                  >
                    {exploreBusy === "meta_scatter" ? "Loading…" : "Plot"}
                  </button>
                  <button
                    type="button"
                    disabled={!metaScatterFig || !metaPlotDivRef.current}
                    onClick={async () => {
                      const el = metaPlotDivRef.current;
                      if (!el) return;
                      try {
                        await Plotly.downloadImage(el, {
                          format: "png",
                          filename: `scatter_${metaX}_${metaY}`,
                          width: 1200,
                          height: 800,
                          scale: 2,
                        });
                      } catch (e) {
                        setLastError(String((e as Error).message));
                      }
                    }}
                  >
                    Export plot (PNG)
                  </button>
                  <button
                    type="button"
                    disabled={!metaScatterCsvRows.length}
                    onClick={() => {
                      const headerCols = ["spectrum_id", metaX, metaY];
                      if (metaColor) headerCols.push(metaColor);
                      if (metaXErr) headerCols.push(metaXErr);
                      if (metaYErr) headerCols.push(metaYErr);
                      const header = headerCols.join(",");
                      const lines = metaScatterCsvRows.map((r) => {
                        const vals: (string | number | null | undefined)[] = [r.spectrum_id, r.x, r.y];
                        if (metaColor) vals.push(r.color);
                        if (metaXErr) vals.push(r.x_err);
                        if (metaYErr) vals.push(r.y_err);
                        return vals.map((v) => (v === null || v === undefined ? "" : String(v))).join(",");
                      });
                      const csv = [header, ...lines].join("\n");
                      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
                      triggerBlobDownload(blob, `scatter_${metaX}_${metaY}.csv`);
                    }}
                  >
                    Export CSV
                  </button>
                </div>
              </>
            )}
          </div>
        ) : null}

        {section === "spectrum_matrix" ? (
          <div style={{ marginTop: "14px" }}>
            <div className="section-title">Matrix export job</div>
            <p className="hint">
              Materializes a shared wavenumber grid for <b>all spectra</b> in the dataset (session subset does not apply).
              Use <code>up_to_step</code> to stop after a pipeline step (e.g. crop + normalize), or leave empty for the full
              saved pipeline. Export needs the <b>same</b> Raman shift axis for every spectrum. If the job fails with
              inconsistent grids, apply a <b>consistent crop</b> to all spectra and add <code>align_resample</code> after crop,
              then choose <code>up_to_step</code> = <code>align_resample</code> (or a later step). Align alone is not enough if
              spectra end up with different surviving wavenumber ranges after crop—then grids can still differ in length.
            </p>
            {emptyDataset || emptyPipeline || !selectedPipeline ? (
              <div className="hint">Select dataset and pipeline.</div>
            ) : (
              <>
                <label className="inline">
                  up_to_step (optional)
                  <select value={matrixUpTo} onChange={(e) => setMatrixUpTo(e.target.value)}>
                    <option value="">Final (all steps)</option>
                    {matrixStepOptions.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="row" style={{ marginTop: "8px" }}>
                  <button
                    type="button"
                    disabled={!!exploreBusy}
                    onClick={async () => {
                      setExploreBusy("matrix");
                      setLastError(null);
                      setFpcaDiscResult(null);
                      setFpcaDiscExploreId(null);
                      setFpcaFdaResult(null);
                      setFpcaFdaExploreId(null);
                      try {
                        const resp = await postMatrixJob({
                          dataset_id: datasetId,
                          pipeline: selectedPipeline.pipeline,
                          up_to_step: matrixUpTo || null,
                          async: true,
                        });
                        setMatrixJobId(resp.matrix_job_id);
                      } catch (e) {
                        setLastError(String((e as Error).message));
                      } finally {
                        setExploreBusy(null);
                      }
                    }}
                  >
                    {exploreBusy === "matrix" ? "Starting…" : "Start matrix job (async)"}
                  </button>
                  <button
                    type="button"
                    className="mini"
                    disabled={matrixPollQ.data?.status !== "completed" || !effectiveMatrixId}
                    onClick={() => {
                      if (!effectiveMatrixId) return;
                      safeDownload(
                        getMatrixJobExportUrl(effectiveMatrixId),
                        `matrix_${effectiveMatrixId}.csv`,
                        (m) => setLastError(m)
                      );
                    }}
                  >
                    Download matrix CSV
                  </button>
                </div>
                {matrixJobId || matrixPollQ.data ? (
                  <div className="hint" style={{ marginTop: "10px" }}>
                    <div>
                      <b>Job:</b> {matrixJobId ?? matrixPollQ.data?.matrix_job_id}
                    </div>
                    <div>
                      <b>Status:</b> {matrixPollQ.data?.status ?? "—"}
                    </div>
                    <div style={{ wordBreak: "break-all" }}>
                      <b>NPZ:</b> {matrixPollQ.data?.npz_path ?? "—"}
                    </div>
                    {matrixPollQ.data?.error ? (
                      <div className="err" style={{ marginTop: "6px" }}>
                        {matrixPollQ.data.error}
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="hint" style={{ marginTop: "8px" }}>
                    No matrix job yet.
                  </div>
                )}
              </>
            )}

            <div className="section-title" style={{ marginTop: "14px" }}>
              Spectrum multivariate
            </div>
            {!matrixPollQ.data?.npz_path || matrixPollQ.data?.status !== "completed" || !effectiveMatrixId ? (
              <div className="hint">Complete a matrix job above first.</div>
            ) : (
              <>
                <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
                  <label className="inline">
                    Discrete method
                    <select value={discreteMethod} onChange={(e) => setDiscreteMethod(e.target.value as "pca" | "spca")}>
                      <option value="pca">PCA on Y</option>
                      <option value="spca">Sparse PCA on Y</option>
                    </select>
                  </label>
                  <label className="inline" title="Unit-variance scaling can amplify noisy Raman regions; use it deliberately for spectrum PCA.">
                    Scaling
                    <select value={discreteScaler} onChange={(e) => setDiscreteScaler(e.target.value as PcaScaler)}>
                      <option value="none">None / mean-center only</option>
                      <option value="standard">StandardScaler / unit variance</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={!!exploreBusy}
                    onClick={async () => {
                      setExploreBusy("fpca_d");
                      setLastError(null);
                      try {
                        const resp = await postFpcaDiscrete({
                          matrix_job_id: effectiveMatrixId,
                          method: discreteMethod,
                          n_components: fpcaN === "" ? null : fpcaN,
                          scaler: discreteScaler,
                          spca_alpha: spcaAlpha,
                          spca_ridge_alpha: spcaRidge,
                        });
                        setFpcaDiscResult(resp.results as Record<string, unknown>);
                        setFpcaDiscExploreId(resp.explore_id);
                      } catch (e) {
                        setLastError(String((e as Error).message));
                      } finally {
                        setExploreBusy(null);
                      }
                    }}
                  >
                    {exploreBusy === "fpca_d" ? "Running…" : discreteMethod === "spca" ? "Run discrete sparse PCA" : "Run discrete PCA"}
                  </button>
                  <label className="inline">
                    n_components
                    <input
                      type="number"
                      min={1}
                      value={fpcaN === "" ? "" : fpcaN}
                      placeholder="default"
                      onChange={(e) => {
                        const v = e.target.value;
                        setFpcaN(v === "" ? "" : Number(v));
                      }}
                    />
                  </label>
                  {discreteMethod === "spca" ? (
                    <>
                      <label className="inline">
                        spca_alpha
                        <input
                          type="number"
                          step="any"
                          value={spcaAlpha}
                          onChange={(e) => setSpcaAlpha(Number(e.target.value))}
                        />
                      </label>
                      <label className="inline">
                        spca_ridge_alpha
                        <input
                          type="number"
                          step="any"
                          value={spcaRidge}
                          onChange={(e) => setSpcaRidge(Number(e.target.value))}
                        />
                      </label>
                    </>
                  ) : null}
                  <label className="inline">
                    Spectrum k-means k
                    <input
                      type="number"
                      min={2}
                      max={200}
                      value={spectrumClusterK}
                      onChange={(e) => setSpectrumClusterK(Number(e.target.value))}
                    />
                  </label>
                  <label className="inline" title="Random seed for k-means initialization">
                    seed
                    <input
                      type="number"
                      value={spectrumClusterSeed}
                      onChange={(e) => setSpectrumClusterSeed(Number(e.target.value))}
                    />
                  </label>
                  <label
                    className="inline"
                    title="Number of PCs of Y used as embedding for spectrum k-means"
                  >
                    n_pc_embedding
                    <input
                      type="number"
                      min={1}
                      max={500}
                      value={spectrumClusterPcEmbedding}
                      onChange={(e) => setSpectrumClusterPcEmbedding(Number(e.target.value))}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={!!exploreBusy}
                    onClick={async () => {
                      setExploreBusy("spec_cl");
                      setLastError(null);
                      try {
                        const resp = await postSpectrumCluster({
                          matrix_job_id: effectiveMatrixId,
                          n_clusters: spectrumClusterK,
                          seed: spectrumClusterSeed,
                          n_pc_embedding: spectrumClusterPcEmbedding,
                        });
                        setSpectrumClusterResult(resp.results as Record<string, unknown>);
                      } catch (e) {
                        setLastError(String((e as Error).message));
                      } finally {
                        setExploreBusy(null);
                      }
                    }}
                  >
                    {exploreBusy === "spec_cl" ? "Running…" : "k-means (PC embedding)"}
                  </button>
                  <button
                    type="button"
                    disabled={!!exploreBusy}
                    onClick={async () => {
                      setExploreBusy("fpca_fda");
                      setLastError(null);
                      try {
                        const resp = await postFpcaFda({
                          matrix_job_id: effectiveMatrixId,
                          n_components: fpcaN === "" ? null : fpcaN,
                        });
                        setFpcaFdaResult(resp.results as Record<string, unknown>);
                        setFpcaFdaExploreId(resp.explore_id);
                      } catch (e) {
                        const msg = String((e as Error).message);
                        setLastError(msg);
                        if (msg.includes("501") || msg.toLowerCase().includes("scikit")) {
                          setLastError(`${msg} (FDA FPCA may require optional dependencies on the server.)`);
                        }
                      } finally {
                        setExploreBusy(null);
                      }
                    }}
                  >
                    {exploreBusy === "fpca_fda" ? "Running…" : "FDA FPCA"}
                  </button>
                </div>
                {fpcaDiscResult ? (
                  <div className="hint" style={{ marginTop: "8px" }}>
                    Discrete FPCA completed{fpcaDiscExploreId ? ` (${fpcaDiscExploreId})` : ""}.
                  </div>
                ) : null}
                {fpcaDiscExploreId ? (
                  <div className="row" style={{ gap: "8px", flexWrap: "wrap", marginTop: "8px" }}>
                    {(["scores", "loadings", "variance", "mean"] as const).map((kind) => (
                      <button
                        key={`fpca-disc-${kind}`}
                        type="button"
                        className="mini"
                        onClick={() =>
                          safeDownload(
                            getExplorePcaExportUrl(fpcaDiscExploreId, kind),
                            `spectrum_pca_${kind}_${fpcaDiscExploreId}.csv`,
                            (m) => setLastError(m)
                          )
                        }
                      >
                        Download {kind} CSV
                      </button>
                    ))}
                  </div>
                ) : null}
                {fpcaFdaResult ? (
                  <div className="hint" style={{ marginTop: "8px" }}>
                    FDA FPCA completed{fpcaFdaExploreId ? ` (${fpcaFdaExploreId})` : ""}.
                  </div>
                ) : null}
                {fpcaFdaExploreId ? (
                  <div className="row" style={{ gap: "8px", flexWrap: "wrap", marginTop: "8px" }}>
                    {(["scores", "loadings", "variance", "mean"] as const).map((kind) => (
                      <button
                        key={`fpca-fda-${kind}`}
                        type="button"
                        className="mini"
                        onClick={() =>
                          safeDownload(
                            getExplorePcaExportUrl(fpcaFdaExploreId, kind),
                            `spectrum_fpca_fda_${kind}_${fpcaFdaExploreId}.csv`,
                            (m) => setLastError(m)
                          )
                        }
                      >
                        Download FDA {kind} CSV
                      </button>
                    ))}
                  </div>
                ) : null}

                <div className="hint" style={{ marginTop: "12px" }}>
                  Plot settings (applies to spectrum PCA/FPCA plots)
                </div>
                <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "flex-end" }}>
                  <label className="inline">
                    Scatter X PC
                    <input type="number" min={1} value={scoresXpc} onChange={(e) => setScoresXpc(Number(e.target.value))} />
                  </label>
                  <label className="inline">
                    Scatter Y PC
                    <input type="number" min={1} value={scoresYpc} onChange={(e) => setScoresYpc(Number(e.target.value))} />
                  </label>
                  <label className="inline" title="Comma-separated list, e.g. 2,3,4,5,6">
                    Pairplot PCs
                    <input
                      type="text"
                      value={pairplotPcs.join(",")}
                      onChange={(e) => {
                        const pcs = e.target.value
                          .split(",")
                          .map((x) => Number(x.trim()))
                          .filter((n) => Number.isFinite(n) && n >= 1)
                          .map((n) => Math.floor(n));
                        setPairplotPcs(pcs.length ? pcs : []);
                      }}
                    />
                  </label>
                  <label className="inline">
                    Loadings topN
                    <input type="number" min={1} max={200} value={loadingsTopN} onChange={(e) => setLoadingsTopN(Number(e.target.value))} />
                  </label>
                </div>

                <div className="row" style={{ gap: "14px", flexWrap: "wrap", alignItems: "center", marginTop: "8px" }}>
                  <div className="hint" style={{ margin: 0 }}>
                    Plots
                  </div>
                  {[
                    ["scores_scatter", "Scores scatter"],
                    ["scores_pairplot", "Scores pairplot"],
                    ["scree", "Scree"],
                    ["cumulative_evr", "Cumulative EVR"],
                    ["loadings_topn", "Loadings topN"],
                    ["loadings_heatmap", "Loadings heatmap"],
                  ].map(([id, label]) => (
                    <label key={id} className="inline">
                      <input
                        type="checkbox"
                        checked={selectedPcaPlots.includes(id)}
                        onChange={(e) => setSelectedPcaPlots(toggleCol(selectedPcaPlots, id, e.target.checked))}
                      />{" "}
                      {label}
                    </label>
                  ))}
                  {[
                    ["cluster_on_scores_scatter", "Cluster on scores"],
                    ["cluster_sizes", "Cluster sizes"],
                  ].map(([id, label]) => (
                    <label key={id} className="inline">
                      <input
                        type="checkbox"
                        checked={selectedClusterPlots.includes(id)}
                        onChange={(e) => setSelectedClusterPlots(toggleCol(selectedClusterPlots, id, e.target.checked))}
                      />{" "}
                      {label}
                    </label>
                  ))}
                </div>
              </>
            )}

            <div className="section-title" style={{ marginTop: "14px" }}>
              Spectrum axes (dataset)
            </div>
            {emptyDataset ? (
              <div className="hint">Select a dataset.</div>
            ) : axesQ.isLoading ? (
              <div className="hint">Loading…</div>
            ) : (
              <div style={{ maxHeight: 160, overflow: "auto", fontSize: "11px" }}>
                {(axesQ.data?.items ?? []).map((row, i) => (
                  <pre key={i} style={{ margin: "4px 0", whiteSpace: "pre-wrap" }}>
                    {JSON.stringify(row)}
                  </pre>
                ))}
                {!axesQ.data?.items?.length ? <div className="hint">No axis rows.</div> : null}
              </div>
            )}
          </div>
        ) : null}
      </div>

      <div className="preprocess-right card">
        <div className="section-title">Plots &amp; results</div>
        {section === "meta_plot" && metaScatterFig ? (
          <PlotlyWrapper
            ref={metaPlotDivRef}
            figure={metaScatterFig}
            previousFigure={null}
            plotStyle={{ mode: "overlay", stackSep: 0 }}
            ghostOverlayEnabled={false}
            className="plot-host"
          />
        ) : null}
        {section === "correlation" && corrFigure ? (
          <PlotlyWrapper
            figure={corrFigure.figure}
            previousFigure={null}
            plotStyle={{ mode: "overlay", stackSep: 0 }}
            ghostOverlayEnabled={false}
            className="plot-host"
          />
        ) : null}
        {section === "correlation" && vifFigure ? (
          <PlotlyWrapper
            figure={vifFigure}
            previousFigure={null}
            plotStyle={{ mode: "overlay", stackSep: 0 }}
            ghostOverlayEnabled={false}
            className="plot-host"
          />
        ) : null}
        {section === "pca_cluster" && clusterResult?.labels ? (
          <div style={{ marginTop: "10px", maxHeight: 280, overflow: "auto", fontSize: "11px" }}>
            <div className="hint">Cluster labels (sample)</div>
            <table className="mini-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>spectrum_id</th>
                  <th>label</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(clusterResult.labels as Record<string, number>)
                  .slice(0, 80)
                  .map(([sid, lb]) => (
                    <tr key={sid}>
                      <td title={sid}>{sid.slice(0, 18)}…</td>
                      <td>{lb}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {section === "spectrum_matrix" && spectrumClusterResult?.labels ? (
          <div style={{ marginTop: "10px", maxHeight: 280, overflow: "auto", fontSize: "11px" }}>
            <div className="hint">Spectrum matrix k-means (sample)</div>
            <table className="mini-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th>spectrum_id</th>
                  <th>label</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(spectrumClusterResult.labels as Record<string, number>)
                  .slice(0, 80)
                  .map(([sid, lb]) => (
                    <tr key={sid}>
                      <td title={sid}>{sid.slice(0, 18)}…</td>
                      <td>{lb}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {section === "spectrum_matrix" && (fpcaDiscResult || fpcaFdaResult) ? (
          <div className="hint" style={{ marginTop: "8px" }}>
            Backend JSON includes optional <code>plots</code> paths; open API artifact_dir on the server for full outputs.
          </div>
        ) : null}
        {(section === "pca_cluster" || section === "spectrum_matrix") && plotCards.length ? (
          <div style={{ marginTop: "10px" }}>
            <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "center", marginBottom: "8px" }}>
              <button type="button" disabled={!!exportBusy} onClick={exportAllPngZip}>
                {exportBusy === "png" ? "Exporting PNG…" : "Export all PNG (zip)"}
              </button>
              <button type="button" disabled={!!exportBusy} onClick={exportAllCsvZip}>
                {exportBusy === "csv" ? "Exporting CSV…" : "Export all CSV (zip)"}
              </button>
              <div className="hint" style={{ margin: 0 }}>
                Exports include all plots currently rendered below.
              </div>
            </div>
            {plotCards.map((c) => (
              <PlotCard key={c.id} card={c} />
            ))}
          </div>
        ) : null}
        {section === "overview" && !datasetId ? <div className="hint">Select a dataset to begin.</div> : null}
        {section === "exports" && (!runId || selectedRun?.status !== "completed") ? (
          <AnalysisRunGateNotice runId={runId} selectedRun={selectedRun} compact />
        ) : null}
      </div>
    </div>
  );
}
