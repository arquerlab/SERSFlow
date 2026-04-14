import { escapeHtml } from "./dom.js";
import { formatFileSizeMb } from "./uploads.js";

export function buildFileOptionsHtml(uploadedItems, selectedValue) {
  const opts = [];
  opts.push(`<option value="">Select a file…</option>`);
  for (const item of uploadedItems) {
    const val = item.relative_path;
    const sizeStr = formatFileSizeMb(item.size_bytes);
    const label = `${item.filename} (${sizeStr})`;
    const sel = val === selectedValue ? " selected" : "";
    opts.push(
      `<option value="${escapeHtml(val)}"${sel} title="${escapeHtml(val)}">${escapeHtml(label)}</option>`
    );
  }
  return opts.join("");
}

export function createSeriesUi({ selectorId, schedulePlotUpdate }) {
  const wrap = document.createElement("div");
  wrap.className = "series-bar selector-attachment";
  wrap.style.display = "none";

  const head = document.createElement("div");
  head.className = "row series-head";

  const title = document.createElement("div");
  title.className = "section-title";
  title.style.margin = "0";
  title.textContent = "Time/Depth points";

  const btnRow = document.createElement("div");
  btnRow.className = "row";
  btnRow.style.gap = "8px";

  const btnAll = document.createElement("button");
  btnAll.type = "button";
  btnAll.className = "mini";
  btnAll.textContent = "All";

  const btnNone = document.createElement("button");
  btnNone.type = "button";
  btnNone.className = "mini danger";
  btnNone.textContent = "None";

  btnRow.appendChild(btnAll);
  btnRow.appendChild(btnNone);
  head.appendChild(title);
  head.appendChild(btnRow);

  const scrub = document.createElement("div");
  scrub.className = "series-scrub";

  const slider = document.createElement("input");
  slider.type = "range";
  slider.className = "series-slider";
  slider.min = "0";
  slider.max = "0";
  slider.step = "1";
  slider.value = "0";

  const ticks = document.createElement("div");
  ticks.className = "series-ticks";
  ticks.setAttribute("aria-hidden", "true");

  const dots = document.createElement("div");
  dots.className = "series-dots";
  dots.setAttribute("aria-hidden", "true");

  const hover = document.createElement("div");
  hover.className = "series-hover";
  hover.style.display = "none";

  scrub.appendChild(slider);
  scrub.appendChild(ticks);
  scrub.appendChild(dots);
  scrub.appendChild(hover);

  const hint = document.createElement("div");
  hint.className = "hint";
  hint.style.marginTop = "8px";
  hint.textContent = "Move the bar to choose a point. Click the bar to toggle that point for plotting.";

  wrap.appendChild(head);
  wrap.appendChild(scrub);
  wrap.appendChild(hint);

  const seriesValueCacheByFile = new Map(); // relative_path -> Map(index -> number)

  const state = {
    selectorId,
    relativePath: "",
    count: 0,
    tickLabels: ["", "", "", "", ""],
    selectedIndices: new Set(),
  };

  function getSeriesValueCache(rel) {
    if (!seriesValueCacheByFile.has(rel)) seriesValueCacheByFile.set(rel, new Map());
    return seriesValueCacheByFile.get(rel);
  }

  function buildSeriesTickLabels(axisPreview, count) {
    if (Array.isArray(axisPreview) && axisPreview.length === 5) {
      return axisPreview.map((v) => {
        const n = Number(v);
        return Number.isFinite(n) ? n.toFixed(1) : "";
      });
    }
    if (!count || count <= 1) return ["0", "", "", "", "0"];
    return ["0", "", "", "", String(count - 1)];
  }

  function updateSubdivisions() {
    const effectiveCount = Math.min(Math.max(state.count, 2), 400);
    const stepPct = 100 / (effectiveCount - 1);
    slider.style.setProperty("--series-step", `${stepPct}%`);
  }

  function renderTicks() {
    ticks.innerHTML = "";
    const labels = state.tickLabels || ["", "", "", "", ""];
    for (let i = 0; i < 5; i++) {
      const t = document.createElement("div");
      t.className = "series-tick";
      t.style.left = `${i * 25}%`;
      const line = document.createElement("div");
      line.className = "series-tick-line";
      const lab = document.createElement("div");
      lab.className = "series-tick-label";
      lab.textContent = labels[i] ?? "";
      t.appendChild(line);
      t.appendChild(lab);
      ticks.appendChild(t);
    }
  }

  function renderDots() {
    dots.innerHTML = "";
    if (!state.count || state.count <= 1) return;
    const indices = Array.from(state.selectedIndices.values()).sort((a, b) => a - b).slice(0, 200);
    for (const idx of indices) {
      const xPct = (idx / (state.count - 1)) * 100;
      const d = document.createElement("div");
      d.className = "series-dot";
      d.style.left = `${xPct}%`;
      dots.appendChild(d);
    }
  }

  function setHoverVisible(v) {
    hover.style.display = v ? "block" : "none";
  }
  function setHoverPos(idx) {
    if (!state.count || state.count <= 1) return;
    const xPct = (idx / (state.count - 1)) * 100;
    hover.style.left = `${xPct}%`;
  }

  async function updateHoverLabel(idx) {
    if (!state.relativePath) return;
    const cache = getSeriesValueCache(state.relativePath);
    if (cache.has(idx)) {
      hover.textContent = cache.get(idx).toFixed(1);
      return;
    }
    const res = await fetch(
      `/plot/series-value?relative_path=${encodeURIComponent(state.relativePath)}&index=${encodeURIComponent(String(idx))}`
    );
    const text = await res.text();
    if (!res.ok) return;
    const data = JSON.parse(text);
    const v = Number(data && data.value);
    if (!Number.isFinite(v)) return;
    cache.set(idx, v);
    hover.textContent = v.toFixed(1);
  }

  slider.addEventListener("mousemove", async (e) => {
    if (!state.count) return;
    const rect = slider.getBoundingClientRect();
    const t = Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(1, rect.width)));
    const idx = Math.round(t * (state.count - 1));
    setHoverVisible(true);
    setHoverPos(idx);
    await updateHoverLabel(idx);
  });
  slider.addEventListener("mouseleave", () => setHoverVisible(false));
  slider.addEventListener("click", () => {
    if (!state.count) return;
    const idx = Math.max(0, Math.min(state.count - 1, Number(slider.value || 0)));
    if (state.selectedIndices.has(idx)) state.selectedIndices.delete(idx);
    else state.selectedIndices.add(idx);
    renderDots();
    schedulePlotUpdate();
  });

  btnAll.addEventListener("click", () => {
    state.selectedIndices = new Set();
    for (let i = 0; i < state.count; i++) state.selectedIndices.add(i);
    renderDots();
    schedulePlotUpdate();
  });
  btnNone.addEventListener("click", () => {
    state.selectedIndices = new Set();
    renderDots();
    schedulePlotUpdate();
  });

  async function setFile(rel) {
    state.relativePath = rel;
    if (!rel) {
      wrap.style.display = "none";
      state.count = 0;
      state.tickLabels = ["", "", "", "", ""];
      state.selectedIndices = new Set();
      ticks.innerHTML = "";
      dots.innerHTML = "";
      hover.style.display = "none";
      return;
    }
    const res = await fetch(`/plot/series-info?relative_path=${encodeURIComponent(rel)}&max_points=5`);
    const text = await res.text();
    if (!res.ok) {
      wrap.style.display = "none";
      state.count = 0;
      state.tickLabels = ["", "", "", "", ""];
      state.selectedIndices = new Set();
      ticks.innerHTML = "";
      dots.innerHTML = "";
      hover.style.display = "none";
      return;
    }
    const info = JSON.parse(text);
    if (!info || !info.is_series) {
      wrap.style.display = "none";
      state.count = 0;
      state.selectedIndices = new Set();
      state.tickLabels = ["", "", "", "", ""];
      ticks.innerHTML = "";
      dots.innerHTML = "";
      hover.style.display = "none";
      return;
    }
    state.count = Number.isFinite(Number(info.count)) ? Number(info.count) : 0;
    state.tickLabels = buildSeriesTickLabels(Array.isArray(info.axis) ? info.axis : [], state.count);
    slider.max = String(Math.max(0, state.count - 1));
    slider.value = "0";
    state.selectedIndices = new Set();
    if (state.count > 0) state.selectedIndices.add(0);
    updateSubdivisions();
    renderTicks();
    renderDots();
    wrap.style.display = state.count > 0 ? "block" : "none";
    schedulePlotUpdate();
  }

  function getState() {
    return {
      relativePath: state.relativePath,
      count: state.count,
      selectedIndices: Array.from(state.selectedIndices.values()),
    };
  }

  return { wrap, setFile, getState };
}

export function createMapUi({ selectorId, mapStateByFile, schedulePlotUpdate }) {
  const wrap = document.createElement("div");
  wrap.className = "series-bar selector-attachment";
  wrap.style.display = "none";

  const head = document.createElement("div");
  head.className = "row series-head";

  const title = document.createElement("div");
  title.className = "section-title";
  title.style.margin = "0";
  title.textContent = "Map points";

  const btnRow = document.createElement("div");
  btnRow.className = "row";
  btnRow.style.gap = "8px";

  const btnAll = document.createElement("button");
  btnAll.type = "button";
  btnAll.className = "mini";
  btnAll.textContent = "All";

  const btnNone = document.createElement("button");
  btnNone.type = "button";
  btnNone.className = "mini danger";
  btnNone.textContent = "None";

  btnRow.appendChild(btnAll);
  btnRow.appendChild(btnNone);
  head.appendChild(title);
  head.appendChild(btnRow);

  const hint = document.createElement("div");
  hint.className = "hint";
  hint.style.marginTop = "8px";
  hint.style.marginBottom = "10px";
  hint.textContent = "Click cells to toggle map points. If available, an embedded preview image is shown behind the grid.";

  const gridEl = document.createElement("div");
  gridEl.className = "map-grid";
  gridEl.setAttribute("aria-label", "Map grid");

  wrap.appendChild(head);
  wrap.appendChild(hint);
  wrap.appendChild(gridEl);

  const state = {
    selectorId,
    relativePath: "",
    indexGrid: [],
    selectedIndices: new Set(),
  };

  function renderGrid() {
    const grid = state.indexGrid || [];
    const rows = grid.length;
    const cols = rows > 0 ? (grid[0] || []).length : 0;
    gridEl.innerHTML = "";
    const w = gridEl.clientWidth || 320;
    const gap = 2;
    const cell = cols > 0 ? Math.max(6, Math.floor((w - gap * Math.max(0, cols - 1)) / cols)) : 14;
    gridEl.style.setProperty("--map-cell", `${cell}px`);
    gridEl.style.gridTemplateColumns = `repeat(${cols}, var(--map-cell))`;

    for (let r = 0; r < rows; r++) {
      const row = grid[r] || [];
      for (let c = 0; c < cols; c++) {
        const idx = row[c];
        const cell = document.createElement("div");
        cell.className = "map-cell";
        if (!Number.isInteger(idx)) {
          cell.classList.add("empty");
          gridEl.appendChild(cell);
          continue;
        }
        if (state.selectedIndices.has(idx)) cell.classList.add("on");
        cell.title = `Toggle point ${idx}`;
        cell.addEventListener("click", () => {
          if (state.selectedIndices.has(idx)) state.selectedIndices.delete(idx);
          else state.selectedIndices.add(idx);
          cell.classList.toggle("on", state.selectedIndices.has(idx));
          if (state.relativePath) {
            mapStateByFile.set(state.relativePath, { selectedIndices: Array.from(state.selectedIndices.values()) });
          }
          schedulePlotUpdate();
        });
        gridEl.appendChild(cell);
      }
    }
  }

  async function applyPreviewBackground(rel) {
    try {
      const url = `/plot/map-preview-image?relative_path=${encodeURIComponent(rel)}`;
      const res = await fetch(url, { method: "GET" });
      if (!res.ok) {
        gridEl.classList.remove("with-preview");
        gridEl.style.backgroundImage = "";
        gridEl.style.aspectRatio = "";
        return;
      }
      gridEl.classList.add("with-preview");
      gridEl.style.backgroundImage = `url('${url}')`;
      const img = new Image();
      img.onload = () => {
        if (img.naturalWidth > 0 && img.naturalHeight > 0) {
          gridEl.style.aspectRatio = `${img.naturalWidth} / ${img.naturalHeight}`;
        }
        requestAnimationFrame(() => renderGrid());
      };
      img.src = url;
    } catch {
      gridEl.classList.remove("with-preview");
      gridEl.style.backgroundImage = "";
      gridEl.style.aspectRatio = "";
    }
  }

  btnAll.addEventListener("click", () => {
    state.selectedIndices = new Set();
    for (const row of state.indexGrid || []) {
      if (!Array.isArray(row)) continue;
      for (const idx of row) if (Number.isInteger(idx)) state.selectedIndices.add(idx);
    }
    renderGrid();
    if (state.relativePath) mapStateByFile.set(state.relativePath, { selectedIndices: Array.from(state.selectedIndices.values()) });
    schedulePlotUpdate();
  });

  btnNone.addEventListener("click", () => {
    state.selectedIndices = new Set();
    renderGrid();
    if (state.relativePath) mapStateByFile.set(state.relativePath, { selectedIndices: [] });
    schedulePlotUpdate();
  });

  async function setFile(rel) {
    state.relativePath = rel;
    state.indexGrid = [];
    state.selectedIndices = new Set();
    gridEl.classList.remove("with-preview");
    gridEl.style.backgroundImage = "";

    if (!rel) {
      wrap.style.display = "none";
      gridEl.innerHTML = "";
      return;
    }

    const res = await fetch(`/plot/map-info?relative_path=${encodeURIComponent(rel)}&max_dim=80`);
    const text = await res.text();
    if (!res.ok) {
      wrap.style.display = "none";
      return;
    }
    const info = JSON.parse(text);
    if (!info || !info.is_map) {
      wrap.style.display = "none";
      return;
    }

    state.indexGrid = Array.isArray(info.index_grid) ? info.index_grid : [];
    const prev = mapStateByFile.get(rel);
    if (prev && Array.isArray(prev.selectedIndices) && prev.selectedIndices.length) {
      for (const i of prev.selectedIndices) if (Number.isInteger(i)) state.selectedIndices.add(i);
    } else {
      for (const row of state.indexGrid) {
        if (!Array.isArray(row)) continue;
        for (const idx of row) if (Number.isInteger(idx)) state.selectedIndices.add(idx);
      }
    }

    renderGrid();
    await applyPreviewBackground(rel);
    wrap.style.display = "block";
    schedulePlotUpdate();
  }

  function getState() {
    return {
      relativePath: state.relativePath,
      selectedIndices: Array.from(state.selectedIndices.values()),
      isMap: wrap.style.display !== "none",
    };
  }

  return { wrap, setFile, getState };
}

