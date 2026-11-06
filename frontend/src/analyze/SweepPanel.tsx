import { useEffect, useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { getFitCurveJob, getFitCurveJobDownloadUrl, getSweepSummary, postSweepJob, type FittingPreviewItem } from "./api";
import { scanGrid } from "../preprocess/peakModelTestFigures";

function MiniPlot({ figure }: { figure: { data: unknown[]; layout: Record<string, unknown> } }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (ref.current) void Plotly.newPlot(ref.current, figure.data as any, figure.layout as any, { displayModeBar: false, responsive: true });
  }, [figure]);
  return <div ref={ref} />;
}

type Props = {
  runId: string;
  stepNum: number;
  selectedIds: string[];
  items: FittingPreviewItem[];
  download: (url: string, filename: string, onErr: (msg: string) => void) => Promise<void>;
};

const COLORS = ["#e67e22", "#3498db", "#9b59b6", "#1abc9c", "#e74c3c", "#f39c12", "#2ecc71"];

/** S1 in Analyze: scan one parameter of a run's fitting step over many spectra (run-level sweep job). */
export function SweepPanel({ runId, stepNum, selectedIds, items, download }: Props) {
  const params = useMemo(() => {
    const comps = items.find((it) => !it.error && it.components?.length)?.components ?? [];
    return comps.flatMap((c) =>
      Object.entries((c as { params?: Record<string, number> }).params ?? {}).map(([k, v]) => ({ id: c.component_id, key: k, value: v }))
    );
  }, [items]);
  const [sel, setSel] = useState("");
  const p = params.find((q) => `${q.id}.${q.key}` === sel) ?? params[0];
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [steps, setSteps] = useState(9);
  const [scope, setScope] = useState<"selected" | "all">("selected");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [summary, setSummary] = useState<Record<string, any> | null>(null);

  const dFrom = p ? (p.key === "pos" ? p.value - 1 : p.key === "m" ? 0 : p.value * 0.5) : 0;
  const dTo = p ? (p.key === "pos" ? p.value + 1 : p.key === "m" ? 100 : p.value * 1.5) : 1;

  async function run() {
    if (!p) return;
    setBusy(true);
    setNote(null);
    setSummary(null);
    try {
      const values = scanGrid(from === "" ? dFrom : Number(from), to === "" ? dTo : Number(to), steps);
      const created = await postSweepJob(runId, {
        fitting_step_num: stepNum,
        grid: [{ component_id: p.id, key: p.key, values }],
        spectrum_ids: scope === "selected" ? selectedIds : null,
      });
      setJobId(created.job_id);
      for (let i = 0; i < 3600; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const st = await getFitCurveJob(created.job_id);
        if (st.status === "completed") {
          setSummary(await getSweepSummary(created.job_id));
          return;
        }
        if (st.status === "failed") throw new Error(st.error || "Sweep failed");
        setNote(`Sweep ${st.status}: ${st.progress_done}/${st.progress_total} fits`);
      }
      throw new Error("Sweep timed out");
    } catch (e) {
      setNote(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  const figs = useMemo(() => {
    if (!summary) return null;
    const axis = (summary.axes ?? [])[0] as string;
    const rows = [...(summary.summary ?? [])].sort((a: any, b: any) => a[axis] - b[axis]);
    const xs = rows.map((r: any) => r[axis]);
    const pct = (summary.pct_columns ?? []) as string[];
    return {
      rmse: {
        data: [{ type: "scatter", mode: "lines+markers", x: xs, y: rows.map((r: any) => r.rmse_mean), name: "RMSE (mean)", line: { color: "#2c3e50" } }],
        layout: { height: 230, margin: { l: 60, r: 10, t: 24, b: 40 }, title: { text: `mean RMSE vs ${axis}`, font: { size: 12 } }, xaxis: { title: { text: axis } } },
      },
      pct: {
        data: pct.map((c, i) => ({
          type: "scatter",
          mode: "lines+markers",
          x: xs,
          y: rows.map((r: any) => r[`${c}_mean`]),
          name: c.replace(/^pct:/, ""),
          line: { color: COLORS[i % COLORS.length] },
        })),
        layout: {
          height: 230,
          margin: { l: 60, r: 10, t: 24, b: 40 },
          title: { text: `mean %area vs ${axis}`, font: { size: 12 } },
          xaxis: { title: { text: axis } },
          legend: { orientation: "h", y: -0.3 },
        },
      },
    };
  }, [summary]);

  return (
    <div data-testid="sweep-panel" style={{ marginTop: 12 }}>
      <div className="section-title">Test peak model (scan over spectra)</div>
      <p className="hint" style={{ marginTop: 0 }}>
        Fix one parameter at each value and refit the run's spectra; mean RMSE and mean %area per value show how strongly
        the result depends on it.
      </p>
      {!params.length ? <div className="hint">Select a spectrum above to choose a parameter.</div> : null}
      <div className="row" style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
        <label className="inline">
          Parameter
          <select value={p ? `${p.id}.${p.key}` : ""} onChange={(e) => setSel(e.target.value)} disabled={!params.length}>
            {params.map((q) => (
              <option key={`${q.id}.${q.key}`} value={`${q.id}.${q.key}`}>
                {q.id}.{q.key}
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
          <input type="number" min={2} max={51} value={steps} onChange={(e) => setSteps(Number(e.target.value) || 9)} style={{ width: 56 }} />
        </label>
        <label className="inline">
          Spectra
          <select value={scope} onChange={(e) => setScope(e.target.value as "selected" | "all")}>
            <option value="selected">Selected ({selectedIds.length})</option>
            <option value="all">All spectra of this step</option>
          </select>
        </label>
        <button type="button" className="mini" data-testid="sweep-run" disabled={busy || !p} onClick={() => void run()}>
          {busy ? "Running…" : "Run scan"}
        </button>
        {summary && jobId ? (
          <button type="button" className="mini" onClick={() => void download(getFitCurveJobDownloadUrl(jobId), `sweep_${runId}.zip`, setNote)}>
            Download zip
          </button>
        ) : null}
      </div>
      {note ? <div className="hint">{note}</div> : null}
      {figs ? (
        <div data-testid="sweep-result">
          <MiniPlot figure={figs.rmse} />
          <MiniPlot figure={figs.pct} />
        </div>
      ) : null}
    </div>
  );
}
