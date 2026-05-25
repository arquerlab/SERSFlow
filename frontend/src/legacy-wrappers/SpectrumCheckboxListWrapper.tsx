import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
import { buildRangeGroupOptions } from "../preprocess/uploadRangeGroups";
import { formatFileSizeMb, summarizeUploadLabels } from "../preprocess/uploadsUtils.ts";

type UploadItem = {
  relative_path: string;
  filename: string;
  size_bytes: number;
  labels?: Record<string, unknown>;
  wn_min?: number | null;
  wn_max?: number | null;
  spectrum_count?: number | null;
};

export type SpectrumCheckboxListHandle = {
  refresh: () => Promise<void>;
};

export const SpectrumCheckboxListWrapper = forwardRef<
  SpectrumCheckboxListHandle,
  { onSelectionChange?: (relativePaths: string[]) => void }
>(function SpectrumCheckboxListWrapper({ onSelectionChange }, ref) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [totalCount, setTotalCount] = useState<number>(0);
  // Keep a ref so toggle() always reads the latest selected without stale closures.
  const selectedRef = useRef<Set<string>>(selected);
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;

  const [rangeMenuValue, setRangeMenuValue] = useState("");

  const rangeOptions = useMemo(() => buildRangeGroupOptions(items), [items]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pendingScrollTopRef = useRef<number | null>(null);

  async function fetchItems() {
    try {
      const res = await fetch("/io/uploads?limit=5000", { cache: "no-store" });
      if (!res.ok) return;
      const data = await res.json();
      const fetched: UploadItem[] = data.items ?? [];
      const total = Number.isFinite(Number(data.count)) ? Number(data.count) : fetched.length;
      const existing = new Set(fetched.map((x) => x.relative_path));
      // Drop selected paths that no longer exist.
      const pruned = new Set([...selectedRef.current].filter((p) => existing.has(p)));
      selectedRef.current = pruned;
      setItems(fetched);
      setSelected(pruned);
      setTotalCount(total);
      onSelectionChangeRef.current?.([...pruned]);
    } catch {
      // silently ignore
    }
  }

  useImperativeHandle(ref, () => ({ refresh: fetchItems }));

  useEffect(() => {
    fetchItems();
    const channel = new BroadcastChannel("sersflow:uploads-changed");
    channel.addEventListener("message", () => fetchItems());
    return () => channel.close();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useLayoutEffect(() => {
    const top = pendingScrollTopRef.current;
    if (top == null) return;
    pendingScrollTopRef.current = null;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = top;
  }, [items.length, selected.size]);

  function toggle(rel: string) {
    // Preserve scroll position across state updates (prevents annoying “jump to top”).
    const el = scrollRef.current;
    pendingScrollTopRef.current = el ? el.scrollTop : null;
    // Compute next set from the ref (always current), then update both ref and state together.
    const next = new Set(selectedRef.current);
    if (next.has(rel)) next.delete(rel);
    else next.add(rel);
    selectedRef.current = next;
    setSelected(next);
    onSelectionChangeRef.current?.([...next]);
  }

  function selectAll() {
    const next = new Set(items.map((x) => x.relative_path));
    selectedRef.current = next;
    setSelected(next);
    onSelectionChangeRef.current?.([...next]);
  }

  function clearSelection() {
    const next = new Set<string>();
    selectedRef.current = next;
    setSelected(next);
    onSelectionChangeRef.current?.([]);
  }

  function selectByRangeGroup(key: string) {
    const g = rangeOptions.find((x) => x.key === key);
    if (!g) return;
    const next = new Set(g.paths);
    selectedRef.current = next;
    setSelected(next);
    onSelectionChangeRef.current?.([...next]);
    setRangeMenuValue("");
  }

  return (
    <div>
      <div
        className="uploads-meta"
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}
      >
        <span>
          {items.length} shown • {totalCount || items.length} total • {selected.size} selected
        </span>
        <span className="row" style={{ gap: "6px", alignItems: "center" }}>
          <label className="inline" style={{ margin: 0 }} title="Groups use 100 cm⁻¹ steps: lower bound rounded down, upper rounded up">
            <span className="hint" style={{ marginRight: "6px" }}>
              Range
            </span>
            <select
              className="mini"
              value={rangeMenuValue}
              disabled={items.length === 0}
              onChange={(e) => {
                const v = String(e.target.value || "");
                setRangeMenuValue(v);
                if (v) selectByRangeGroup(v);
              }}
            >
              <option value="">Select by wavenumber range…</option>
              {rangeOptions.map((g) => (
                <option key={g.key} value={g.key}>
                  {g.label}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="mini" onClick={selectAll} disabled={items.length === 0} title="Select every listed file">
            Select all
          </button>
          <button type="button" className="mini" onClick={clearSelection} disabled={selected.size === 0} title="Clear selection">
            Clear selection
          </button>
        </span>
      </div>
      <div className="scrollbox" ref={scrollRef}>
        {items.map((item) => {
          const checked = selected.has(item.relative_path);
          const sizeStr = formatFileSizeMb(item.size_bytes);
          const { short: labelsShort, full: labelsFull } = summarizeUploadLabels(item.labels);
          const displayText = labelsShort
            ? `${item.filename} (${sizeStr}) — ${labelsShort}`
            : `${item.filename} (${sizeStr})`;
          const titleText = labelsFull
            ? `${item.filename} — ${sizeStr}\n${labelsFull}`
            : `${item.filename} — ${sizeStr}`;
          return (
            <div
              key={item.relative_path}
              className="uploads-item"
              style={{ cursor: "pointer" }}
              onClick={() => toggle(item.relative_path)}
            >
              {/* readOnly + no onChange: the row onClick is the single toggle handler */}
              <input
                type="checkbox"
                className="uploads-select-cb"
                checked={checked}
                readOnly
              />
              <span className="uploads-item-label" title={titleText}>
                {displayText}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
});
