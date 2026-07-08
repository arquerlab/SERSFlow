import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { buildRangeGroupOptions } from "../preprocess/uploadRangeGroups";
import {
  FILTER_KEYS,
  distinctLabelValues,
  matchesLabelSelections,
  type LabelSelections,
} from "../preprocess/uploadLabelFilters";
import {
  buildUploadsTree,
  collectFolderFilePaths,
  sortedFileEntries,
  sortedFolderEntries,
  type UploadFolderNode,
} from "../preprocess/uploadsTree";
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

export type UploadDatasetPickerHandle = {
  refresh: () => Promise<void>;
};

function setCheckboxIndeterminate(el: HTMLInputElement | null, value: boolean) {
  if (el) el.indeterminate = value;
}

export const UploadDatasetPicker = forwardRef<
  UploadDatasetPickerHandle,
  { onSelectionChange?: (relativePaths: string[]) => void }
>(function UploadDatasetPicker({ onSelectionChange }, ref) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [totalCount, setTotalCount] = useState(0);
  const [rangeMenuValue, setRangeMenuValue] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [labelSelections, setLabelSelections] = useState<LabelSelections>({});
  const [openFolderKeys, setOpenFolderKeys] = useState<Set<string>>(new Set());

  const selectedRef = useRef<Set<string>>(selected);
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pendingScrollTopRef = useRef<number | null>(null);

  const visibleItems = useMemo(() => {
    return items.filter((item) => matchesLabelSelections(item.labels, labelSelections));
  }, [items, labelSelections]);

  const visiblePaths = useMemo(() => new Set(visibleItems.map((x) => x.relative_path)), [visibleItems]);
  const visibleCount = visibleItems.length;
  const rangeOptions = useMemo(() => buildRangeGroupOptions(visibleItems), [visibleItems]);
  const tree = useMemo(() => buildUploadsTree(visibleItems), [visibleItems]);
  const distinctByKey = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const k of FILTER_KEYS) out[k] = distinctLabelValues(items, k);
    return out;
  }, [items]);

  async function fetchItems() {
    try {
      const res = await fetch("/io/uploads?limit=5000", { cache: "no-store", credentials: "include" });
      if (!res.ok) return;
      const data = await res.json();
      const fetched: UploadItem[] = data.items ?? [];
      const total = Number.isFinite(Number(data.count)) ? Number(data.count) : fetched.length;
      const existing = new Set(fetched.map((x) => x.relative_path));
      const pruned = new Set([...selectedRef.current].filter((p) => existing.has(p)));
      selectedRef.current = pruned;
      setItems(fetched);
      setSelected(pruned);
      setTotalCount(total);
      onSelectionChangeRef.current?.([...pruned]);
    } catch {
      // ignore
    }
  }

  useImperativeHandle(ref, () => ({ refresh: fetchItems }));

  useEffect(() => {
    fetchItems();
    const channel = new BroadcastChannel("sersflow:uploads-changed");
    channel.addEventListener("message", () => fetchItems());
    return () => channel.close();
  }, []);

  useLayoutEffect(() => {
    const top = pendingScrollTopRef.current;
    if (top == null) return;
    pendingScrollTopRef.current = null;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = top;
  }, [visibleCount, selected.size, Object.keys(labelSelections).length]);

  function emitSelection(next: Set<string>) {
    selectedRef.current = next;
    setSelected(next);
    onSelectionChangeRef.current?.([...next]);
  }

  function togglePath(rel: string) {
    const el = scrollRef.current;
    pendingScrollTopRef.current = el ? el.scrollTop : null;
    const next = new Set(selectedRef.current);
    if (next.has(rel)) next.delete(rel);
    else next.add(rel);
    emitSelection(next);
  }

  function setFolderSelection(paths: string[], checked: boolean) {
    const el = scrollRef.current;
    pendingScrollTopRef.current = el ? el.scrollTop : null;
    const next = new Set(selectedRef.current);
    for (const rel of paths) {
      if (checked) next.add(rel);
      else next.delete(rel);
    }
    emitSelection(next);
  }

  function selectAllVisible() {
    emitSelection(new Set(visibleItems.map((x) => x.relative_path)));
  }

  function clearSelection() {
    emitSelection(new Set());
  }

  function selectByRangeGroup(key: string) {
    const g = rangeOptions.find((x) => x.key === key);
    if (!g) return;
    emitSelection(new Set(g.paths.filter((p) => visiblePaths.has(p))));
    setRangeMenuValue("");
  }

  function toggleSelectionValue(key: string, value: string) {
    setLabelSelections((prev) => {
      const cur = Array.isArray(prev[key]) ? prev[key] : [];
      const exists = cur.includes(value);
      const nextVals = exists ? cur.filter((v) => v !== value) : [...cur, value];
      const next: LabelSelections = { ...prev, [key]: nextVals };
      if (nextVals.length === 0) delete next[key];
      return next;
    });
  }

  function clearKeySelection(key: string) {
    setLabelSelections((prev) => {
      const next: LabelSelections = { ...prev };
      delete next[key];
      return next;
    });
  }

  function toggleFolderOpen(key: string, open: boolean) {
    setOpenFolderKeys((prev) => {
      const next = new Set(prev);
      if (open) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function renderFolder(folderNode: UploadFolderNode, depth: number): ReactNode {
    const key = String(folderNode.key || folderNode.name || "");
    const descendants = collectFolderFilePaths(folderNode);
    const visibleDescendants = descendants.filter((rel) => visiblePaths.has(rel));
    if (!visibleDescendants.length) return null;

    const checkedCount = visibleDescendants.filter((rel) => selected.has(rel)).length;
    const isOpen = openFolderKeys.has(key) || depth <= 1;

    return (
      <details
        key={key}
        className="upload-tree-folder"
        open={isOpen}
        onToggle={(e) => toggleFolderOpen(key, (e.currentTarget as HTMLDetailsElement).open)}
      >
        <summary className="upload-tree-folder-summary">
          <div className="upload-tree-folder-row" style={{ paddingLeft: `${Math.max(0, depth - 1) * 16}px` }}>
            <input
              type="checkbox"
              className="uploads-folder-cb"
              ref={(el) => setCheckboxIndeterminate(el, checkedCount > 0 && checkedCount < visibleDescendants.length)}
              checked={visibleDescendants.length > 0 && checkedCount === visibleDescendants.length}
              onClick={(ev) => ev.stopPropagation()}
              onChange={(ev) => setFolderSelection(visibleDescendants, ev.target.checked)}
            />
            <span className="upload-tree-folder-label">{folderNode.name}</span>
            <span className="upload-tree-folder-count">
              ({visibleDescendants.length}
              {Object.keys(labelSelections).length && visibleDescendants.length !== descendants.length ? `/${descendants.length}` : ""})
            </span>
          </div>
        </summary>
        <div className="upload-tree-children">
          {sortedFolderEntries(folderNode).map((child) => renderFolder(child, depth + 1))}
          {sortedFileEntries(folderNode).map((file) => {
            const rel = String(file.item.relative_path || "");
            if (!visiblePaths.has(rel)) return null;
            const sizeStr = formatFileSizeMb(Number(file.item.size_bytes) || 0);
            const { short: labelsShort, full: labelsFull } = summarizeUploadLabels(
              file.item.labels as Record<string, unknown> | undefined
            );
            const displayText = labelsShort ? `${file.name} — ${labelsShort}` : file.name;
            const titleText = labelsFull ? `${file.name} — ${sizeStr}\n${labelsFull}` : `${file.name} — ${sizeStr}`;
            return (
              <div
                key={rel}
                className="uploads-item"
                style={{ paddingLeft: `${depth * 16}px`, cursor: "pointer" }}
                onClick={() => togglePath(rel)}
              >
                <input type="checkbox" className="uploads-select-cb" checked={selected.has(rel)} readOnly />
                <span className="uploads-item-label" title={titleText}>
                  {displayText} ({sizeStr})
                </span>
              </div>
            );
          })}
        </div>
      </details>
    );
  }

  const folders = sortedFolderEntries(tree);

  return (
    <div className="upload-dataset-picker">
      <div className="uploads-meta uploads-picker-toolbar">
        <span>
          {visibleCount} shown • {totalCount || items.length} total • {selected.size} selected
        </span>
        <span className="row" style={{ gap: "6px", alignItems: "center", flexWrap: "wrap" }}>
          <label className="inline" style={{ margin: 0 }} title="Groups use 100 cm⁻¹ steps">
            <span className="hint" style={{ marginRight: "6px" }}>
              Range
            </span>
            <select
              className="mini"
              value={rangeMenuValue}
              disabled={visibleCount === 0}
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
          <button type="button" className="mini" onClick={selectAllVisible} disabled={visibleCount === 0}>
            Select all visible
          </button>
          <button type="button" className="mini" onClick={clearSelection} disabled={selected.size === 0}>
            Clear
          </button>
          <button type="button" className="mini" onClick={() => setFiltersOpen((x) => !x)}>
            Filters{Object.keys(labelSelections).length ? ` (${Object.keys(labelSelections).length})` : ""}
          </button>
        </span>
      </div>

      {filtersOpen ? (
        <div className="upload-picker-filters card-inner">
          <div className="hint" style={{ margin: 0 }}>
            Click a label key to select one or more values (AND across keys, OR within a key).
          </div>
          <div style={{ display: "grid", gap: "6px" }}>
            {FILTER_KEYS.map((key) => {
              const values = distinctByKey[key] ?? [];
              const selectedVals = labelSelections[key] ?? [];
              const selectedCount = selectedVals.length;
              return (
                <details key={key} className="upload-filter-col">
                  <summary className="upload-filter-col-summary">
                    <span style={{ fontFamily: "var(--mono)", fontSize: "12px" }}>{key}</span>
                    <span className="hint" style={{ marginLeft: "8px" }}>
                      {selectedCount ? `${selectedCount} selected` : "All"}
                    </span>
                  </summary>
                  <div className="upload-filter-col-body">
                    <button type="button" className="mini" onClick={() => clearKeySelection(key)} disabled={!selectedCount}>
                      (Select all)
                    </button>
                    <div className="upload-filter-values">
                      {values.length ? (
                        values.map((v) => {
                          const checked = selectedVals.includes(v);
                          return (
                            <button
                              key={v}
                              type="button"
                              className={`upload-filter-value${checked ? " is-checked" : ""}`}
                              onClick={() => toggleSelectionValue(key, v)}
                              title={v}
                            >
                              <span className="upload-filter-check">{checked ? "✓" : ""}</span>
                              <span className="upload-filter-value-text">{v}</span>
                            </button>
                          );
                        })
                      ) : (
                        <div className="hint">No values found.</div>
                      )}
                    </div>
                  </div>
                </details>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="scrollbox upload-picker-scroll" ref={scrollRef}>
        {folders.length ? folders.map((folder) => renderFolder(folder, 1)) : <div className="hint">No uploads match.</div>}
      </div>
    </div>
  );
});
