import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createReference, deleteReference, importReference, listReferences } from "./api";
import type { FitPreviewInput } from "./fitInputs";

type Props = {
  inputs: FitPreviewInput[];
  /** Provenance of the preview spectra (session, pipeline steps before the fitting step). */
  provenance: Record<string, unknown>;
};

/** M1: per-user library of measured reference spectra (save from the fitting preview, import text, delete). */
export function ReferenceLibraryPanel({ inputs, provenance }: Props) {
  const qc = useQueryClient();
  const refsQ = useQuery({ queryKey: ["references"], queryFn: () => listReferences() });
  const [sid, setSid] = useState("");
  const [name, setName] = useState("");
  const [xMin, setXMin] = useState("");
  const [xMax, setXMax] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const chosen = inputs.find((i) => i.spectrum_id === sid) ?? inputs[0];

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg(ok);
      await qc.invalidateQueries({ queryKey: ["references"] });
    } catch (e) {
      setMsg(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <details data-testid="reference-library" style={{ fontSize: 12 }}>
      <summary style={{ cursor: "pointer", fontWeight: 700 }}>Reference spectra library ({refsQ.data?.count ?? 0})</summary>
      <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
        <div className="hint" style={{ margin: 0 }}>
          Measured spectra used as <b>Reference spectrum</b> components (CasaXPS linear least squares). Save them already
          calibrated and background-subtracted; each is stored normalised to unit area.
        </div>
        <div className="row" style={{ gap: 6, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="inline">
            Preview spectrum
            <select value={chosen?.spectrum_id ?? ""} onChange={(e) => setSid(e.target.value)} disabled={!inputs.length}>
              {inputs.length ? null : <option value="">run the fitting preview first</option>}
              {inputs.map((i) => (
                <option key={i.spectrum_id} value={i.spectrum_id}>
                  {i.spectrum_id}
                </option>
              ))}
            </select>
          </label>
          <label className="inline">
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. CoO standard" style={{ width: 140 }} />
          </label>
          <label className="inline">
            from
            <input type="number" value={xMin} onChange={(e) => setXMin(e.target.value)} placeholder="min" style={{ width: 64 }} />
          </label>
          <label className="inline">
            to
            <input type="number" value={xMax} onChange={(e) => setXMax(e.target.value)} placeholder="max" style={{ width: 64 }} />
          </label>
          <button
            type="button"
            className="mini"
            data-testid="reference-save"
            disabled={busy || !chosen || !name.trim()}
            onClick={() =>
              void run(
                () =>
                  createReference({
                    name: name.trim(),
                    x: chosen!.x,
                    y: chosen!.y,
                    x_min: xMin === "" ? null : Number(xMin),
                    x_max: xMax === "" ? null : Number(xMax),
                    source: { ...provenance, spectrum_id: chosen!.spectrum_id, stage: "input of the fitting step" },
                  }),
                `Saved "${name.trim()}"`
              )
            }
          >
            Save as reference
          </button>
          <label className="mini" style={{ cursor: "pointer" }} title="Two columns: energy, intensity">
            Import text…
            <input
              type="file"
              accept=".txt,.csv,.dat,.xy"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                void f.text().then((content) =>
                  run(() => importReference({ name: name.trim() || f.name, content, filename: f.name }), `Imported ${f.name}`)
                );
                e.target.value = "";
              }}
            />
          </label>
        </div>
        {msg ? <div className="hint">{msg}</div> : null}
        <table className="table" style={{ fontSize: 12 }}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Range</th>
              <th>Source</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(refsQ.data?.items ?? []).map((r) => (
              <tr key={r.reference_id}>
                <td title={r.reference_id}>{r.name}</td>
                <td>
                  {r.x_min?.toFixed(1)} – {r.x_max?.toFixed(1)}
                </td>
                <td className="hint">{String(r.source?.kind ?? "")}</td>
                <td>
                  <button
                    type="button"
                    className="mini danger"
                    disabled={busy}
                    onClick={() => {
                      if (window.confirm(`Delete reference "${r.name}"? Fits that use it will fail.`)) {
                        void run(() => deleteReference(r.reference_id), `Deleted "${r.name}"`);
                      }
                    }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
