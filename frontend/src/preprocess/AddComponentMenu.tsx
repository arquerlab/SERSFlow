import { useEffect, useMemo, useState } from "react";
import {
  applyFittingRecipe,
  listFittingRecipeIndex,
  postFittingFit,
  type FittingComponentSpecPublic,
  type FittingRecipeIndexItem,
} from "./api";
import { appendRecipeApplyIntoEditor } from "./FittingRecipePicker";
import {
  defaultRowsForComponent,
  flattenFittingForPipeline,
  isPeakComponentType,
  uniqueComponentIdAgainst,
  type FittingEditorParams,
} from "./fittingUtils";
import { BACKGROUND_CHOICES, BASELINE_LIKE, addBackground, addSatellite, shiftGroup } from "./interactiveEdit";
import { addPeak, adoptDisplayedParams, buildFitRequest, maxResidualPoint, peakHandles, type FitMeta, type NewPeakShape } from "./interactiveFit";
import { SpinOrbitPartnerControl } from "./SpinOrbitPartnerControl";

export type CommitOpts = { select?: string; refit?: boolean; note?: string };

type Props = {
  fp: FittingEditorParams;
  meta: FitMeta;
  catalog: FittingComponentSpecPublic[] | undefined;
  technique: string;
  /** Component currently selected in the inspector (default for parent-peak pickers). */
  selectedId: string | null;
  onCommit: (next: FittingEditorParams, opts?: CommitOpts) => void | Promise<void>;
  onClose: () => void;
};

type Kind = "peak" | "background" | "doublet" | "multiplet" | "satellite" | "other";
const KINDS: Array<{ id: Kind; label: string; hint: string }> = [
  { id: "peak", label: "Peak", hint: "A new peak at the largest residual, or at an energy you choose" },
  { id: "background", label: "Background", hint: "Shirley, Tougaard, linear, erfc step, ... (active, fitted with the peaks)" },
  { id: "doublet", label: "Doublet partner", hint: "The other spin-orbit member of a peak (2p, 3d, 4f) with the locked area ratio" },
  { id: "multiplet", label: "Library multiplet", hint: "Peaks of a library compound fit (e.g. Co3O4) placed at an energy, with their locked ratios" },
  { id: "satellite", label: "Satellite", hint: "A shake-up peak tied to a main peak by offset and area ratio" },
  { id: "other", label: "Other", hint: "Fermi edge, reference spectrum and the remaining component types" },
];

/** Height of the data above the model at ``x`` (nearest point), floored at 5 % of the data range. */
function residualAt(meta: FitMeta, x: number): number {
  let best = 0;
  let bd = Infinity;
  for (let i = 0; i < meta.x.length; i++) {
    const d = Math.abs(meta.x[i]! - x);
    const r = meta.residual[i];
    if (d < bd && r != null && Number.isFinite(r)) {
      bd = d;
      best = i;
    }
  }
  const r = Number(meta.residual[best] ?? 0);
  const span = Math.max(...meta.y) - Math.min(...meta.y);
  return r > 0 ? r : 0.05 * span;
}

/** One menu for everything that can be added to the model from the plot. */
export function AddComponentMenu({ fp, meta, catalog, technique, selectedId, onCommit, onClose }: Props) {
  const [kind, setKind] = useState<Kind>("peak");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const resid = useMemo(() => maxResidualPoint(meta), [meta]);
  const peaks = fp.components.map((c, ci) => ({ c, ci })).filter(({ c }) => isPeakComponentType(String(c.component_type)));
  const selPeak = peaks.find((p) => p.c.component_id === selectedId) ?? peaks[peaks.length - 1];
  const peakTypes = useMemo(() => (catalog ?? []).map((c) => c.component_type).filter((t) => isPeakComponentType(t)), [catalog]);

  // ---- shared placement (peak and multiplet) ----
  const [place, setPlace] = useState<"residual" | "x">(resid ? "residual" : "x");
  const [xText, setXText] = useState("");
  const placeX = place === "residual" && resid ? resid.x : Number(xText);

  // ---- peak ----
  const [shapeMode, setShapeMode] = useState<"copy" | "shape">(peaks.length ? "copy" : "shape");
  const [shapeType, setShapeType] = useState("gl");
  const [shapeFwhm, setShapeFwhm] = useState("1.5");
  const [copyId, setCopyId] = useState<string>("");
  const copyCi = peaks.find((p) => p.c.component_id === copyId)?.ci ?? selPeak?.ci ?? -1;

  // ---- background ----
  const [bgType, setBgType] = useState("shirley_bg");
  const [sbSource, setSbSource] = useState("");
  const [degree, setDegree] = useState("1");
  const currentBaseline = fp.components.find((c) => BASELINE_LIKE.has(String(c.component_type)));

  // ---- satellite ----
  const [satParent, setSatParent] = useState("");
  const satCi = peaks.find((p) => p.c.component_id === satParent)?.ci ?? selPeak?.ci ?? -1;
  const [satOffset, setSatOffset] = useState("");
  const [satRatio, setSatRatio] = useState("");
  useEffect(() => {
    // prefill from the largest residual: offset from the parent, ratio of its height to the parent's
    if (satCi < 0 || !resid) return;
    const h = peakHandles(meta, fp).find((q) => q.ci === satCi);
    const pos = meta.components.find((m) => m.component_id === fp.components[satCi]?.component_id)?.params.pos;
    if (h && typeof pos === "number" && h.height > 0) {
      setSatOffset(String(Math.round((resid.x - pos) * 100) / 100));
      setSatRatio(String(Math.round((resid.residual / h.height) * 1000) / 1000));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [satCi, kind]);

  // ---- multiplet ----
  const [q, setQ] = useState("");
  const [items, setItems] = useState<FittingRecipeIndexItem[]>([]);
  const [recipeId, setRecipeId] = useState("");
  useEffect(() => {
    if (kind !== "multiplet") return;
    const t = window.setTimeout(() => {
      void listFittingRecipeIndex({ q: q.trim() || undefined, element: undefined, limit: 12 })
        .then((r) => setItems(r.items))
        .catch((e) => setErr(String((e as Error)?.message ?? e)));
    }, 250);
    return () => window.clearTimeout(t);
  }, [kind, q]);

  // ---- other ----
  const otherTypes = useMemo(
    () =>
      (catalog ?? [])
        .map((c) => c.component_type)
        .filter((t) => !isPeakComponentType(t) && !BACKGROUND_CHOICES.some((b) => b.type === t)),
    [catalog]
  );
  const [otherType, setOtherType] = useState("");

  async function run(fn: () => Promise<void> | void) {
    setErr(null);
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  const needX = (): number => {
    if (!Number.isFinite(placeX)) throw new Error("enter the energy to place it at");
    return placeX;
  };

  async function addPeakNow() {
    const x = needX();
    const height = place === "residual" && resid ? resid.residual : residualAt(meta, x);
    const shape: NewPeakShape =
      shapeMode === "copy" && copyCi >= 0
        ? { kind: "copy", ci: copyCi }
        : { kind: "shape", componentType: shapeType, fwhm: Number(shapeFwhm) > 0 ? Number(shapeFwhm) : null };
    let ampPerHeight: number | null = null;
    if (shape.kind === "shape") {
      // Evaluate the new shape alone at unit amplitude to convert the height into its amplitude.
      const probe = addPeak({ ...fp, components: [] }, meta, catalog, { x, height: 1 }, shape, 1);
      const flat = flattenFittingForPipeline(probe.fp) as Record<string, unknown>;
      const one = await postFittingFit({
        ...buildFitRequest(flat, { spectrum_id: "probe", x: meta.x, y: meta.x.map(() => 1) }, { technique, weighting: "none", fit: false }),
        fit_min_x: undefined,
        fit_max_x: undefined,
      });
      const yh = (one.components[0]?.y_hat ?? []).map(Number).filter(Number.isFinite);
      const mx = yh.length ? Math.max(...yh) : 0;
      ampPerHeight = mx > 0 ? 1 / mx : null;
    }
    const { fp: next, component_id } = addPeak(fp, meta, catalog, { x, height }, shape, ampPerHeight);
    await onCommit(next, { select: component_id, note: `Added ${component_id} at ${x.toFixed(2)} (height ${height.toFixed(0)}).` });
  }

  async function addBgNow() {
    if (bgType === "shirley_of_bg" && !sbSource) throw new Error("choose the peak whose Shirley step to use");
    const r = addBackground(fp, meta, catalog, bgType, { sbSource: sbSource || null, degree: Number(degree) || 1 });
    await onCommit(r.fp, {
      select: r.component_id,
      refit: r.needsRefit,
      note: `Added ${r.component_id}${r.replaced ? ` (replaced ${r.replaced})` : ""}${r.needsRefit ? "; refitting to scale it" : ""}.`,
    });
  }

  async function addSatNow() {
    if (satCi < 0) throw new Error("select the main peak");
    const r = addSatellite(fp, meta, satCi, { offset: Number(satOffset), ratio: Number(satRatio) });
    await onCommit(r.fp, { select: r.component_id, note: `Added ${r.component_id}, tied to ${fp.components[satCi]!.component_id}.` });
  }

  async function addMultipletNow() {
    if (!recipeId) throw new Error("pick a library fit first");
    const x = needX();
    const applied = await applyFittingRecipe(recipeId, { include_background: false });
    const base = adoptDisplayedParams(fp, meta);
    const before = new Set(base.components.map((c) => c.component_id));
    const merged = appendRecipeApplyIntoEditor(base, applied, catalog);
    const added = merged.components.filter((c) => !before.has(c.component_id));
    const peaksAdded = added.filter((c) => isPeakComponentType(String(c.component_type)));
    if (!peaksAdded.length) throw new Error("that fit has no peaks to add");
    // The recipe's strongest peak lands at x; the rest keep their separations.
    const lead = peaksAdded.reduce((a, b) => ((b.rows.find((r) => r.key === "amp")?.p0 ?? 0) > (a.rows.find((r) => r.key === "amp")?.p0 ?? 0) ? b : a));
    const leadPos = lead.rows.find((r) => r.key === "pos")?.p0 ?? x;
    const shifted = shiftGroup(merged, { ...meta, fitted: false }, added.map((c) => c.component_id), x - leadPos);
    await onCommit(shifted, { select: lead.component_id, note: `Added ${recipeId} (${peaksAdded.length} peaks) with its main peak at ${x.toFixed(2)}. Refit to optimise.` });
  }

  async function addOtherNow() {
    if (!otherType) throw new Error("choose a component type");
    const used = new Set(fp.components.map((c) => String(c.component_id ?? "").toLowerCase()).filter(Boolean));
    const id = uniqueComponentIdAgainst(otherType.replace(/_.*$/, ""), used);
    const rows = defaultRowsForComponent(otherType as never, 0, catalog);
    const base = adoptDisplayedParams(fp, meta);
    await onCommit(
      { ...base, components: [...base.components, { component_id: id, component_type: otherType as never, degree: 0, rows }] },
      { select: id, note: `Added ${id}. Set its options in the card.` }
    );
  }

  const posControls = (
    <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      <label className="inline" style={{ margin: 0 }}>
        <input type="radio" checked={place === "residual"} disabled={!resid} onChange={() => setPlace("residual")} /> Largest residual{resid ? ` (${resid.x.toFixed(2)})` : " (none)"}
      </label>
      <label className="inline" style={{ margin: 0 }}>
        <input type="radio" checked={place === "x"} onChange={() => setPlace("x")} /> At
        <input value={xText} onChange={(e) => setXText(e.target.value)} onFocus={() => setPlace("x")} style={{ width: 70 }} placeholder="energy" data-testid="add-x" />
      </label>
    </div>
  );

  return (
    <div className="card-inner" data-testid="add-menu" style={{ display: "grid", gap: 8, fontSize: 12, marginBottom: 6 }}>
      <div className="row" style={{ gap: 4, flexWrap: "wrap", alignItems: "center" }}>
        {KINDS.map((k) => (
          <button key={k.id} type="button" className={`mini${kind === k.id ? " active" : ""}`} onClick={() => setKind(k.id)} title={k.hint} data-testid={`add-kind-${k.id}`}>
            {k.label}
          </button>
        ))}
        <button type="button" className="mini" style={{ marginLeft: "auto" }} onClick={onClose}>
          Close
        </button>
      </div>
      <div className="hint" style={{ margin: 0 }}>
        {KINDS.find((k) => k.id === kind)!.hint}
      </div>

      {kind === "peak" ? (
        <div style={{ display: "grid", gap: 6 }}>
          {posControls}
          <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <label className="inline" style={{ margin: 0 }}>
              <input type="radio" checked={shapeMode === "copy"} disabled={!peaks.length} onChange={() => setShapeMode("copy")} /> Copy of
            </label>
            <select value={copyCi >= 0 ? fp.components[copyCi]!.component_id : ""} onChange={(e) => setCopyId(e.target.value)} disabled={shapeMode !== "copy" || !peaks.length}>
              {peaks.map((p) => (
                <option key={p.ci} value={p.c.component_id}>
                  {p.c.component_id} ({p.c.component_type})
                </option>
              ))}
            </select>
            <label className="inline" style={{ margin: 0 }}>
              <input type="radio" checked={shapeMode === "shape"} onChange={() => setShapeMode("shape")} /> New shape
            </label>
            <select value={shapeType} onChange={(e) => setShapeType(e.target.value)} disabled={shapeMode !== "shape"} data-testid="add-shape">
              {(peakTypes.length ? peakTypes : ["gl"]).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <label className="inline" style={{ margin: 0 }}>
              FWHM
              <input type="number" step="0.1" min="0" value={shapeFwhm} onChange={(e) => setShapeFwhm(e.target.value)} disabled={shapeMode !== "shape"} style={{ width: 60 }} />
            </label>
            <button type="button" className="mini" disabled={busy} onClick={() => void run(addPeakNow)} data-testid="add-go-peak">
              Add peak
            </button>
          </div>
        </div>
      ) : null}

      {kind === "background" ? (
        <div style={{ display: "grid", gap: 6 }}>
          <div style={{ display: "grid", gap: 2 }}>
            {BACKGROUND_CHOICES.map((b) => (
              <label key={b.type} className="inline" style={{ margin: 0, gap: 6 }} title={b.hint}>
                <input type="radio" checked={bgType === b.type} onChange={() => setBgType(b.type)} data-testid={`add-bg-${b.type}`} />
                <b style={{ width: 150 }}>{b.label}</b>
                <span className="hint" style={{ margin: 0 }}>{b.hint}</span>
              </label>
            ))}
          </div>
          <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            {bgType === "shirley_of_bg" ? (
              <label className="inline" style={{ margin: 0 }}>
                Peak
                <select value={sbSource} onChange={(e) => setSbSource(e.target.value)}>
                  <option value="">choose…</option>
                  {peaks.map((p) => (
                    <option key={p.ci} value={p.c.component_id}>
                      {p.c.component_id}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {bgType === "polynomial_background" ? (
              <label className="inline" style={{ margin: 0 }}>
                Degree
                <input type="number" min="1" max="6" value={degree} onChange={(e) => setDegree(e.target.value)} style={{ width: 50 }} />
              </label>
            ) : null}
            {BASELINE_LIKE.has(bgType) && currentBaseline ? (
              <span className="hint" style={{ margin: 0 }}>replaces {currentBaseline.component_id}</span>
            ) : null}
            <button type="button" className="mini" disabled={busy} onClick={() => void run(addBgNow)} data-testid="add-go-bg">
              Add background
            </button>
          </div>
        </div>
      ) : null}

      {kind === "doublet" ? (
        <div style={{ display: "grid", gap: 6 }}>
          <label className="inline" style={{ margin: 0 }}>
            Main peak
            <select value={selPeak?.c.component_id ?? ""} onChange={(e) => setCopyId(e.target.value)}>
              {peaks.map((p) => (
                <option key={p.ci} value={p.c.component_id}>
                  {p.c.component_id}
                </option>
              ))}
            </select>
          </label>
          {selPeak ? (
            <SpinOrbitPartnerControl
              key={selPeak.c.component_id}
              fp={adoptDisplayedParams(fp, meta)}
              componentId={selPeak.c.component_id}
              fittingCatalog={catalog}
              onApply={(next) => void onCommit(next, { note: `Added the partner of ${selPeak.c.component_id}.` })}
            />
          ) : (
            <div className="hint">Add a peak first.</div>
          )}
        </div>
      ) : null}

      {kind === "multiplet" ? (
        <div style={{ display: "grid", gap: 6 }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search compound or element (Co3O4, Ni, ...)" data-testid="add-recipe-q" />
          <div style={{ maxHeight: 150, overflow: "auto", display: "grid", gap: 1 }}>
            {items.map((it) => (
              <label key={it.id} className="inline" style={{ margin: 0, gap: 6 }}>
                <input type="radio" checked={recipeId === it.id} onChange={() => setRecipeId(it.id)} />
                {it.label}
              </label>
            ))}
            {!items.length ? <div className="hint">No matching library fits.</div> : null}
          </div>
          {posControls}
          <div className="row" style={{ gap: 8, alignItems: "center" }}>
            <button type="button" className="mini" disabled={busy || !recipeId} onClick={() => void run(addMultipletNow)} data-testid="add-go-multiplet">
              Add multiplet
            </button>
            <span className="hint" style={{ margin: 0 }}>the compound's strongest peak goes at the energy; background is not added</span>
          </div>
        </div>
      ) : null}

      {kind === "satellite" ? (
        <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <label className="inline" style={{ margin: 0 }}>
            Main peak
            <select value={satCi >= 0 ? fp.components[satCi]!.component_id : ""} onChange={(e) => setSatParent(e.target.value)}>
              {peaks.map((p) => (
                <option key={p.ci} value={p.c.component_id}>
                  {p.c.component_id}
                </option>
              ))}
            </select>
          </label>
          <label className="inline" style={{ margin: 0 }}>
            Offset (eV)
            <input value={satOffset} onChange={(e) => setSatOffset(e.target.value)} style={{ width: 60 }} />
          </label>
          <label className="inline" style={{ margin: 0 }}>
            Area ratio
            <input value={satRatio} onChange={(e) => setSatRatio(e.target.value)} style={{ width: 60 }} />
          </label>
          <button type="button" className="mini" disabled={busy || satCi < 0} onClick={() => void run(addSatNow)} data-testid="add-go-satellite">
            Add satellite
          </button>
          <span className="hint" style={{ margin: 0 }}>prefilled from the largest residual</span>
        </div>
      ) : null}

      {kind === "other" ? (
        <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <select value={otherType} onChange={(e) => setOtherType(e.target.value)}>
            <option value="">choose a type…</option>
            {otherTypes.map((t) => (
              <option key={t} value={t}>
                {catalog?.find((c) => c.component_type === t)?.display_name ?? t}
              </option>
            ))}
          </select>
          <button type="button" className="mini" disabled={busy || !otherType} onClick={() => void run(addOtherNow)} data-testid="add-go-other">
            Add
          </button>
        </div>
      ) : null}
      {err ? <div className="err">{err}</div> : null}
    </div>
  );
}
