import { useEffect, useMemo, useState } from "react";
import {
  getFitCurveJob,
  getFitCurveJobDownloadUrl,
  getMonteCarloSummary,
  postMonteCarloJob,
  type FittingPreviewItem,
} from "./api";
import {
  componentUncertaintyCells,
  formatInterval,
  formatValueError,
  hasAnyStderr,
  mcToCovRatio,
  type MonteCarloSummary,
} from "./fitUncertainty";

type Props = {
  runId: string;
  stepNum: number;
  selectedIds: string[];
  items: FittingPreviewItem[];
  download: (url: string, filename: string, onErr: (msg: string) => void) => Promise<void>;
};

/** F2: covariance ± per parameter (from the run's stored columns) and on-demand Monte Carlo uncertainties. */
export function FitUncertaintyPanel({ runId, stepNum, selectedIds, items, download }: Props) {
  const [nRep, setNRep] = useState(100);
  const [seed, setSeed] = useState(0);
  const [scope, setScope] = useState<"selected" | "all">("selected");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [summary, setSummary] = useState<MonteCarloSummary | null>(null);
  const [mcSpectrum, setMcSpectrum] = useState<string>("");

  useEffect(() => {
    setSummary(null);
    setJobId(null);
    setNote(null);
  }, [runId, stepNum]);

  const okItems = items.filter((it) => !it.error && it.components?.length);
  const anyStderr = okItems.some((it) => hasAnyStderr(it.components));
  const nSpectra = scope === "selected" ? selectedIds.length : null;

  async function runMonteCarlo() {
    setBusy(true);
    setNote(null);
    setSummary(null);
    try {
      const created = await postMonteCarloJob(runId, {
        fitting_step_num: stepNum,
        n_replicates: nRep,
        seed,
        spectrum_ids: scope === "selected" ? selectedIds : null,
      });
      setJobId(created.job_id);
      for (let i = 0; i < 7200; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const st = await getFitCurveJob(created.job_id);
        if (st.status === "completed") {
          const s = await getMonteCarloSummary(created.job_id);
          setSummary(s);
          setMcSpectrum(s.spectra.find((x) => !x.error)?.spectrum_id ?? "");
          setNote(null);
          return;
        }
        if (st.status === "failed") throw new Error(st.error || "Monte Carlo job failed");
        setNote(`Monte Carlo ${st.status}: ${st.progress_done}/${st.progress_total} fits`);
      }
      throw new Error("Monte Carlo job timed out");
    } catch (e) {
      setNote(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  const mcRows = useMemo(
    () => (summary?.rows ?? []).filter((r) => !mcSpectrum || r.spectrum_id === mcSpectrum),
    [summary, mcSpectrum]
  );
  const mcMeta = summary?.spectra.find((s) => s.spectrum_id === mcSpectrum);
  const failedSpectra = (summary?.spectra ?? []).filter((s) => s.error);

  return (
    <div data-testid="fit-uncertainty-panel" style={{ marginTop: 12 }}>
      <div className="section-title">Parameter uncertainties</div>
      {okItems.length === 0 ? (
        <div className="hint">Select spectra above to see fitted parameters with their errors.</div>
      ) : !anyStderr ? (
        <div className="hint">
          This run has no stored parameter errors (made before uncertainties were exported). Re-run the analysis to get
          ± values; Monte Carlo below works on any completed run.
        </div>
      ) : (
        <div className="hint" style={{ marginTop: 0 }}>
          ± = 1σ from the fit covariance, scaled by the reduced χ². Fixed parameters carry no error.
        </div>
      )}
      {okItems.map((it) => (
        <details key={it.spectrum_id} open={okItems.length === 1} style={{ marginTop: 4 }}>
          <summary style={{ cursor: "pointer" }}>{it.spectrum_id}</summary>
          <table className="table" data-testid="fit-uncertainty-table" style={{ fontSize: 12, marginTop: 4 }}>
            <thead>
              <tr>
                <th>Component</th>
                <th>Parameters</th>
              </tr>
            </thead>
            <tbody>
              {it.components.map((c) => (
                <tr key={c.component_id}>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {c.component_id} <span className="hint">({c.component_type})</span>
                  </td>
                  <td>
                    {componentUncertaintyCells(c).map((cell) => (
                      <span
                        key={cell.key}
                        style={{ marginRight: 12, whiteSpace: "nowrap", opacity: cell.fixed ? 0.6 : 1 }}
                      >
                        <b>{cell.key}</b> {cell.text}
                      </span>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ))}

      <div className="section-title" style={{ marginTop: 12 }}>
        Monte Carlo
      </div>
      <p className="hint" style={{ marginTop: 0 }}>
        Refits noisy copies of each best fit (noise from the fit weighting; backgrounds recomputed each time). Captures
        background and peak-overlap uncertainty that the covariance misses. Cost: spectra × replicates fits.
      </p>
      <div className="row" style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
        <label className="inline">
          Replicates
          <input
            type="number"
            min={2}
            max={2000}
            value={nRep}
            style={{ width: 80 }}
            onChange={(e) => setNRep(Math.max(2, Math.min(2000, Math.floor(Number(e.target.value) || 2))))}
          />
        </label>
        <label className="inline">
          Seed
          <input
            type="number"
            min={0}
            value={seed}
            style={{ width: 70 }}
            onChange={(e) => setSeed(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
          />
        </label>
        <label className="inline">
          Spectra
          <select value={scope} onChange={(e) => setScope(e.target.value as "selected" | "all")}>
            <option value="selected">Selected ({selectedIds.length})</option>
            <option value="all">All spectra of this step</option>
          </select>
        </label>
        <button
          type="button"
          className="mini"
          data-testid="mc-run"
          disabled={busy || (scope === "selected" && selectedIds.length === 0)}
          onClick={() => void runMonteCarlo()}
        >
          {busy ? "Running…" : "Run Monte Carlo"}
        </button>
        {summary && jobId ? (
          <button
            type="button"
            className="mini"
            onClick={() => void download(getFitCurveJobDownloadUrl(jobId), `monte_carlo_${runId}.zip`, setNote)}
          >
            Download zip
          </button>
        ) : null}
        {nSpectra != null && !busy ? (
          <span className="hint" style={{ margin: 0 }}>
            {nSpectra * nRep} fits
          </span>
        ) : null}
      </div>
      {note ? (
        <div className="hint" data-testid="mc-note" style={{ marginTop: 6 }}>
          {note}
        </div>
      ) : null}
      {failedSpectra.length ? (
        <div className="warn-note" style={{ marginTop: 6 }}>
          {failedSpectra.map((s) => (
            <div key={s.spectrum_id}>
              {s.spectrum_id}: {s.error}
            </div>
          ))}
        </div>
      ) : null}
      {summary ? (
        <div style={{ marginTop: 8 }} data-testid="mc-result">
          <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <label className="inline">
              Spectrum
              <select value={mcSpectrum} onChange={(e) => setMcSpectrum(e.target.value)}>
                {summary.spectra
                  .filter((s) => !s.error)
                  .map((s) => (
                    <option key={s.spectrum_id} value={s.spectrum_id}>
                      {s.spectrum_id}
                    </option>
                  ))}
              </select>
            </label>
            {mcMeta ? (
              <span className="hint" style={{ margin: 0 }}>
                {mcMeta.n_ok}/{summary.n_replicates} replicates converged · noise: {mcMeta.noise_model} · seed{" "}
                {summary.seed}
              </span>
            ) : null}
          </div>
          <table className="table" style={{ fontSize: 12, marginTop: 4 }}>
            <thead>
              <tr>
                <th>Component</th>
                <th>Quantity</th>
                <th>Best fit ± 1σ (cov.)</th>
                <th>MC SD</th>
                <th>MC 95 % interval</th>
                <th title="Monte Carlo SD / covariance error; well above 1 = uncertainty the covariance misses">
                  MC / cov.
                </th>
              </tr>
            </thead>
            <tbody>
              {mcRows.map((r) => {
                const ratio = mcToCovRatio(r);
                return (
                  <tr key={`${r.component_id}.${r.quantity}`}>
                    <td>{r.component_id}</td>
                    <td>{r.quantity === "area_pct" ? "%area" : r.quantity}</td>
                    <td>{formatValueError(r.best_fit, r.stderr_cov)}</td>
                    <td>{formatValueError(r.mc_sd, null)}</td>
                    <td>{formatInterval(r.mc_p2_5, r.mc_p97_5, r.mc_sd)}</td>
                    <td style={ratio != null && ratio > 1.5 ? { color: "#b45309", fontWeight: 600 } : undefined}>
                      {ratio == null ? "—" : ratio.toFixed(2)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
