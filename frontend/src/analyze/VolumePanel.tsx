import { createPortal } from "react-dom";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { fetchAnalysisSpectrum, fetchObservationColumns } from "./api";
import { downloadBlob, downloadCsv, plotlyDivToPngBytes } from "./export";
import {
  Z_TITLE,
  buildVolume,
  clampIdx,
  colorRange,
  depthProfile,
  isVolume,
  montageFigure,
  nearestIdx,
  pickLayers,
  planeFigure,
  profileFigure,
  project,
  roiSpectrumIds,
  sliceXY,
  sliceXZ,
  sliceYZ,
  stackFigure,
  volumeCsvRows,
  zIndicesInRange,
  type PlotlyFig,
  type ProjectionMode,
  type VolumeRow,
} from "./volumeModel";

type ViewTab = "slices" | "montage" | "stack";
type XyMode = "slice" | ProjectionMode;

const XY_MODE_LABEL: Record<XyMode, string> = {
  slice: "Slice at depth",
  mean: "Mean over depth range",
  max: "Max over depth range",
  min: "Min over depth range",
  sum: "Sum over depth range",
  argmax: "Depth of maximum (z map)",
};

function toNum(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

type PlotProps = { fig: PlotlyFig | null; onClick?: (ev: any) => void; height?: number };

/** Minimal Plotly host (no theme rewriting, so 3-D scenes, shapes and subplots stay intact). */
const PlainPlot = forwardRef<HTMLDivElement, PlotProps>(function PlainPlot({ fig, onClick, height = 380 }, ref) {
  const divRef = useRef<HTMLDivElement | null>(null);
  const clickRef = useRef(onClick);
  clickRef.current = onClick;
  useImperativeHandle(ref, () => divRef.current as HTMLDivElement);

  useEffect(() => {
    const el = divRef.current as any;
    if (!el || !fig) return;
    const color = getComputedStyle(el).color || "#222";
    const layout = {
      autosize: true,
      height,
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color, size: 12 },
      ...fig.layout,
    };
    let cancelled = false;
    Promise.resolve(Plotly.react(el, fig.data as any, layout as any, { responsive: true, displaylogo: false })).then(() => {
      if (cancelled) return;
      el.removeAllListeners?.("plotly_click");
      el.on?.("plotly_click", (ev: any) => clickRef.current?.(ev));
    });
    return () => {
      cancelled = true;
    };
  }, [fig, height]);

  useEffect(() => {
    const el = divRef.current;
    return () => {
      if (el) Plotly.purge(el);
    };
  }, []);

  return <div ref={divRef} style={{ width: "100%", minHeight: height }} />;
});

function FigureCard({ id, fig, onClick, height }: { id: string; fig: PlotlyFig | null; onClick?: (ev: any) => void; height?: number }) {
  const ref = useRef<HTMLDivElement | null>(null);
  if (!fig) return null;
  return (
    <div className="card-inner" style={{ minWidth: 0 }}>
      <div className="row" style={{ justifyContent: "flex-end", margin: 0 }}>
        <button
          type="button"
          className="mini"
          onClick={async () => {
            if (!ref.current) return;
            const bytes = await plotlyDivToPngBytes(ref.current, { width: 1200, scale: 2 });
            downloadBlob(`${id}.png`, new Blob([bytes as unknown as BlobPart], { type: "image/png" }));
          }}
        >
          Download PNG
        </button>
      </div>
      <PlainPlot ref={ref} fig={fig} onClick={onClick} height={height} />
    </div>
  );
}

export function VolumePanel({ runId, featureColumns }: { runId: string; featureColumns: string[] }) {
  const [featA, setFeatA] = useState("");
  const [featB, setFeatB] = useState("");
  const [useRatio, setUseRatio] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filesRows, setFilesRows] = useState<Record<string, VolumeRow[]>>({});
  const [file, setFile] = useState("");
  const [loadedKey, setLoadedKey] = useState("");

  const [tab, setTab] = useState<ViewTab>("slices");
  const [xyMode, setXyMode] = useState<XyMode>("slice");
  const [cross, setCross] = useState({ xi: 0, yi: 0, zi: 0 });
  const [slab, setSlab] = useState<[number, number]>([0, 0]);
  const [roiRadius, setRoiRadius] = useState(0);
  const [sharedScale, setSharedScale] = useState(true);
  const [maskMin, setMaskMin] = useState("");
  const [maskMax, setMaskMax] = useState("");
  const [zOffset, setZOffset] = useState("0");
  const [zScale, setZScale] = useState("1");
  const [playing, setPlaying] = useState(false);
  const [montageLayers, setMontageLayers] = useState(12);
  const [montageCols, setMontageCols] = useState(4);
  const [stackLayers, setStackLayers] = useState(10);
  const [stackOpacity, setStackOpacity] = useState(0.85);
  const [reverseZ, setReverseZ] = useState(false);
  const [spectraFig, setSpectraFig] = useState<PlotlyFig | null>(null);
  const [spectraMsg, setSpectraMsg] = useState("");
  // Figures and view controls render into the wide results pane; data controls stay in the sidebar.
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null);
  useEffect(() => {
    const el = document.getElementById("volume-results");
    if (el !== portalTarget) setPortalTarget(el);
  });

  useEffect(() => {
    if (!featA && featureColumns.length) setFeatA(featureColumns[0]);
  }, [featureColumns, featA]);

  const ratioActive = useRatio && !!featB;

  const load = useCallback(async () => {
    if (!runId || !featA) return;
    setLoading(true);
    setError(null);
    try {
      const cols = [featA, ...(featB ? [featB] : []), "relative_path", "axis_z", "axis_map_x", "axis_map_y"];
      const { rows } = await fetchObservationColumns(runId, Array.from(new Set(cols)), 500_000);
      const byFile: Record<string, VolumeRow[]> = {};
      for (const r of rows) {
        const z = toNum(r.axis_z);
        const x = toNum(r.axis_map_x);
        const y = toNum(r.axis_map_y);
        const rel = String(r.relative_path ?? "");
        if (!rel || z === null || x === null || y === null) continue;
        (byFile[rel] ??= []).push({
          spectrum_id: String(r.spectrum_id ?? ""),
          x,
          y,
          z,
          a: toNum(r[featA]),
          b: featB ? toNum(r[featB]) : null,
        });
      }
      // Only files with several depth levels are volumes.
      const vols: Record<string, VolumeRow[]> = {};
      for (const [rel, rs] of Object.entries(byFile)) if (new Set(rs.map((q) => q.z.toFixed(6))).size > 1) vols[rel] = rs;
      setFilesRows(vols);
      setFile((cur) => (cur && vols[cur] ? cur : Object.keys(vols).sort()[0] ?? ""));
      setLoadedKey(`${runId}|${featA}|${featB}`);
    } catch (e) {
      setError(String((e as Error)?.message ?? e));
    } finally {
      setLoading(false);
    }
  }, [runId, featA, featB]);

  useEffect(() => {
    if (!runId || !featA) return;
    load();
  }, [load, runId, featA]);

  const volume = useMemo(() => {
    const rs = filesRows[file];
    if (!rs) return null;
    return buildVolume(rs, {
      ratio: ratioActive,
      maskMin: maskMin.trim() === "" ? null : Number(maskMin),
      maskMax: maskMax.trim() === "" ? null : Number(maskMax),
      zOffset: Number(zOffset),
      zScale: Number(zScale),
    });
  }, [filesRows, file, ratioActive, maskMin, maskMax, zOffset, zScale]);

  const nz = volume?.zs.length ?? 0;
  useEffect(() => {
    if (!volume) return;
    setCross((c) => ({ xi: clampIdx(c.xi, volume.xs.length), yi: clampIdx(c.yi, volume.ys.length), zi: clampIdx(c.zi, volume.zs.length) }));
    setSlab((s) => (s[1] === 0 && s[0] === 0 ? [0, volume.zs.length - 1] : [clampIdx(s[0], volume.zs.length), clampIdx(s[1], volume.zs.length)]));
    setSpectraFig(null);
  }, [volume]);

  useEffect(() => {
    if (!playing || nz < 2) return;
    const t = window.setInterval(() => setCross((c) => ({ ...c, zi: (c.zi + 1) % nz })), 450);
    return () => window.clearInterval(t);
  }, [playing, nz]);

  const label = ratioActive ? `${featA} / ${featB}` : featA;
  const fileFiles = Object.keys(filesRows).sort();

  const figs = useMemo(() => {
    if (!volume || !isVolume(volume)) return null;
    const v = volume;
    const zi = clampIdx(cross.zi, v.zs.length);
    const xv = v.xs[clampIdx(cross.xi, v.xs.length)];
    const yv = v.ys[clampIdx(cross.yi, v.ys.length)];
    const zv = v.zs[zi];
    const shared = colorRange(v, true);

    let xyPlane = sliceXY(v, zi);
    let xyTitle = `XY at z = ${zv.toFixed(1)} µm`;
    let xyRange = sharedScale ? shared : colorRange(v, false, xyPlane);
    let xyCb = label;
    if (xyMode !== "slice") {
      const idx = zIndicesInRange(v, v.zs[slab[0]], v.zs[slab[1]]);
      xyPlane = project(v, xyMode, idx);
      const lo = v.zs[Math.min(slab[0], slab[1])].toFixed(1);
      const hi = v.zs[Math.max(slab[0], slab[1])].toFixed(1);
      xyTitle = `${XY_MODE_LABEL[xyMode]} [${lo}, ${hi}] µm`;
      xyRange = colorRange(v, false, xyPlane);
      if (xyMode === "argmax") xyCb = Z_TITLE;
    }
    const xy = planeFigure({
      title: xyTitle,
      x: v.xs,
      y: v.ys,
      z: xyPlane,
      xTitle: "x (µm)",
      yTitle: "y (µm)",
      colorbarTitle: xyCb,
      range: xyRange,
      crosshair: { x: xv, y: yv },
      colorscale: xyMode === "argmax" ? "Turbo" : undefined,
    });
    const xz = planeFigure({
      title: `XZ at y = ${yv}`,
      x: v.xs,
      y: v.zs,
      z: sliceXZ(v, cross.yi),
      xTitle: "x (µm)",
      yTitle: Z_TITLE,
      colorbarTitle: label,
      range: shared,
      crosshair: { x: xv, y: zv },
    });
    const yz = planeFigure({
      title: `YZ at x = ${xv}`,
      x: v.ys,
      y: v.zs,
      z: sliceYZ(v, cross.xi),
      xTitle: "y (µm)",
      yTitle: Z_TITLE,
      colorbarTitle: label,
      range: shared,
      crosshair: { x: yv, y: zv },
    });
    const prof = profileFigure(
      depthProfile(v, cross.xi, cross.yi, roiRadius),
      label,
      `${label} vs depth at (x=${xv}, y=${yv})${roiRadius > 0 ? `, ROI radius ${roiRadius}` : ""}`
    );
    const montage = montageFigure(v, pickLayers(v.zs.length, montageLayers), {
      cols: montageCols,
      shared: sharedScale,
      label,
      title: `${label}: depth layers`,
    });
    const stack = stackFigure(v, pickLayers(v.zs.length, stackLayers), {
      opacity: stackOpacity,
      label,
      title: `${label}: stacked depth layers`,
      reverseZ,
    });
    return { xy, xz, yz, prof, montage, stack };
  }, [volume, cross, xyMode, slab, sharedScale, roiRadius, label, montageLayers, montageCols, stackLayers, stackOpacity, reverseZ]);

  function setPoint(patch: Partial<{ xi: number; yi: number; zi: number }>) {
    setCross((c) => ({ ...c, ...patch }));
  }

  const onXyClick = (ev: any) => {
    const p = ev?.points?.[0];
    if (!p || !volume) return;
    setPoint({ xi: nearestIdx(volume.xs, Number(p.x)), yi: nearestIdx(volume.ys, Number(p.y)) });
  };
  const onXzClick = (ev: any) => {
    const p = ev?.points?.[0];
    if (!p || !volume) return;
    setPoint({ xi: nearestIdx(volume.xs, Number(p.x)), zi: nearestIdx(volume.zs, Number(p.y)) });
  };
  const onYzClick = (ev: any) => {
    const p = ev?.points?.[0];
    if (!p || !volume) return;
    setPoint({ yi: nearestIdx(volume.ys, Number(p.x)), zi: nearestIdx(volume.zs, Number(p.y)) });
  };
  const onProfileClick = (ev: any) => {
    const p = ev?.points?.[0];
    if (!p || !volume) return;
    setPoint({ zi: nearestIdx(volume.zs, Number(p.x)) });
  };
  const onMontageClick = (ev: any) => {
    const p = ev?.points?.[0];
    if (!p || !volume) return;
    const layers = pickLayers(volume.zs.length, montageLayers);
    const zi = layers[p.curveNumber] ?? cross.zi;
    setPoint({ xi: nearestIdx(volume.xs, Number(p.x)), yi: nearestIdx(volume.ys, Number(p.y)), zi });
  };

  async function overlayRoiSpectra() {
    if (!volume) return;
    const ids = roiSpectrumIds(volume, cross.zi, cross.xi, cross.yi, roiRadius).slice(0, 40);
    if (!ids.length) {
      setSpectraFig(null);
      setSpectraMsg("No spectra in the ROI at this depth.");
      return;
    }
    setSpectraMsg(`Loading ${ids.length} spectra…`);
    try {
      const sp = await Promise.all(ids.map((id) => fetchAnalysisSpectrum(runId, id)));
      const x = (sp[0].x ?? []).map((v) => (v === null ? NaN : v));
      const ys = sp.map((s) => (s.y ?? []).map((v) => (v === null ? NaN : v)));
      const mean = x.map((_, i) => {
        const vals = ys.map((y) => y[i]).filter((q) => Number.isFinite(q));
        return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : NaN;
      });
      const data: any[] = ys.map((y, i) => ({
        type: "scatter",
        mode: "lines",
        x,
        y,
        opacity: ids.length > 1 ? 0.35 : 1,
        line: { width: 1 },
        name: sp[i].spectrum_id,
        showlegend: false,
      }));
      if (ids.length > 1) data.push({ type: "scatter", mode: "lines", x, y: mean, name: "ROI mean", line: { width: 3, color: "#d62728" } });
      setSpectraFig({
        data,
        layout: {
          title: { text: `ROI spectra at z = ${volume.zs[cross.zi].toFixed(1)} µm (${ids.length})` },
          xaxis: { title: { text: "Raman shift (cm⁻¹)" } },
          yaxis: { title: { text: "Intensity" } },
          margin: { l: 60, r: 20, t: 40, b: 50 },
          showlegend: ids.length > 1,
        },
      });
      setSpectraMsg("");
    } catch (e) {
      setSpectraMsg(String((e as Error)?.message ?? e));
    }
  }

  const noVolume = !loading && loadedKey && fileFiles.length === 0;

  return (
    <div style={{ marginTop: "22px" }}>
      <div className="section-title">Volume maps (X × Y × depth)</div>
      <p className="hint">
        For maps acquired at several depths. Click any slice to move the crosshair; the other panels and the depth profile follow.
      </p>
      <div className="row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "flex-end" }}>
        <label className="inline">
          Feature
          <select value={featA} onChange={(e) => setFeatA(e.target.value)}>
            {featureColumns.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="inline">
          Feature B (ratio)
          <select value={featB} onChange={(e) => setFeatB(e.target.value)}>
            <option value="">none</option>
            {featureColumns.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="inline">
          <input type="checkbox" checked={useRatio} disabled={!featB} onChange={(e) => setUseRatio(e.target.checked)} /> Show A / B
        </label>
        {fileFiles.length > 1 ? (
          <label className="inline">
            File
            <select value={file} onChange={(e) => setFile(e.target.value)}>
              {fileFiles.map((f) => (
                <option key={f} value={f}>
                  {f.split(/[\\/]/).pop()}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <button type="button" disabled={loading || !featA} onClick={() => load()}>
          {loading ? "Loading…" : "Reload"}
        </button>
        {volume ? (
          <button
            type="button"
            onClick={() => downloadCsv(`volume_${label.replace(/[^a-zA-Z0-9._-]+/g, "_")}.csv`, volumeCsvRows(volume, label))}
          >
            Export volume CSV
          </button>
        ) : null}
      </div>
      {error ? <p className="hint">Error: {error}</p> : null}
      {noVolume ? <p className="hint">No volume maps found in this run (needs map X/Y and several depth levels).</p> : null}

      {volume && figs ? (
        <>
          <div className="row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "flex-end", marginTop: "10px" }}>
            <label className="inline">
              Mask: a ≥
              <input style={{ width: "80px" }} value={maskMin} onChange={(e) => setMaskMin(e.target.value)} placeholder="min" />
            </label>
            <label className="inline">
              a ≤
              <input style={{ width: "80px" }} value={maskMax} onChange={(e) => setMaskMax(e.target.value)} placeholder="max" />
            </label>
            <label className="inline" title="z' = (z − offset) × scale. Offset sets the surface to 0; scale is e.g. a refractive-index factor (off by default).">
              Depth offset (µm)
              <input style={{ width: "70px" }} value={zOffset} onChange={(e) => setZOffset(e.target.value)} />
            </label>
            <label className="inline">
              Depth scale
              <input style={{ width: "60px" }} value={zScale} onChange={(e) => setZScale(e.target.value)} />
            </label>
            <label className="inline">
              <input type="checkbox" checked={sharedScale} onChange={(e) => setSharedScale(e.target.checked)} /> Shared colour scale
            </label>
          </div>

          {portalTarget
            ? createPortal(
                <div style={{ marginTop: "14px" }}>
                  <div className="section-title">
                    Volume: {label} ({file.split(/[\/]/).pop()})
                  </div>
          <div className="row" style={{ gap: "6px", marginTop: "10px" }}>
            {(
              [
                ["slices", "Slices + depth profile"],
                ["montage", "Montage of layers"],
                ["stack", "3D stack of heatmaps"],
              ] as Array<[ViewTab, string]>
            ).map(([id, text]) => (
              <button key={id} type="button" className={tab === id ? "mini active" : "mini"} onClick={() => setTab(id)}>
                {text}
              </button>
            ))}
          </div>

          {tab === "slices" ? (
            <>
              <div className="row" style={{ flexWrap: "wrap", gap: "10px", alignItems: "flex-end", marginTop: "10px" }}>
                <label className="inline">
                  XY view
                  <select value={xyMode} onChange={(e) => setXyMode(e.target.value as XyMode)}>
                    {(Object.keys(XY_MODE_LABEL) as XyMode[]).map((m) => (
                      <option key={m} value={m}>
                        {XY_MODE_LABEL[m]}
                      </option>
                    ))}
                  </select>
                </label>
                {xyMode === "slice" ? (
                  <>
                    <label className="inline">
                      Depth z (µm)
                      <select value={cross.zi} onChange={(e) => setPoint({ zi: Number(e.target.value) })}>
                        {volume.zs.map((z, i) => (
                          <option key={i} value={i}>
                            {z.toFixed(1)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <input
                      type="range"
                      min={0}
                      max={Math.max(0, nz - 1)}
                      value={cross.zi}
                      onChange={(e) => setPoint({ zi: Number(e.target.value) })}
                      aria-label="Depth layer"
                    />
                    <button type="button" className="mini" onClick={() => setPlaying((p) => !p)}>
                      {playing ? "Pause" : "Play layers"}
                    </button>
                  </>
                ) : (
                  <>
                    <label className="inline">
                      Slab from
                      <select value={slab[0]} onChange={(e) => setSlab([Number(e.target.value), slab[1]])}>
                        {volume.zs.map((z, i) => (
                          <option key={i} value={i}>
                            {z.toFixed(1)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="inline">
                      to
                      <select value={slab[1]} onChange={(e) => setSlab([slab[0], Number(e.target.value)])}>
                        {volume.zs.map((z, i) => (
                          <option key={i} value={i}>
                            {z.toFixed(1)}
                          </option>
                        ))}
                      </select>
                    </label>
                  </>
                )}
                <label className="inline" title="0 = single point; 1 = 3 × 3 cells; …">
                  ROI radius (cells)
                  <input
                    type="number"
                    min={0}
                    max={20}
                    style={{ width: "60px" }}
                    value={roiRadius}
                    onChange={(e) => setRoiRadius(Math.max(0, Math.floor(Number(e.target.value) || 0)))}
                  />
                </label>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: "10px", marginTop: "10px" }}>
                <FigureCard id="volume_xy" fig={figs.xy} onClick={onXyClick} />
                <FigureCard id="volume_xz" fig={figs.xz} onClick={onXzClick} />
                <FigureCard id="volume_yz" fig={figs.yz} onClick={onYzClick} />
                <FigureCard id="volume_depth_profile" fig={figs.prof} onClick={onProfileClick} />
              </div>
              <div className="row" style={{ gap: "8px", marginTop: "8px", alignItems: "center" }}>
                <button type="button" onClick={overlayRoiSpectra}>
                  Show spectra of ROI at this depth
                </button>
                {spectraMsg ? <span className="hint">{spectraMsg}</span> : null}
              </div>
              {spectraFig ? <FigureCard id="volume_roi_spectra" fig={spectraFig} /> : null}
            </>
          ) : null}

          {tab === "montage" ? (
            <>
              <div className="row" style={{ gap: "10px", alignItems: "flex-end", marginTop: "10px" }}>
                <label className="inline">
                  Layers shown
                  <input type="number" min={1} max={60} style={{ width: "60px" }} value={montageLayers} onChange={(e) => setMontageLayers(Math.max(1, Number(e.target.value) || 1))} />
                </label>
                <label className="inline">
                  Columns
                  <input type="number" min={1} max={10} style={{ width: "60px" }} value={montageCols} onChange={(e) => setMontageCols(Math.max(1, Number(e.target.value) || 1))} />
                </label>
              </div>
              <FigureCard id="volume_montage" fig={figs.montage} onClick={onMontageClick} height={Math.max(380, Math.ceil(Math.min(montageLayers, nz) / Math.max(1, montageCols)) * 170 + 60)} />
            </>
          ) : null}

          {tab === "stack" ? (
            <>
              <div className="row" style={{ gap: "10px", alignItems: "flex-end", marginTop: "10px" }}>
                <label className="inline">
                  Layers shown
                  <input type="number" min={1} max={60} style={{ width: "60px" }} value={stackLayers} onChange={(e) => setStackLayers(Math.max(1, Number(e.target.value) || 1))} />
                </label>
                <label className="inline">
                  Opacity
                  <input type="range" min={0.1} max={1} step={0.05} value={stackOpacity} onChange={(e) => setStackOpacity(Number(e.target.value))} />
                </label>
                <label className="inline">
                  <input type="checkbox" checked={reverseZ} onChange={(e) => setReverseZ(e.target.checked)} /> Reverse depth axis
                </label>
              </div>
              <p className="hint">
                Each plane is one depth layer drawn at its own z. Lower the opacity or show fewer layers to see through the stack.
              </p>
              <FigureCard id="volume_stack" fig={figs.stack} height={560} />
            </>
          ) : null}
                </div>,
                portalTarget
              )
            : null}
        </>
      ) : null}
    </div>
  );
}
