import { useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
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

export type MvMethod = "correlation" | "pca" | "nmf" | "mcr" | "cos2d" | "classic";

const METHOD_LABEL: Record<MvMethod, string> = {
  correlation: "Correlation matrix",
  pca: "PCA (+ varimax)",
  nmf: "NMF",
  mcr: "MCR-ALS",
  cos2d: "2D-COS",
  classic: "Classic: PCA / sPCA, k-means, FDA",
};

const METHOD_HINT: Record<MvMethod, string> = {
  correlation:
    "Pearson or Spearman correlation between channels (which bands move together) or between spectra (which samples look alike). Clustered order puts similar variables next to each other so blocks appear on the diagonal.",
  pca: "Orthogonal components of the mean-centred matrix. Varimax rotates the retained components towards fewer, more peak-like loadings without changing the fitted subspace.",
  nmf: "Non-negative components and contributions; no centring. Non-unique: check the start spread and the error-vs-k scan before interpreting.",
  mcr: "NMF-initialised alternating least squares with chemical constraints. Fix measured spectra of the matrix as known components. Rotational ambiguity remains.",
  cos2d:
    "Synchronous / asynchronous 2D correlation of the dynamic spectra. The perturbation is the sample order or a numeric column of an analysis run (potential, time, ...). Uneven perturbation values are resampled onto an even grid.",
  classic: "The original spectrum PCA / sparse PCA, k-means on PC scores and functional PCA, shown below.",
};

type Props = {
  matrixJobId: string | null;
  matrixReady: boolean;
  completedMatrices: { id: string; label: string }[];
  onPickMatrix: (id: string) => void;
  /** Analysis run used as the perturbation source for 2D-COS. */
  analysisRunId: string;
  onError: (msg: string | null) => void;
  method: MvMethod;
  onMethodChange: (m: MvMethod) => void;
  /** Right-hand pane element; results are rendered there when given. */
  resultsSlot: HTMLElement | null;
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
    <div className="hint" style={{ marginTop: "6px" }}>
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

function Field({ label, title, children, wide }: { label: string; title?: string; children: ReactNode; wide?: boolean }) {
  return (
    <label className={`mv-field${wide ? " mv-wide" : ""}`} title={title}>
      <span>{label}</span>
      {children}
    </label>
  );
}

function Check({ checked, onChange, label, title }: { checked: boolean; onChange: (v: boolean) => void; label: string; title?: string }) {
  return (
    <label className="mv-check" title={title}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function MultivariatePanel({
  matrixJobId,
  matrixReady,
  completedMatrices,
  onPickMatrix,
  analysisRunId,
  onError,
  method,
  onMethodChange,
  resultsSlot,
}: Props) {
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
    if (!matrixJobId || method === "classic") return;
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
        <div className="mv-results-head">{METHOD_LABEL[method]} result</div>
        <div className="hint">
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

  const results: ReactNode = (
    <div>
      {method === "correlation" && corrRes ? (
        <>
          <div className="mv-results-head">Correlation matrix result</div>
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
          <div className="mv-results-head">2D-COS result</div>
          <div className="hint">
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
    </div>
  );

  const hasResult =
    (method === "correlation" && !!corrRes) ||
    (method === "pca" && !!pcaRes) ||
    (method === "nmf" && !!nmfRes) ||
    (method === "mcr" && !!mcrRes) ||
    (method === "cos2d" && !!cosRes);

  return (
    <div style={{ marginTop: "14px" }}>
      <div className="section-title">Multivariate analysis</div>

      <div className="mv-box">
        <div className="mv-title">1 · Data and method</div>
        <div className="mv-grid" style={{ gridTemplateColumns: "1fr" }}>
          <Field label="Matrix job">
            <select value={matrixJobId ?? ""} onChange={(e) => onPickMatrix(e.target.value)}>
              <option value="">— select a completed matrix —</option>
              {completedMatrices.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Method">
            <select value={method} onChange={(e) => onMethodChange(e.target.value as MvMethod)}>
              {(Object.keys(METHOD_LABEL) as MvMethod[]).map((m) => (
                <option key={m} value={m}>
                  {METHOD_LABEL[m]}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <p className="hint" style={{ margin: "8px 0 0" }}>
          {METHOD_HINT[method]}
        </p>
        {!matrixReady ? (
          <div className="hint" style={{ marginTop: "6px", color: "#b35c00" }}>
            Select a completed matrix job (build one in the Spectrum matrix section).
          </div>
        ) : null}
      </div>

      {matrixReady && method !== "classic" ? (
        <>
          <details className="mv-box">
            <summary style={{ cursor: "pointer", fontWeight: 800, fontSize: 13 }}>2 · Matrix preprocessing {request ? "· modified" : "· defaults"}</summary>

            <div className="mv-sub">Window</div>
            <div className="mv-grid">
              <Field label="Crop x (from / to)" title="Keep only this x window">
                <div className="mv-pair">
                  <input type="number" value={cropLo} onChange={(e) => setCropLo(e.target.value)} placeholder="from" />
                  <input type="number" value={cropHi} onChange={(e) => setCropHi(e.target.value)} placeholder="to" />
                </div>
              </Field>
              <Field label="Exclude windows" title="Windows to remove, e.g. 500,520; 1000,1040">
                <input type="text" value={exclText} onChange={(e) => setExclText(e.target.value)} placeholder="lo,hi; lo,hi" />
              </Field>
              <Field label="Bin (channels)" title="Average this many neighbouring channels">
                <input type="number" min={1} max={64} value={pre.bin ?? 1} onChange={(e) => setP("bin", Math.max(1, Number(e.target.value) || 1))} />
              </Field>
            </div>

            <div className="mv-sub">Smoothing / derivative</div>
            <div className="mv-grid">
              <Field label="Window (odd, 0 = off)" title="Savitzky–Golay window">
                <input type="number" min={0} value={pre.smooth_window ?? 0} onChange={(e) => setP("smooth_window", Math.max(0, Number(e.target.value) || 0))} />
              </Field>
              <Field label="Polynomial order">
                <input type="number" min={1} max={7} value={pre.smooth_poly ?? 3} onChange={(e) => setP("smooth_poly", Math.max(1, Number(e.target.value) || 3))} />
              </Field>
              <Field label="Derivative" title="Removes baselines but amplifies noise">
                <select value={pre.derivative ?? 0} onChange={(e) => setP("derivative", Number(e.target.value) as 0 | 1 | 2)}>
                  <option value={0}>none</option>
                  <option value={1}>1st</option>
                  <option value={2}>2nd</option>
                </select>
              </Field>
            </div>

            <div className="mv-sub">Each spectrum (rows)</div>
            <div className="mv-grid">
              <Field label="Normalisation">
                <select value={pre.row_norm ?? "none"} onChange={(e) => setP("row_norm", e.target.value as MatrixPreprocess["row_norm"])}>
                  <option value="none">none</option>
                  <option value="area">area</option>
                  <option value="max">max</option>
                  <option value="l2">vector (L2)</option>
                  <option value="snv">SNV</option>
                  <option value="ref_band">reference band</option>
                </select>
              </Field>
              {pre.row_norm === "ref_band" ? (
                <Field label="Reference band (from / to)">
                  <div className="mv-pair">
                    <input type="number" value={refLo} onChange={(e) => setRefLo(e.target.value)} placeholder="from" />
                    <input type="number" value={refHi} onChange={(e) => setRefHi(e.target.value)} placeholder="to" />
                  </div>
                </Field>
              ) : null}
              <Field label="Transform">
                <select value={pre.transform ?? "none"} onChange={(e) => setP("transform", e.target.value as MatrixPreprocess["transform"])}>
                  <option value="none">none</option>
                  <option value="sqrt">sqrt</option>
                  <option value="log">log(1 + y)</option>
                </select>
              </Field>
            </div>

            <div className="mv-sub">Each channel (columns)</div>
            <div className="hint" style={{ margin: "0 0 6px" }}>
              Centring is handled by the method: PCA mean-centres, the others must not be centred.
            </div>
            <div className="mv-grid">
              <Field label="Non-negativity" title="NMF / MCR need non-negative data; a negative minimum is shifted automatically">
                <select value={pre.nonneg ?? "none"} onChange={(e) => setP("nonneg", e.target.value as MatrixPreprocess["nonneg"])}>
                  <option value="none">none</option>
                  <option value="clip">clip negatives to 0</option>
                  <option value="shift">shift minimum to 0</option>
                </select>
              </Field>
              <Field label="Scaling" title="Pareto (1/√σ) is the usual compromise; Poisson scaling suits counting data and needs non-negative values">
                <select value={pre.scale ?? "none"} onChange={(e) => setP("scale", e.target.value as MatrixPreprocess["scale"])}>
                  <option value="none">none</option>
                  <option value="autoscale">autoscale</option>
                  <option value="pareto">Pareto</option>
                  <option value="range">range</option>
                  <option value="poisson">Poisson (counts)</option>
                </select>
              </Field>
            </div>
          </details>

          <div className="mv-box">
            <div className="mv-title">3 · {METHOD_LABEL[method]} options</div>
            <div className="mv-grid">
              {method === "correlation" ? (
                <>
                  <Field label="Correlate">
                    <select value={corrAxis} onChange={(e) => setCorrAxis(e.target.value as "channels" | "samples")}>
                      <option value="channels">channels (bands)</option>
                      <option value="samples">samples (spectra)</option>
                    </select>
                  </Field>
                  <Field label="Coefficient">
                    <select value={corrMethod} onChange={(e) => setCorrMethod(e.target.value as "pearson" | "spearman")}>
                      <option value="pearson">Pearson</option>
                      <option value="spearman">Spearman</option>
                    </select>
                  </Field>
                  <Check checked={reorder} onChange={setReorder} label="Clustered order" title="Reorder rows and columns by hierarchical clustering" />
                  {reorder ? (
                    <Field label="Linkage">
                      <select value={linkage} onChange={(e) => setLinkage(e.target.value as typeof linkage)}>
                        <option value="average">average</option>
                        <option value="complete">complete</option>
                        <option value="single">single</option>
                        <option value="ward">ward</option>
                      </select>
                    </Field>
                  ) : null}
                </>
              ) : null}

              {method === "pca" || method === "nmf" || method === "mcr" ? (
                <Field label="Components (k)">
                  <input type="number" min={1} max={50} value={k} onChange={(e) => setK(Math.max(1, Number(e.target.value) || 1))} />
                </Field>
              ) : null}

              {method === "pca" ? (
                <>
                  <Field label="Scaling after preprocessing">
                    <select value={pcaScaler} onChange={(e) => setPcaScaler(e.target.value as "none" | "standard")}>
                      <option value="none">mean-centre only</option>
                      <option value="standard">unit variance</option>
                    </select>
                  </Field>
                  <Check checked={varimax} onChange={setVarimax} label="Varimax rotation" />
                </>
              ) : null}

              {method === "nmf" ? (
                <>
                  <Field label="Random starts" title="The best start is kept">
                    <input type="number" min={1} max={50} value={nStarts} onChange={(e) => setNStarts(Math.max(1, Number(e.target.value) || 1))} />
                  </Field>
                  <Field label="Scan k = 1 … N (0 = off)" title="Also fit every k up to N and plot the error">
                    <input type="number" min={0} max={20} value={scanMax} onChange={(e) => setScanMax(Math.max(0, Number(e.target.value) || 0))} />
                  </Field>
                </>
              ) : null}

              {method === "mcr" ? (
                <>
                  <Check checked={nonnegConc} onChange={setNonnegConc} label="Contributions ≥ 0" />
                  <Check checked={nonnegSpec} onChange={setNonnegSpec} label="Spectra ≥ 0" />
                  <Check checked={closure} onChange={setClosure} label="Closure (sum = 1)" title="Contributions of each spectrum sum to 1" />
                  <Check checked={unimodal} onChange={setUnimodal} label="Unimodal spectra" title="Each component spectrum has a single maximum" />
                  <Field wide label="Fixed spectra (comma-separated ids)" title="Spectrum ids of this matrix held fixed as the first components">
                    <input type="text" value={fixedIds} onChange={(e) => setFixedIds(e.target.value)} placeholder="optional" />
                  </Field>
                </>
              ) : null}

              {method === "cos2d" ? (
                <>
                  <Field label="Perturbation">
                    <select value={pert} onChange={(e) => setPert(e.target.value as typeof pert)}>
                      <option value="sample_order">sample order</option>
                      <option value="observation_column">observation column</option>
                    </select>
                  </Field>
                  {pert === "observation_column" ? (
                    <Field label="Column" title={analysisRunId ? `Column of analysis run ${analysisRunId}` : "Select an analysis run in the header first"}>
                      <input type="text" value={pertCol} onChange={(e) => setPertCol(e.target.value)} placeholder="e.g. potential_V" />
                    </Field>
                  ) : null}
                  <Field label="Reference spectrum">
                    <select value={cosRef} onChange={(e) => setCosRef(e.target.value as typeof cosRef)}>
                      <option value="mean">mean</option>
                      <option value="first">first</option>
                      <option value="last">last</option>
                    </select>
                  </Field>
                </>
              ) : null}
            </div>

            {method === "pca" || method === "nmf" || method === "mcr" ? (
              <>
                <div className="mv-sub">Scores scatter</div>
                <div className="mv-grid">
                  <Field label="X component">
                    <input type="number" min={1} value={scoreX} onChange={(e) => setScoreX(Math.max(1, Number(e.target.value) || 1))} />
                  </Field>
                  <Field label="Y component">
                    <input type="number" min={1} value={scoreY} onChange={(e) => setScoreY(Math.max(1, Number(e.target.value) || 2))} />
                  </Field>
                </div>
              </>
            ) : null}

            {method === "cos2d" && pert === "observation_column" && !analysisRunId ? (
              <div className="hint" style={{ color: "#b35c00", marginTop: "8px" }}>
                Observation-column perturbation needs an analysis run selected in the header.
              </div>
            ) : null}

            <button type="button" className="mv-run" disabled={busy || !matrixJobId} onClick={() => void run()}>
              {busy ? "Running…" : `Run ${METHOD_LABEL[method]}`}
            </button>
          </div>

          {hasResult ? (
            resultsSlot ? (
              createPortal(results, resultsSlot)
            ) : (
              <div className="mv-box">{results}</div>
            )
          ) : (
            <div className="hint" style={{ marginTop: "8px" }}>
              Results appear in the right-hand pane.
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
