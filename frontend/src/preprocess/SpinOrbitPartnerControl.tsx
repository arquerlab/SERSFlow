import { useState } from "react";
import { postSpinOrbitPartner } from "./api";
import { flattenFittingForPipeline, migrateFittingParamsToEditor, type FittingEditorParams } from "./fittingUtils";
import { guessSubshell, isLowJComponentId, SUBSHELL_LABELS, type Subshell } from "./spinOrbit";

type Props = {
  fp: FittingEditorParams;
  componentId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  fittingCatalog: any;
  onApply: (next: FittingEditorParams) => void;
};

/** F3 "Create x 2" for one peak: adds the spin-orbit partner with offset, FWHM, shape and area-ratio links. */
export function SpinOrbitPartnerControl({ fp, componentId, fittingCatalog, onApply }: Props) {
  const [subshell, setSubshell] = useState<Subshell>(() => guessSubshell(componentId, fp.xps_region) ?? "p");
  const [splitting, setSplitting] = useState("");
  const [fwhmRatio, setFwhmRatio] = useState("");
  const [lockArea, setLockArea] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  if (!componentId || isLowJComponentId(componentId)) return null;
  const split = Number(splitting);
  const ratio = fwhmRatio.trim() ? Number(fwhmRatio) : null;
  const valid = Number.isFinite(split) && split > 0 && (ratio == null || (Number.isFinite(ratio) && ratio > 0));

  async function add() {
    setBusy(true);
    setMsg(null);
    try {
      const resp = await postSpinOrbitPartner({
        params: flattenFittingForPipeline(fp) as Record<string, unknown>,
        component_id: componentId,
        splitting_eV: split,
        subshell,
        lock_area: lockArea,
        fwhm_ratio: ratio,
      });
      onApply({ ...migrateFittingParamsToEditor(resp.params, fittingCatalog) });
      setMsg(`Added ${resp.partner_id}`);
    } catch (e) {
      setMsg(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <details data-testid="so-partner-control" style={{ fontSize: 12 }}>
      <summary style={{ cursor: "pointer" }} title="CasaXPS 'Create x 2': add the other spin-orbit member of this peak">
        Spin-orbit partner…
      </summary>
      <div style={{ display: "grid", gap: 4, marginTop: 4 }}>
        <label className="inline" style={{ justifyContent: "space-between" }}>
          Subshell
          <select value={subshell} onChange={(e) => setSubshell(e.target.value as Subshell)}>
            {(Object.keys(SUBSHELL_LABELS) as Subshell[]).map((s) => (
              <option key={s} value={s}>
                {SUBSHELL_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="inline" style={{ justifyContent: "space-between" }}>
          Splitting (eV)
          <input
            type="number"
            step="0.01"
            min={0}
            placeholder="e.g. 15.0"
            value={splitting}
            onChange={(e) => setSplitting(e.target.value)}
            style={{ width: 80 }}
            title="Binding energy of the low-j member minus this peak (element and chemical-state specific)"
          />
        </label>
        <label className="inline" style={{ justifyContent: "space-between" }}>
          FWHM ratio
          <input
            type="number"
            step="0.01"
            min={0}
            placeholder="equal"
            value={fwhmRatio}
            onChange={(e) => setFwhmRatio(e.target.value)}
            style={{ width: 80 }}
            title="Partner FWHM / this FWHM; empty = equal. Ti/V 2p1/2 are ~2x broader (Coster-Kronig)"
          />
        </label>
        <label className="inline">
          <input type="checkbox" checked={lockArea} onChange={(e) => setLockArea(e.target.checked)} />
          Lock area ratio
        </label>
        <button type="button" className="mini" disabled={!valid || busy} onClick={() => void add()}>
          {busy ? "Adding…" : "Add partner"}
        </button>
        {msg ? <div className="hint">{msg}</div> : null}
      </div>
    </details>
  );
}
