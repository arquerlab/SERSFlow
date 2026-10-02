import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState } from "react";
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

export type SpectrumCheckboxListHandle = {
  refresh: () => Promise<void>;
};

function setCheckboxIndeterminate(el: HTMLInputElement | null, value: boolean) {
  if (el) el.indeterminate = value;
}

export const SpectrumCheckboxListWrapper = forwardRef<
  SpectrumCheckboxListHandle,
  {
    onSelectionChange?: (relativePaths: string[], recordIndices?: Record<string, number[]>) => void;
  }
>(function SpectrumCheckboxListWrapper({ onSelectionChange }, ref) {
  const queryClient = useQueryClient();
  const uploadsQ = useUploadsList({ limit: 5000 });
  const [items, setItems] = useState<UploadItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [totalCount, setTotalCount] = useState<number>(0);
  const selectedRef = useRef<Set<string>>(selected);
  const onSelectionChangeRef = useRef(onSelectionChange);
  onSelectionChangeRef.current = onSelectionChange;

  const [rangeMenuValue, setRangeMenuValue] = useState("");

  const rangeOptions = useMemo(() => buildRangeGroupOptions(items), [items]);
  const regionOptions = useMemo(() => buildXpsRegionGroupOptions(items), [items]);
  const formatsQ = useFormatsCatalog();
  const formatsCatalog = formatsQ.data?.items;
  const majorityFamily = useMemo(
    () => majorityTechniqueFamily(items, formatsCatalog),
    [items, formatsCatalog]
  );
  const majorityTie = useMemo(
    () => isTechniqueFamilyTie(items, formatsCatalog),
    [items, formatsCatalog]
  );
  const selectedParents = useMemo(() => parentPathsFromSelectionKeys(selected), [selected]);
  const selectionMixed = useMemo(
    () => selectionMixesTechniques(selectedParents, items),
    [selectedParents, items]
  );

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const pendingScrollTopRef = useRef<number | null>(null);

  function emit(next: Set<string>) {
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
      const pruned = new Set(
        [...selectedRef.current].filter((key) => existing.has(parseSelectionKey(key).relativePath))
      );
      setItems(fetched);
      setTotalCount(total);
      emit(pruned);
    } catch {
      // silently ignore
    }
  }

  useImperativeHandle(ref, () => ({ refresh: fetchItems }));

  useEffect(() => {
    const data = uploadsQ.data;
    if (!data) return;
    const fetched: UploadItem[] = (data.items as UploadItem[]) ?? [];
    const total = Number.isFinite(Number(data.count)) ? Number(data.count) : fetched.length;
    const existing = new Set(fetched.map((x) => x.relative_path));
    const pruned = new Set(
      [...selectedRef.current].filter((key) => existing.has(parseSelectionKey(key).relativePath))
    );
    setItems(fetched);
    setTotalCount(total);
    emit(pruned);
  }, [uploadsQ.data]);

  useEffect(() => {
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

  function clearKeysForPath(next: Set<string>, rel: string) {
    for (const key of [...next]) {
      if (parseSelectionKey(key).relativePath === rel) next.delete(key);
    }
  }

  function toggle(rel: string) {
    const el = scrollRef.current;
    pendingScrollTopRef.current = el ? el.scrollTop : null;
    const next = new Set(selectedRef.current);
    const hasAny = [...next].some((k) => parseSelectionKey(k).relativePath === rel);
    clearKeysForPath(next, rel);
    if (!hasAny) next.add(rel);
    emit(next);
  }

  function toggleBlock(rel: string, index: number) {
    const el = scrollRef.current;
    pendingScrollTopRef.current = el ? el.scrollTop : null;
    const next = new Set(selectedRef.current);
    const item = items.find((x) => x.relative_path === rel);
    const blocks = sortedBlockEntries(item?.labels);
    const bkey = blockSelectionKey(rel, index);
    if (next.has(rel)) {
      next.delete(rel);
      for (const b of blocks) {
        if (b.index !== index) next.add(blockSelectionKey(rel, b.index));
      }
    } else if (next.has(bkey)) {
      next.delete(bkey);
    } else {
      next.add(bkey);
    }
    emit(next);
  }

  function selectAll() {
    emit(new Set(items.map((x) => x.relative_path)));
  }

  function clearSelection() {
    emit(new Set());
  }

  function selectByRangeGroup(key: string) {
    const g = rangeOptions.find((x) => x.key === key);
    if (!g) return;
    emit(new Set(g.paths));
    setRangeMenuValue("");
  }

  function selectByRegionGroup(key: string) {
    const g = regionOptions.find((x) => x.key === key);
    if (!g) return;
    const keys = g.selectionKeys?.length ? g.selectionKeys : g.paths;
    emit(new Set(keys));
    setRangeMenuValue("");
  }

  function pathSelected(rel: string): boolean {
    return [...selected].some((k) => parseSelectionKey(k).relativePath === rel);
  }

  function blockSelected(rel: string, index: number): boolean {
    if (selected.has(rel)) return true;
    return selected.has(blockSelectionKey(rel, index));
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

  return (
    <div>
      <div
        className="uploads-meta"
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "8px", flexWrap: "wrap" }}
      >
        <span>
          {items.length} shown • {totalCount || items.length} total • {selectedParents.length} selected
        </span>
        <span className="row" style={{ gap: "6px", alignItems: "center" }}>
          {majorityFamily === "xps" ? (
            <label className="inline" style={{ margin: 0 }} title="Select spectra blocks for an XPS region (not whole multi-region files)">
              <span className="hint" style={{ marginRight: "6px" }}>
                XPS region
              </span>
              <select
                className="mini"
                value={rangeMenuValue}
                disabled={items.length === 0}
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
          )}
          <button type="button" className="mini" onClick={selectAll} disabled={items.length === 0} title="Select all shown">
            Select all shown
          </button>
          <button type="button" className="mini" onClick={clearSelection} disabled={selectedParents.length === 0} title="Clear selection">
            Clear selection
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
      <div className="scrollbox" ref={scrollRef}>
        {items.map((item) => {
          const sizeStr = formatFileSizeMb(item.size_bytes ?? 0);
          const name = item.filename || item.relative_path;
          const labels = item.labels as Record<string, unknown> | undefined;
          const { short: labelsShort, full: labelsFull } = summarizeUploadLabels(labels);
          const displayText = labelsShort
            ? `${name} (${sizeStr}) — ${labelsShort}`
            : `${name} (${sizeStr})`;
          const titleText = labelsFull
            ? `${name} — ${sizeStr}\n${labelsFull}`
            : `${name} — ${sizeStr}`;
          const blocks = sortedBlockEntries(labels);
          const checked = pathSelected(item.relative_path);
          return (
            <div key={item.relative_path}>
              <div
                className="uploads-item"
                style={{ cursor: "pointer" }}
                onClick={() => toggle(item.relative_path)}
              >
                <input
                  type="checkbox"
                  className="uploads-select-cb"
                  checked={checked}
                  readOnly
                  ref={(el) => setCheckboxIndeterminate(el, pathIndeterminate(item.relative_path, blocks.length))}
                />
                <span className="uploads-item-label" title={titleText}>
                  {displayText}
                  {blocks.length ? ` · ${blocks.length} spectra` : ""}
                </span>
              </div>
              {blocks.map((b) => {
                const merged = mergePathAndBlockLabels(labels, b.meta);
                const { short: bshort, full: bfull } = summarizeUploadLabels(merged);
                const bname = blockDisplayName(b.meta);
                const on = blockSelected(item.relative_path, b.index);
                return (
                  <div
                    key={`${item.relative_path}#${b.index}`}
                    className="uploads-item"
                    style={{ cursor: "pointer", paddingLeft: "18px", opacity: 0.95 }}
                    onClick={(ev) => {
                      ev.stopPropagation();
                      toggleBlock(item.relative_path, b.index);
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
    </div>
  );
});
