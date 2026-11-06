import { useQuery } from "@tanstack/react-query";
import { listReferences } from "./api";
import type { FittingComponentEditor, FittingEditorParams } from "./fittingUtils";
import { TOUGAARD_PRESETS } from "./fitInputs";

type Props = {
  fp: FittingEditorParams;
  ci: number;
  onApply: (next: FittingEditorParams) => void;
};

const AVG_TYPES = new Set(["shirley_bg", "linear_bg"]);

/** B1 / L1 / M1 options of one component: Av Width + offsets, SB source peak, reference spectrum, Tougaard presets. */
export function ComponentOptionsEditor({ fp, ci, onApply }: Props) {
  const comp = fp.components[ci]!;
  const ct = String(comp.component_type);
  const opts = comp.options ?? {};
  const refsQ = useQuery({ queryKey: ["references"], queryFn: () => listReferences(), enabled: ct === "reference_spectrum" });

  function setOpts(patch: Record<string, unknown>) {
    const next = { ...opts, ...patch };
    for (const [k, v] of Object.entries(next)) if (v === undefined || v === null || v === "") delete next[k];
    const comps = fp.components.slice();
    comps[ci] = { ...comp, options: Object.keys(next).length ? next : undefined } as FittingComponentEditor;
    onApply({ ...fp, components: comps });
  }

  function applyPreset(values: Record<string, number>) {
    const comps = fp.components.slice();
    comps[ci] = { ...comp, rows: comp.rows.map((r) => (r.key in values ? { ...r, p0: values[r.key]! } : r)) };
    onApply({ ...fp, components: comps });
  }

  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? String(v) : "");

  if (AVG_TYPES.has(ct)) {
    return (
      <div data-testid="bg-endpoint-options" style={{ display: "grid", gap: 4, fontSize: 12 }}>
        <label className="inline" style={{ justifyContent: "space-between" }} title="CasaXPS Av Width: channels averaged on each side of the region ends (empty = auto)">
          Av Width (± channels)
          <input
            type="number"
            min={0}
            placeholder="auto"
            value={num(opts.avg_width)}
            onChange={(e) => setOpts({ avg_width: e.target.value === "" ? undefined : Math.max(0, Math.floor(Number(e.target.value))) })}
            style={{ width: 70 }}
          />
        </label>
        <label className="inline" style={{ justifyContent: "space-between" }} title="Lower the background at the low-x (low BE) end by this percent">
          Offset low end (%)
          <input
            type="number"
            step="0.5"
            placeholder="0"
            value={num(opts.offset_low_pct)}
            onChange={(e) => setOpts({ offset_low_pct: e.target.value === "" ? undefined : Number(e.target.value) })}
            style={{ width: 70 }}
          />
        </label>
        <label className="inline" style={{ justifyContent: "space-between" }} title="Lower the background at the high-x (high BE) end by this percent">
          Offset high end (%)
          <input
            type="number"
            step="0.5"
            placeholder="0"
            value={num(opts.offset_high_pct)}
            onChange={(e) => setOpts({ offset_high_pct: e.target.value === "" ? undefined : Number(e.target.value) })}
            style={{ width: 70 }}
          />
        </label>
      </div>
    );
  }
  if (ct === "shirley_of_bg") {
    const peaks = fp.components.filter((c, j) => j !== ci && c.component_id && !String(c.component_type).endsWith("_bg"));
    return (
      <label className="inline" style={{ justifyContent: "space-between", fontSize: 12 }} title="CasaXPS SB(0)X: Shirley profile of this peak">
        Shirley of peak
        <select value={String(opts.of ?? "")} onChange={(e) => setOpts({ of: e.target.value || undefined })}>
          <option value="">— choose —</option>
          {peaks.map((p) => (
            <option key={p.component_id} value={p.component_id}>
              {p.component_id}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (ct === "reference_spectrum") {
    const items = refsQ.data?.items ?? [];
    return (
      <div style={{ display: "grid", gap: 4, fontSize: 12 }}>
        <label className="inline" style={{ justifyContent: "space-between" }}>
          Reference
          <select
            data-testid="reference-select"
            value={String(opts.reference_id ?? "")}
            onChange={(e) => {
              const r = items.find((it) => it.reference_id === e.target.value);
              setOpts({ reference_id: r?.reference_id, reference_sha256: r?.sha256 });
            }}
          >
            <option value="">— choose —</option>
            {items.map((r) => (
              <option key={r.reference_id} value={r.reference_id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        {!items.length ? <span className="hint">No references yet: save one from the library panel below.</span> : null}
      </div>
    );
  }
  if (ct === "tougaard_bg" || ct === "tougaard_u4_bg") {
    return (
      <div className="row" style={{ gap: 4, flexWrap: "wrap", fontSize: 12 }}>
        {TOUGAARD_PRESETS.map((p) => (
          <button key={p.id} type="button" className="mini" title={p.label} onClick={() => applyPreset(p.values)}>
            {p.id.toUpperCase()} preset
          </button>
        ))}
        <span className="hint" style={{ margin: 0 }}>
          U3/U4: enter B, C, C' (−1), D, T0 yourself
        </span>
      </div>
    );
  }
  return null;
}
