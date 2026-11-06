import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { PlotlyWrapper } from "../legacy-wrappers/PlotlyWrapper";
import { postFittingFit, type FittingComponentSpecPublic } from "./api";
import { buildFitResidualFigure } from "./fitResidualPlot";
import { flattenFittingForPipeline, type FittingEditorParams } from "./fittingUtils";
import type { FitPreviewInput } from "./fitInputs";
import {
  baselineAt,
  buildFitRequest,
  dragPeak,
  maxResidualPoint,
  peakHandles,
  setWindow,
  setWindowEdge,
  type DragKind,
  type FitMeta,
  type PeakHandle,
} from "./interactiveFit";
import { backgroundHandles, dragBackground, groupAnchor, recipeGroups, shiftGroup, type BgHandle } from "./interactiveEdit";
import { AddComponentMenu, type CommitOpts } from "./AddComponentMenu";
import { ComponentInspector } from "./ComponentInspector";

export type FitEntry = {
  data: Record<string, unknown>[];
  layout: Record<string, unknown>;
  spectrum_id?: string;
  fit_meta?: FitMeta;
};

/** Evaluate the editor's current values on one spectrum (no optimiser) and return the redrawn figure entry. */
export async function evaluateFitEntry(
  fp: FittingEditorParams,
  input: FitPreviewInput,
  prev: FitMeta,
  technique: string
): Promise<FitEntry> {
  const flat = flattenFittingForPipeline(fp) as Record<string, unknown>;
  const resp = await postFittingFit(buildFitRequest(flat, input, { technique, weighting: fp.weighting ?? "auto", fit: false }));
  const residual =
    resp.residual ??
    input.y.map((yv, i) => {
      const yh = resp.y_hat?.[i];
      return yh == null || !Number.isFinite(Number(yh)) ? null : yv - Number(yh);
    });
  const built = buildFitResidualFigure({
    x: input.x,
    y: input.y,
    yHat: resp.y_hat ?? [],
    residual,
    residualNormalised: resp.residual_normalised ?? null,
    residualView: fp.residual_view ?? "raw",
    components: resp.components ?? [],
    diagnostics: resp.diagnostics,
    title: `${input.spectrum_id} (edited, not refitted)`,
    xAxisTitle: prev.xAxisTitle,
    fillOpacity: Math.max(0, Math.min(1, typeof fp.fill_opacity === "number" ? fp.fill_opacity : 0.15)),
  });
  return {
    ...built,
    spectrum_id: input.spectrum_id,
    fit_meta: {
      x: input.x,
      y: input.y,
      yHat: resp.y_hat ?? [],
      residual,
      components: (resp.components ?? []).map((c) => ({
        component_id: c.component_id,
        component_type: c.component_type,
        params: c.params ?? {},
        area: c.area ?? null,
        y_hat: c.y_hat ?? null,
      })),
      fitted: false,
      fitMin: typeof flat.fit_min_x === "number" ? flat.fit_min_x : null,
      fitMax: typeof flat.fit_max_x === "number" ? flat.fit_max_x : null,
      xAxisTitle: prev.xAxisTitle,
    },
  };
}

type Props = {
  entry: FitEntry;
  fp: FittingEditorParams;
  catalog: FittingComponentSpecPublic[] | undefined;
  technique: string;
  /** Write the edited params into the fitting step. */
  onCommit: (next: FittingEditorParams) => void;
  /** Redraw the figure for edited params (no commit). */
  onEvaluate: (next: FittingEditorParams) => Promise<void>;
  /** Refit from the current values (the normal preview run). */
  onRefit: () => void;
};

type DragState = {
  id: string;
  kind: DragKind | "win-min" | "win-max" | "bg" | "group";
  handle?: PeakHandle;
  bg?: BgHandle;
  group?: string[];
  anchorX?: number;
  fp0: FittingEditorParams;
  meta0: FitMeta;
};

const THROTTLE_MS = 90;

/**
 * X1: the fitting preview with draggable peak handles (position + height at the maximum, width at the half-maximum),
 * draggable fit-window limits, box selection of the window and "add peak at max residual".
 */
export function InteractiveFitFigure({ entry, fp, catalog, technique, onCommit, onEvaluate, onRefit }: Props) {
  const meta = entry.fit_meta;
  const divRef = useRef<HTMLDivElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [tick, setTick] = useState(0);
  const lastSig = useRef("");
  const [editOn, setEditOn] = useState(true);
  const [selecting, setSelecting] = useState(false);
  const [live, setLive] = useState<{ id: string; x: number; y: number } | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const frozen = useRef<{ x: boolean; y: boolean } | null>(null);
  const pending = useRef<FittingEditorParams | null>(null);
  const inFlight = useRef(false);
  const [note, setNote] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const onRefitRef = useRef(onRefit);
  onRefitRef.current = onRefit;

  // Axis geometry lives inside Plotly; poll its signature so the overlay follows zoom, pan and resize.
  useEffect(() => {
    const t = window.setInterval(() => {
      const gd = divRef.current as any;
      const fl = gd?._fullLayout;
      if (!fl?.xaxis || !fl?.yaxis) return;
      const sig = [fl.xaxis.range, fl.yaxis.range, fl.xaxis._offset, fl.yaxis._offset, fl.xaxis._length, fl.yaxis._length, entry.data.length].join("|");
      if (sig !== lastSig.current) {
        lastSig.current = sig;
        setTick((n) => n + 1);
      }
    }, 200);
    return () => window.clearInterval(t);
  }, [entry]);

  const handles = useMemo(() => (meta && editOn ? peakHandles(meta, fp) : []), [meta, fp, editOn]);
  const bgHandles = useMemo(() => (meta && editOn ? backgroundHandles(meta, fp) : []), [meta, fp, editOn]);
  const groups = useMemo(
    () =>
      meta && editOn
        ? recipeGroups(fp)
            .map((g) => ({ ...g, anchor: groupAnchor(meta, g.members) }))
            .filter((g) => g.anchor != null)
        : [],
    [meta, fp, editOn]
  );

  function axes(): { xa: any; ya: any } | null {
    const fl = (divRef.current as any)?._fullLayout;
    return fl?.xaxis && fl?.yaxis ? { xa: fl.xaxis, ya: fl.yaxis } : null;
  }
  const toPx = (x: number, y: number): { px: number; py: number } | null => {
    const a = axes();
    if (!a) return null;
    const px = a.xa._offset + a.xa.l2p(x);
    const py = a.ya._offset + a.ya.l2p(y);
    return Number.isFinite(px) && Number.isFinite(py) ? { px, py } : null;
  };
  const toData = (clientX: number, clientY: number): { x: number; y: number } | null => {
    const a = axes();
    const rect = divRef.current?.getBoundingClientRect();
    if (!a || !rect) return null;
    return { x: a.xa.p2l(clientX - rect.left - a.xa._offset), y: a.ya.p2l(clientY - rect.top - a.ya._offset) };
  };

  // Throttled live re-evaluation while dragging (latest request wins).
  const scheduleEval = useCallback(
    (next: FittingEditorParams) => {
      pending.current = next;
      if (inFlight.current) return;
      inFlight.current = true;
      const pump = async () => {
        while (pending.current) {
          const p = pending.current;
          pending.current = null;
          try {
            await onEvaluate(p);
          } catch (e) {
            setNote(String((e as Error)?.message ?? e));
          }
          await new Promise((r) => window.setTimeout(r, THROTTLE_MS));
        }
        inFlight.current = false;
      };
      void pump();
    },
    [onEvaluate]
  );

  function begin(e: React.PointerEvent, state: Omit<DragState, "fp0" | "meta0">) {
    if (!meta) return;
    e.preventDefault();
    e.stopPropagation();
    try {
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
    } catch {
      // synthetic pointers (tests) cannot be captured; the drag still works through bubbling
    }
    dragRef.current = { ...state, fp0: fp, meta0: meta };
    setNote(null);
    // Freeze the axes while dragging: autoscale would move the plot under the pointer.
    const gd = divRef.current as any;
    const fl = gd?._fullLayout;
    if (fl?.xaxis && fl?.yaxis) {
      frozen.current = { x: !!fl.xaxis.autorange, y: !!fl.yaxis.autorange };
      void Plotly.relayout(gd, {
        "xaxis.range": [...fl.xaxis.range],
        "yaxis.range": [...fl.yaxis.range],
      } as any);
    }
  }

  function unfreeze() {
    const f = frozen.current;
    frozen.current = null;
    if (!f) return;
    window.setTimeout(() => {
      const gd = divRef.current as any;
      if (!gd?._fullLayout) return;
      void Plotly.relayout(gd, { ...(f.x ? { "xaxis.autorange": true } : {}), ...(f.y ? { "yaxis.autorange": true } : {}) } as any);
    }, 500);
  }

  function nextFor(d: DragState, at: { x: number; y: number }): FittingEditorParams {
    if (d.kind === "win-min") return setWindowEdge(d.fp0, d.meta0, "min", at.x);
    if (d.kind === "win-max") return setWindowEdge(d.fp0, d.meta0, "max", at.x);
    if (d.kind === "bg") return dragBackground(d.fp0, d.meta0, d.bg!, at);
    if (d.kind === "group") return shiftGroup(d.fp0, d.meta0, d.group!, at.x - (d.anchorX ?? at.x));
    return dragPeak(d.fp0, d.meta0, d.handle!, d.kind, at);
  }

  function move(e: React.PointerEvent) {
    const d = dragRef.current;
    if (!d) return;
    const at = toData(e.clientX, e.clientY);
    if (!at) return;
    setLive({ id: d.id, ...at });
    scheduleEval(nextFor(d, at));
  }

  function end(e: React.PointerEvent) {
    const d = dragRef.current;
    if (!d) return;
    dragRef.current = null;
    setLive(null);
    const at = toData(e.clientX, e.clientY);
    if (at) {
      const next = nextFor(d, at);
      onCommit(next);
      scheduleEval(next);
    }
    unfreeze();
  }

  // Box selection of the fit window (dragmode "select", horizontal).
  useEffect(() => {
    const gd = divRef.current as any;
    if (!gd || !gd._fullLayout) return;
    void Plotly.relayout(gd, { dragmode: selecting ? "select" : "zoom", selectdirection: "h", ...(selecting ? {} : { selections: [] }) } as any);
  }, [selecting, entry]);

  useEffect(() => {
    if (!selecting || !meta) return;
    const handler = (ev: any) => {
      const r = ev?.range?.x as [number, number] | undefined;
      if (!r || r.length !== 2) return;
      const next = setWindow(fp, meta, r[0], r[1]);
      setSelecting(false);
      if (next !== fp) {
        onCommit(next);
        scheduleEval(next);
      }
    };
    const bind = () => {
      const gd = divRef.current as any;
      if (!gd?.on) return;
      gd.removeListener?.("plotly_selected", handler);
      gd.on("plotly_selected", handler);
    };
    bind();
    const t = window.setInterval(bind, 400); // a full redraw drops listeners
    return () => {
      window.clearInterval(t);
      (divRef.current as any)?.removeListener?.("plotly_selected", handler);
    };
  }, [selecting, meta, fp, onCommit, scheduleEval]);

  const residualPoint = meta ? maxResidualPoint(meta) : null;
  const selCi = selectedId ? fp.components.findIndex((c) => c.component_id === selectedId) : -1;

  /** Write an edit into the step, redraw it, and optionally select the new component / refit afterwards. */
  const commitEdit = useCallback(
    async (next: FittingEditorParams, opts?: CommitOpts) => {
      onCommit(next);
      await onEvaluate(next);
      if (opts?.select !== undefined) setSelectedId(opts.select);
      if (opts?.note) setNote(opts.note);
      else setNote(null);
      if (opts?.refit) window.setTimeout(() => onRefitRef.current(), 500); // after the step state has propagated
    },
    [onCommit, onEvaluate]
  );

  /** Suggested satellite for a parent peak from the largest residual. */
  const satelliteHint = (parentCi: number): { offset: number; ratio: number } | null => {
    if (!meta || !residualPoint) return null;
    const h = peakHandles(meta, fp).find((q) => q.ci === parentCi);
    const pos = meta.components.find((m) => m.component_id === fp.components[parentCi]?.component_id)?.params.pos;
    return h && typeof pos === "number" && h.height > 0 ? { offset: residualPoint.x - pos, ratio: residualPoint.residual / h.height } : null;
  };

  void tick; // overlay positions are recomputed on every render after a geometry change
  const a = axes();
  const winLo = meta ? (meta.fitMin ?? Math.min(...meta.x)) : 0;
  const winHi = meta ? (meta.fitMax ?? Math.max(...meta.x)) : 0;

  return (
    <div data-testid="interactive-fit" style={{ width: "100%" }}>
      <div className="row" style={{ gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 4, fontSize: 12 }}>
        <label className="inline" style={{ margin: 0 }} title="Show draggable handles: peak maximum (position + height) and half-maximum (width)">
          <input type="checkbox" checked={editOn} onChange={(e) => setEditOn(e.target.checked)} data-testid="fit-edit-toggle" /> Edit peaks
        </label>
        <button type="button" className={`mini${selecting ? " active" : ""}`} onClick={() => setSelecting((s) => !s)} disabled={!meta} data-testid="fit-select-window" title="Drag a box on the plot to set the fit window">
          {selecting ? "Drag a box on the plot…" : "Select fit window"}
        </button>
        {fp.fit_min_x != null || fp.fit_max_x != null ? (
          <button type="button" className="mini" onClick={() => { const n = { ...fp, fit_min_x: null, fit_max_x: null }; onCommit(n); scheduleEval(n); }} title="Fit the whole spectrum">
            Clear window
          </button>
        ) : null}
        <button type="button" className={`mini${addOpen ? " active" : ""}`} onClick={() => setAddOpen((o) => !o)} disabled={!meta} data-testid="fit-add-peak" title="Add a peak, background, doublet partner, library multiplet, satellite or other component">
          Add ▾
        </button>
        <button type="button" className="mini" onClick={onRefit} data-testid="fit-refit" title="Refit from the current values">
          Refit
        </button>
        {meta && !meta.fitted ? <span className="hint" style={{ margin: 0 }}>edited — not refitted</span> : null}
      </div>
      {meta && addOpen ? (
        <AddComponentMenu
          fp={fp}
          meta={meta}
          catalog={catalog}
          technique={technique}
          selectedId={selectedId}
          onCommit={commitEdit}
          onClose={() => setAddOpen(false)}
        />
      ) : null}
      {meta ? (
        <div className="row" style={{ gap: 4, flexWrap: "wrap", marginBottom: 4, fontSize: 11 }} data-testid="component-chips">
          {fp.components.map((c) => (
            <button
              key={c.component_id}
              type="button"
              className={`mini${selectedId === c.component_id ? " active" : ""}`}
              onClick={() => setSelectedId(selectedId === c.component_id ? null : c.component_id)}
              title={String(c.component_type)}
              data-testid={`chip-${c.component_id}`}
            >
              {c.component_id}
            </button>
          ))}
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
      <div style={{ flex: "1 1 0", minWidth: 0 }}>
      <div ref={hostRef} style={{ position: "relative", width: "100%", height: 520, minHeight: 520 }}>
        <PlotlyWrapper
          ref={divRef}
          figure={entry as any}
          previousFigure={null}
          plotStyle={{ mode: "overlay", stackSep: 0 }}
          ghostOverlayEnabled={false}
          className="plot"
          preserveView
        />
        {meta && a ? (
          <svg
            data-testid="fit-overlay"
            style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", pointerEvents: "none" }}
            onPointerMove={move}
            onPointerUp={end}
          >
            {/* fit-window limits */}
            {[
              { id: "win-min", x: winLo, kind: "win-min" as const },
              { id: "win-max", x: winHi, kind: "win-max" as const },
            ].map((w) => {
              const px = toPx(live?.id === w.id ? live.x : w.x, a.ya.range[0]);
              if (!px) return null;
              const top = a.ya._offset;
              const bottom = a.ya._offset + a.ya._length;
              return (
                <g key={w.id}>
                  <line x1={px.px} x2={px.px} y1={top} y2={bottom} stroke="#2980b9" strokeWidth={1.5} strokeDasharray="5 3" />
                  <rect
                    x={px.px - 6}
                    y={top}
                    width={12}
                    height={bottom - top}
                    fill="transparent"
                    style={{ pointerEvents: "all", cursor: "ew-resize" }}
                    data-testid={w.id}
                    onPointerDown={(e) => begin(e, { id: w.id, kind: w.kind })}
                    onPointerMove={move}
                    onPointerUp={end}
                  />
                  <rect x={px.px - 5} y={top} width={10} height={14} fill="#2980b9" rx={2} style={{ pointerEvents: "none" }} />
                </g>
              );
            })}
            {handles.map((h) => {
              const mv = h.canMove || h.canHeight;
              const draggedMove = live?.id === `${h.component_id}:move`;
              const draggedWidth = live?.id === `${h.component_id}:width`;
              const p = toPx(draggedMove ? live!.x : h.xMax, draggedMove ? live!.y : h.top);
              const hp = h.halfX != null ? toPx(draggedWidth ? live!.x : h.halfX, h.halfY) : null;
              return (
                <g key={h.component_id}>
                  {p ? (
                    <circle
                      data-testid={`handle-${h.component_id}-move`}
                      cx={p.px}
                      cy={p.py}
                      r={7}
                      fill={mv ? h.color : "#fff"}
                      stroke={mv ? "#fff" : "#999"}
                      strokeWidth={2}
                      style={{ pointerEvents: mv ? "all" : "none", cursor: mv ? "grab" : "default" }}
                      onPointerDown={(e) => {
                        setSelectedId(h.component_id);
                        if (mv) begin(e, { id: `${h.component_id}:move`, kind: "move", handle: h });
                      }}
                      onPointerMove={move}
                      onPointerUp={end}
                    >
                      <title>{`${h.component_id}: drag to move (position) and resize (height)${mv ? "" : " — locked"}`}</title>
                    </circle>
                  ) : null}
                  {hp && h.canWidth ? (
                    <rect
                      data-testid={`handle-${h.component_id}-width`}
                      x={hp.px - 5}
                      y={hp.py - 5}
                      width={10}
                      height={10}
                      fill="#fff"
                      stroke={h.color}
                      strokeWidth={2}
                      style={{ pointerEvents: "all", cursor: "ew-resize" }}
                      onPointerDown={(e) => {
                        setSelectedId(h.component_id);
                        begin(e, { id: `${h.component_id}:width`, kind: "width", handle: h });
                      }}
                      onPointerMove={move}
                      onPointerUp={end}
                    >
                      <title>{`${h.component_id}: drag to change the FWHM`}</title>
                    </rect>
                  ) : null}
                </g>
              );
            })}
            {/* ties: dotted line from a follower peak to its driver */}
            {(fp.param_links ?? [])
              .filter((l) => l.mode !== "expr" && l.source_key === "pos")
              .map((l) => {
                const a = handles.find((h) => h.component_id === l.source_component_id);
                const b = handles.find((h) => h.component_id === l.target_component_id);
                const pa = a && toPx(a.xMax, a.top);
                const pb = b && toPx(b.xMax, b.top);
                return pa && pb ? <line key={`tie-${l.source_component_id}`} x1={pa.px} y1={pa.py} x2={pb.px} y2={pb.py} stroke="#7f8c8d" strokeWidth={1} strokeDasharray="2 3" /> : null;
              })}
            {/* background handles */}
            {bgHandles.map((b) => {
              const dragged = live?.id === b.key;
              const p = toPx(dragged && (b.kind === "edge" || b.kind === "edge-width") ? live!.x : b.x, dragged ? live!.y : b.y);
              if (!p) return null;
              return (
                <rect
                  key={b.key}
                  data-testid={`bg-handle-${b.key}`}
                  x={p.px - 6}
                  y={p.py - 6}
                  width={12}
                  height={12}
                  transform={`rotate(45 ${p.px} ${p.py})`}
                  fill={b.canEdit ? "#7f8c8d" : "#fff"}
                  stroke="#fff"
                  strokeWidth={2}
                  style={{ pointerEvents: b.canEdit ? "all" : "none", cursor: b.kind === "edge-width" ? "ew-resize" : b.kind === "edge" ? "move" : "ns-resize" }}
                  onPointerDown={(e) => {
                    setSelectedId(b.component_id);
                    if (b.canEdit) begin(e, { id: b.key, kind: "bg", bg: b });
                  }}
                  onPointerMove={move}
                  onPointerUp={end}
                >
                  <title>{b.title}</title>
                </rect>
              );
            })}
            {/* recipe groups: one handle to move the whole multiplet */}
            {groups.map((g) => {
              const p = g.anchor ? toPx(live?.id === `grp:${g.id}` ? live.x : g.anchor.x, g.anchor.top) : null;
              if (!p) return null;
              return (
                <g key={`grp-${g.id}`} transform={`translate(${p.px}, ${p.py - 22})`}>
                  <polygon
                    data-testid={`group-handle-${g.id}`}
                    points="0,-8 8,0 0,8 -8,0"
                    fill="#2c3e50"
                    stroke="#fff"
                    strokeWidth={2}
                    style={{ pointerEvents: "all", cursor: "ew-resize" }}
                    onPointerDown={(e) => begin(e, { id: `grp:${g.id}`, kind: "group", group: g.members, anchorX: g.anchor!.x })}
                    onPointerMove={move}
                    onPointerUp={end}
                  >
                    <title>{`${g.id}: drag to move all ${g.members.length} peaks together`}</title>
                  </polygon>
                </g>
              );
            })}
          </svg>
        ) : null}
      </div>
      </div>
      {meta && selCi >= 0 ? (
        <div style={{ flex: "0 0 380px" }}>
          <ComponentInspector fp={fp} meta={meta} ci={selCi} catalog={catalog} onChange={(n) => void commitEdit(n)} onSelect={setSelectedId} satelliteHint={satelliteHint} />
        </div>
      ) : null}
      </div>
      {note ? <div className="hint">{note}</div> : null}
      {meta && editOn ? (
        <div className="hint" style={{ margin: "2px 0 0" }}>
          Drag a ● to move a peak (position) and set its height; a □ changes its width; a ◆ above a multiplet moves all its peaks; grey
          diamonds on a background set its levels (a fixed level takes the dragged value); blue lines set the fit window. Click a handle or
          a name above to edit it in the card. Fixed or linked parameters have no handle; values stay inside their bounds. Edits show the
          model without refitting; use Refit to optimise. Baseline under the first peak: {handles[0] ? baselineAt(meta, handles[0].xMax).toFixed(0) : "–"}.
        </div>
      ) : null}
    </div>
  );
}
