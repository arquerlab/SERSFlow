import { useEffect, useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { postTestPeakModel } from "./api";
import { flattenFittingForPipeline, type FittingEditorParams } from "./fittingUtils";
import { inlineTarget, type FitPreviewInput } from "./fitInputs";
import {
  areaHistogramFigure,
  areaPctFigure,
  chi2Figure,
  overlayFigure,
  scanGrid,
  type NoiseResult,
  type ScanPoint,
} from "./peakModelTestFigures";

function MiniPlot({ figure }: { figure: { data: unknown[]; layout: Record<string, unknown> } }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (ref.current) void Plotly.newPlot(ref.current, figure.data as any, figure.layout as any, { displayModeBar: false, responsive: true });
  }, [figure]);
  return <div ref={ref} />;
}

type Props = {
  fp: FittingEditorParams;
  inputs: FitPreviewInput[];
  technique: string;
};

type Target = { label: string; key: string; component_id?: string; component_type?: string; current: number };

/** S1 "Test peak model" in the Peak Fitting step: scan a parameter (χ² and %area profiles) or refit noise replicates. */
export function TestPeakModelPanel({ fp, inputs, technique }: Props) {
  const targets = useMemo<Target[]>(() => {
    const out: Target[] = [];
    const byTypeKey = new Map<string, number>();
    for (const c of fp.components) {
      for (const r of c.rows) {
        if (c.component_id) out.push({ label: `${c.component_id}.${r.key}`, key: r.key, component_id: c.component_id, current: r.p0 });
        const tk = `${c.component_type}|${r.key}`;
        byTypeKey.set(tk, (byTypeKey.get(tk) ?? 0) + 1);
      }
    }
    for (const [tk, n] of byTypeKey) {
      if (n < 2) continue;
      const [ct, key] = tk.split("|") as [string, string];
      const first = fp.components.find((c) => c.component_type === ct)?.rows.find((r) => r.key === key);
      out.push({ label: `all ${ct} peaks: ${key}`, key, component_type: ct, current: first?.p0 ?? 0 });
    }
    return out;
  }, [fp]);

  const [mode, setMode] = useState<"scan" | "noise">("scan");
  const [sid, setSid] = useState("");
  const [targetLabel, setTargetLabel] = useState("");
  const target = targets.find((t) => t.label === targetLabel) ?? targets[0];
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [steps, setSteps] = useState(11);
  const [nRep, setNRep] = useState(50);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [scan, setScan] = useState<{ points: ScanPoint[]; best_value: number | null; label: string } | null>(null);
  const [noise, setNoise] = useState<(NoiseResult & { params: Array<Record<string, any>>; noise_model: string; n_ok: number }) | null>(null);
  const input = inputs.find((i) => i.spectrum_id === sid) ?? inputs[0];

  function defaults(t: Target | undefined): [number, number] {
    const v = t?.current ?? 0;
    if (t?.key === "pos") return [v - 1, v + 1];
    if (t?.key === "m") return [0, 100];
    return [v * 0.5, v * 1.5 || 1];
  }
  const [dFrom, dTo] = defaults(target);

  async function run() {
    if (!input) return;
    setBusy(true);
    setErr(null);
    try {
      const flat = flattenFittingForPipeline(fp) as Record<string, any>;
      const fit = {
        target: inlineTarget(input),
        components: flat.components,
        p0: flat.p0,
        bounds: { lower: flat.bounds_lower, upper: flat.bounds_upper },
        vary: flat.vary,
        param_links: flat.param_links ?? [],
        technique_family: technique,
        weighting: fp.weighting ?? "auto",
        fit_min_x: flat.fit_min_x ?? null,
        fit_max_x: flat.fit_max_x ?? null,
        initial_guess_mode: "default",
      };
      if (mode === "scan") {
        if (!target) throw new Error("No parameter to scan");
        const values = scanGrid(from === "" ? dFrom : Number(from), to === "" ? dTo : Number(to), steps);
        const r = await postTestPeakModel({
          fit,
          mode: "scan",
          key: target.key,
          component_id: target.component_id ?? null,
          component_type: target.component_type ?? null,
          values,
        });
        setScan({ points: r.points as ScanPoint[], best_value: r.best_value ?? null, label: target.label });
        setNoise(null);
      } else {
        const r = await postTestPeakModel({ fit, mode: "noise", n_replicates: nRep });
        setNoise(r as any);
        setScan(null);
      }
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <details data-testid="test-peak-model" style={{ fontSize: 12 }}>
      <summary style={{ cursor: "pointer", fontWeight: 700 }}>Test peak model</summary>
      <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
        <div className="hint" style={{ margin: 0 }}>
          Scan one parameter and watch χ² and %area: a flat χ² while %area moves means the model cannot pin that component
          down. Noise replicates refit noisy copies of the best fit (F2 Monte Carlo).
        </div>
        <div className="row" style={{ gap: 6, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="inline">
            Spectrum
            <select value={input?.spectrum_id ?? ""} onChange={(e) => setSid(e.target.value)} disabled={!inputs.length}>
              {inputs.length ? null : <option value="">run the fitting preview first</option>}
              {inputs.map((i) => (
                <option key={i.spectrum_id} value={i.spectrum_id}>
                  {i.spectrum_id}
                </option>
              ))}
            </select>
          </label>
          <label className="inline">
            Mode
            <select value={mode} onChange={(e) => setMode(e.target.value as "scan" | "noise")}>
              <option value="scan">Parameter scan</option>
              <option value="noise">Noise replicates</option>
            </select>
          </label>
          {mode === "scan" ? (
            <>
              <label className="inline">
                Parameter
                <select data-testid="tpm-param" value={target?.label ?? ""} onChange={(e) => setTargetLabel(e.target.value)}>
                  {targets.map((t) => (
                    <option key={t.label} value={t.label}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="inline">
                from
                <input type="number" value={from} placeholder={dFrom.toFixed(3)} onChange={(e) => setFrom(e.target.value)} style={{ width: 80 }} />
              </label>
              <label className="inline">
                to
                <input type="number" value={to} placeholder={dTo.toFixed(3)} onChange={(e) => setTo(e.target.value)} style={{ width: 80 }} />
              </label>
              <label className="inline">
                steps
                <input type="number" min={2} max={101} value={steps} onChange={(e) => setSteps(Number(e.target.value) || 11)} style={{ width: 56 }} />
              </label>
            </>
          ) : (
            <label className="inline">
              Replicates
              <input type="number" min={2} max={500} value={nRep} onChange={(e) => setNRep(Number(e.target.value) || 50)} style={{ width: 64 }} />
            </label>
          )}
          <button type="button" className="mini" data-testid="tpm-run" disabled={busy || !input} onClick={() => void run()}>
            {busy ? "Running…" : "Run"}
          </button>
        </div>
        {err ? <div className="err">{err}</div> : null}
        {scan ? (
          <div data-testid="tpm-scan-result">
            <div className="hint" style={{ margin: 0 }}>
              χ² minimum at {scan.best_value != null ? scan.best_value.toFixed(4) : "—"} ·{" "}
              {scan.points.filter((p) => p.error).length} failed point(s)
            </div>
            <MiniPlot figure={chi2Figure(scan.points, scan.label, scan.best_value)} />
            <MiniPlot figure={areaPctFigure(scan.points, scan.label)} />
          </div>
        ) : null}
        {noise ? (
          <div data-testid="tpm-noise-result">
            <div className="hint" style={{ margin: 0 }}>
              {noise.n_ok} replicates · noise: {noise.noise_model}
            </div>
            <MiniPlot figure={overlayFigure(noise, technique === "xps")} />
            <MiniPlot figure={areaHistogramFigure(noise)} />
            <table className="table" style={{ fontSize: 11 }}>
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Best</th>
                  <th>± cov.</th>
                  <th>MC SD</th>
                </tr>
              </thead>
              <tbody>
                {noise.params.map((p) => (
                  <tr key={p.name}>
                    <td>{p.name}</td>
                    <td>{typeof p.best === "number" ? p.best.toPrecision(6) : "—"}</td>
                    <td>{typeof p.stderr_cov === "number" ? p.stderr_cov.toPrecision(2) : "—"}</td>
                    <td>{typeof p.mc_sd === "number" ? p.mc_sd.toPrecision(2) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </details>
  );
}
