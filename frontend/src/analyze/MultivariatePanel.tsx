import { useMemo, useState } from "react";
import { PlotlyWrapper, type PlotlyFigure } from "../legacy-wrappers/PlotlyWrapper";
import {
  postSpectrum2dcos,
  postSpectrumCorrelation,
  postSpectrumMcr,
  postSpectrumNmf,
  postSpectrumPca,
  type CorrelationMatrixResult,
  type Cos2dResult,
  type FactorResult,
  type MatrixPreprocess,
  type MatrixPreprocessingMeta,
} from "./multivariateApi";
import {
  buildComponentSpectra,
  buildContributions,
  buildCorrelationHeatmap,
  buildCosAutopower,
  buildCosMap,
  buildNmfScan,
  buildScoresScatter,
  buildVarianceBars,
  compactPreprocess,
} from "./multivariatePlots";

type Method = "correlation" | "pca" | "nmf" | "mcr" | "cos2d";

const METHOD_LABEL: Record<Method, string> = {
  correlation: "Correlation matrix",
  pca: "PCA (+ varimax)",
  nmf: "NMF",
  mcr: "MCR-ALS",
  cos2d: "2D-COS",
};

const METHOD_HINT: Record<Method, string> = {
  correlation:
    "Pearson or Spearman correlation between channels (which bands move together) or between spectra (which samples look alike). Clustered order puts similar variables next to each other so blocks appear on the diagonal.",
  pca: "Orthogonal components of the mean-centred matrix. Varimax rotates the retained components towards fewer, more peak-like loadings without changing the fitted subspace.",
  nmf: "Non-negative components and contributions; no centring. Non-unique: check the start spread and the error-vs-k scan before interpreting.",
  mcr: "NMF-initialised alternating least squares with chemical constraints. Fix measured spectra of the matrix as known components. Rotational ambiguity remains.",
  cos2d:
    "Synchronous / asynchronous 2D correlation of the dynamic spectra. The perturbation is the sample order or a numeric column of an analysis run (potential, time, ...). Uneven perturbation values are resampled onto an even grid.",
};

const NONNEG_METHODS: Method[] = ["nmf", "mcr"];

type Props = {
  matrixJobId: string | null;
  matrixReady: boolean;
  completedMatrices: { id: string; label: string }[];
  onPickMatrix: (id: string) => void;
  /** Analysis run used as the perturbation source for 2D-COS. */
  analysisRunId: string;
  onError: (msg: string | null) => void;
};

function num(v: string): number | null {
  if (v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function PlotBox({ figure }: { figure: PlotlyFigure | null }) {
  if (!figure) return null;
  return (
    <div className="plot-card" style={{ marginTop: "10px" }}>
      <PlotlyWrapper
        figure={figure}
        previousFigure={null}
        plotStyle={{ mode: "overlay", stackSep: 0 }}
        ghostOverlayEnabled={false}
        className="plot-host"
      />
    </div>
  );
}

function PrepSummary({ meta }: { meta?: MatrixPreprocessingMeta }) {
  if (!meta) return null;
  return (
    <div className="hint" style={{ marginTop: "8px" }}>
      <b>Matrix preprocessing:</b> {meta.steps?.length ? meta.steps.join(" → ") : "none"}
      {meta.n_channels_in != null ? ` (${meta.n_channels_in} → ${meta.n_channels_out} channels)` : ""}
      {(meta.warnings ?? []).map((w, i) => (
        <div key={i} style={{ color: "#b35c00" }}>
          ⚠ {w}
        </div>
      ))}
    </div>
  );
}

export function MultivariatePanel({ matrixJobId, matrixReady, completedMatrices, onPickMatrix, analysisRunId, onError }: Props) {
  const [method, setMethod] = useState<Method>("correlation");
  const [busy, setBusy] = useState(false);

  // preprocessing
  const [pre, setPre] = useState<MatrixPreprocess>({ bin: 1, row_norm: "none", transform: "none", nonneg: "none", center: "mean", scale: "none", derivative: 0, smooth_window: 0, smooth_poly: 3 });
  const [cropLo, setCropLo] = useState("");
  const [cropHi, setCropHi] = useState("");
  const [exclText, setExclText] = useState("");
  const [refLo, setRefLo] = useState("");
  const [refHi, setRefHi] = useState("");

  // per-method options
  const [corrAxis, setCorrAxis] = useState<"channels" | "samples">("channels");
  const [corrMethod, setCorrMethod] = useState<"pearson" | "spearman">("pearson");
  const [reorder, setReorder] = useState(true);
  const [linkage, setLinkage] = useState<"average" | "complete" | "single" | "ward">("average");
  const [k, setK] = useState(3);
  const [pcaScaler, setPcaScaler] = useState<"none" | "standard">("none");
  const [varimax, setVarimax] = useState(false);
  const [nStarts, setNStarts] = useState(5);
  const [scanMax, setScanMax] = useState(6);
  const [nonnegConc, setNonnegConc] = useState(true);
  const [nonnegSpec, setNonnegSpec] = useState(true);
  const [closure, setClosure] = useState(false);
  const [unimodal, setUnimodal] = useState(false);
  const [fixedIds, setFixedIds] = useState("");
  const [pert, setPert] = useState<"sample_order" | "observation_column">("sample_order");
  const [pertCol, setPertCol] = useState("");
  const [cosRef, setCosRef] = useState<"mean" | "first" | "last">("mean");
  const [scoreX, setScoreX] = useState(1);
  const [scoreY, setScoreY] = useState(2);

  // results (one per method)
  const [corrRes, setCorrRes] = useState<CorrelationMatrixResult | null>(null);
  const [pcaRes, setPcaRes] = useState<FactorResult | null>(null);
  const [nmfRes, setNmfRes] = useState<FactorResult | null>(null);
  const [mcrRes, setMcrRes] = useState<FactorResult | null>(null);
  const [cosRes, setCosRes] = useState<Cos2dResult | null>(null);

  const nonnegOnly = NONNEG_METHODS.includes(method);
  const noCentre = nonnegOnly || method === "cos2d" || method === "pca" || method === "correlation";

  const request = useMemo<MatrixPreprocess | null>(() => {
    const p: MatrixPreprocess = { ...pre };
    const lo = num(cropLo);
    const hi = num(cropHi);
    p.crop = lo != null && hi != null ? [lo, hi] : null;
    p.exclude = exclText
      .split(";")
      .map((s) => s.split(",").map((t) => Number(t.trim())))
      .filter((w) => w.length === 2 && w.every((v) => Number.isFinite(v))) as [number, number][];
    const rl = num(refLo);
    const rh = num(refHi);
    p.ref_band = rl != null && rh != null ? [rl, rh] : null;
    return compactPreprocess(p);
  }, [pre, cropLo, cropHi, exclText, refLo, refHi]);

  const setP = <K extends keyof MatrixPreprocess>(key: K, value: MatrixPreprocess[K]) => setPre((o) => ({ ...o, [key]: value }));

  const run = async () => {
    if (!matrixJobId) return;
    setBusy(true);
    onError(null);
    try {
      if (method === "correlation") {
        const r = await postSpectrumCorrelation({ matrix_job_id: matrixJobId, axis: corrAxis, method: corrMethod, reorder, linkage, preprocess: request });
        setCorrRes(r.results);
      } else if (method === "pca") {
        const r = await postSpectrumPca({ matrix_job_id: matrixJobId, n_components: k, scaler: pcaScaler, rotation: varimax ? "varimax" : "none", preprocess: request });
        setPcaRes(r.results);
      } else if (method === "nmf") {
        const scan = scanMax >= 2 ? Array.from({ length: scanMax }, (_, i) => i + 1) : null;
        const r = await postSpectrumNmf({ matrix_job_id: matrixJobId, n_components: k, n_starts: nStarts, scan_k: scan, preprocess: request });
        setNmfRes(r.results);
      } else if (method === "mcr") {
        const ids = fixedIds.split(",").map((s) => s.trim()).filter(Boolean);
        const r = await postSpectrumMcr({
          matrix_job_id: matrixJobId,
          n_components: k,
          nonneg_conc: nonnegConc,
          nonneg_spec: nonnegSpec,
          closure,
          unimodal_spec: unimodal,
          normalise_spec: true,
          fixed_spectrum_ids: ids.length ? ids : null,
          preprocess: request,
        });
        setMcrRes(r.results);
      } else {
        const r = await postSpectrum2dcos({
          matrix_job_id: matrixJobId,
          perturbation: pert,
          analysis_run_id: pert === "observation_column" ? analysisRunId || null : null,
          perturbation_column: pert === "observation_column" ? pertCol.trim() || null : null,
          reference: cosRef,
          preprocess: request,
        });
        setCosRes(r.results);
      }
    } catch (e) {
      onError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const factorBlock = (res: FactorResult | null, label: string) => {
    if (!res) return null;
    return (
      <>
        <div className="hint" style={{ marginTop: "10px" }}>
          k = {res.n_components}
          {res.r2 != null ? ` · R² = ${res.r2.toFixed(4)}` : ""}
          {res.lack_of_fit_pct != null ? ` · lack of fit ${res.lack_of_fit_pct.toFixed(2)} %` : ""}
          {res.start_error_spread_pct != null ? ` · start spread ${res.start_error_spread_pct.toFixed(2)} %` : ""}
          {res.iterations != null ? ` · ${res.iterations} iterations${res.converged ? "" : " (not converged)"}` : ""}
          {res.rotation?.applied ? " · varimax rotated" : ""}
        </div>
        {res.note ? <div className="hint">{res.note}</div> : null}
        <PrepSummary meta={res.matrix_preprocessing} />
        <PlotBox figure={buildComponentSpectra(res, label)} />
        <PlotBox figure={buildContributions(res, label)} />
        <PlotBox figure={buildVarianceBars(res, label)} />
        <PlotBox figure={buildScoresScatter(res, label, scoreX - 1, scoreY - 1)} />
        <PlotBox figure={buildNmfScan(res)} />
      </>
    );
  };

  return (
    <div style={{ marginTop: "14px" }}>
      <div className="section-title">Multivariate analysis</div>
      <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
        <label className="inline">
          Matrix
          <select value={matrixJobId ?? ""} onChange={(e) => onPickMatrix(e.target.value)}>
            <option value="">— select a completed matrix —</option>
            {completedMatrices.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label className="inline">
          Method
          <select value={method} onChange={(e) => setMethod(e.target.value as Method)}>
            {(Object.keys(METHOD_LABEL) as Method[]).map((m) => (
              <option key={m} value={m}>
                {METHOD_LABEL[m]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="hint">{METHOD_HINT[method]}</p>

      {!matrixReady ? (
        <div className="hint">Select a completed matrix job (build one in the Spectrum matrix section).</div>
      ) : (
        <>
          <details style={{ marginTop: "6px" }}>
            <summary>Matrix preprocessing{request ? " (modified)" : ""}</summary>
            <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "flex-end", marginTop: "6px" }}>
              <label className="inline" title="Keep only this x window">
                Crop x
                <input type="number" style={{ width: "80px" }} value={cropLo} onChange={(e) => setCropLo(e.target.value)} placeholder="from" />
                <input type="number" style={{ width: "80px" }} value={cropHi} onChange={(e) => setCropHi(e.target.value)} placeholder="to" />
              </label>
              <label className="inline" title="Windows to remove, e.g. 500,520; 1000,1040">
                Exclude
                <input type="text" style={{ width: "150px" }} value={exclText} onChange={(e) => setExclText(e.target.value)} placeholder="lo,hi; lo,hi" />
              </label>
              <label className="inline" title="Average this many neighbouring channels">
                Bin
                <input type="number" min={1} max={64} style={{ width: "60px" }} value={pre.bin ?? 1} onChange={(e) => setP("bin", Math.max(1, Number(e.target.value) || 1))} />
              </label>
            </div>
            <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "flex-end", marginTop: "6px" }}>
              <label className="inline" title="Savitzky–Golay window (odd, 0 = off)">
                Smooth window
                <input type="number" min={0} style={{ width: "70px" }} value={pre.smooth_window ?? 0} onChange={(e) => setP("smooth_window", Math.max(0, Number(e.target.value) || 0))} />
              </label>
              <label className="inline">
                Polynomial
                <input type="number" min={1} max={7} style={{ width: "60px" }} value={pre.smooth_poly ?? 3} onChange={(e) => setP("smooth_poly", Math.max(1, Number(e.target.value) || 3))} />
              </label>
              <label className="inline" title="Derivative removes baselines but amplifies noise">
                Derivative
                <select value={pre.derivative ?? 0} onChange={(e) => setP("derivative", Number(e.target.value) as 0 | 1 | 2)}>
                  <option value={0}>none</option>
                  <option value={1}>1st</option>
                  <option value={2}>2nd</option>
                </select>
              </label>
              <label className="inline">
                Row normalisation
                <select value={pre.row_norm ?? "none"} onChange={(e) => setP("row_norm", e.target.value as MatrixPreprocess["row_norm"])}>
                  <option value="none">none</option>
                  <option value="area">area</option>
                  <option value="max">max</option>
                  <option value="l2">vector (L2)</option>
                  <option value="snv">SNV</option>
                  <option value="ref_band">reference band</option>
                </select>
              </label>
              {pre.row_norm === "ref_band" ? (
                <label className="inline">
                  Ref band
                  <input type="number" style={{ width: "80px" }} value={refLo} onChange={(e) => setRefLo(e.target.value)} placeholder="from" />
                  <input type="number" style={{ width: "80px" }} value={refHi} onChange={(e) => setRefHi(e.target.value)} placeholder="to" />
                </label>
              ) : null}
            </div>
            <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "flex-end", marginTop: "6px" }}>
              <label className="inline">
                Transform
                <select value={pre.transform ?? "none"} onChange={(e) => setP("transform", e.target.value as MatrixPreprocess["transform"])}>
                  <option value="none">none</option>
                  <option value="sqrt">sqrt</option>
                  <option value="log">log(1+y)</option>
                </select>
              </label>
              <label className="inline" title="NMF / MCR need non-negative data; a negative minimum is shifted automatically">
                Non-negativity
                <select value={pre.nonneg ?? "none"} onChange={(e) => setP("nonneg", e.target.value as MatrixPreprocess["nonneg"])}>
                  <option value="none">none</option>
                  <option value="clip">clip negatives to 0</option>
                  <option value="shift">shift minimum to 0</option>
                </select>
              </label>
              <label className="inline" title={noCentre ? "This method centres itself or must not be centred" : "Column centring"}>
                Centring
                <select disabled={noCentre} value={noCentre ? "none" : pre.center ?? "mean"} onChange={(e) => setP("center", e.target.value as MatrixPreprocess["center"])}>
                  <option value="mean">mean</option>
                  <option value="median">median</option>
                  <option value="none">none</option>
                </select>
              </label>
              <label className="inline" title="Pareto (1/√σ) is the usual compromise; Poisson scaling suits counting data and needs non-negative values">
                Scaling
                <select value={pre.scale ?? "none"} onChange={(e) => setP("scale", e.target.value as MatrixPreprocess["scale"])}>
                  <option value="none">none</option>
                  <option value="autoscale">autoscale (unit variance)</option>
                  <option value="pareto">Pareto</option>
                  <option value="range">range</option>
                  <option value="poisson">Poisson (counting data)</option>
                </select>
              </label>
            </div>
          </details>

          <div className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "flex-end", marginTop: "10px" }}>
            {method === "correlation" ? (
              <>
                <label className="inline">
                  Between
                  <select value={corrAxis} onChange={(e) => setCorrAxis(e.target.value as "channels" | "samples")}>
                    <option value="channels">channels (bands)</option>
                    <option value="samples">samples (spectra)</option>
                  </select>
                </label>
                <label className="inline">
                  Coefficient
                  <select value={corrMethod} onChange={(e) => setCorrMethod(e.target.value as "pearson" | "spearman")}>
                    <option value="pearson">Pearson</option>
                    <option value="spearman">Spearman</option>
                  </select>
                </label>
                <label className="inline">
                  <input type="checkbox" checked={reorder} onChange={(e) => setReorder(e.target.checked)} /> Clustered order
                </label>
                {reorder ? (
                  <label className="inline">
                    Linkage
                    <select value={linkage} onChange={(e) => setLinkage(e.target.value as typeof linkage)}>
                      <option value="average">average</option>
                      <option value="complete">complete</option>
                      <option value="single">single</option>
                      <option value="ward">ward</option>
                    </select>
                  </label>
                ) : null}
              </>
            ) : null}
            {method === "pca" || method === "nmf" || method === "mcr" ? (
              <label className="inline">
                Components k
                <input type="number" min={1} max={50} style={{ width: "70px" }} value={k} onChange={(e) => setK(Math.max(1, Number(e.target.value) || 1))} />
              </label>
            ) : null}
            {method === "pca" ? (
              <>
                <label className="inline">
                  Scaling after preprocessing
                  <select value={pcaScaler} onChange={(e) => setPcaScaler(e.target.value as "none" | "standard")}>
                    <option value="none">mean-centre only</option>
                    <option value="standard">unit variance</option>
                  </select>
                </label>
                <label className="inline">
                  <input type="checkbox" checked={varimax} onChange={(e) => setVarimax(e.target.checked)} /> Varimax rotation
                </label>
              </>
            ) : null}
            {method === "nmf" ? (
              <>
                <label className="inline" title="Random restarts; the best one is kept">
                  Starts
                  <input type="number" min={1} max={50} style={{ width: "60px" }} value={nStarts} onChange={(e) => setNStarts(Math.max(1, Number(e.target.value) || 1))} />
                </label>
                <label className="inline" title="Also fit k = 1..N and plot the error (0 = off)">
                  Scan k up to
                  <input type="number" min={0} max={20} style={{ width: "60px" }} value={scanMax} onChange={(e) => setScanMax(Math.max(0, Number(e.target.value) || 0))} />
                </label>
              </>
            ) : null}
            {method === "mcr" ? (
              <>
                <label className="inline">
                  <input type="checkbox" checked={nonnegConc} onChange={(e) => setNonnegConc(e.target.checked)} /> C ≥ 0
                </label>
                <label className="inline">
                  <input type="checkbox" checked={nonnegSpec} onChange={(e) => setNonnegSpec(e.target.checked)} /> S ≥ 0
                </label>
                <label className="inline" title="Contributions of each spectrum sum to 1">
                  <input type="checkbox" checked={closure} onChange={(e) => setClosure(e.target.checked)} /> Closure
                </label>
                <label className="inline" title="Each component spectrum has a single maximum">
                  <input type="checkbox" checked={unimodal} onChange={(e) => setUnimodal(e.target.checked)} /> Unimodal
                </label>
                <label className="inline" title="Comma-separated spectrum ids of this matrix held fixed as the first components">
                  Fixed spectra (ids)
                  <input type="text" style={{ width: "180px" }} value={fixedIds} onChange={(e) => setFixedIds(e.target.value)} />
                </label>
              </>
            ) : null}
            {method === "cos2d" ? (
              <>
                <label className="inline">
                  Perturbation
                  <select value={pert} onChange={(e) => setPert(e.target.value as typeof pert)}>
                    <option value="sample_order">sample order</option>
                    <option value="observation_column">observation column</option>
                  </select>
                </label>
                {pert === "observation_column" ? (
                  <label className="inline" title={analysisRunId ? `Column of analysis run ${analysisRunId}` : "Select an analysis run in the header first"}>
                    Column
                    <input type="text" style={{ width: "160px" }} value={pertCol} onChange={(e) => setPertCol(e.target.value)} placeholder="e.g. potential_V" />
                  </label>
                ) : null}
                <label className="inline">
                  Reference
                  <select value={cosRef} onChange={(e) => setCosRef(e.target.value as typeof cosRef)}>
                    <option value="mean">mean spectrum</option>
                    <option value="first">first spectrum</option>
                    <option value="last">last spectrum</option>
                  </select>
                </label>
              </>
            ) : null}
            <button type="button" disabled={busy || !matrixJobId} onClick={() => void run()}>
              {busy ? "Running…" : `Run ${METHOD_LABEL[method]}`}
            </button>
          </div>
          {method === "cos2d" && pert === "observation_column" && !analysisRunId ? (
            <div className="hint" style={{ color: "#b35c00" }}>
              Observation-column perturbation needs an analysis run selected in the header.
            </div>
          ) : null}

          {method === "pca" || method === "nmf" || method === "mcr" ? (
            <div className="row" style={{ gap: "8px", alignItems: "center", marginTop: "6px" }}>
              <span className="hint">Scores scatter:</span>
              <input type="number" min={1} style={{ width: "55px" }} value={scoreX} onChange={(e) => setScoreX(Math.max(1, Number(e.target.value) || 1))} />
              <span className="hint">vs</span>
              <input type="number" min={1} style={{ width: "55px" }} value={scoreY} onChange={(e) => setScoreY(Math.max(1, Number(e.target.value) || 2))} />
            </div>
          ) : null}

          {method === "correlation" && corrRes ? (
            <>
              <PrepSummary meta={corrRes.matrix_preprocessing} />
              {corrRes.n_constant_variables ? <div className="hint">{corrRes.n_constant_variables} constant variable(s) have no correlation (shown blank).</div> : null}
              <PlotBox figure={buildCorrelationHeatmap(corrRes)} />
            </>
          ) : null}
          {method === "pca" ? factorBlock(pcaRes, "PC") : null}
          {method === "nmf" ? factorBlock(nmfRes, "NMF") : null}
          {method === "mcr" ? factorBlock(mcrRes, "MCR") : null}
          {method === "cos2d" && cosRes ? (
            <>
              <div className="hint" style={{ marginTop: "10px" }}>
                {cosRes.n_spectra} spectra · perturbation: {cosRes.perturbation_label}
                {cosRes.resampled ? " · resampled onto an even grid" : ""}
                {cosRes.n_spectra_without_perturbation ? ` · ${cosRes.n_spectra_without_perturbation} spectra had no perturbation value and were dropped` : ""}
              </div>
              {cosRes.note ? <div className="hint">{cosRes.note}</div> : null}
              <PrepSummary meta={cosRes.matrix_preprocessing} />
              <PlotBox figure={buildCosMap(cosRes, "synchronous")} />
              <PlotBox figure={buildCosMap(cosRes, "asynchronous")} />
              <PlotBox figure={buildCosAutopower(cosRes)} />
            </>
          ) : null}
        </>
      )}
    </div>
  );
}
