import { $ } from "./ui/dom.js";
import { createUploadsController, createUploadedLabelsEditorController, formatFileSizeMb } from "./ui/uploads.js";
import { fetchFigure, getSelectedPaths, plotFromEndpoint } from "./ui/plot.js";
import { buildFileOptionsHtml, createMapUi, createSeriesUi } from "./ui/plot_selectors.js";
import { wireColumnSplitter } from "./ui/column_splitter.js";

const drop = $("drop");
const fileInput = $("files");
const folderInput = $("folders");
const uploadBtn = $("uploadBtn");
const clearSelectionBtn = $("clearSelectionBtn");
const refreshBtn = $("refreshBtn");
const excludeExtsInput = $("excludeExts");
const extFilterModeSelect = $("extFilterMode");
const err = $("error");
const status = $("status");
const fileList = $("fileList");
const uploadedList = $("uploadedList");
const uploadsMeta = $("uploadsMeta");
const selectAllBtn = $("selectAllBtn");
const selectNoneBtn = $("selectNoneBtn");
const unloadBtn = $("unloadBtn");
const unloadAllBtn = $("unloadAllBtn");
const purgeHiddenBtn = $("purgeHiddenBtn");
const labelsEditor = $("labelsEditor");

const rawRefreshBtn = $("rawRefreshBtn");
const addPlotFileBtn = $("addPlotFileBtn");
const plotFileSelectors = $("plotFileSelectors");
const plotSpectrumBtn = $("plotSpectrumBtn");
const plotSeriesHeatmapBtn = $("plotSeriesHeatmapBtn");
const plotModeSelect = $("plotMode");
const stackSepInput = $("stackSep");
const plotDiv = $("plot");

function setStatus(s) {
  status.textContent = s || "";
}
function showError(message) {
  err.style.display = "block";
  err.textContent = message;
}
function clearError() {
  err.style.display = "none";
  err.textContent = "";
}

function clearQueuedSelection() {
  clearError();
  setStatus("");
  if (fileInput) fileInput.value = "";
  if (folderInput) folderInput.value = "";
  if (fileList) fileList.innerHTML = "";
}

function listSelectedFiles(files) {
  fileList.innerHTML = "";
  if (!files || files.length === 0) return;
  const maxShow = 200;
  const shown = Array.from(files).slice(0, maxShow);
  for (const f of shown) {
    const li = document.createElement("li");
    const relName = String(f.webkitRelativePath || f.name || "");
    li.textContent = `${relName} (${formatFileSizeMb(f.size)})`;
    li.title = `${relName} — ${formatFileSizeMb(f.size)}`;
    fileList.appendChild(li);
  }
  const remaining = files.length - shown.length;
  if (remaining > 0) {
    const li = document.createElement("li");
    li.textContent = `…and ${remaining} more`;
    fileList.appendChild(li);
  }
}

function queuedFiles() {
  const out = [];
  if (fileInput && fileInput.files) out.push(...Array.from(fileInput.files));
  if (folderInput && folderInput.files) out.push(...Array.from(folderInput.files));
  return out;
}

function _parseExtensionFilterList() {
  const raw = excludeExtsInput ? String(excludeExtsInput.value || "") : "";
  const parts = raw
    .split(/[,\s]+/g)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
    .map((s) => (s.startsWith(".") ? s.slice(1) : s));
  return new Set(parts);
}

function _extFilterMode() {
  const v = extFilterModeSelect ? String(extFilterModeSelect.value || "") : "only";
  return v === "only" ? "only" : "skip";
}

function _fileExtLower(name) {
  const s = String(name || "");
  const i = s.lastIndexOf(".");
  if (i < 0) return "";
  return s.slice(i + 1).toLowerCase();
}

function applyUploadFilters(files) {
  const mode = _extFilterMode();
  const exts = _parseExtensionFilterList();
  if (!exts.size) return { kept: Array.from(files || []), skipped: [] };
  const kept = [];
  const skipped = [];
  for (const f of Array.from(files || [])) {
    const relName = String(f.webkitRelativePath || f.name || "");
    const ext = _fileExtLower(relName);
    if (mode === "skip") {
      if (ext && exts.has(ext)) skipped.push(f);
      else kept.push(f);
    } else {
      if (ext && exts.has(ext)) kept.push(f);
      else skipped.push(f);
    }
  }
  return { kept, skipped };
}

let uploadedLabelsEditor = null;
const uploads = createUploadsController({
  uploadedListEl: uploadedList,
  uploadsMetaEl: uploadsMeta,
  onSelectedPathsChange: (paths, items, total) => {
    uploadedLabelsEditor?.setContext({ items, selectedPaths: paths, total });
  },
  onUploadedItemsChange: () => syncUploadsAfterListChange(),
});
uploadedLabelsEditor = createUploadedLabelsEditorController({
  editorEl: labelsEditor,
  onRefreshFromUploads: () => refreshUploadedList(),
});

let selectorIds = [crypto.randomUUID()];
let seriesUiBySelectorId = new Map(); // selectorId -> { wrap, setFile, getState }
let mapUiBySelectorId = new Map(); // selectorId -> { wrap, setFile, getState }
let mapStateByFile = new Map(); // relative_path -> { selectedIndices: number[] }

let _plotUpdateTimer = null;
function schedulePlotUpdate() {
  if (_plotUpdateTimer) clearTimeout(_plotUpdateTimer);
  _plotUpdateTimer = setTimeout(() => {
    plotCombinedSelection();
  }, 120);
}

function renderPlotSelectors() {
  if (!plotFileSelectors) return;
  const uploadedItems = uploads.getUploadedItems();
  const existing = new Set(uploadedItems.map((x) => x.relative_path));
  if (!selectorIds || selectorIds.length === 0) selectorIds = [crypto.randomUUID()];

  const currentValuesById = new Map();
  for (const id of selectorIds) {
    const el = document.querySelector(`select[data-sel-id="${id}"]`);
    const v = el ? el.value : "";
    currentValuesById.set(id, existing.has(v) ? v : "");
  }

  plotFileSelectors.innerHTML = "";
  seriesUiBySelectorId = new Map();
  mapUiBySelectorId = new Map();

  for (const id of selectorIds) {
    const row = document.createElement("div");
    row.className = "selector-row";

    const select = document.createElement("select");
    select.setAttribute("data-sel-id", id);
    const selectedValue = currentValuesById.get(id) || "";
    select.innerHTML = buildFileOptionsHtml(uploadedItems, selectedValue);

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "mini danger";
    removeBtn.textContent = "-";
    removeBtn.title = "Remove this file selector";
    removeBtn.disabled = selectorIds.length <= 1;
    removeBtn.addEventListener("click", () => {
      selectorIds = selectorIds.filter((x) => x !== id);
      renderPlotSelectors();
      schedulePlotUpdate();
    });

    row.appendChild(select);
    row.appendChild(removeBtn);
    plotFileSelectors.appendChild(row);

    const seriesUi = createSeriesUi({ selectorId: id, schedulePlotUpdate });
    seriesUiBySelectorId.set(id, seriesUi);
    plotFileSelectors.appendChild(seriesUi.wrap);
    seriesUi.setFile((selectedValue || "").trim());

    const mapUi = createMapUi({ selectorId: id, mapStateByFile, schedulePlotUpdate });
    mapUiBySelectorId.set(id, mapUi);
    plotFileSelectors.appendChild(mapUi.wrap);
    mapUi.setFile((selectedValue || "").trim());

    select.addEventListener("change", () => {
      seriesUi.setFile((select.value || "").trim());
      mapUi.setFile((select.value || "").trim());
    });
  }
}

/** Notify other tabs/frames (e.g. the Prepare / Analyze panel) that the uploads list changed. */
const _uploadsChangedChannel = new BroadcastChannel("sersflow:uploads-changed");

async function refreshUploadedList() {
  await uploads.refreshUploadedList();
}

function syncUploadsAfterListChange() {
  uploadedLabelsEditor?.setContext({
    items: uploads.getUploadedItems(),
    selectedPaths: Array.from(uploads.getSelectedSet()),
    total: uploads.getTotalCount(),
  });
  renderPlotSelectors();
  _uploadsChangedChannel.postMessage({ ts: Date.now() });
}

function chunkArray(arr, chunkSize) {
  const out = [];
  const n = arr.length;
  const size = Math.max(1, Number(chunkSize) || 1);
  for (let i = 0; i < n; i += size) out.push(arr.slice(i, i + size));
  return out;
}

async function withTimeout(promise, timeoutMs, label = "operation") {
  const ms = Math.max(0, Number(timeoutMs) || 0);
  if (!ms) return await promise;
  let timer = null;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function probeFilesReadable(files, { timeoutPerFileMs = 10000 } = {}) {
  // This catches a very common “0 bytes sent forever” failure mode on Windows/OneDrive:
  // the browser hangs trying to read placeholder/cloud-only files while streaming the request body.
  const bad = [];
  for (const f of files) {
    const relName = String(f.webkitRelativePath || f.name || "").trim() || f.name;
    try {
      const p = f.slice(0, 1).arrayBuffer();
      await withTimeout(p, timeoutPerFileMs, `Read "${relName}"`);
    } catch (e) {
      bad.push(relName);
    }
  }
  return bad;
}

async function uploadChunk(files, { batchIndex, batchCount, uploadedSoFar, totalFiles, totalBytes }) {
  setStatus(`Preparing batch ${batchIndex + 1}/${batchCount} (${files.length} files)…`);

  setStatus(`Checking local readability for batch ${batchIndex + 1}/${batchCount}…`);
  const unreadable = await probeFilesReadable(files, { timeoutPerFileMs: 10000 });
  if (unreadable.length) {
    const shown = unreadable.slice(0, 10);
    const more = unreadable.length - shown.length;
    const suffix = more > 0 ? ` …and ${more} more` : "";
    throw new Error(
      `Some files could not be read locally (often OneDrive “online-only” placeholders or AV locking). ` +
        `Move the folder to a local path (e.g. C:\\temp\\) and retry. Unreadable: ${shown.join(", ")}${suffix}`
    );
  }

  const fd = new FormData();
  const sourceModifiedMs = {};
  for (const f of files) {
    const relName = String(f.webkitRelativePath || f.name || "").trim();
    fd.append("files", f, relName || f.name);
    if (relName && Number.isFinite(f.lastModified) && f.lastModified > 0) {
      sourceModifiedMs[relName] = f.lastModified;
    }
  }
  if (Object.keys(sourceModifiedMs).length) {
    fd.append("source_modified_ms_json", JSON.stringify(sourceModifiedMs));
  }
  const chunkBytes = Array.from(files).reduce((acc, f) => acc + (f.size || 0), 0);
  setStatus(
    `Uploading batch ${batchIndex + 1}/${batchCount} — ` +
      `${uploadedSoFar}/${totalFiles} files (` +
      `${formatFileSizeMb(totalBytes)} total, ${formatFileSizeMb(chunkBytes)} this batch)…`
  );

  const maxAttempts = 2;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    // Fail-fast: prevents “stuck forever” when the request stalls.
    const timeoutMs = 3 * 60 * 1000;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      setStatus(`Sending batch ${batchIndex + 1}/${batchCount} (attempt ${attempt}/${maxAttempts})…`);
      const res = await fetch(`/io/upload`, {
        method: "POST",
        body: fd,
        signal: controller.signal,
        credentials: "include",
      });
      const text = await res.text();
      if (!res.ok) throw new Error(text || `Upload failed (${res.status}).`);
      return text || "Uploaded.";
    } catch (e) {
      const msg = String(e && e.message ? e.message : e);
      const isLast = attempt === maxAttempts;
      if (isLast) throw new Error(msg || "Upload failed.");
      setStatus(
        `Batch ${batchIndex + 1}/${batchCount} stalled/failed (attempt ${attempt}/${maxAttempts}). Retrying…`
      );
      await new Promise((r) => setTimeout(r, 500));
    } finally {
      clearTimeout(timer);
    }
  }
  return "Uploaded.";
}

async function upload(files) {
  clearError();
  if (!files || files.length === 0) {
    showError("No files selected.");
    return;
  }

  const filtered = applyUploadFilters(files);
  const all = filtered.kept;
  if (filtered.skipped.length) {
    const mode = _extFilterMode();
    const hint = mode === "only" ? "Only extensions" : "Skip extensions";
    setStatus(`Skipping ${filtered.skipped.length} file(s) due to extension filter (${hint}).`);
  }
  if (!all.length) {
    showError("All selected files were skipped by the current extension filter.");
    return;
  }
  const totalBytes = all.reduce((acc, f) => acc + (f.size || 0), 0);
  // Reliability defaults for many small files: smaller chunks + low concurrency.
  const chunks = chunkArray(all, 25);
  const concurrency = 1;

  let completedFiles = 0;
  let lastMessage = "";
  const queue = chunks.map((chunk, i) => ({ chunk, i }));

  async function worker() {
    while (queue.length) {
      const next = queue.shift();
      if (!next) return;
      const { chunk, i } = next;
      try {
        lastMessage = await uploadChunk(chunk, {
          batchIndex: i,
          batchCount: chunks.length,
          uploadedSoFar: completedFiles,
          totalFiles: all.length,
          totalBytes,
        });
        completedFiles += chunk.length;
        setStatus(`Uploaded ${completedFiles}/${all.length} files…`);
        // Small breather so the browser can flush IO / UI.
        await new Promise((r) => setTimeout(r, 50));
      } catch (e) {
        throw new Error(String(e && e.message ? e.message : e));
      }
    }
  }

  try {
    const workers = Array.from({ length: Math.min(concurrency, chunks.length) }, () => worker());
    await Promise.all(workers);
  } catch (e) {
    showError(String(e && e.message ? e.message : e));
    setStatus("Upload failed.");
    return;
  }

  setStatus(lastMessage || `Uploaded ${completedFiles} file(s).`);
  await refreshUploadedList();
}

async function plotCombinedSelection() {
  clearError();
  try {
    const paths = getSelectedPaths(plotFileSelectors);
    if (!paths.length) {
      showError("Select at least 1 file to plot.");
      return;
    }

    const figs = [];
    for (const rel of paths) {
      let usedSeries = false;
      for (const ui of seriesUiBySelectorId.values()) {
        const st = ui.getState();
        if (st.relativePath === rel && st.count > 0) {
          const indices = (st.selectedIndices || []).slice(0, 30);
          if (!indices.length) throw new Error(`No series points selected for: ${rel}`);
          figs.push(await fetchFigure("/plot/series-points", { relative_path: rel, indices }));
          usedSeries = true;
          break;
        }
      }
      if (usedSeries) continue;

      let usedMap = false;
      for (const ui of mapUiBySelectorId.values()) {
        const st = ui.getState();
        if (st.relativePath === rel && st.isMap) {
          const indices = (st.selectedIndices || []).slice(0, 30);
          if (!indices.length) throw new Error(`No map points selected for: ${rel}`);
          figs.push(await fetchFigure("/plot/map-points", { relative_path: rel, indices }));
          usedMap = true;
          break;
        }
      }
      if (usedMap) continue;

      figs.push(
        await fetchFigure("/plot/spectrum", {
          relative_path: rel,
        })
      );
    }

    if (!figs.length) return;
    const combined = {
      data: [],
      layout: { ...(figs[0].layout || {}) },
    };
    for (const f of figs) {
      if (Array.isArray(f.data)) combined.data.push(...f.data);
    }

    // Optional stacking when multiple traces exist.
    const mode = plotModeSelect && plotModeSelect.value ? String(plotModeSelect.value) : "overlay";
    if (mode === "stack" && combined.data.length > 1) {
      const sepRaw = stackSepInput ? Number(stackSepInput.value) : 0;
      const sep = Number.isFinite(sepRaw) ? sepRaw : 0;
      combined.data = combined.data.map((tr, i) => {
        const y = Array.isArray(tr.y) ? tr.y : null;
        if (!y || sep === 0) return tr;
        const y2 = y.map((v) => (Number.isFinite(Number(v)) ? Number(v) + i * sep : v));
        return { ...tr, y: y2 };
      });
    }
    Plotly.react(plotDiv, combined.data, combined.layout, { responsive: true });
  } catch (e) {
    showError(String(e && e.message ? e.message : e));
  }
}

async function plotSeriesHeatmap() {
  const paths = getSelectedPaths(plotFileSelectors);
  if (paths.length !== 1) {
    showError("Select exactly 1 file for series heatmap.");
    return;
  }
  await plotFromEndpoint({
    plotDiv,
    endpoint: "/plot/series-heatmap",
    payload: { relative_path: paths[0] },
    showError,
    clearError,
  });
}

function initTabs() {
  const tabs = document.querySelectorAll("#tabs .tab");
  const tabUploads = $("tab-uploads");
  const tabRaw = $("tab-raw");
  const tabSpa = $("tab-spa");

  if (!tabUploads || !tabRaw || !tabSpa) return;

  function setActiveTabButton(dataTab) {
    for (const t of tabs) {
      t.classList.toggle("active", t.getAttribute("data-tab") === dataTab);
    }
  }

  function showPanel(el) {
    for (const p of [tabUploads, tabRaw, tabSpa]) p.classList.remove("active");
    el.classList.add("active");
  }

  for (const t of tabs) {
    t.addEventListener("click", () => {
      const key = t.getAttribute("data-tab");
      setActiveTabButton(key);
      if (key === "uploads") showPanel(tabUploads);
      else if (key === "raw") showPanel(tabRaw);
      else if (key === "prepare") {
        showPanel(tabSpa);
        window.location.hash = "#/";
      } else if (key === "analyze") {
        showPanel(tabSpa);
        window.location.hash = "#/analyze";
      }
    });
  }

  window.addEventListener("hashchange", () => {
    if (!tabSpa.classList.contains("active")) return;
    const analyze = window.location.hash.includes("/analyze");
    setActiveTabButton(analyze ? "analyze" : "prepare");
  });

  if (window.location.hash.includes("/analyze")) {
    setActiveTabButton("analyze");
    showPanel(tabSpa);
  }
}

drop.addEventListener("dragover", (e) => {
  e.preventDefault();
  drop.classList.add("dragover");
});
drop.addEventListener("dragleave", () => drop.classList.remove("dragover"));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  drop.classList.remove("dragover");
  if (e.dataTransfer.files && e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    const filtered = applyUploadFilters(fileInput.files);
    listSelectedFiles(filtered.kept);
    upload(filtered.kept);
  }
});

function refreshQueuedPreview() {
  const filtered = applyUploadFilters(queuedFiles());
  listSelectedFiles(filtered.kept);
  if (filtered.skipped.length) {
    const mode = _extFilterMode();
    const hint = mode === "only" ? "Only extensions" : "Skip extensions";
    setStatus(
      `Queued ${filtered.kept.length} file(s), skipping ${filtered.skipped.length} due to extension filter (${hint}).`
    );
  } else if (filtered.kept.length) {
    const mode = _extFilterMode();
    const hint = mode === "only" ? "Only extensions" : "Skip extensions";
    setStatus(`Queued ${filtered.kept.length} file(s). Extension filter mode: ${hint}.`);
  }
}

fileInput.addEventListener("change", () => refreshQueuedPreview());
if (folderInput) folderInput.addEventListener("change", () => refreshQueuedPreview());
if (excludeExtsInput) excludeExtsInput.addEventListener("input", () => refreshQueuedPreview());
if (extFilterModeSelect) extFilterModeSelect.addEventListener("change", () => refreshQueuedPreview());
uploadBtn.addEventListener("click", () => {
  const filtered = applyUploadFilters(queuedFiles());
  upload(filtered.kept);
});
if (clearSelectionBtn) clearSelectionBtn.addEventListener("click", () => clearQueuedSelection());

refreshBtn.addEventListener("click", () => refreshUploadedList());
rawRefreshBtn.addEventListener("click", () => refreshUploadedList());

selectAllBtn.addEventListener("click", () => {
  uploads.setSelectedSet(new Set(uploads.getUploadedItems().map((x) => x.relative_path)));
  uploads.renderUploadList();
});
selectNoneBtn.addEventListener("click", () => {
  uploads.setSelectedSet(new Set());
  uploads.renderUploadList();
});

unloadBtn.addEventListener("click", async () => {
  clearError();
  setStatus("Hiding selected files...");
  const out = await uploads.unloadSelected();
  if (!out.ok) {
    showError(out.message);
    setStatus("Hide failed.");
    return;
  }
  setStatus(out.message);
  await refreshUploadedList();
  schedulePlotUpdate();
});

unloadAllBtn.addEventListener("click", async () => {
  clearError();
  setStatus("Hiding all files...");
  const out = await uploads.unloadAll();
  if (!out.ok) {
    showError(out.message);
    setStatus("Hide failed.");
    return;
  }
  setStatus(out.message);
  await refreshUploadedList();
  schedulePlotUpdate();
});

purgeHiddenBtn.addEventListener("click", async () => {
  clearError();
  setStatus("Preparing purge preview...");
  try {
    const out = await uploads.purgeUnusedHidden();
    if (!out.ok) {
      showError(out.message);
      setStatus("Purge failed.");
      return;
    }
    setStatus(out.message);
    await refreshUploadedList();
    schedulePlotUpdate();
  } catch (e) {
    showError(String(e?.message || e));
    setStatus("Purge failed.");
  }
});

plotSpectrumBtn.addEventListener("click", () => plotCombinedSelection());
plotSeriesHeatmapBtn.addEventListener("click", () => plotSeriesHeatmap());
if (plotModeSelect) plotModeSelect.addEventListener("change", () => schedulePlotUpdate());
if (stackSepInput) stackSepInput.addEventListener("input", () => schedulePlotUpdate());

addPlotFileBtn.addEventListener("click", () => {
  selectorIds.push(crypto.randomUUID());
  renderPlotSelectors();
});

initTabs();
refreshUploadedList();

wireColumnSplitter({
  layoutEl: $("rawLayout"),
  leftEl: $("rawLeft"),
  handleEl: $("rawSplitHandle"),
  storageKey: "sersflow:raw-sidebar-w",
  defaultWidth: 340,
  minWidth: 280,
  maxWidth: 720,
  onResizeEnd: () => {
    if (plotDiv && window.Plotly) {
      try {
        window.Plotly.Plots.resize(plotDiv);
      } catch {
        // ignore
      }
    }
  },
});

