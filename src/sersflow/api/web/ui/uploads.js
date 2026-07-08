import { fetchJson, fetchText } from "./api.js";

/** Build a short label line + full tooltip from API `labels` object. */
export function summarizeUploadLabels(labels) {
  if (!labels || typeof labels !== "object") return { short: "", full: "" };
  const parts = [];

  const num = (v) => {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };

  if (labels.sample) parts.push(String(labels.sample));
  if (labels.ph != null && labels.ph !== "") parts.push(`pH=${labels.ph}`);
  if (labels.gas) parts.push(String(labels.gas));

  const pv = num(labels.potential_V);
  const pref = labels.potential_ref;
  if (pv != null && pref) {
    if (pref === "OCP") parts.push("OCP");
    else if (pref === "VRHE") parts.push(`${pv}VRHE`);
    else if (pref === "VAgAgCl") parts.push(`${pv}V Ag/AgCl`);
    else if (pref === "V") parts.push(`${pv} V`);
    else parts.push(`${pv}V`);
  }

  const cd = num(labels.current_density_A_cm2);
  const caLegacy = num(labels.current_A);
  const cAmp = cd != null ? cd : caLegacy;
  if (cAmp != null) {
    const macm2 = cAmp * 1000;
    parts.push(`${Number.isFinite(macm2) ? macm2 : cAmp}mA·cm⁻²`);
  }

  const lnm = num(labels.laser_nm);
  if (lnm != null) parts.push(`${lnm}nm`);
  const lp = num(labels.laser_power_pct);
  if (lp != null) parts.push(`${lp}%`);

  if (labels.electrolyte) {
    const cM = num(labels.concentration_M != null ? labels.concentration_M : labels.electrolyte_M);
    if (cM != null) parts.push(`${cM}M ${labels.electrolyte}`);
    else parts.push(String(labels.electrolyte));
  }

  const full = parts.join(" • ");
  const maxPrimary = 5;
  const short =
    parts.length <= maxPrimary ? full : `${parts.slice(0, maxPrimary).join(" • ")} • …`;
  return { short, full };
}

/** Size in mebibytes (1024²), fixed 3 decimals, suffixed with " MB". */
export function formatFileSizeMb(bytes) {
  const mb = (Number(bytes) || 0) / (1024 * 1024);
  if (!Number.isFinite(mb) || mb <= 0) return "0.000 MB";
  return `${mb.toFixed(3)} MB`;
}

function splitRelPath(relativePath) {
  const rel = String(relativePath || "").replace(/\\/g, "/");
  return rel.split("/").filter(Boolean);
}

function toDisplayParts(relativePath, fallbackName) {
  const parts = splitRelPath(relativePath);
  // `relative_path` is stored as `<batch_id>/<original_relative_subpath>`.
  // Hide the internal batch id and group by the original folder names.
  if (parts.length >= 2) {
    const withoutBatch = parts.slice(1);
    if (withoutBatch.length >= 2) return withoutBatch;
    const leaf = withoutBatch[0] || String(fallbackName || "unknown");
    return ["(no folder)", leaf];
  }
  const name = String(fallbackName || "unknown");
  return ["(no folder)", name];
}

function makeFolderNode(name, key, batchId = null) {
  return {
    type: "folder",
    name,
    key,
    batchId,
    folders: new Map(),
    files: [],
  };
}

function buildUploadsTree(items) {
  const root = makeFolderNode("__root__", "__root__");
  for (const item of items || []) {
    const rel = String(item?.relative_path || "");
    if (!rel) continue;
    const parts = toDisplayParts(rel, item?.filename);
    const top = parts[0] || "(no folder)";
    if (!root.folders.has(top)) {
      root.folders.set(top, makeFolderNode(top, `folder:${top}`, null));
    }
    let node = root.folders.get(top);
    for (let i = 1; i < parts.length - 1; i += 1) {
      const part = parts[i];
      const key = `${node.key}/${part}`;
      if (!node.folders.has(part)) {
        node.folders.set(part, makeFolderNode(part, key, null));
      }
      node = node.folders.get(part);
    }
    node.files.push({
      type: "file",
      name: parts[parts.length - 1],
      item,
    });
  }
  return root;
}

function sortedFolderEntries(folderNode) {
  return Array.from(folderNode.folders.values()).sort((a, b) => a.name.localeCompare(b.name));
}

function sortedFileEntries(folderNode) {
  return folderNode.files.slice().sort((a, b) => a.name.localeCompare(b.name));
}

function collectFolderFilePaths(folderNode) {
  const out = [];
  for (const f of folderNode.files) out.push(String(f.item.relative_path));
  for (const child of folderNode.folders.values()) out.push(...collectFolderFilePaths(child));
  return out;
}

function setElementIndeterminate(inputEl, value) {
  if (!inputEl) return;
  inputEl.indeterminate = !!value;
}

export function createUploadsModel() {
  let uploadedItems = [];
  let selected = new Set();

  function getUploadedItems() {
    return uploadedItems;
  }
  function getSelectedSet() {
    return selected;
  }
  function setSelectedSet(next) {
    selected = next;
  }
  function toggle(relativePath, checked) {
    const rel = String(relativePath || "");
    if (!rel) return;
    const next = checked == null ? !selected.has(rel) : !!checked;
    if (next) selected.add(rel);
    else selected.delete(rel);
  }

  async function refreshUploadedList() {
    const data = await fetchJson("/io/uploads?limit=5000");
    uploadedItems = data.items || [];
    const existing = new Set(uploadedItems.map((x) => x.relative_path));
    selected = new Set(Array.from(selected).filter((p) => existing.has(p)));
    return { items: uploadedItems, count: data.count || uploadedItems.length };
  }

  return { refreshUploadedList, getUploadedItems, getSelectedSet, setSelectedSet, toggle };
}

/**
 * @param {object} opts
 * @param {HTMLElement} opts.uploadedListEl
 * @param {HTMLElement} opts.uploadsMetaEl
 * @param {(paths: string[], items: object[], totalCount: number) => void} [opts.onSelectedPathsChange]
 * @param {(items: object[], totalCount: number) => void} [opts.onUploadedItemsChange]
 * @param {() => boolean} [opts.isMounted]
 */
export function createUploadsController({ uploadedListEl, uploadsMetaEl, onSelectedPathsChange, onUploadedItemsChange, isMounted }) {
  let uploadedItems = [];
  let selected = new Set();
  let totalCount = 0;
  const openFolderKeys = new Set(); // persist expanded state across re-renders

  function _mounted() {
    return typeof isMounted === "function" ? isMounted() : true;
  }

  function _pruneSelection() {
    const existing = new Set(uploadedItems.map((x) => x.relative_path));
    selected = new Set(Array.from(selected).filter((p) => existing.has(p)));
  }

  function _emitSelection() {
    const paths = Array.from(selected.values());
    const total = Number.isFinite(Number(totalCount)) && totalCount > 0 ? totalCount : uploadedItems.length;
    uploadsMetaEl.textContent = `${uploadedItems.length} shown • ${total} total • ${paths.length} selected`;
    if (typeof onSelectedPathsChange === "function") onSelectedPathsChange(paths, uploadedItems, total);
  }

  function getUploadedItems() {
    return uploadedItems;
  }

  function getSelectedSet() {
    return selected;
  }

  function getTotalCount() {
    return Number.isFinite(Number(totalCount)) && totalCount > 0 ? totalCount : uploadedItems.length;
  }

  function setSelectedSet(next) {
    selected = next instanceof Set ? next : new Set();
    _pruneSelection();
    if (_mounted()) renderUploadList();
  }

  async function _unloadPaths(paths) {
    const deduped = Array.from(new Set((paths || []).filter(Boolean)));
    if (!deduped.length) return { ok: true, message: "No files selected." };
    const { res, text } = await fetchText("/io/unload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ relative_paths: deduped }),
    });
    if (!res.ok) return { ok: false, message: text || `Hide failed (${res.status}).` };
    for (const rel of deduped) selected.delete(rel);
    return { ok: true, message: text || "Hidden from active uploads." };
  }

  async function purgeUnusedHidden() {
    const preview = await fetchJson("/io/purge/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hidden_only: true }),
    });
    const items = Array.isArray(preview.items) ? preview.items : [];
    const purgeable = items.filter((item) => Number(item.blocked_count || 0) === 0).map((item) => String(item.relative_path || ""));
    const blockedCount = Object.keys(preview.blocked || {}).length;
    const purgeableSize = items
      .filter((item) => Number(item.blocked_count || 0) === 0)
      .reduce((sum, item) => sum + (Number(item.size_bytes) || 0), 0);

    if (!purgeable.length) {
      const blockedMsg = blockedCount ? ` ${blockedCount} file(s) are blocked because old path-only datasets still need them.` : "";
      return { ok: true, message: `No purgeable hidden files found.${blockedMsg}` };
    }

    const msg = [
      `Permanently delete ${purgeable.length} hidden file(s)?`,
      `Estimated space to free: ${formatFileSizeMb(purgeableSize)}.`,
      blockedCount ? `${blockedCount} blocked file(s) will be kept.` : "",
      "This cannot be undone.",
    ]
      .filter(Boolean)
      .join("\n");
    if (!window.confirm(msg)) return { ok: true, message: "Purge cancelled." };

    const { res, text } = await fetchText("/io/purge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ relative_paths: purgeable }),
    });
    if (!res.ok) return { ok: false, message: text || `Purge failed (${res.status}).` };
    let data = {};
    try {
      data = JSON.parse(text || "{}");
    } catch {
      data = {};
    }
    return {
      ok: true,
      message: `Purged ${Number(data.deleted || 0)} file(s). Missing: ${Number(data.missing || 0)}. Blocked: ${Object.keys(data.blocked || {}).length}.`,
    };
  }

  function renderUploadList() {
    if (!_mounted()) return;
    uploadedListEl.innerHTML = "";
    _pruneSelection();

    const tree = buildUploadsTree(uploadedItems);
    const folders = sortedFolderEntries(tree);
    if (!folders.length) {
      _emitSelection();
      return;
    }

    const renderFolder = (folderNode, parentEl, depth) => {
      const folderWrap = document.createElement("details");
      folderWrap.className = "upload-tree-folder";
      const key = String(folderNode.key || folderNode.name || "");
      if (openFolderKeys.has(key)) folderWrap.open = true;
      else if (depth <= 1) folderWrap.open = true;

      folderWrap.addEventListener("toggle", () => {
        if (!key) return;
        if (folderWrap.open) openFolderKeys.add(key);
        else openFolderKeys.delete(key);
      });

      const summary = document.createElement("summary");
      summary.className = "upload-tree-folder-summary";

      const row = document.createElement("div");
      row.className = "upload-tree-folder-row";
      row.style.paddingLeft = `${Math.max(0, depth - 1) * 16}px`;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "uploads-folder-cb";

      const descendants = collectFolderFilePaths(folderNode);
      const selectedCount = descendants.filter((rel) => selected.has(rel)).length;
      cb.checked = descendants.length > 0 && selectedCount === descendants.length;
      setElementIndeterminate(cb, selectedCount > 0 && selectedCount < descendants.length);
      cb.addEventListener("click", (ev) => ev.stopPropagation());
      cb.addEventListener("change", () => {
        const shouldSelect = cb.checked;
        for (const rel of descendants) {
          if (shouldSelect) selected.add(rel);
          else selected.delete(rel);
        }
        renderUploadList();
      });

      const label = document.createElement("span");
      label.className = "upload-tree-folder-label";
      label.textContent = folderNode.name;
      label.title = folderNode.name;

      const count = document.createElement("span");
      count.className = "upload-tree-folder-count";
      count.textContent = `(${descendants.length})`;

      const unloadBtn = document.createElement("button");
      unloadBtn.type = "button";
      unloadBtn.className = "mini danger";
      unloadBtn.textContent = "Hide folder";
      unloadBtn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const out = await _unloadPaths(descendants);
        if (!out.ok) {
          window.alert(out.message);
          return;
        }
        await refreshUploadedList();
      });

      row.appendChild(cb);
      row.appendChild(label);
      row.appendChild(count);
      row.appendChild(unloadBtn);
      summary.appendChild(row);
      folderWrap.appendChild(summary);

      const children = document.createElement("div");
      children.className = "upload-tree-children";

      for (const child of sortedFolderEntries(folderNode)) {
        renderFolder(child, children, depth + 1);
      }
      for (const file of sortedFileEntries(folderNode)) {
        const rel = String(file.item.relative_path || "");
        const fileRow = document.createElement("div");
        fileRow.className = "uploads-item";
        fileRow.style.paddingLeft = `${depth * 16}px`;

        const fcb = document.createElement("input");
        fcb.type = "checkbox";
        fcb.className = "uploads-select-cb";
        fcb.setAttribute("data-relative-path", rel);
        fcb.checked = selected.has(rel);
        fcb.addEventListener("change", () => {
          if (fcb.checked) selected.add(rel);
          else selected.delete(rel);
          renderUploadList();
        });

        const sizeStr = formatFileSizeMb(file.item.size_bytes);
        const { short: labelsShort, full: labelsFull } = summarizeUploadLabels(file.item.labels);
        const baseTitle = `${file.item.filename} — ${sizeStr}\n${rel}`;
        const textSpan = document.createElement("span");
        textSpan.className = "uploads-item-label";
        textSpan.textContent = labelsShort
          ? `${file.name} (${sizeStr}) — ${labelsShort}`
          : `${file.name} (${sizeStr})`;
        textSpan.title = labelsFull ? `${baseTitle}\n${labelsFull}` : baseTitle;
        textSpan.style.cursor = "pointer";
        textSpan.addEventListener("click", () => {
          if (selected.has(rel)) selected.delete(rel);
          else selected.add(rel);
          renderUploadList();
        });

        fileRow.appendChild(fcb);
        fileRow.appendChild(textSpan);
        children.appendChild(fileRow);
      }

      folderWrap.appendChild(children);
      parentEl.appendChild(folderWrap);
    };

    for (const folder of folders) renderFolder(folder, uploadedListEl, 1);
    _emitSelection();
  }

  async function refreshUploadedList(options) {
    const isCancelled =
      typeof options === "function" ? options : options && typeof options.isCancelled === "function"
        ? options.isCancelled
        : null;
    try {
      const data = await fetchJson("/io/uploads?limit=5000");
      if (isCancelled?.()) return uploadedItems;
      if (!_mounted()) return uploadedItems;
      uploadedItems = data.items || [];
      totalCount = data.count != null ? Number(data.count) : uploadedItems.length;
      renderUploadList();
      if (typeof onUploadedItemsChange === "function") onUploadedItemsChange(uploadedItems, getTotalCount());
      return uploadedItems;
    } catch {
      if (isCancelled?.()) return uploadedItems;
      return uploadedItems;
    }
  }

  async function unloadSelected() {
    const out = await _unloadPaths(Array.from(selected));
    if (!out.ok) return out;
    selected = new Set();
    _emitSelection();
    return out;
  }

  async function unloadAll() {
    if (!uploadedItems || uploadedItems.length === 0) return { ok: true, message: "No uploaded files to hide." };
    const out = await _unloadPaths(uploadedItems.map((x) => x.relative_path));
    if (!out.ok) return out;
    selected = new Set();
    _emitSelection();
    return out;
  }

  return {
    refreshUploadedList,
    renderUploadList,
    unloadSelected,
    unloadAll,
    purgeUnusedHidden,
    getUploadedItems,
    getSelectedSet,
    getTotalCount,
    setSelectedSet,
  };
}

function stringifyForLabelEditor(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/**
 * Canonical label keys (match `extract_labels` in the backend). Always shown in the editor
 * so naming stays consistent even when auto-extraction finds nothing.
 */
export const DEFAULT_LABEL_KEYS = [
  "acquired_utc",
  "sample",
  "gas",
  "ph",
  "current_density_A_cm2",
  "potential_V",
  "potential_ref",
  "laser_nm",
  "laser_power_pct",
  "electrolyte",
  "concentration_M",
];

const DEFAULT_LABEL_KEY_SET = new Set(DEFAULT_LABEL_KEYS);

/** Short hint line listing default keys (for UI copy). */
export function defaultLabelKeysHintText() {
  return DEFAULT_LABEL_KEYS.join(", ");
}

/** Parse cell text to JSON scalar (null, bool, number, object/array via JSON) or string. */
export function coerceLabelValueFromText(text) {
  const s = String(text ?? "").trim();
  if (s === "") return null;
  const low = s.toLowerCase();
  if (low === "true") return true;
  if (low === "false") return false;
  if (low === "null") return null;
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}

/**
 * Current uploads only: multi-select tree list + labels table (PUT /io/labels, POST /io/labels/auto).
 * Default keys always appear so naming stays aligned with auto-extraction.
 */
export function createUploadedLabelsEditorController({ fileListEl, fileMetaEl, editorEl, onRefreshFromUploads }) {
  let fileItems = [];
  let selectedRels = new Set();
  let totalCount = 0;
  const openFolderKeys = new Set(); // persist expanded state across re-renders

  function itemByRel() {
    const m = new Map();
    for (const item of fileItems) m.set(item.relative_path, item);
    return m;
  }

  function pruneSelection() {
    const existing = new Set(fileItems.map((x) => x.relative_path));
    selectedRels = new Set(Array.from(selectedRels).filter((x) => existing.has(x)));
  }

  function selectedItems() {
    const m = itemByRel();
    return Array.from(selectedRels).map((rel) => m.get(rel)).filter(Boolean);
  }

  function updateMeta() {
    if (!fileMetaEl) return;
    const total = Number.isFinite(Number(totalCount)) && totalCount > 0 ? totalCount : fileItems.length;
    const n = selectedRels.size;
    fileMetaEl.textContent = n ? `${n} selected for editing` : `${fileItems.length} shown • ${total} total`;
  }

  function setContext({ items, selectedPaths, total }) {
    fileItems = Array.isArray(items) ? items : [];
    selectedRels = new Set(Array.isArray(selectedPaths) ? selectedPaths : []);
    totalCount = Number.isFinite(Number(total)) ? Number(total) : fileItems.length;
    pruneSelection();
    updateMeta();
    renderFileList();
    renderEditor();
  }

  function setSelection(paths) {
    selectedRels = new Set(Array.isArray(paths) ? paths : []);
    pruneSelection();
    updateMeta();
    renderFileList();
    renderEditor();
  }

  function renderFileList() {
    if (!fileListEl) return;
    fileListEl.innerHTML = "";
    pruneSelection();

    const tree = buildUploadsTree(fileItems);
    const folders = sortedFolderEntries(tree);
    if (!folders.length) return;

    const renderFolder = (folderNode, parentEl, depth) => {
      const wrap = document.createElement("details");
      wrap.className = "upload-tree-folder";
      const key = String(folderNode.key || folderNode.name || "");
      if (openFolderKeys.has(key)) wrap.open = true;
      else if (depth <= 1) wrap.open = true;

      wrap.addEventListener("toggle", () => {
        if (!key) return;
        if (wrap.open) openFolderKeys.add(key);
        else openFolderKeys.delete(key);
      });

      const summary = document.createElement("summary");
      summary.className = "upload-tree-folder-summary";

      const row = document.createElement("div");
      row.className = "upload-tree-folder-row";
      row.style.paddingLeft = `${Math.max(0, depth - 1) * 16}px`;

      const descendants = collectFolderFilePaths(folderNode);
      const checkedCount = descendants.filter((rel) => selectedRels.has(rel)).length;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "uploads-folder-cb";
      cb.checked = descendants.length > 0 && checkedCount === descendants.length;
      setElementIndeterminate(cb, checkedCount > 0 && checkedCount < descendants.length);
      cb.addEventListener("click", (ev) => ev.stopPropagation());
      cb.addEventListener("change", () => {
        if (cb.checked) {
          for (const rel of descendants) selectedRels.add(rel);
        } else {
          for (const rel of descendants) selectedRels.delete(rel);
        }
        renderFileList();
        renderEditor();
      });

      const label = document.createElement("span");
      label.className = "upload-tree-folder-label";
      label.textContent = folderNode.name;

      const count = document.createElement("span");
      count.className = "upload-tree-folder-count";
      count.textContent = `(${descendants.length})`;

      row.appendChild(cb);
      row.appendChild(label);
      row.appendChild(count);
      summary.appendChild(row);
      wrap.appendChild(summary);

      const children = document.createElement("div");
      children.className = "upload-tree-children";

      for (const child of sortedFolderEntries(folderNode)) {
        renderFolder(child, children, depth + 1);
      }
      for (const file of sortedFileEntries(folderNode)) {
        const rel = String(file.item.relative_path || "");
        const fileRow = document.createElement("div");
        fileRow.className = "upload-labels-file-item";
        fileRow.style.paddingLeft = `${depth * 16}px`;
        if (selectedRels.has(rel)) fileRow.classList.add("selected");

        const cbFile = document.createElement("input");
        cbFile.type = "checkbox";
        cbFile.className = "uploads-select-cb";
        cbFile.checked = selectedRels.has(rel);
        cbFile.addEventListener("change", () => {
          if (cbFile.checked) selectedRels.add(rel);
          else selectedRels.delete(rel);
          renderFileList();
          renderEditor();
        });

        const title = document.createElement("div");
        title.className = "upload-labels-file-title";
        const sizeStr = formatFileSizeMb(file.item.size_bytes);
        const { short: labelsShort } = summarizeUploadLabels(file.item.labels);
        title.textContent = labelsShort ? `${file.name} — ${labelsShort}` : file.name;
        title.title = `${rel}\n${sizeStr}`;
        title.addEventListener("click", () => {
          if (selectedRels.has(rel)) selectedRels.delete(rel);
          else selectedRels.add(rel);
          renderFileList();
          renderEditor();
        });

        const meta = document.createElement("div");
        meta.className = "upload-labels-file-meta";
        const savedAt = file.item.saved_at ? String(file.item.saved_at) : "";
        const modifiedUtc = file.item.modified_utc ? String(file.item.modified_utc) : "";
        const when = modifiedUtc ? `modified ${modifiedUtc}` : savedAt ? `saved ${savedAt}` : "";
        meta.textContent = `${sizeStr}${when ? ` • ${when}` : ""}`;

        const textWrap = document.createElement("div");
        textWrap.style.minWidth = "0";
        textWrap.style.flex = "1";
        textWrap.appendChild(title);
        textWrap.appendChild(meta);

        fileRow.appendChild(cbFile);
        fileRow.appendChild(textWrap);
        children.appendChild(fileRow);
      }

      wrap.appendChild(children);
      parentEl.appendChild(wrap);
    };

    for (const folder of folders) renderFolder(folder, fileListEl, 1);
  }

  function renderEditor() {
    if (!editorEl) return;
    editorEl.innerHTML = "";

    const selected = selectedItems();
    const selectedCount = selected.length;
    if (selectedCount === 0) return;

    const info = document.createElement("p");
    info.className = "hint";
    info.textContent =
      selectedCount === 1
        ? `Editing labels for 1 file: ${selected[0].filename}`
        : `Bulk edit mode for ${selectedCount} files. Only changed fields will be overwritten.`;
    editorEl.appendChild(info);

    const primary = selectedCount === 1 ? selected[0] : null;
    const labels = primary && typeof primary.labels === "object" ? primary.labels : {};

    const table = document.createElement("table");
    table.className = "labels-editor-table";
    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    const h1 = document.createElement("th");
    h1.textContent = "Key";
    const h2 = document.createElement("th");
    h2.textContent = "Value";
    hr.appendChild(h1);
    hr.appendChild(h2);
    thead.appendChild(hr);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");

    let fixedRowCount = 0;

    function appendFixedKeyRow(key, val) {
      const tr = document.createElement("tr");
      tr.dataset.rowKind = "fixed";
      const tdK = document.createElement("td");
      tdK.className = "labels-editor-key-fixed";
      const code = document.createElement("code");
      code.textContent = key;
      tdK.appendChild(code);
      const tdV = document.createElement("td");
      const inV = document.createElement("input");
      inV.type = "text";
      inV.className = "label-value";
      inV.dataset.fixedKey = key;
      inV.dataset.initial = val;
      inV.value = val;
      inV.autocomplete = "off";
      if (key === "acquired_utc") {
        inV.disabled = true;
        inV.title = "Automatically set from the original file last-modified time (UTC) before upload.";
      }
      tdV.appendChild(inV);
      tr.appendChild(tdK);
      tr.appendChild(tdV);
      tbody.appendChild(tr);
      fixedRowCount += 1;
    }

    function appendExtraRow(key, val) {
      const tr = document.createElement("tr");
      tr.dataset.rowKind = "extra";
      const tdK = document.createElement("td");
      const tdV = document.createElement("td");
      const inK = document.createElement("input");
      inK.type = "text";
      inK.className = "label-key";
      inK.value = key;
      inK.dataset.initial = key;
      inK.autocomplete = "off";
      const inV = document.createElement("input");
      inV.type = "text";
      inV.className = "label-value";
      inV.value = val;
      inV.dataset.initial = val;
      inV.autocomplete = "off";
      tdK.appendChild(inK);
      tdV.appendChild(inV);
      tr.appendChild(tdK);
      tr.appendChild(tdV);
      tbody.appendChild(tr);
    }

    for (const key of DEFAULT_LABEL_KEYS) {
      const v = Object.prototype.hasOwnProperty.call(labels, key) ? labels[key] : undefined;
      appendFixedKeyRow(key, stringifyForLabelEditor(v));
    }

    if (primary) {
      const o = labels && typeof labels === "object" ? labels : {};
      for (const k of Object.keys(o).sort()) {
        if (DEFAULT_LABEL_KEY_SET.has(k)) continue;
        appendExtraRow(k, stringifyForLabelEditor(o[k]));
      }
    }

    table.appendChild(tbody);
    editorEl.appendChild(table);

    const toolbar = document.createElement("div");
    toolbar.className = "row labels-editor-toolbar";

    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.textContent = "Add custom row";
    addBtn.addEventListener("click", () => appendExtraRow("", ""));

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "mini danger";
    removeBtn.textContent = "Remove last custom row";
    removeBtn.addEventListener("click", () => {
      const trs = tbody.querySelectorAll("tr");
      if (trs.length <= fixedRowCount) return;
      trs[trs.length - 1].remove();
    });

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.textContent = selectedCount === 1 ? "Save" : `Apply to ${selectedCount} files`;
    saveBtn.addEventListener("click", async () => {
      const patch = {};

      for (const key of DEFAULT_LABEL_KEYS) {
        const input = tbody.querySelector(`input.label-value[data-fixed-key="${key}"]`);
        const raw = input ? String(input.value ?? "") : "";
        const initial = input ? String(input.dataset.initial ?? "") : "";
        if (raw === initial) continue;
        patch[key] = coerceLabelValueFromText(raw);
      }
      for (const tr of tbody.querySelectorAll('tr[data-row-kind="extra"]')) {
        const keyEl = tr.querySelector(".label-key");
        const valEl = tr.querySelector(".label-value");
        const keyRaw = keyEl ? String(keyEl.value || "").trim() : "";
        const keyInitial = keyEl ? String(keyEl.dataset.initial || "").trim() : "";
        const valRaw = valEl ? String(valEl.value || "") : "";
        const valInitial = valEl ? String(valEl.dataset.initial || "") : "";
        if (keyRaw === "" && valRaw === "") continue;
        if (keyRaw === keyInitial && valRaw === valInitial) continue;
        if (!keyRaw) continue;
        if (DEFAULT_LABEL_KEY_SET.has(keyRaw)) continue;
        patch[keyRaw] = coerceLabelValueFromText(valRaw);
      }

      const changedKeys = Object.keys(patch);
      if (!changedKeys.length) {
        window.alert("No label changes detected.");
        return;
      }

      const byRel = itemByRel();
      for (const rel of Array.from(selectedRels)) {
        const item = byRel.get(rel);
        const prev = item && item.labels && typeof item.labels === "object" ? item.labels : {};
        const merged = { ...prev };
        for (const k of changedKeys) merged[k] = patch[k];
        const { res, text } = await fetchText("/io/labels", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ relative_path: rel, labels: merged }),
        });
        if (!res.ok) {
          window.alert(text || `Save failed (${res.status}) on ${rel}.`);
          return;
        }
      }
      await refreshFromUploads();
    });

    const autoBtn = document.createElement("button");
    autoBtn.type = "button";
    autoBtn.className = "mini";
    autoBtn.textContent = selectedCount === 1 ? "Reload auto labels" : `Reload auto labels (${selectedCount})`;
    autoBtn.addEventListener("click", async () => {
      const rels = Array.from(selectedRels);
      if (!rels.length) return;
      const res = await fetch("/io/labels/auto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ relative_paths: rels }),
      });
      let msg = "";
      try {
        const data = await res.json();
        msg =
          data && typeof data === "object"
            ? `Auto labels: updated ${data.updated || 0}/${data.requested || rels.length}, missing ${data.missing || 0}, failed ${data.failed || 0}.`
            : "";
      } catch {
        msg = "";
      }
      if (!res.ok) {
        window.alert(msg || `Auto-label reload failed (${res.status}).`);
        return;
      }
      if (msg) window.alert(msg);
      await refreshFromUploads();
    });

    toolbar.appendChild(addBtn);
    toolbar.appendChild(removeBtn);
    toolbar.appendChild(saveBtn);
    toolbar.appendChild(autoBtn);
    editorEl.appendChild(toolbar);
  }

  async function refreshFromUploads() {
    if (typeof onRefreshFromUploads === "function") {
      await onRefreshFromUploads();
      return fileItems;
    }
    if (!fileMetaEl) return fileItems;
    try {
      const data = await fetchJson("/io/uploads?limit=5000");
      fileItems = data.items || [];
      pruneSelection();
      totalCount = data.count != null ? Number(data.count) : fileItems.length;
      updateMeta();
      renderFileList();
      renderEditor();
      return fileItems;
    } catch {
      fileMetaEl.textContent = "Failed to load uploads.";
      return fileItems;
    }
  }

  return { refreshFromUploads, renderFileList, renderEditor, setContext, setSelection };
}
