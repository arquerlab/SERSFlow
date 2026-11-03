import { useEffect, useMemo, useState } from "react";
import { DraftNumberInput } from "../lib/draftInputs";
import { TickDropdown } from "./TickDropdown";
import { fetchDatasetFilterFields, type FilterFieldCatalogItem } from "./api";

export type AggregateMethod = "all" | "by_label" | "by_range";
export type AggregateReducer = "cumulative" | "mean" | "median";

export type AggregateSpectraParams = {
  method: AggregateMethod;
  group_by: string[];
  range_label: string;
  range_width: number | null;
  range_origin: number | null;
  split_by_region: boolean;
  reducer: AggregateReducer;
  min_group_size: number;
};

type Props = {
  datasetId: string | null;
  params: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
};

export function defaultAggregateSpectraParams(): AggregateSpectraParams {
  return {
    method: "all",
    group_by: [],
    range_label: "",
    range_width: null,
    range_origin: null,
    split_by_region: true,
    reducer: "cumulative",
    min_group_size: 1,
  };
}

function asNum(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function normalizeAggregateSpectraParams(raw: Record<string, unknown>): AggregateSpectraParams {
  const d = defaultAggregateSpectraParams();
  const m = String(raw.method ?? raw.mode ?? d.method);
  const gb = raw.group_by;
  const reducer = String(raw.reducer ?? d.reducer);
  return {
    method: m === "by_label" || m === "by_range" ? m : "all",
    group_by: Array.isArray(gb)
      ? gb.map(String).filter(Boolean)
      : typeof gb === "string"
        ? gb.split(",").map((s) => s.trim()).filter(Boolean)
        : [],
    range_label: String(raw.range_label ?? ""),
    range_width: asNum(raw.range_width),
    range_origin: asNum(raw.range_origin),
    split_by_region: raw.split_by_region == null ? d.split_by_region : Boolean(raw.split_by_region),
    reducer: reducer === "mean" || reducer === "median" ? reducer : "cumulative",
    min_group_size: Math.max(1, Math.trunc(asNum(raw.min_group_size) ?? 1)),
  };
}

export function AggregateSpectraEditor({ datasetId, params, onChange }: Props) {
  const [fields, setFields] = useState<FilterFieldCatalogItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const p = normalizeAggregateSpectraParams(params);

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
        if (!cancelled) setErr(String((e as Error)?.message ?? e));
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  // Group by accepts any label (categorical, or numeric such as current density). Region is always split
  // separately (see "split by region"), so it is not offered here.
  const groupFields = useMemo(() => fields.filter((f) => f.id !== "xps_region"), [fields]);
  const labelOf = useMemo(() => new Map(groupFields.map((f) => [f.id, f.label] as const)), [groupFields]);
  const rangeFields = useMemo(
    () => [...groupFields].sort((a, b) => Number(b.kind === "numeric") - Number(a.kind === "numeric")),
    [groupFields]
  );

  function patch(partial: Partial<AggregateSpectraParams>) {
    onChange({ ...p, ...partial } as unknown as Record<string, unknown>);
  }

  return (
    <div style={{ display: "grid", gap: "8px" }}>
      <label className="inline" style={{ justifyContent: "space-between" }}>
        aggregate
        <select value={p.method} onChange={(e) => patch({ method: e.target.value as AggregateMethod })}>
          <option value="all">all spectra</option>
          <option value="by_label">by label</option>
          <option value="by_range">by range (bins)</option>
        </select>
      </label>

      {p.method === "by_label" ? (
        <>
          <label className="inline" style={{ justifyContent: "space-between" }}>
            group by
            <TickDropdown
              appearance="select"
              options={groupFields.map((f) => f.id)}
              selected={p.group_by}
              onChange={(next) => patch({ group_by: next })}
              emptySummary="Select labels…"
              title={p.group_by.map((id) => labelOf.get(id) ?? id).join(", ")}
            />
          </label>
          {!p.group_by.length ? (
            <div className="hint">Tick one or more labels; spectra sharing all their values are aggregated.</div>
          ) : null}
        </>
      ) : null}

      {p.method === "by_range" ? (
        <>
          <label className="inline" style={{ justifyContent: "space-between" }}>
            range label
            <select value={p.range_label} onChange={(e) => patch({ range_label: String(e.target.value || "") })}>
              <option value="">Select label…</option>
              {rangeFields.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                  {f.kind === "numeric" ? "" : " (timestamp / text)"}
                </option>
              ))}
            </select>
          </label>
          <label className="inline" style={{ justifyContent: "space-between" }}>
            range width
            <DraftNumberInput value={p.range_width} onChange={(n) => patch({ range_width: n })} nullable />
          </label>
          <label className="inline" style={{ justifyContent: "space-between" }}>
            range origin
            <DraftNumberInput value={p.range_origin} onChange={(n) => patch({ range_origin: n })} nullable />
          </label>
          {!p.range_label || p.range_width == null || p.range_width <= 0 ? (
            <div className="hint">
              Pick a numeric or timestamp label and a bin width in its unit (seconds for time). Empty origin starts at the
              smallest value.
            </div>
          ) : null}
        </>
      ) : null}

      <label className="inline" style={{ justifyContent: "space-between" }}>
        split by region
        <input type="checkbox" checked={p.split_by_region} onChange={(e) => patch({ split_by_region: e.target.checked })} />
      </label>

      <label className="inline" style={{ justifyContent: "space-between" }}>
        reducer
        <select value={p.reducer} onChange={(e) => patch({ reducer: e.target.value as AggregateReducer })}>
          <option value="cumulative">cumulative (sum)</option>
          <option value="mean">mean</option>
          <option value="median">median</option>
        </select>
      </label>

      <label className="inline" style={{ justifyContent: "space-between" }}>
        min group size
        <DraftNumberInput
          value={p.min_group_size}
          integer
          min={1}
          onChange={(n) => {
            if (n != null) patch({ min_group_size: n });
          }}
        />
      </label>
      {err ? <div className="err">{err}</div> : null}
    </div>
  );
}
