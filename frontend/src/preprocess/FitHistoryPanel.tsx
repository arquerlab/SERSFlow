import { useCallback, useEffect, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import {
  clearFitHistory,
  deleteFitHistory,
  getFitHistory,
  getFitHistoryCompare,
  patchFitHistory,
  postFitHistory,
  postFittingFit,
  type FitHistoryCompare,
  type FitHistoryItem,
  type FitHistorySummary,
} from "./api";
import { buildFitRequest } from "./interactiveFit";
import type { FitPreviewInput } from "./fitInputs";

function ComparePlot({ x, y, a, b, labelA, labelB }: { x: number[]; y: number[]; a: Array<number | null>; b: Array<number | null>; labelA: string; labelB: string }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    void Plotly.newPlot(
      ref.current,
      [
        { type: "scatter", mode: "lines", x, y, name: "Data", line: { color: "#333", width: 1 } },
        { type: "scatter", mode: "lines", x, y: a, name: labelA, line: { color: "#e74c3c", width: 2 } },
        { type: "scatter", mode: "lines", x, y: b, name: labelB, line: { color: "#2980b9", width: 2, dash: "dash" } },
      ] as any,
      { height: 260, margin: { l: 60, r: 10, t: 10, b: 40 }, legend: { orientation: "h", y: -0.25 } } as any,
      { displayModeBar: false, responsive: true }
    );
  }, [x, y, a, b, labelA, labelB]);
  return <div ref={ref} data-testid="history-compare-plot" />;
}

function fmt(v: number | null | undefined, d = 3): string {
  if (v == null || !Number.isFinite(v)) return "–";
  return Math.abs(v) >= 1e4 || (v !== 0 && Math.abs(v) < 1e-3) ? v.toExponential(2) : v.toFixed(d);
}

function nameOf(it: FitHistoryItem): string {
  return it.label || new Date(it.created_at).toLocaleString();
}

type Props = {
  scopeKey: string;
  technique: string;
  /** First spectrum of the preview (compare overlay). */
  input: FitPreviewInput | undefined;
  /** Current editor state, as pipeline-format params + summary, for "Store as…". */
  current: () => { params: Record<string, unknown>; summary: FitHistorySummary } | null;
  /** RECALL: put the snapshot's params back into the fitting step (and redraw). */
  onRecall: (params: Record<string, any>) => void;
  /** Bumped by the parent after each automatic snapshot. */
  refreshToken: number;
};

/** X1 fit history: STORE / RECALL / RESET with compare (parameter table + curve overlay). */
export function FitHistoryPanel({ scopeKey, technique, input, current, onRecall, refreshToken }: Props) {
  const [items, setItems] = useState<FitHistoryItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<string[]>([]);
  const [cmp, setCmp] = useState<{ table: FitHistoryCompare; ya: Array<number | null>; yb: Array<number | null> } | null>(null);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    try {
      const r = await getFitHistory(scopeKey, true);
      setItems(r.items);
      setErr(null);
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    }
  }, [scopeKey]);

  useEffect(() => {
    void reload();
  }, [reload, refreshToken]);

  async function store() {
    const cur = current();
    if (!cur) return;
    const label = window.prompt("Name for this model state:", "");
    if (label === null) return;
    try {
      await postFitHistory({ scope_key: scopeKey, params: cur.params, summary: cur.summary, label: label.trim() || undefined, pinned: true });
      await reload();
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    }
  }

  async function reset() {
    if (!window.confirm("Remove all unpinned snapshots of this fit? Named (pinned) ones stay.")) return;
    try {
      await clearFitHistory(scopeKey);
      setSel([]);
      setCmp(null);
      await reload();
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    }
  }

  async function compare() {
    if (sel.length !== 2 || !input) return;
    setBusy(true);
    setErr(null);
    try {
      const [a, b] = sel.map((id) => items.find((i) => i.history_id === id)!);
      const table = await getFitHistoryCompare(a.history_id, b.history_id);
      const ev = async (it: FitHistoryItem) => {
        const r = await postFittingFit(buildFitRequest(it.params ?? {}, input, { technique, weighting: "none", fit: false }));
        return (r.y_hat ?? []) as Array<number | null>;
      };
      setCmp({ table, ya: await ev(a), yb: await ev(b) });
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  const a = items.find((i) => i.history_id === sel[0]);
  const b = items.find((i) => i.history_id === sel[1]);

  return (
    <details data-testid="fit-history" style={{ fontSize: 12 }}>
      <summary style={{ cursor: "pointer", fontWeight: 700 }}>Fit history ({items.length})</summary>
      <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
        <div className="hint" style={{ margin: 0 }}>
          Every preview fit is stored automatically (identical states are merged, the latest 50 unnamed are kept). Store a named
          state to keep it, recall one to put its model back, or compare two.
        </div>
        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
          <button type="button" className="mini" onClick={() => void store()} data-testid="history-store" disabled={!current()}>
            Store as…
          </button>
          <button type="button" className="mini danger" onClick={() => void reset()} data-testid="history-reset" disabled={!items.some((i) => !i.pinned)}>
            Reset (clear unpinned)
          </button>
          <button type="button" className="mini" onClick={() => void compare()} data-testid="history-compare" disabled={sel.length !== 2 || !input || busy}>
            Compare selected
          </button>
        </div>
        {err ? <div className="err">{err}</div> : null}
        <div style={{ maxHeight: 220, overflow: "auto", display: "grid", gap: 2 }}>
          {items.map((it) => (
            <div key={it.history_id} className="row" style={{ gap: 6, alignItems: "center" }} data-testid="history-row">
              <input
                type="checkbox"
                checked={sel.includes(it.history_id)}
                onChange={(e) => setSel((s) => (e.target.checked ? [...s, it.history_id].slice(-2) : s.filter((x) => x !== it.history_id)))}
                title="Select two to compare"
              />
              <span style={{ flex: 1, fontWeight: it.pinned ? 700 : 400 }}>
                {it.pinned ? "★ " : ""}
                {nameOf(it)}
                <span className="hint" style={{ margin: "0 0 0 6px" }}>
                  {it.summary.redchi != null ? `χ²ν ${fmt(it.summary.redchi)}` : ""}
                  {it.summary.rmse != null ? ` · RMSE ${fmt(it.summary.rmse, 2)}` : ""}
                  {it.summary.fitted === false ? " · edited" : ""}
                </span>
              </span>
              <button type="button" className="mini" onClick={() => it.params && onRecall(it.params)} data-testid="history-recall" title="Put this model back">
                Recall
              </button>
              <button
                type="button"
                className="mini"
                onClick={() => void patchFitHistory(it.history_id, { pinned: !it.pinned }).then(reload)}
                title={it.pinned ? "Unpin" : "Pin (keep)"}
              >
                {it.pinned ? "★" : "☆"}
              </button>
              <button type="button" className="mini danger" onClick={() => void deleteFitHistory(it.history_id).then(reload)} title="Delete">
                ✕
              </button>
            </div>
          ))}
          {!items.length ? <div className="hint">No snapshots yet: run the preview to store the first one.</div> : null}
        </div>
        {cmp && a && b && input ? (
          <div data-testid="history-compare-result" style={{ display: "grid", gap: 6 }}>
            <ComparePlot x={input.x} y={input.y} a={cmp.ya} b={cmp.yb} labelA={`A: ${nameOf(a)}`} labelB={`B: ${nameOf(b)}`} />
            <div style={{ maxHeight: 240, overflow: "auto" }}>
              <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th align="left">Component</th>
                    <th align="left">Param</th>
                    <th align="right">A</th>
                    <th align="right">B</th>
                    <th align="right">Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {cmp.table.rows.map((r, i) => (
                    <tr key={i} style={{ background: r.delta != null && Math.abs(r.delta) > 1e-9 ? "rgba(255,200,0,0.12)" : undefined }}>
                      <td>{r.component_id}{r.only_in ? ` (only in ${r.only_in.toUpperCase()})` : ""}</td>
                      <td>{r.key}</td>
                      <td align="right">{fmt(r.a)}</td>
                      <td align="right">{fmt(r.b)}</td>
                      <td align="right">{fmt(r.delta)}</td>
                    </tr>
                  ))}
                  {cmp.table.stats.map((s) => (
                    <tr key={`s-${s.name}`}>
                      <td colSpan={2}><i>{s.name}</i></td>
                      <td align="right">{fmt(s.a)}</td>
                      <td align="right">{fmt(s.b)}</td>
                      <td align="right">{s.a != null && s.b != null ? fmt(s.b - s.a) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="hint" style={{ margin: 0 }}>
              Window A {fmt(cmp.table.window_a[0], 1)}–{fmt(cmp.table.window_a[1], 1)}, B {fmt(cmp.table.window_b[0], 1)}–{fmt(cmp.table.window_b[1], 1)}.
              Curves are evaluations of the stored parameters on the first previewed spectrum.
            </div>
          </div>
        ) : null}
      </div>
    </details>
  );
}
