import { useEffect, useState } from "react";
import { DraftNumberInput } from "../lib/draftInputs";
import { TickDropdown } from "./TickDropdown";
import { fetchDatasetFilterFields, type FilterFieldCatalogItem } from "./api";

export type MetadataFilterClause = {
  field: string;
  op: string;
  values?: string[];
  value?: number;
};

type Props = {
  datasetId: string | null;
  params: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
};

function clausesFromParams(params: Record<string, unknown>): MetadataFilterClause[] {
  const raw = params.filters;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((x) => x && typeof x === "object")
    .map((x) => {
      const o = x as Record<string, unknown>;
      return {
        field: String(o.field || ""),
        op: String(o.op || "in"),
        values: Array.isArray(o.values) ? o.values.map(String) : [],
        value: o.value == null ? undefined : Number(o.value),
      };
    });
}

export function MetadataFilterEditor({ datasetId, params, onChange }: Props) {
  const [fields, setFields] = useState<FilterFieldCatalogItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const clauses = clausesFromParams(params);

  useEffect(() => {
    if (!datasetId) {
      setFields([]);
      return;
    }
    let cancelled = false;
    fetchDatasetFilterFields(datasetId)
      .then((res) => {
        if (!cancelled) {
          setFields(res.fields || []);
          setErr(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e?.message ?? e));
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  function setClauses(next: MetadataFilterClause[]) {
    // "keep" = retain spectra matching all clauses (matches editor hint).
    onChange({ ...params, filters: next, action: "keep" });
  }

  function fieldDef(id: string) {
    return fields.find((f) => f.id === id) || null;
  }

  return (
    <div style={{ display: "grid", gap: "10px" }}>
      <div className="hint">
        Mask spectra on this branch (like crop): matches keep their XY; non-matches become empty
        so later steps on this branch ignore them. Use input_from=initial on a later filter to
        restart from the full dataset (e.g. C1s branch then O1s branch). Multiple values in one
        row are OR; rows in one step are AND.
      </div>
      {err ? <div className="error">{err}</div> : null}
      {clauses.map((clause, i) => {
        const def = fieldDef(clause.field);
        return (
          <div key={i} className="row" style={{ gap: "10px", flexWrap: "wrap", alignItems: "flex-start" }}>
            <label className="inline" style={{ margin: 0 }}>
              Filter by
              <select
                value={clause.field}
                onChange={(e) => {
                  const id = e.target.value;
                  const f = fieldDef(id);
                  const next = [...clauses];
                  next[i] = {
                    field: id,
                    op: f?.kind === "numeric" ? ">=" : "in",
                    values: [],
                    value: f?.min,
                  };
                  setClauses(next);
                }}
              >
                <option value="">Select field…</option>
                {fields.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.label}
                  </option>
                ))}
              </select>
            </label>
            {def?.kind === "categorical" ? (
              <TickDropdown
                label="Values"
                options={def.values ?? []}
                selected={clause.values ?? []}
                emptySummary="None selected"
                onChange={(vals) => {
                  const next = [...clauses];
                  next[i] = { ...clause, op: "in", values: vals };
                  setClauses(next);
                }}
              />
            ) : def?.kind === "numeric" ? (
              <span className="row" style={{ gap: "6px", alignItems: "center" }}>
                <select
                  value={clause.op || ">="}
                  onChange={(e) => {
                    const next = [...clauses];
                    next[i] = { ...clause, op: e.target.value };
                    setClauses(next);
                  }}
                >
                  {["=", "!=", ">", ">=", "<", "<="].map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
                <DraftNumberInput
                  value={Number.isFinite(Number(clause.value)) ? Number(clause.value) : def.min ?? 0}
                  onChange={(n) => {
                    if (n == null) return;
                    const next = [...clauses];
                    next[i] = { ...clause, value: n };
                    setClauses(next);
                  }}
                />
                <span className="hint">
                  {def.min != null && def.max != null ? `${def.min}…${def.max}` : ""}
                </span>
              </span>
            ) : null}
            <button
              type="button"
              className="mini danger"
              onClick={() => setClauses(clauses.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </div>
        );
      })}
      <div className="row" style={{ gap: "8px" }}>
        <button
          type="button"
          className="mini"
          disabled={!fields.length}
          onClick={() => {
            const f = fields[0];
            if (!f) return;
            setClauses([
              ...clauses,
              {
                field: f.id,
                op: f.kind === "numeric" ? ">=" : "in",
                values: [],
                value: f.min,
              },
            ]);
          }}
        >
          Add filter
        </button>
        <button type="button" className="mini" disabled={!clauses.length} onClick={() => setClauses([])}>
          Clear filters
        </button>
      </div>
    </div>
  );
}
