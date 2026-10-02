import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { UPLOADS_LIST_QUERY_KEY, fetchUploadsList, useUploadsList, type UploadListItem } from "../preprocess/hooks/useUploadsList";
import { buildRangeGroupOptions } from "../preprocess/uploadRangeGroups";
import { useFormatsCatalog } from "../preprocess/hooks/useFormatsCatalog";
import {
  buildXpsRegionGroupOptions,
  isTechniqueFamilyTie,
  majorityTechniqueFamily,
  selectionMixesTechniques,
} from "../preprocess/uploadXpsRegionGroups";
import {
  FILTER_KEYS,
  distinctLabelValues,
  labelsMatchSelections,
  matchesLabelSelections,
  visibleFilterKeys,
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
import {
  blockDisplayName,
  blockSelectionKey,
  mergePathAndBlockLabels,
  parentPathsFromSelectionKeys,
  parseSelectionKey,
  recordIndicesByPathFromSelectionKeys,
  sortedBlockEntries,
} from "../preprocess/uploadBlockSpectra";

type UploadItem = UploadListItem;

export type UploadDatasetPickerHandle = {
  refresh: () => Promise<void>;
};

function setCheckboxIndeterminate(el: HTMLInputElement | null, value: boolean) {
  if (el) el.indeterminate = value;
}

function pruneSelectionKeys(keys: Set<string>, existingPaths: Set<string>, itemsByPath: Map<string, UploadItem>): Set<string> {
  const next = new Set<string>();
  for (const key of keys) {
    const { relativePath, recordIndex } = parseSelectionKey(key);
    if (!existingPaths.has(relativePath)) continue;
    if (recordIndex == null) {
      next.add(relativePath);
      continue;
    }
    const blocks = sortedBlockEntries(itemsByPath.get(relativePath)?.labels);
    if (blocks.some((b) => b.index === recordIndex)) next.add(key);
  }
  return next;
}

export const UploadDatasetPicker = forwardRef<
  UploadDatasetPickerHandle,
  {
    onSelectionChange?: (relativePaths: string[], recordIndices?: Record<string, number[]>) => void;
  }
>(function UploadDatasetPicker({ onSelectionChange }, ref) {
  const queryClient = useQueryClient();
  const uploadsQ = useUploadsList({ limit: 5000 });
  const [items, setItems] = useState<UploadItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set()); // path or path#idx
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

  const selectedParentPaths = useMemo(() => parentPathsFromSelectionKeys(selected), [selected]);
  const selectedParentSet = useMemo(() => new Set(selectedParentPaths), [selectedParentPaths]);

  const visibleItems = useMemo(() => {
    return items.filter((item) => matchesLabelSelections(item.labels, labelSelections));
  }, [items, labelSelections]);

  const visiblePaths = useMemo(() => new Set(visibleItems.map((x) => x.relative_path)), [visibleItems]);
  const visibleCount = visibleItems.length;
  const rangeOptions = useMemo(() => buildRangeGroupOptions(visibleItems), [visibleItems]);
  const regionOptions = useMemo(() => buildXpsRegionGroupOptions(visibleItems), [visibleItems]);
  const formatsQ = useFormatsCatalog();
  const formatsCatalog = formatsQ.data?.items;
  const majorityFamily = useMemo(
    () => majorityTechniqueFamily(visibleItems, formatsCatalog),
    [visibleItems, formatsCatalog]
  );
  const majorityTie = useMemo(
    () => isTechniqueFamilyTie(visibleItems, formatsCatalog),
    [visibleItems, formatsCatalog]
  );
  const selectionMixed = useMemo(
    () => selectionMixesTechniques(selectedParentPaths, items),
    [selectedParentPaths, items]
  );
  const tree = useMemo(() => buildUploadsTree(visibleItems), [visibleItems]);
  const distinctByKey = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const k of FILTER_KEYS) out[k] = distinctLabelValues(items, k);
    return out;
  }, [items]);
  const majorityFamilyAll = useMemo(
    () => majorityTechniqueFamily(items, formatsCatalog),
    [items, formatsCatalog]
  );
  const filterKeysShown = useMemo(
    () => visibleFilterKeys(items, majorityFamilyAll),
    [items, majorityFamilyAll]
  );

  function emitSelection(next: Set<string>) {
    selectedRef.current = next;
    setSelected(next);
    const paths = parentPathsFromSelectionKeys(next);
    const idxs = recordIndicesByPathFromSelectionKeys(next);
    onSelectionChangeRef.current?.(paths, Object.keys(idxs).length ? idxs : undefined);
  }

  async function fetchItems() {
    try {
      await queryClient.invalidateQueries({ queryKey: UPLOADS_LIST_QUERY_KEY });
      const data = await queryClient.fetchQuery({
        queryKey: [...UPLOADS_LIST_QUERY_KEY, 5000],
        queryFn: () => fetchUploadsList(5000),
      });
      const fetched: UploadItem[] = data.items ?? [];
      const total = Number.isFinite(Number(data.count)) ? Number(data.count) : fetched.length;
      const existing = new Set(fetched.map((x) => x.relative_path));
      const byPath = new Map(fetched.map((x) => [x.relative_path, x]));
      const pruned = pruneSelectionKeys(selectedRef.current, existing, byPath);
      selectedRef.current = pruned;
      setItems(fetched);
      setSelected(pruned);
      setTotalCount(total);
      const paths = parentPathsFromSelectionKeys(pruned);
      const idxs = recordIndicesByPathFromSelectionKeys(pruned);
      onSelectionChangeRef.current?.(paths, Object.keys(idxs).length ? idxs : undefined);
    } catch {
      // ignore
    }
  }

  useImperativeHandle(ref, () => ({ refresh: fetchItems }));

  useEffect(() => {
    const data = uploadsQ.data;
    if (!data) return;
    const fetched: UploadItem[] = (data.items as UploadItem[]) ?? [];
    const total = Number.isFinite(Number(data.count)) ? Number(data.count) : fetched.length;
    const existing = new Set(fetched.map((x) => x.relative_path));
    const byPath = new Map(fetched.map((x) => [x.relative_path, x]));
    const pruned = pruneSelectionKeys(selectedRef.current, existing, byPath);
    selectedRef.current = pruned;
    setItems(fetched);
    setSelected(pruned);
    setTotalCount(total);
    const paths = parentPathsFromSelectionKeys(pruned);
    const idxs = recordIndicesByPathFromSelectionKeys(pruned);
    onSelectionChangeRef.current?.(paths, Object.keys(idxs).length ? idxs : undefined);
  }, [uploadsQ.data]);

  useEffect(() => {
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

  function clearKeysForPath(next: Set<string>, rel: string) {
    for (const key of [...next]) {
      const { relativePath } = parseSelectionKey(key);
      if (relativePath === rel) next.delete(key);
    }
  }

  function togglePath(rel: string) {
    const el = scrollRef.current;
    pendingScrollTopRef.current = el ? el.scrollTop : null;
    const next = new Set(selectedRef.current);
    const hasAny = [...next].some((k) => parseSelectionKey(k).relativePath === rel);
    clearKeysForPath(next, rel);
    if (!hasAny) next.add(rel);
    emitSelection(next);
  }

  function toggleBlock(rel: string, index: number) {
    const el = scrollRef.current;
    pendingScrollTopRef.current = el ? el.scrollTop : null;
    const next = new Set(selectedRef.current);
    const item = items.find((x) => x.relative_path === rel);
    const blocks = sortedBlockEntries(item?.labels);
    const bkey = blockSelectionKey(rel, index);
    if (next.has(rel)) {
      // Whole file was selected: expand to all blocks except the one being unchecked.
      next.delete(rel);
      for (const b of blocks) {
        if (b.index !== index) next.add(blockSelectionKey(rel, b.index));
      }
    } else if (next.has(bkey)) {
      next.delete(bkey);
    } else {
      next.add(bkey);
    }
    emitSelection(next);
  }

  function setFolderSelection(paths: string[], checked: boolean) {
    const el = scrollRef.current;
    pendingScrollTopRef.current = el ? el.scrollTop : null;
    const next = new Set(selectedRef.current);
    for (const rel of paths) {
      clearKeysForPath(next, rel);
      if (checked) next.add(rel);
    }
    emitSelection(next);
  }

  function selectAllVisible() {
    const next = new Set<string>();
    const filterActive = Object.values(labelSelections).some((a) => Array.isArray(a) && a.length > 0);
    for (const item of visibleItems) {
      const blocks = sortedBlockEntries(item.labels);
      if (!blocks.length) {
        next.add(item.relative_path);
        continue;
      }
      if (!filterActive) {
        next.add(item.relative_path);
        continue;
      }
      for (const b of blocks) {
        const merged = mergePathAndBlockLabels(item.labels, b.meta);
        if (labelsMatchSelections(merged, labelSelections)) {
          next.add(blockSelectionKey(item.relative_path, b.index));
        }
      }
    }
    emitSelection(next);
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

  function selectByRegionGroup(key: string) {
    const g = regionOptions.find((x) => x.key === key);
    if (!g) return;
    const keys = (g.selectionKeys?.length ? g.selectionKeys : g.paths).filter((sel) => {
      const { relativePath } = parseSelectionKey(sel);
      return visiblePaths.has(relativePath);
    });
    emitSelection(new Set(keys));
    setRangeMenuValue("");
  }

  function pathSelected(rel: string): boolean {
    return [...selected].some((k) => parseSelectionKey(k).relativePath === rel);
  }

  function pathIndeterminate(rel: string, blockCount: number): boolean {
    if (selected.has(rel) || blockCount <= 0) return false;
    let n = 0;
    for (const key of selected) {
      const p = parseSelectionKey(key);
      if (p.relativePath === rel && p.recordIndex != null) n += 1;
    }
    return n > 0 && n < blockCount;
  }

  function blockSelected(rel: string, index: number): boolean {
    if (selected.has(rel)) return true; // whole file → all blocks shown selected
    return selected.has(blockSelectionKey(rel, index));
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

    const checkedCount = visibleDescendants.filter((rel) => pathSelected(rel)).length;
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
            const labels = file.item.labels as Record<string, unknown> | undefined;
            const { short: labelsShort, full: labelsFull } = summarizeUploadLabels(labels);
            const displayText = labelsShort ? `${file.name} — ${labelsShort}` : file.name;
            const titleText = labelsFull ? `${file.name} — ${sizeStr}\n${labelsFull}` : `${file.name} — ${sizeStr}`;
            const blocks = sortedBlockEntries(labels);
            const fileOn = pathSelected(rel);
            return (
              <div key={rel}>
                <div
                  className="uploads-item"
                  style={{ paddingLeft: `${depth * 16}px`, cursor: "pointer" }}
                  onClick={() => togglePath(rel)}
                >
                  <input
                    type="checkbox"
                    className="uploads-select-cb"
                    checked={fileOn}
                    readOnly
                    ref={(el) => setCheckboxIndeterminate(el, pathIndeterminate(rel, blocks.length))}
                  />
                  <span className="uploads-item-label" title={titleText}>
                    {displayText} ({sizeStr})
                    {blocks.length ? ` · ${blocks.length} spectra` : ""}
                  </span>
                </div>
                {blocks.map((b) => {
                  const merged = mergePathAndBlockLabels(labels, b.meta);
                  if (!labelsMatchSelections(merged, labelSelections)) return null;
                  const { short: bshort, full: bfull } = summarizeUploadLabels(merged);
                  const bname = blockDisplayName(b.meta);
                  const on = blockSelected(rel, b.index);
                  return (
                    <div
                      key={`${rel}#${b.index}`}
                      className="uploads-item"
                      style={{ paddingLeft: `${depth * 16 + 18}px`, cursor: "pointer", opacity: 0.95 }}
                      onClick={(ev) => {
                        ev.stopPropagation();
                        toggleBlock(rel, b.index);
                      }}
                      title={bfull || `Toggle spectrum block #${b.index}`}
                    >
                      <input type="checkbox" className="uploads-select-cb" checked={on} readOnly />
                      <span className="uploads-item-label">
                        {bshort ? `↳ ${bname} — ${bshort}` : `↳ ${bname}`}
                      </span>
                    </div>
                  );
                })}
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
          {visibleCount} shown • {totalCount || items.length} total • {selectedParentSet.size} selected
        </span>
        <span className="row" style={{ gap: "6px", alignItems: "center", flexWrap: "wrap" }}>
          {majorityFamily === "xps" ? (
            <label className="inline" style={{ margin: 0 }} title="Select spectra blocks for an XPS region (not whole multi-region files)">
              <span className="hint" style={{ marginRight: "6px" }}>
                XPS region
              </span>
              <select
                className="mini"
                value={rangeMenuValue}
                disabled={visibleCount === 0}
                onChange={(e) => {
                  const v = String(e.target.value || "");
                  setRangeMenuValue(v);
                  if (v) selectByRegionGroup(v);
                }}
              >
                <option value="">Select by XPS region…</option>
                {regionOptions.map((g) => (
                  <option key={g.key} value={g.key}>
                    {g.label}
                  </option>
                ))}
              </select>
            </label>
          ) : (
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
          )}
          <button type="button" className="mini" onClick={selectAllVisible} disabled={visibleCount === 0}>
            Select all visible
          </button>
          <button type="button" className="mini" onClick={clearSelection} disabled={selectedParentSet.size === 0}>
            Clear
          </button>
          <button type="button" className="mini" onClick={() => setFiltersOpen((x) => !x)}>
            Filters{Object.keys(labelSelections).length ? ` (${Object.keys(labelSelections).length})` : ""}
          </button>
        </span>
      </div>
      {majorityTie ? (
        <div className="hint" style={{ marginTop: "6px" }}>
          Equal XPS and vibrational file counts — showing wavenumber range groups (vibrational default).
        </div>
      ) : null}
      {selectionMixed ? (
        <div className="hint" style={{ color: "var(--danger, #b00020)", marginTop: "6px" }}>
          Selection mixes XPS and vibrational files. A dataset cannot combine both; deselect one technique before Create.
        </div>
      ) : null}

      {filtersOpen ? (
        <div className="upload-picker-filters card-inner">
          <div className="hint" style={{ margin: 0 }}>
            Click a label key to select one or more values (AND across keys, OR within a key).
          </div>
          <div style={{ display: "grid", gap: "6px" }}>
            {filterKeysShown.map((key) => {
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
