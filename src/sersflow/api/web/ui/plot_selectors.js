import { escapeHtml } from "./dom.js";
import { formatFileSizeMb } from "./uploads.js";

export function buildFileOptionsHtml(uploadedItems, selectedValue) {
  const opts = [];
  opts.push(`<option value="">Select a file…</option>`);
  for (const item of uploadedItems) {
    const val = item.relative_path;
    const sizeStr = formatFileSizeMb(item.size_bytes);
    const blocks = item.labels && item.labels.vms_spectra && typeof item.labels.vms_spectra === "object"
      ? Object.keys(item.labels.vms_spectra).length
      : 0;
    const multiTag = blocks > 0 ? ` · ${blocks} blocks` : "";
    const label = `${item.filename} (${sizeStr})${multiTag}`;
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
      `/plot/series-value?relative_path=${encodeURIComponent(state.relativePath)}&index=${encodeURIComponent(String(idx))}`,
      { credentials: "include" },
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
    const res = await fetch(`/plot/series-info?relative_path=${encodeURIComponent(rel)}&max_points=5`, {
      credentials: "include",
    });
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
  hint.textContent =
    "Click cells to toggle map points. If available, the embedded preview is cropped to the Raman map area behind the grid.";

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
      const params = new URLSearchParams({ relative_path: rel, crop_to_map: "true" });
      const url = `/plot/map-preview-image?${params.toString()}`;
      const res = await fetch(url, { method: "GET", credentials: "include" });
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

    const res = await fetch(`/plot/map-info?relative_path=${encodeURIComponent(rel)}&max_dim=80`, {
      credentials: "include",
    });
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


/**
 * Multi-block (VAMAS) filter UI  mode + metadata filters, like series/map attachment.
 * Filter ops mirror Python evaluate_filters (AND across rows).
 */
export function createMultiUi({ selectorId, schedulePlotUpdate }) {
  const wrap = document.createElement('div');
  wrap.className = 'series-bar selector-attachment';
  wrap.style.display = 'none';

  const head = document.createElement('div');
  head.className = 'row series-head';
  const title = document.createElement('div');
  title.className = 'section-title';
  title.style.margin = '0';
  title.textContent = 'Multi-spectrum blocks';

  const modeLabel = document.createElement('label');
  modeLabel.className = 'inline';
  modeLabel.style.margin = '0';
  modeLabel.innerHTML = 'Mode <select class=\"mini multi-mode\"><option value=\"averages\">Averaged</option><option value=\"individuals\">Individual</option><option value=\"all\">All</option></select>';

  head.appendChild(title);
  head.appendChild(modeLabel);

  const blocksHost = document.createElement('details');
  blocksHost.className = 'multi-blocks-list';
  blocksHost.style.marginTop = '8px';
  blocksHost.open = false;
  const blocksSummary = document.createElement('summary');
  blocksSummary.className = 'hint';
  blocksSummary.textContent = 'Blocks';
  const blocksList = document.createElement('div');
  blocksList.style.display = 'grid';
  blocksList.style.gap = '2px';
  blocksList.style.maxHeight = '160px';
  blocksList.style.overflow = 'auto';
  blocksList.style.marginTop = '4px';
  blocksHost.appendChild(blocksSummary);
  blocksHost.appendChild(blocksList);

  const filtersHost = document.createElement('div');
  filtersHost.style.display = 'grid';
  filtersHost.style.gap = '6px';
  filtersHost.style.marginTop = '8px';

  const addFilterBtn = document.createElement('button');
  addFilterBtn.type = 'button';
  addFilterBtn.className = 'mini';
  addFilterBtn.textContent = 'Add filter';
  const clearBtn = document.createElement('button');
  clearBtn.type = 'button';
  clearBtn.className = 'mini danger';
  clearBtn.textContent = 'Clear filters';
  const btnRow = document.createElement('div');
  btnRow.className = 'row';
  btnRow.style.gap = '8px';
  btnRow.style.marginTop = '6px';
  btnRow.appendChild(addFilterBtn);
  btnRow.appendChild(clearBtn);

  const summary = document.createElement('div');
  summary.className = 'hint';
  summary.style.marginTop = '8px';

  wrap.appendChild(head);
  wrap.appendChild(blocksHost);
  wrap.appendChild(filtersHost);
  wrap.appendChild(btnRow);
  wrap.appendChild(summary);

  const state = {
    selectorId,
    relativePath: '',
    isMulti: false,
    blocks: [],
    fields: [],
    mode: 'averages',
    filters: [],
    matchedIndices: [],
    explicitIndices: new Set(),
  };
  const modeSelect = modeLabel.querySelector('select');

  function evaluateMetaFilters(row, filters) {
    if (!filters || !filters.length) return true;
    for (const clause of filters) {
      const field = String(clause.field || '');
      if (!field) continue;
      const op = String(clause.op || 'in');
      const raw = row[field];
      if (op === 'in') {
        const values = Array.isArray(clause.values) ? clause.values.map(String) : [];
        if (!values.length) return false;
        if (raw == null || !values.includes(String(raw))) return false;
        continue;
      }
      const num = Number(raw);
      const target = Number(clause.value);
      if (!Number.isFinite(num) || !Number.isFinite(target)) return false;
      if ((op === '=' || op === 'eq' || op === '==') && !(num === target)) return false;
      else if ((op === '!=' || op === 'ne') && !(num !== target)) return false;
      else if ((op === '>' || op === 'gt') && !(num > target)) return false;
      else if ((op === '>=' || op === 'gte') && !(num >= target)) return false;
      else if ((op === '<' || op === 'lt') && !(num < target)) return false;
      else if ((op === '<=' || op === 'lte') && !(num <= target)) return false;
    }
    return true;
  }

  function indicesForMode(blocks, mode) {
    const avgs = blocks.filter((b) => String(b.spectrum_role || 'average') === 'average').map((b) => b.index);
    const inds = blocks.filter((b) => String(b.spectrum_role || '') === 'individual').map((b) => b.index);
    if (mode === 'all') return blocks.map((b) => b.index);
    if (mode === 'averages') return avgs.length ? avgs : inds;
    return inds.length ? inds : avgs;
  }

  function blockLabel(b) {
    let name = '';
    if (b.block_name) name = String(b.block_name);
    else {
      const region = b.xps_region || 'block';
      const role = b.spectrum_role || 'spectrum';
      name = region + ' · ' + role;
    }
    const bits = [];
    if (b.sample) bits.push(String(b.sample));
    if (b.potential_ref === 'OCP') bits.push('OCP');
    else if (b.potential_V != null && b.potential_ref) bits.push(String(b.potential_V) + String(b.potential_ref));
    if (b.current_density_A_cm2 != null && Number.isFinite(Number(b.current_density_A_cm2))) {
      bits.push(String(Number(b.current_density_A_cm2) * 1000) + 'mA·cm⁻²');
    }
    if (b.gas) bits.push(String(b.gas));
    return bits.length ? name + ' — ' + bits.join(' · ') : name;
  }

  function selectedIndices() {
    if (state.explicitIndices.size > 0) {
      return Array.from(state.explicitIndices).sort((a, b) => a - b);
    }
    return state.matchedIndices.slice();
  }

  function recompute() {
    const modeKeep = new Set(indicesForMode(state.blocks, state.mode));
    const matched = [];
    for (const b of state.blocks) {
      if (!modeKeep.has(b.index)) continue;
      if (!evaluateMetaFilters(b, state.filters)) continue;
      matched.push(b.index);
    }
    state.matchedIndices = matched;
    const useExplicit = state.explicitIndices.size > 0;
    const active = selectedIndices();
    const cap = 30;
    const plotted = active.length > cap ? cap : active.length;
    if (useExplicit) {
      summary.textContent = active.length === 0
        ? 'No blocks selected.'
        : active.length > cap
          ? active.length + ' blocks selected (plotting first ' + plotted + ').'
          : active.length + ' block(s) selected (overrides mode/filters).';
    } else {
      summary.textContent = matched.length === 0
        ? 'No blocks match the current mode/filters.'
        : matched.length > cap
          ? matched.length + ' of ' + state.blocks.length + ' blocks match (plotting first ' + plotted + ').'
          : matched.length + ' of ' + state.blocks.length + ' blocks match.';
    }
    schedulePlotUpdate();
  }

  function renderBlocksList() {
    blocksList.innerHTML = '';
    blocksSummary.textContent = 'Blocks (' + state.blocks.length + ') — tick to plot specific ones';
    for (const b of state.blocks) {
      const row = document.createElement('label');
      row.className = 'inline';
      row.style.margin = '0';
      row.style.display = 'flex';
      row.style.gap = '6px';
      row.style.alignItems = 'center';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = state.explicitIndices.has(b.index);
      cb.addEventListener('change', () => {
        if (cb.checked) state.explicitIndices.add(b.index);
        else state.explicitIndices.delete(b.index);
        recompute();
      });
      const lab = document.createElement('span');
      lab.textContent = '#' + b.index + ' ' + blockLabel(b);
      lab.style.fontSize = '12px';
      row.appendChild(cb);
      row.appendChild(lab);
      blocksList.appendChild(row);
    }
  }

  function fieldDef(id) { return (state.fields || []).find((f) => f.id === id) || null; }

  function renderFilters() {
    filtersHost.innerHTML = '';
    state.filters.forEach((clause, fi) => {
      const row = document.createElement('div');
      row.className = 'row';
      row.style.gap = '8px';
      row.style.flexWrap = 'wrap';
      row.style.alignItems = 'flex-start';
      const fieldSel = document.createElement('select');
      fieldSel.className = 'mini';
      for (const f of state.fields) {
        const opt = document.createElement('option');
        opt.value = f.id;
        opt.textContent = f.label || f.id;
        if (f.id === clause.field) opt.selected = true;
        fieldSel.appendChild(opt);
      }
      if (!clause.field && state.fields[0]) clause.field = state.fields[0].id;
      const right = document.createElement('div');
      right.style.display = 'flex';
      right.style.gap = '6px';
      right.style.flexWrap = 'wrap';
      right.style.alignItems = 'center';
      function paintRight() {
        right.innerHTML = '';
        const def = fieldDef(clause.field);
        if (!def) return;
        if (def.kind === 'categorical') {
          clause.op = 'in';
          if (!Array.isArray(clause.values)) clause.values = [];
          const selected = new Set(clause.values.map(String));
          for (const v of def.values || []) {
            const lab = document.createElement('label');
            lab.className = 'inline';
            lab.style.margin = '0';
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = selected.has(String(v));
            cb.addEventListener('change', () => {
              if (cb.checked) clause.values = [...new Set([...(clause.values || []), String(v)])];
              else clause.values = (clause.values || []).filter((x) => String(x) !== String(v));
              recompute();
            });
            lab.appendChild(cb);
            lab.appendChild(document.createTextNode(' ' + v));
            right.appendChild(lab);
          }
        } else {
          if (!clause.op || clause.op === 'in') clause.op = '>=';
          const opSel = document.createElement('select');
          opSel.className = 'mini';
          for (const op of ['=', '!=', '>', '>=', '<', '<=']) {
            const o = document.createElement('option');
            o.value = op; o.textContent = op;
            if (op === clause.op) o.selected = true;
            opSel.appendChild(o);
          }
          opSel.addEventListener('change', () => { clause.op = opSel.value; recompute(); });
          const num = document.createElement('input');
          num.type = 'number';
          num.className = 'mini';
          num.style.width = '100px';
          num.value = clause.value != null && Number.isFinite(Number(clause.value)) ? String(clause.value) : '';
          num.placeholder = def.min != null && def.max != null ? (def.min + '' + def.max) : 'value';
          num.addEventListener('change', () => { clause.value = Number(num.value); recompute(); });
          const hint = document.createElement('span');
          hint.className = 'hint';
          if (def.min != null && def.max != null) hint.textContent = 'range ' + def.min + '' + def.max;
          right.appendChild(opSel); right.appendChild(num); right.appendChild(hint);
        }
      }
      fieldSel.addEventListener('change', () => {
        clause.field = fieldSel.value; clause.values = []; clause.value = undefined; paintRight(); recompute();
      });
      const rm = document.createElement('button');
      rm.type = 'button'; rm.className = 'mini danger'; rm.textContent = '×';
      rm.addEventListener('click', () => { state.filters.splice(fi, 1); renderFilters(); recompute(); });
      row.appendChild(fieldSel); row.appendChild(right); row.appendChild(rm);
      filtersHost.appendChild(row);
      paintRight();
    });
  }

  modeSelect.addEventListener('change', () => {
    state.mode = modeSelect.value === 'individuals' ? 'individuals' : modeSelect.value === 'all' ? 'all' : 'averages';
    recompute();
  });
  addFilterBtn.addEventListener('click', () => {
    const unused = (state.fields || []).find((f) => !state.filters.some((c) => c.field === f.id));
    const next = unused || state.fields[0];
    if (!next) return;
    const values = next.kind === 'categorical' ? [...(next.values || [])].map(String) : [];
    state.filters.push({
      field: next.id,
      op: next.kind === 'numeric' ? '>=' : 'in',
      values,
      value: next.min,
    });
    renderFilters(); recompute();
  });
  clearBtn.addEventListener('click', () => {
    // Keep the default XPS region row (first region in file order) when clearing extras.
    const first = firstXpsRegion();
    if (first) {
      state.filters = [{ field: 'xps_region', op: 'in', values: [first] }];
    } else {
      state.filters = [];
    }
    renderFilters();
    recompute();
  });

  function firstXpsRegion() {
    for (const b of state.blocks || []) {
      const r = String(b.xps_region || '').trim();
      if (r) return r;
    }
    const regionField = (state.fields || []).find((f) => f.id === 'xps_region');
    const v = regionField && Array.isArray(regionField.values) ? regionField.values[0] : null;
    return v != null ? String(v) : '';
  }

  let loadGen = 0;
  async function setFile(rel) {
    const gen = ++loadGen;
    state.relativePath = rel;
    state.isMulti = false;
    state.blocks = [];
    state.fields = [];
    state.filters = [];
    state.matchedIndices = [];
    state.explicitIndices = new Set();
    if (!rel) {
      wrap.style.display = 'none';
      return;
    }
    const res = await fetch('/plot/multi-info?relative_path=' + encodeURIComponent(rel), { credentials: 'include' });
    const text = await res.text();
    if (gen !== loadGen) return;
    if (!res.ok) {
      wrap.style.display = 'none';
      return;
    }
    const info = JSON.parse(text);
    if (!info || !info.is_multi) {
      wrap.style.display = 'none';
      return;
    }
    state.isMulti = true;
    state.blocks = Array.isArray(info.blocks) ? info.blocks : [];
    state.fields = Array.isArray(info.fields) ? info.fields : [];
    state.mode = 'averages';
    modeSelect.value = 'averages';
    state.explicitIndices = new Set();
    // Default: XPS region filter with only the first region in the file selected.
    const firstRegion = firstXpsRegion();
    if (firstRegion) {
      state.filters = [{ field: 'xps_region', op: 'in', values: [firstRegion] }];
    } else {
      state.filters = [];
    }
    renderBlocksList();
    renderFilters();
    wrap.style.display = 'block';
    recompute();
  }

  function getState() {
    return {
      relativePath: state.relativePath,
      isMulti: state.isMulti,
      selectedIndices: selectedIndices(),
      hasExplicitSelection: state.explicitIndices.size > 0,
    };
  }
  return { wrap, setFile, getState };
}
