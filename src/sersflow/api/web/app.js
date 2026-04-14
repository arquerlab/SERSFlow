import { $ } from "./ui/dom.js";
import { createUploadsController, formatFileSizeMb } from "./ui/uploads.js";
import { fetchFigure, getSelectedPaths, plotFromEndpoint } from "./ui/plot.js";
import { buildFileOptionsHtml, createMapUi, createSeriesUi } from "./ui/plot_selectors.js";

const drop = $("drop");
const fileInput = $("files");
const uploadBtn = $("uploadBtn");
const refreshBtn = $("refreshBtn");
const err = $("error");
const status = $("status");
const fileList = $("fileList");
const uploadedList = $("uploadedList");
const uploadsMeta = $("uploadsMeta");
const selectAllBtn = $("selectAllBtn");
const selectNoneBtn = $("selectNoneBtn");
const unloadBtn = $("unloadBtn");
const unloadAllBtn = $("unloadAllBtn");

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

function listSelectedFiles(files) {
  fileList.innerHTML = "";
  if (!files || files.length === 0) return;
  for (const f of files) {
    const li = document.createElement("li");
    li.textContent = `${f.name} (${formatFileSizeMb(f.size)})`;
    li.title = `${f.name} — ${formatFileSizeMb(f.size)}`;
    fileList.appendChild(li);
  }
}

const uploads = createUploadsController({ uploadedListEl: uploadedList, uploadsMetaEl: uploadsMeta });

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

async function refreshUploadedList() {
  await uploads.refreshUploadedList();
  renderPlotSelectors();
}

async function upload(files) {
  clearError();
  if (!files || files.length === 0) {
    showError("No files selected.");
    return;
  }
  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  const totalBytes = Array.from(files).reduce((acc, f) => acc + (f.size || 0), 0);
  setStatus(`Uploading ${files.length} file(s) (${formatFileSizeMb(totalBytes)})...`);
  const res = await fetch(`/io/upload`, { method: "POST", body: fd });
  const text = await res.text();
  if (!res.ok) {
    showError(text || `Upload failed (${res.status}).`);
    setStatus("Upload failed.");
    return;
  }
  setStatus(text || "Uploaded.");
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
  const panels = { uploads: $("tab-uploads"), raw: $("tab-raw"), preprocess: $("tab-preprocess") };
  for (const t of tabs) {
    t.addEventListener("click", () => {
      for (const t2 of tabs) t2.classList.remove("active");
      t.classList.add("active");
      const key = t.getAttribute("data-tab");
      for (const k of Object.keys(panels)) panels[k].classList.remove("active");
      panels[key].classList.add("active");
    });
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
    listSelectedFiles(fileInput.files);
    upload(fileInput.files);
  }
});

fileInput.addEventListener("change", () => listSelectedFiles(fileInput.files));
uploadBtn.addEventListener("click", () => upload(fileInput.files));

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
  setStatus("Unloading selected files...");
  const out = await uploads.unloadSelected();
  if (!out.ok) {
    showError(out.message);
    setStatus("Unload failed.");
    return;
  }
  setStatus(out.message);
  renderPlotSelectors();
  schedulePlotUpdate();
});

unloadAllBtn.addEventListener("click", async () => {
  clearError();
  setStatus("Unloading all files...");
  const out = await uploads.unloadAll();
  if (!out.ok) {
    showError(out.message);
    setStatus("Unload failed.");
    return;
  }
  setStatus(out.message);
  renderPlotSelectors();
  schedulePlotUpdate();
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

