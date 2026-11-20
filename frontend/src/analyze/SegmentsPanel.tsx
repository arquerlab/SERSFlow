import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Plotly from "plotly.js-dist-min";
import { fetchObservationColumns } from "./api";
import { downloadCsv } from "./export";
import {
  postSegments,
  type AlignmentSummary,
  type DepthAlignParams,
  type SegmentsResult,
} from "./segmentsApi";
import {
  boundaryScatterFigure,
  costFigure,
  labelCsvRows,
  profileFigure,
  shiftFigure,
  signatureCsvRows,
  zoneColor,
  type Fig,
} from "./segmentsPlots";

function num(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function Field({ label, title, children }: { label: string; title?: string; children: ReactNode }) {
  return (
    <label className="mv-field" title={title}>
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

function Plot({ fig, height = 340 }: { fig: Fig | null; height?: number }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = ref.current as any;
    if (!el || !fig) return;
    const color = getComputedStyle(el).color || "#222";
    Plotly.react(
      el,
      fig.data as any,
      {
        autosize: true,
        height,
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { color, size: 12 },
        ...fig.layout,
      } as any,
      { responsive: true, displaylogo: false }
    );
  }, [fig, height]);
  useEffect(() => {
    const el = ref.current;
    return () => {
      if (el) Plotly.purge(el);
    };
  }, []);
  if (!fig) return null;
  return <div ref={ref} style={{ width: "100%", minHeight: height }} />;
}

/**
 * Segment spectra along an ordered axis (depth, time, distance) from fitted features, without PCA:
 * exact contiguous (dynamic-programming) zones or plain k-means, with an optional interface alignment
 * between map positions first.
 */
export function SegmentsPanel({
  runId,
  featureColumns,
  axisColumns,
}: {
  runId: string;
  featureColumns: string[];
  axisColumns: string[];
}) {
  const orderCandidates = useMemo(() => {
    const pref = ["axis_z", "axis_time_s"];
    const all = Array.from(new Set([...axisColumns, ...featureColumns]));
    return [...pref.filter((p) => all.includes(p)), ...all.filter((c) => !pref.includes(c))];
  }, [axisColumns, featureColumns]);
  const posCandidates = useMemo(() => axisColumns.filter((c) => c.startsWith("axis_map_")), [axisColumns]);

  const [orderCol, setOrderCol] = useState("");
  const [feats, setFeats] = useState<string[]>([]);
  const [method, setMethod] = useState<"contiguous" | "kmeans">("contiguous");
  const [k, setK] = useState(4);
  const [kMax, setKMax] = useState(6);
  const [binW, setBinW] = useState("5");
  const [winsor, setWinsor] = useState("99");
  const [clip, setClip] = useState("5");
  const [standardize, setStandardize] = useState(true);
  const [seed, setSeed] = useState(0);
  const [nInit, setNInit] = useState(50);
  const [perPos, setPerPos] = useState(true);

  const [align, setAlign] = useState(false);
  const [aFeat, setAFeat] = useState("");
  const [aMode, setAMode] = useState<"edge" | "argmax">("edge");
  const [aDir, setADir] = useState<"down" | "up">("down");
  const [aSmooth, setASmooth] = useState(3);
  const [aPlateau, setAPlateau] = useState("");
  const [aLoLo, setALoLo] = useState("");
  const [aLoHi, setALoHi] = useState("");
  const [aSearch, setASearch] = useState("");
  const [aRefX, setARefX] = useState("");
  const [aRefY, setARefY] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<SegmentsResult | null>(null);
  const [names, setNames] = useState<string[]>([]);
  const [profFeat, setProfFeat] = useState("");
  const [profVals, setProfVals] = useState<(number | null)[] | null>(null);
  const [lastBin, setLastBin] = useState(5);

  useEffect(() => {
    if (!orderCol || !orderCandidates.includes(orderCol)) setOrderCol(orderCandidates[0] ?? "");
  }, [orderCandidates, orderCol]);
  useEffect(() => {
    setFeats((f) => f.filter((c) => featureColumns.includes(c)));
    if (aFeat && !featureColumns.includes(aFeat)) setAFeat("");
  }, [featureColumns, aFeat]);
  useEffect(() => {
    setRes(null);
    setProfVals(null);
  }, [runId]);

  const toggle = (c: string, on: boolean) => setFeats((f) => (on ? (f.includes(c) ? f : [...f, c]) : f.filter((x) => x !== c)));

  async function run() {
    setBusy(true);
    setError(null);
    try {
      let alignBody: DepthAlignParams | null = null;
      if (align) {
        if (!aFeat) throw new Error("Choose the feature that carries the interface for the alignment.");
        const lo = num(aLoLo);
        const hi = num(aLoHi);
        const rx = num(aRefX);
        const ry = num(aRefY);
        alignBody = {
          feature_column: aFeat,
          position_columns: posCandidates.length ? posCandidates : ["axis_map_x", "axis_map_y"],
          mode: aMode,
          direction: aDir,
          smooth: aSmooth,
          plateau_z_max: num(aPlateau),
          low_z_range: lo != null && hi != null ? [lo, hi] : null,
          search_z_min: num(aSearch),
          reference: rx != null && ry != null ? [rx, ry] : null,
        };
      }
      if (!feats.length) throw new Error("Select at least one feature column.");
      const bw = num(binW) ?? 5;
      const out = await postSegments({
        analysis_run_id: runId,
        feature_columns: feats,
        order_column: orderCol,
        method,
        n_segments: k,
        k_max: Math.max(kMax, k),
        bin_width: bw,
        winsor_pct: num(winsor),
        robust_clip: num(clip),
        standardize,
        seed,
        n_init: nInit,
        per_position_check: perPos && posCandidates.length > 0,
        position_columns: posCandidates.length ? posCandidates : ["axis_map_x", "axis_map_y"],
        align: alignBody,
      });
      const r = out.results;
      setRes(r);
      setLastBin(bw);
      setNames((old) => r.zone_names.map((d, i) => (old[i] && old.length === r.zone_names.length ? old[i] : d)));
      setProfVals(null);
      setProfFeat(r.feature_columns[0] ?? "");
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  // values of the profile feature joined to the segmented spectra
  useEffect(() => {
    if (!res || !profFeat) return;
    let cancelled = false;
    fetchObservationColumns(runId, ["spectrum_id", profFeat], 500_000)
      .then(({ rows }) => {
        if (cancelled) return;
        const m = new Map<string, number | null>();
        for (const r of rows) {
          const v = r[profFeat];
          const n = typeof v === "number" ? v : v == null || v === "" ? null : Number(v);
          m.set(String(r.spectrum_id), n != null && Number.isFinite(n) ? n : null);
        }
        setProfVals(res.spectrum_ids.map((id) => m.get(id) ?? null));
      })
      .catch(() => !cancelled && setProfVals(null));
    return () => {
      cancelled = true;
    };
  }, [res, profFeat, runId]);

  const costFig = useMemo(() => (res ? costFigure(res) : null), [res]);
  const profFig = useMemo(
    () => (res && profVals ? profileFigure(res, profVals, profFeat, lastBin, names) : null),
    [res, profVals, profFeat, lastBin, names]
  );
  const bndFig = useMemo(() => (res ? boundaryScatterFigure(res) : null), [res]);
  const shiftFig = useMemo(() => (res?.alignment ? shiftFigure(res.alignment as AlignmentSummary) : null), [res]);

  return (
    <div style={{ marginTop: 14 }}>
      <div className="section-title">Clustering / Segmentation along an ordered axis</div>
      <div className="hint" style={{ marginBottom: 8 }}>
        Split spectra along depth (or time, distance) from fitted features, without PCA. <b>Contiguous</b> finds the optimal
        consecutive zones (exact dynamic programming); <b>k-means</b> clusters the same features and need not be contiguous.
        Features are winsorised, robust-scaled and standardised first, so isolated failed-fit spikes do not dominate.
      </div>

      <div className="mv-grid">
        <Field label="Order axis">
          <select value={orderCol} onChange={(e) => setOrderCol(e.target.value)}>
            {orderCandidates.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Method">
          <select value={method} onChange={(e) => setMethod(e.target.value as "contiguous" | "kmeans")}>
            <option value="contiguous">Contiguous segmentation</option>
            <option value="kmeans">k-means</option>
          </select>
        </Field>
        <Field label="Segments (K)">
          <input type="number" min={2} max={50} value={k} onChange={(e) => setK(Math.max(2, Number(e.target.value) || 2))} />
        </Field>
        <Field label="Scan K up to" title="Cost (and silhouette for k-means) is computed for K = 1..this value">
          <input type="number" min={2} max={50} value={kMax} onChange={(e) => setKMax(Math.max(2, Number(e.target.value) || 2))} />
        </Field>
        {method === "contiguous" ? (
          <Field label="z bin width" title="Spectra are averaged in bins of this width before the split; 0 = every distinct z">
            <input type="text" value={binW} onChange={(e) => setBinW(e.target.value)} />
          </Field>
        ) : (
          <>
            <Field label="Seed">
              <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value) || 0)} />
            </Field>
            <Field label="Restarts (n_init)" title="At least 20 is used for stability">
              <input type="number" min={1} value={nInit} onChange={(e) => setNInit(Math.max(1, Number(e.target.value) || 1))} />
            </Field>
          </>
        )}
        <Field label="Winsorise at percentile" title="Upper clip per feature; empty = off">
          <input type="text" value={winsor} onChange={(e) => setWinsor(e.target.value)} />
        </Field>
        <Field label="Robust clip (± IQR units)" title="After median/IQR scaling; empty = off">
          <input type="text" value={clip} onChange={(e) => setClip(e.target.value)} />
        </Field>
        <Check checked={standardize} onChange={setStandardize} label="Standardise (z-score)" />
        {method === "contiguous" && posCandidates.length ? (
          <Check checked={perPos} onChange={setPerPos} label="Per-position boundary check" title="Repeat the split independently at each map position to see how tight each boundary is" />
        ) : null}
      </div>

      <div className="hint" style={{ margin: "10px 0 4px" }}>
        Features
        <button type="button" className="mini" style={{ marginLeft: 8 }} onClick={() => setFeats(featureColumns.filter((c) => /(_area|_amp)$|area|amp/.test(c)))}>
          Areas / amplitudes
        </button>
        <button type="button" className="mini" style={{ marginLeft: 4 }} onClick={() => setFeats(featureColumns.slice())}>
          All
        </button>
        <button type="button" className="mini" style={{ marginLeft: 4 }} onClick={() => setFeats([])}>
          Clear
        </button>
        <span style={{ marginLeft: 8 }}>{feats.length} selected</span>
      </div>
      <div style={{ maxHeight: 180, overflow: "auto", border: "1px solid rgba(255,255,255,0.08)", padding: 6 }}>
        {featureColumns.map((c) => (
          <label key={c} className="inline" style={{ display: "inline-block", marginRight: 12 }} title={c}>
            <input type="checkbox" checked={feats.includes(c)} onChange={(e) => toggle(c, e.target.checked)} /> {c}
          </label>
        ))}
      </div>

      <div style={{ marginTop: 10 }}>
        <Check
          checked={align}
          onChange={setAlign}
          label="Align z between map positions first (interface / edge)"
          title="Per position, the half-height crossing of one feature along z is located and every position is shifted relative to the reference"
        />
        {align ? (
          <div className="mv-grid" style={{ marginTop: 6 }}>
            <Field label="Interface feature">
              <select value={aFeat} onChange={(e) => setAFeat(e.target.value)}>
                <option value="">(choose)</option>
                {featureColumns.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Criterion">
              <select value={aMode} onChange={(e) => setAMode(e.target.value as "edge" | "argmax")}>
                <option value="edge">Half-height edge (robust)</option>
                <option value="argmax">Position of maximum (noisy)</option>
              </select>
            </Field>
            <Field label="Profile with increasing z">
              <select value={aDir} onChange={(e) => setADir(e.target.value as "down" | "up")}>
                <option value="down">falls</option>
                <option value="up">rises</option>
              </select>
            </Field>
            <Field label="Smoothing (points)">
              <input type="number" min={1} value={aSmooth} onChange={(e) => setASmooth(Math.max(1, Number(e.target.value) || 1))} />
            </Field>
            <Field label="Plateau: z ≤" title="Plateau = mean of the 6 largest smoothed values with z at or below this. Empty = lowest third of the z range">
              <input type="text" value={aPlateau} onChange={(e) => setAPlateau(e.target.value)} placeholder="auto" />
            </Field>
            <Field label="Low level: z from" title="Minimum is taken over this z range. Empty = everything above the plateau">
              <input type="text" value={aLoLo} onChange={(e) => setALoLo(e.target.value)} placeholder="auto" />
            </Field>
            <Field label="Low level: z to">
              <input type="text" value={aLoHi} onChange={(e) => setALoHi(e.target.value)} placeholder="auto" />
            </Field>
            <Field label="Search edge from z ≥" title="First downward crossing at or above this z. Empty = start of the scan">
              <input type="text" value={aSearch} onChange={(e) => setASearch(e.target.value)} placeholder="auto" />
            </Field>
            <Field label="Reference x" title="Both empty = position closest to the map centre. The reference keeps its z.">
              <input type="text" value={aRefX} onChange={(e) => setARefX(e.target.value)} placeholder="centre" />
            </Field>
            <Field label="Reference y">
              <input type="text" value={aRefY} onChange={(e) => setARefY(e.target.value)} placeholder="centre" />
            </Field>
          </div>
        ) : null}
      </div>

      <div className="row" style={{ gap: 8, marginTop: 10, alignItems: "center" }}>
        <button type="button" disabled={busy || !runId || !orderCol} onClick={run}>
          {busy ? "Running…" : method === "contiguous" ? "Run contiguous segmentation" : "Run k-means"}
        </button>
        {error ? <span className="hint" style={{ color: "#d62728" }}>{error}</span> : null}
      </div>

      {res ? (
        <div style={{ marginTop: 14 }}>
          <div className="hint">
            {res.n_rows} spectra segmented{res.n_dropped_rows ? ` (${res.n_dropped_rows} skipped: missing z or feature values)` : ""}
            {res.cuts ? ` · boundaries at ${res.cuts.map((c) => c.toFixed(1)).join(", ")}` : ""}
            {res.contiguity != null ? ` · contiguity ${(res.contiguity * 100).toFixed(1)}% (100% = every cluster is one z interval)` : ""}
            {res.alignment
              ? ` · alignment: reference ${res.alignment.reference.join(", ")} at ${res.alignment.reference_edge_z.toFixed(1)}, shifts ${res.alignment.shift_min?.toFixed(1)}…${res.alignment.shift_max?.toFixed(1)}` +
                (res.alignment.n_positions_without_edge ? `, ${res.alignment.n_positions_without_edge} positions without an edge (left unshifted)` : "")
              : ""}
          </div>

          <table className="table" style={{ marginTop: 8, fontSize: 12 }}>
            <thead>
              <tr>
                <th>Zone name (editable)</th>
                <th>n</th>
                <th>z from</th>
                <th>z to</th>
              </tr>
            </thead>
            <tbody>
              {res.segments.map((s) => (
                <tr key={s.segment}>
                  <td>
                    <span style={{ display: "inline-block", width: 10, height: 10, background: zoneColor(s.segment), marginRight: 6 }} />
                    <input
                      type="text"
                      value={names[s.segment] ?? ""}
                      onChange={(e) => setNames((n) => n.map((v, i) => (i === s.segment ? e.target.value : v)))}
                    />
                  </td>
                  <td>{s.n}</td>
                  <td>{s.z_min.toFixed(1)}</td>
                  <td>{s.z_max.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="row" style={{ gap: 8, margin: "8px 0" }}>
            <button type="button" className="mini" onClick={() => downloadCsv(`segments_${res.method}_K${res.n_segments}_labels.csv`, labelCsvRows(res, names))}>
              Download labels CSV
            </button>
            <button type="button" className="mini" onClick={() => downloadCsv(`segments_${res.method}_K${res.n_segments}_median_features.csv`, signatureCsvRows(res, names))}>
              Download zone signature CSV
            </button>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(420px, 1fr))", gap: 12 }}>
            <Plot fig={costFig} />
            {bndFig ? <Plot fig={bndFig} /> : null}
            {shiftFig ? <Plot fig={shiftFig} /> : null}
          </div>

          <div className="row" style={{ gap: 8, margin: "12px 0 4px", alignItems: "center" }}>
            <span className="hint">Profile of</span>
            <select value={profFeat} onChange={(e) => setProfFeat(e.target.value)}>
              {res.feature_columns.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <Plot fig={profFig} height={360} />
        </div>
      ) : null}
    </div>
  );
}
