import { useState } from "react";
import { DraftNumberInput } from "../lib/draftInputs";
import { ComponentOptionsEditor } from "./ComponentOptionsEditor";
import { SpinOrbitPartnerControl } from "./SpinOrbitPartnerControl";
import type { FittingComponentSpecPublic } from "./api";
import {
  PEAK_TYPE_LABELS,
  changeFittingComponentType,
  copyFittingComponent,
  isPeakComponentType,
  type FittingEditorParams,
} from "./fittingUtils";
import {
  BASELINE_LIKE,
  addSatellite,
  deleteComponent,
  hasExpression,
  setRowField,
  tieCandidates,
  tieOf,
  tieParam,
  type TieMode,
} from "./interactiveEdit";
import { adoptDisplayedParams, isFollower, type FitMeta } from "./interactiveFit";

type Props = {
  fp: FittingEditorParams;
  meta: FitMeta;
  ci: number;
  catalog: FittingComponentSpecPublic[] | undefined;
  /** Commit new params (written into the step and redrawn). */
  onChange: (next: FittingEditorParams) => void;
  onSelect: (componentId: string | null) => void;
  /** Suggested satellite placement from the largest residual (offset from the parent, area ratio), when known. */
  satelliteHint?: (parentCi: number) => { offset: number; ratio: number } | null;
};

const TIE_LABEL: Record<TieMode, string> = { none: "Free", equal: "Equal to", offset: "Offset from", area_ratio: "Area ratio to" };

function fmt(v: number): string {
  if (!Number.isFinite(v)) return "";
  const a = Math.abs(v);
  return a >= 1000 || (a > 0 && a < 0.01) ? v.toPrecision(5) : String(Math.round(v * 10000) / 10000);
}

/** Small card for the selected component: values, lock, bounds, tie to another peak, shape, options, partner, satellite. */
export function ComponentInspector({ fp, meta, ci, catalog, onChange, onSelect, satelliteHint }: Props) {
  const comp = fp.components[ci];
  const [sat, setSat] = useState<{ offset: string; ratio: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!comp) return null;
  const id = comp.component_id;
  const ct = String(comp.component_type);
  const isPeak = isPeakComponentType(ct);
  const isBg = BASELINE_LIKE.has(ct) || ct.endsWith("_bg");
  // Show the drawn (fitted) values, as the handles do; the first edit adopts them.
  const shown = adoptDisplayedParams(fp, meta);
  const rows = shown.components[ci]!.rows;
  const peakTypes = (catalog ?? []).map((c) => c.component_type).filter((t) => isPeakComponentType(t));

  const apply = (next: FittingEditorParams) => {
    setErr(null);
    onChange(next);
  };

  function openSat() {
    const hint = satelliteHint?.(ci);
    setSat({ offset: hint ? String(Math.round(hint.offset * 100) / 100) : "", ratio: hint ? String(Math.round(hint.ratio * 1000) / 1000) : "" });
  }

  function createSat() {
    try {
      const o = Number(sat?.offset);
      const r = Number(sat?.ratio);
      if (!Number.isFinite(o) || !Number.isFinite(r)) throw new Error("enter the offset (eV) and the area ratio");
      const res = addSatellite(fp, meta, ci, { offset: o, ratio: r });
      apply(res.fp);
      onSelect(res.component_id);
      setSat(null);
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    }
  }

  return (
    <div className="card-inner" data-testid="component-inspector" style={{ display: "grid", gap: 6, fontSize: 12, alignContent: "start" }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <b>{id}</b>
        <span className="row" style={{ gap: 4 }}>
          <button type="button" className="mini" title="Duplicate this component" onClick={() => apply(copyFittingComponent(shown, ci))}>
            Duplicate
          </button>
          <button
            type="button"
            className="mini danger"
            data-testid="inspector-delete"
            title="Delete this component (its ties are removed)"
            onClick={() => {
              apply(deleteComponent(shown, ci));
              onSelect(null);
            }}
          >
            Delete
          </button>
          <button type="button" className="mini" title="Close" onClick={() => onSelect(null)}>
            ✕
          </button>
        </span>
      </div>
      {isPeak ? (
        <label className="inline" style={{ justifyContent: "space-between", margin: 0 }}>
          Shape
          <select
            value={ct}
            onChange={(e) => apply(changeFittingComponentType(shown, ci, e.target.value as never, catalog))}
            data-testid="inspector-shape"
          >
            {peakTypes.map((t) => (
              <option key={t} value={t}>
                {PEAK_TYPE_LABELS[t as keyof typeof PEAK_TYPE_LABELS] ?? t}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <div className="hint" style={{ margin: 0 }}>
          {ct}
          {isBg ? " (background)" : ""}
        </div>
      )}
      <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th align="left">Param</th>
            <th align="right">Value</th>
            <th title="Keep this value fixed in the fit">Fix</th>
            <th>min</th>
            <th>max</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const follower = isFollower(shown, id, r.key);
            const expr = hasExpression(shown, id, r.key);
            const tie = tieOf(shown, id, r.key);
            const cands = tieCandidates(shown, id, r.key);
            const tieModes: TieMode[] = r.key === "amp" ? ["none", "equal", "offset", "area_ratio"] : ["none", "equal", "offset"];
            return (
              <tr key={r.key} data-testid={`inspector-row-${r.key}`}>
                <td title={r.label}>{r.key}</td>
                <td align="right">
                  <DraftNumberInput
                    value={Number.isFinite(r.p0) ? fmt(r.p0) : ""}
                    disabled={follower}
                    onChange={(n) => n != null && apply(setRowField(fp, meta, ci, r.key, { p0: n, auto: false }))}
                    style={{ width: 70 }}
                  />
                </td>
                <td align="center">
                  <input
                    type="checkbox"
                    checked={r.vary === false}
                    disabled={follower}
                    onChange={(e) => apply(setRowField(fp, meta, ci, r.key, { vary: !e.target.checked }))}
                  />
                </td>
                <td>
                  <DraftNumberInput nullable value={r.lower ?? ""} disabled={follower} onChange={(n) => apply(setRowField(fp, meta, ci, r.key, { lower: n }))} style={{ width: 52 }} />
                </td>
                <td>
                  <DraftNumberInput nullable value={r.upper ?? ""} disabled={follower} onChange={(n) => apply(setRowField(fp, meta, ci, r.key, { upper: n }))} style={{ width: 52 }} />
                </td>
                {expr ? (
                  <td colSpan={1} className="hint" title="Defined by an expression: edit it in the form below">
                    ƒ
                  </td>
                ) : cands.length || tie.mode !== "none" ? (
                  <td style={{ whiteSpace: "nowrap" }}>
                    <select
                      value={tie.mode}
                      title="Tie this parameter to another component"
                      data-testid={`tie-mode-${r.key}`}
                      onChange={(e) => {
                        const mode = e.target.value as TieMode;
                        const driver = tie.driver || cands[0] || "";
                        apply(tieParam(fp, meta, id, r.key, mode, driver));
                      }}
                    >
                      {tieModes.map((m) => (
                        <option key={m} value={m}>
                          {TIE_LABEL[m]}
                        </option>
                      ))}
                    </select>
                    {tie.mode !== "none" ? (
                      <>
                        <select value={tie.driver} onChange={(e) => apply(tieParam(fp, meta, id, r.key, tie.mode, e.target.value, tie.value))}>
                          {[...new Set([tie.driver, ...cands])].filter(Boolean).map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ))}
                        </select>
                        {tie.value != null ? (
                          <DraftNumberInput
                            value={fmt(tie.value)}
                            onChange={(n) => n != null && apply(tieParam(fp, meta, id, r.key, tie.mode, tie.driver, n))}
                            style={{ width: 54 }}
                            title={tie.mode === "offset" ? "Offset (same unit as the parameter)" : "Area ratio"}
                          />
                        ) : null}
                      </>
                    ) : null}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
      {isBg || ct === "reference_spectrum" ? <ComponentOptionsEditor fp={shown} ci={ci} onApply={apply} /> : null}
      {isPeak ? (
        <div style={{ display: "grid", gap: 4 }}>
          <SpinOrbitPartnerControl fp={shown} componentId={id} fittingCatalog={catalog} onApply={apply} />
          <details open={sat != null} onToggle={(e) => (e.currentTarget.open ? sat == null && openSat() : setSat(null))}>
            <summary style={{ cursor: "pointer" }} title="Shake-up or other satellite tied to this peak by offset and area ratio">
              Satellite…
            </summary>
            {sat ? (
              <div className="row" style={{ gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 4 }}>
                <label className="inline" style={{ margin: 0 }}>
                  Offset (eV)
                  <input value={sat.offset} onChange={(e) => setSat({ ...sat, offset: e.target.value })} style={{ width: 60 }} data-testid="sat-offset" />
                </label>
                <label className="inline" style={{ margin: 0 }}>
                  Area ratio
                  <input value={sat.ratio} onChange={(e) => setSat({ ...sat, ratio: e.target.value })} style={{ width: 60 }} data-testid="sat-ratio" />
                </label>
                <button type="button" className="mini" onClick={createSat} data-testid="sat-add">
                  Add satellite
                </button>
                <span className="hint" style={{ margin: 0 }}>
                  prefilled from the largest residual when there is one
                </span>
              </div>
            ) : null}
          </details>
        </div>
      ) : null}
      {err ? <div className="err">{err}</div> : null}
    </div>
  );
}
