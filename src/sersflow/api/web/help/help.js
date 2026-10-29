// Help tab: static HTML fragments under /static/help/pages/, rendered into #help-root.
// Pages are plain HTML (no build step). Cross-links use <a data-help="page-id#anchor">.
// URL form: #help/<page-id>[/<anchor>] (shareable; Back/Forward work).

const PAGES_BASE = "/static/help/pages/";
const LAST_KEY = "specflow.help.last";
// Bump when the pages are re-checked against a SpecFlow release (shown at the bottom of each page).
export const GUIDE_VERSION = "0.2.0";
export const GUIDE_REVIEWED = "2026-10-29";

export const HELP_SECTIONS = [
  {
    title: "Tutorials",
    pages: [
      { id: "start", title: "Start here: how SpecFlow works" },
      { id: "t-vibrational", title: "1 · SERS / Raman: files to correlation" },
      { id: "t-xps-calibrate", title: "2 · XPS: load and calibrate" },
      { id: "t-xps-fit", title: "3 · XPS: fit and compare" },
      { id: "t-maps", title: "4 · Maps and time series" },
      { id: "t-reuse", title: "5 · Reuse, share and export" },
      { id: "t-mcp", title: "6 · Work with an AI assistant (MCP)" },
    ],
  },
  {
    title: "Quick help",
    pages: [
      { id: "r-cheatsheet", title: "Cheat sheet" },
      { id: "r-decisions", title: "Which method should I use?" },
      { id: "r-faq", title: "FAQ" },
    ],
  },
  {
    title: "Reference manual",
    pages: [
      { id: "r-uploads", title: "Uploads tab" },
      { id: "r-labels", title: "Labels and file naming" },
      { id: "r-raw", title: "Raw visualization tab" },
      { id: "r-datasets", title: "Prepare: datasets, sessions, subsets" },
      { id: "r-pipeline", title: "Prepare: the pipeline builder" },
      { id: "r-steps", title: "Pipeline steps A–Z" },
      { id: "r-baseline", title: "Baseline methods" },
      { id: "r-fitting", title: "Peak fitting" },
      { id: "r-xps", title: "XPS specifics" },
      { id: "r-features", title: "Features: integration, peaks, metrics" },
      { id: "r-analyze", title: "Analyze tab" },
      { id: "r-exports", title: "Exports and column names" },
      { id: "r-python", title: "Python client" },
      { id: "r-mcp", title: "MCP server: setup" },
      { id: "r-mcp-tools", title: "MCP server: tools and safety" },
      { id: "r-troubleshooting", title: "Troubleshooting" },
      { id: "r-glossary", title: "Glossary" },
    ],
  },
];

const ALL_PAGES = HELP_SECTIONS.flatMap((s) => s.pages);
const PAGE_IDS = new Set(ALL_PAGES.map((p) => p.id));

// Pipeline steps: search results, auto-links and in-app "Help" links point here.
export const STEPS = [
  { name: "Alignment & Resampling", target: "r-steps#step-align", words: "align resample grid interpolate common axis step points", desc: "Interpolate every spectrum onto a common x grid." },
  { name: "Baseline Correction", target: "r-steps#step-baseline", words: "baseline background fluorescence asls arpls airpls snip subtract", desc: "Estimate and subtract a slowly varying background." },
  { name: "Cosmic Ray Removal", target: "r-steps#step-cosmic", words: "cosmic ray spike despike zscore derivative remove", desc: "Find narrow spikes and replace them (vibrational only)." },
  { name: "Cropping", target: "r-steps#step-crop", words: "crop trim range min_x max_x restrict", desc: "Keep only a chosen x range." },
  { name: "Derivative", target: "r-steps#step-derivative", words: "derivative gradient order", desc: "First or higher-order spectral derivative." },
  { name: "Low-Signal Filter", target: "r-steps#step-lowsignal", words: "low signal filter weak dead threshold qc", desc: "Remove whole spectra that are too weak." },
  { name: "Metadata Filter", target: "r-steps#step-metadata", words: "metadata filter label region select keep mask branch", desc: "Keep only spectra whose labels match, on this branch." },
  { name: "Normalization", target: "r-steps#step-normalize", words: "normalize normalise normalization max vector l2 internal standard scale", desc: "Rescale spectrum intensity." },
  { name: "Outlier Detection", target: "r-steps#step-outlier", words: "outlier detection anomaly correlation median pca qc", desc: "Remove spectra that look unlike the rest." },
  { name: "Reference Transformation", target: "r-steps#step-reference", words: "reference transformation blank solvent subtract divide", desc: "Subtract or divide by a reference spectrum." },
  { name: "Smoothing", target: "r-steps#step-smoothing", words: "smooth smoothing savitzky golay savgol noise window polyorder", desc: "Savitzky–Golay noise reduction." },
  { name: "X-axis Calibration", target: "r-steps#step-xcal", words: "x axis calibration charge correction shift offset reference band fermi 284.8", desc: "Shift the x axis by an offset or a reference peak." },
  { name: "Peak Fitting", target: "r-fitting", words: "peak fitting fit model gaussian lorentzian voigt pseudo-voigt component bounds recipe curve_fit lmfit", desc: "Fit peak models and export fitted parameters." },
  { name: "Peak Integration", target: "r-features#step-integration", words: "peak integration integrate area window band", desc: "Integrate intensity over x windows." },
  { name: "Peak Identification", target: "r-features#step-identification", words: "peak identification probe intensity nearest peak position", desc: "Read intensities or peak positions at chosen places." },
  { name: "Metric Calculation", target: "r-features#step-metric", words: "metric calculation formula ratio operation derived", desc: "Compute new columns, such as ratios, from earlier features." },
];

// Extra search vocabulary for topics that are not pipeline steps.
const SYNONYMS = {
  csv: "export observation wide long parquet",
  export: "csv download parquet manifest bundle",
  mcp: "ai assistant llm cursor claude server tools",
  "meta_": "labels metadata columns",
  charge: "calibration 284.8 c1s fermi",
  despike: "cosmic ray spike",
  ratio: "metric calculation formula",
  pca: "principal component scores loadings scree sparse",
  label: "metadata sample ph potential rename filename",
  heatmap: "map time series",
};

// Terms auto-linked in tutorials (first mention per section). Case-sensitive.
const LINK_TERMS = [
  ...STEPS.map((s) => [s.name, s.target]),
  ["Shirley", "r-xps#backgrounds-static-or-active-never-both"],
  ["Tougaard", "r-xps#backgrounds-static-or-active-never-both"],
  ["asls", "r-baseline"],
  ["Fit diagnostics", "r-analyze#fit-diagnostics"],
  ["Heatmaps", "r-analyze#heatmaps"],
  ["Correlation / VIF", "r-analyze#correlation-vif"],
  ["PCA / Cluster", "r-analyze#pca-cluster"],
];
const LINK_RE = new RegExp(
  "(" +
    LINK_TERMS.map((t) => t[0])
      .sort((a, b) => b.length - a.length)
      .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|") +
    ")",
  "g"
);
const LINK_TARGET = new Map(LINK_TERMS);
const AUTOLINK_PAGES = (id) => id === "start" || id.startsWith("t-");

// "Help" links placed next to headings in the other tabs (heading text -> target).
const CONTEXT_LINKS = {
  "Upload files": "r-uploads",
  "Uploaded files & metadata": "r-uploads#uploaded-files-metadata",
  "Edit labels": "r-labels",
  "Raw visualization": "r-raw",
  "Pipeline & preview": "r-datasets",
  "Create new dataset": "r-datasets#create-new-dataset",
  Subsets: "r-datasets#the-plot-card",
  Pipeline: "r-pipeline",
  "Saved pipelines (library)": "r-pipeline#saving-loading-sharing",
  Run: "r-datasets#session-and-preview-bar",
  "Features & statistics": "r-analyze",
  Runs: "r-analyze#overview-runs",
  Exports: "r-analyze#exports",
  "Correlation & VIF": "r-analyze#correlation-vif",
  "PCA & k-means": "r-analyze#pca-cluster",
  "Map / time heatmaps": "r-analyze#heatmaps",
  Plots: "r-analyze#plots",
  "Parameter vs parameter": "r-analyze#plots",
  "Matrix export job": "r-analyze#spectrum-matrix-pca",
  ...Object.fromEntries(STEPS.map((s) => [s.name, s.target])),
};

const cache = new Map();
let root = null;
let current = null;
let built = false;
let lastRoute = "";
let lastTerms = [];
let serverVersion;

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

async function loadPage(id) {
  if (cache.has(id)) return cache.get(id);
  let html;
  try {
    const res = await fetch(`${PAGES_BASE}${id}.html`, { cache: "no-cache" });
    html = res.ok
      ? await res.text()
      : `<p class="help-missing">This page (<code>${id}</code>) could not be loaded (HTTP ${res.status}).</p>`;
  } catch (e) {
    html = `<p class="help-missing">This page (<code>${id}</code>) could not be loaded.</p>`;
  }
  cache.set(id, html);
  return html;
}

function slug(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

// Give every h2/h3 a stable id (explicit ids are kept). Used for rendering and for search.
function assignIds(container) {
  const used = new Set([...container.querySelectorAll("[id]")].map((e) => e.id));
  for (const h of container.querySelectorAll("h2, h3")) {
    if (h.id) continue;
    let s = slug(h.textContent) || "section";
    while (used.has(s)) s += "-x";
    used.add(s);
    h.id = s;
  }
}

// ---------------------------------------------------------------- routing (#help/page/anchor)

function routeFromHash() {
  const m = /^#help(?:\/([a-z0-9-]+))?(?:\/([A-Za-z0-9_-]+))?/.exec(window.location.hash);
  return m ? { id: m[1] || null, anchor: m[2] || null } : null;
}

function writeRoute(id, anchor, replace) {
  const hash = `#help/${id}${anchor ? "/" + anchor : ""}`;
  lastRoute = hash;
  if (window.location.hash === hash) return;
  const url = window.location.pathname + window.location.search + hash;
  if (replace) history.replaceState(null, "", url);
  else history.pushState(null, "", url);
}

function onHashChange() {
  const panel = document.getElementById("tab-help");
  if (!panel) return;
  if (window.location.hash === lastRoute) return;
  const r = routeFromHash();
  if (!r) return;
  // Back/forward or a pasted link: show the Help tab and the page.
  if (!panel.classList.contains("active")) document.querySelector('#tabs .tab[data-tab="help"]')?.click();
  openHelp(r.id || undefined, r.anchor || undefined, { push: false });
}

// ---------------------------------------------------------------- shell

function buildShell() {
  root.innerHTML = `
    <aside class="help-nav" aria-label="Help navigation">
      <input id="helpSearch" class="help-search" type="search" placeholder="Search the guide…  ( / )" aria-label="Search the guide" />
      <nav id="helpNavList"></nav>
    </aside>
    <article class="help-body">
      <div id="helpToc" class="help-toc" hidden></div>
      <div id="helpContent" class="help-content" tabindex="-1"></div>
      <div id="helpFoot" class="help-foot"></div>
      <div id="helpPager" class="help-pager"></div>
    </article>`;
  const list = root.querySelector("#helpNavList");
  for (const sec of HELP_SECTIONS) {
    const h = document.createElement("div");
    h.className = "help-nav-title";
    h.textContent = sec.title;
    list.appendChild(h);
    for (const p of sec.pages) {
      const a = document.createElement("a");
      a.href = `#help/${p.id}`;
      a.className = "help-nav-link";
      a.dataset.help = p.id;
      a.textContent = p.title;
      list.appendChild(a);
    }
  }
  root.addEventListener("click", (ev) => {
    const copy = ev.target.closest("button.help-copy");
    if (copy) {
      const code = copy.parentElement.querySelector("code, pre");
      navigator.clipboard?.writeText(code.innerText).then(() => {
        copy.textContent = "Copied";
        setTimeout(() => (copy.textContent = "Copy"), 1200);
      });
      return;
    }
    const a = ev.target.closest("a[data-help]");
    if (!a) return;
    ev.preventDefault();
    const [id, anchor] = a.dataset.help.split("#");
    const fromSearch = !!a.closest(".help-hit");
    showPage(id, anchor, { push: true, highlight: fromSearch ? lastTerms : [] });
  });
  const search = root.querySelector("#helpSearch");
  let timer = null;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => runSearch(search.value.trim()), 180);
  });
  search.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      search.value = "";
      runSearch("");
    }
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "/" || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (!document.getElementById("tab-help")?.classList.contains("active")) return;
    const t = ev.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
    ev.preventDefault();
    search.focus();
    search.select();
  });
  built = true;
}

function setActive(id) {
  for (const a of root.querySelectorAll(".help-nav-link")) {
    const on = a.dataset.help === id;
    a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
}

function buildToc(content) {
  const toc = root.querySelector("#helpToc");
  const heads = [...content.querySelectorAll("h2")];
  if (heads.length < 3) {
    toc.hidden = true;
    toc.innerHTML = "";
    return;
  }
  toc.innerHTML = "<span>On this page:</span>";
  for (const h of heads) {
    const a = document.createElement("a");
    a.href = `#help/${current}/${h.id}`;
    a.textContent = h.textContent;
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      h.scrollIntoView({ behavior: "smooth", block: "start" });
      writeRoute(current, h.id, true);
    });
    toc.appendChild(a);
  }
  toc.hidden = false;
}

function renderPager(id) {
  const i = ALL_PAGES.findIndex((p) => p.id === id);
  const pager = root.querySelector("#helpPager");
  const prev = ALL_PAGES[i - 1];
  const next = ALL_PAGES[i + 1];
  pager.innerHTML = "";
  if (prev) pager.innerHTML += `<a href="#help/${prev.id}" data-help="${prev.id}">← ${esc(prev.title)}</a>`;
  else pager.innerHTML += "<span></span>";
  if (next) pager.innerHTML += `<a href="#help/${next.id}" data-help="${next.id}">${esc(next.title)} →</a>`;
}

// ---------------------------------------------------------------- page decorations

function autolink(container) {
  const skip = "A,H1,H2,H3,PRE,CODE,SCRIPT,STYLE,FIGCAPTION";
  const items = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType === 1) {
      if (n.tagName === "H2") items.push({ reset: true });
    } else if (!n.parentElement.closest(skip)) {
      LINK_RE.lastIndex = 0;
      if (LINK_RE.test(n.nodeValue)) items.push({ node: n });
      LINK_RE.lastIndex = 0;
    }
  }
  let seen = new Set();
  for (const it of items) {
    if (it.reset) {
      seen = new Set();
      continue;
    }
    const text = it.node.nodeValue;
    const frag = document.createDocumentFragment();
    let last = 0;
    let changed = false;
    for (const m of text.matchAll(LINK_RE)) {
      if (seen.has(m[1])) continue;
      seen.add(m[1]);
      frag.append(text.slice(last, m.index));
      const a = document.createElement("a");
      const target = LINK_TARGET.get(m[1]);
      a.href = `#help/${target.replace("#", "/")}`;
      a.className = "help-auto";
      a.dataset.help = target;
      a.title = "Open the reference for " + m[1];
      a.textContent = m[1];
      frag.append(a);
      last = m.index + m[1].length;
      changed = true;
    }
    if (!changed) continue;
    frag.append(text.slice(last));
    it.node.replaceWith(frag);
  }
}

function addCopyButtons(container) {
  for (const pre of container.querySelectorAll("pre")) {
    if (pre.querySelector(".help-copy")) continue;
    pre.classList.add("has-copy");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "help-copy";
    b.textContent = "Copy";
    pre.appendChild(b);
  }
}

function highlight(container, terms) {
  const ts = terms.filter((t) => t.length > 1);
  if (!ts.length) return;
  const re = new RegExp("(" + ts.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
  const nodes = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.parentElement.closest("pre,script,style,button") && re.test(n.nodeValue)) nodes.push(n);
    re.lastIndex = 0;
  }
  for (const n of nodes.slice(0, 200)) {
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of n.nodeValue.matchAll(re)) {
      frag.append(n.nodeValue.slice(last, m.index));
      const mark = document.createElement("mark");
      mark.textContent = m[0];
      frag.append(mark);
      last = m.index + m[0].length;
    }
    frag.append(n.nodeValue.slice(last));
    n.replaceWith(frag);
  }
}

async function getServerVersion() {
  if (serverVersion !== undefined) return serverVersion;
  try {
    const r = await fetch("/openapi.json");
    serverVersion = r.ok ? (await r.json()).info?.version || null : null;
  } catch (e) {
    serverVersion = null;
  }
  return serverVersion;
}

async function renderFoot() {
  const foot = root.querySelector("#helpFoot");
  const v = await getServerVersion();
  const stale = v && v !== GUIDE_VERSION;
  foot.className = "help-foot" + (stale ? " stale" : "");
  foot.innerHTML =
    `Guide reviewed against SpecFlow ${esc(GUIDE_VERSION)} on ${esc(GUIDE_REVIEWED)}.` +
    (v ? ` This server runs ${esc(v)}.` : "") +
    (stale ? " Some details may have changed; the live lists on the reference pages always match this server." : "");
}

// Live catalogs from the server so defaults and names never go stale.
async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

const GENERATORS = {
  async steps() {
    // The catalog depends on the technique (e.g. Cosmic Ray Removal is vibrational only): merge both.
    const [vib, xps] = await Promise.all([
      getJson("/meta/pipeline-steps?technique_family=vibrational"),
      getJson("/meta/pipeline-steps?technique_family=xps"),
    ]);
    const xpsIds = new Set(xps.items.map((s) => s.id));
    const byId = new Map();
    for (const s of [...vib.items, ...xps.items]) if (s.palette_group && !byId.has(s.id)) byId.set(s.id, s);
    const rows = [...byId.values()]
      .map((s) => {
        const vibOnly = !xpsIds.has(s.id);
        return `<tr><td>${esc(s.label)}</td><td><code>${esc(s.id)}</code></td><td>${esc(s.palette_group)}</td><td>${esc(s.description || "")}${vibOnly ? " <i>(vibrational only)</i>" : ""}</td></tr>`;
      })
      .join("");
    return `<table><tr><th>Step</th><th>Internal name</th><th>Palette group</th><th>What it does (from the server)</th></tr>${rows}</table>
      <p class="hint">Internal names appear in the Plot card's “After: &lt;name&gt;” views and in pipeline JSON files.</p>`;
  },
  async baseline() {
    const d = await getJson("/pipeline/baseline-methods");
    return d.categories
      .map((c) => {
        const ms = d.methods.filter((m) => m.category === c.id && m.ui_enabled !== false);
        if (!ms.length) return "";
        const rows = ms
          .map((m) => {
            const prim = (m.params || [])
              .filter((p) => p.ui_role === "primary")
              .map((p) => `<code>${esc(p.key)}</code> = ${esc(p.default === null || p.default === undefined ? "auto" : p.default)}`)
              .join(", ");
            return `<tr><td><code>${esc(m.id)}</code></td><td>${prim || "<i>(no primary parameters)</i>"}</td></tr>`;
          })
          .join("");
        return `<h3>${esc(c.label)}</h3><table><tr><th>Method</th><th>Main parameters and defaults</th></tr>${rows}</table>`;
      })
      .join("");
  },
  async "fit-models"() {
    const d = await getJson("/fitting/models");
    const seen = new Set();
    const rows = d.components
      .filter((c) => !seen.has(c.component_type) && seen.add(c.component_type))
      .map((c) => {
        const ps = (c.params || [])
          .map((p) => `<code>${esc(p.key)}</code>${p.default === null || p.default === undefined ? "" : "=" + esc(p.default)}`)
          .join(", ");
        const name = c.display_name.replace(/[^\x20-\x7e]/g, "–");
        return `<tr><td><code>${esc(c.component_type)}</code></td><td>${esc(name)}</td><td>${ps}</td></tr>`;
      })
      .join("");
    return `<table><tr><th>Type id</th><th>Name</th><th>Parameters (start values where set)</th></tr>${rows}</table>`;
  },
};

async function hydrateGenerated(content) {
  for (const el of content.querySelectorAll("[data-gen]")) {
    const gen = GENERATORS[el.dataset.gen];
    if (!gen) continue;
    try {
      el.innerHTML = await gen();
      assignIds(content);
    } catch (e) {
      el.innerHTML = `<p class="hint">The live list is not available right now (${esc(e.message)}).</p>`;
    }
  }
}

// ---------------------------------------------------------------- pages

let navSeq = 0; // the latest navigation wins when several are in flight

export async function showPage(id, anchor, opts = {}) {
  if (!PAGE_IDS.has(id)) id = "start";
  const seq = ++navSeq;
  const content = root.querySelector("#helpContent");
  root.querySelector("#helpSearch").value = "";
  content.innerHTML = '<p class="hint">Loading…</p>';
  const html = await loadPage(id);
  if (seq !== navSeq) return;
  content.innerHTML = html;
  assignIds(content);
  if (AUTOLINK_PAGES(id)) autolink(content);
  addCopyButtons(content);
  current = id;
  try {
    localStorage.setItem(LAST_KEY, id);
  } catch (e) {
    /* storage unavailable */
  }
  if (opts.push !== false) writeRoute(id, anchor, false);
  else lastRoute = `#help/${id}${anchor ? "/" + anchor : ""}`;
  setActive(id);
  buildToc(content);
  renderPager(id);
  renderFoot();
  if (opts.highlight?.length) highlight(content, opts.highlight);
  await hydrateGenerated(content);
  if (seq !== navSeq) return;
  const target = anchor ? content.querySelector(`#${CSS.escape(anchor)}`) : null;
  if (target) target.scrollIntoView({ block: "start" });
  else root.scrollIntoView({ block: "start" });
}

const sectionCache = new Map();

// Split a page into sections at each h2/h3 so search can point at the exact heading.
async function sectionsOf(p) {
  if (sectionCache.has(p.id)) return sectionCache.get(p.id);
  const box = document.createElement("div");
  box.innerHTML = await loadPage(p.id);
  assignIds(box);
  const out = [];
  let cur = { id: "", heading: p.title, text: "" };
  for (const el of box.children) {
    if (el.tagName === "H2" || el.tagName === "H3") {
      out.push(cur);
      cur = { id: el.id, heading: el.textContent.trim(), text: "" };
    } else {
      cur.text += " " + el.textContent.replace(/\s+/g, " ");
    }
  }
  out.push(cur);
  const res = out.filter((s) => s.text.trim() || s.id);
  sectionCache.set(p.id, res);
  return res;
}

function mark(text, terms) {
  const ts = terms.filter((t) => t.length > 1);
  const safe = esc(text);
  if (!ts.length) return safe;
  const re = new RegExp("(" + ts.map((t) => esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi");
  return safe.replace(re, "<mark>$1</mark>");
}

async function runSearch(q) {
  if (!q) return showPage(current || "start", null, { push: false });
  const content = root.querySelector("#helpContent");
  root.querySelector("#helpToc").hidden = true;
  root.querySelector("#helpPager").innerHTML = "";
  content.innerHTML = '<p class="hint">Searching…</p>';
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  lastTerms = terms;
  // A term also matches the vocabulary registered for it (SYNONYMS).
  const expand = (t) => t + " " + Object.entries(SYNONYMS).filter(([k]) => t.includes(k)).map(([, v]) => v).join(" ");
  const expanded = terms.map(expand);

  const stepHits = STEPS.filter((st) => {
    const hay = (st.name + " " + st.words + " " + st.desc).toLowerCase();
    return expanded.every((alts, i) => hay.includes(terms[i]) || alts.split(" ").some((w) => w.length > 2 && hay.includes(w)));
  }).sort((a, b) => {
    const an = terms.every((t) => a.name.toLowerCase().includes(t)) ? 0 : 1;
    const bn = terms.every((t) => b.name.toLowerCase().includes(t)) ? 0 : 1;
    return an - bn;
  });

  const hits = [];
  for (const p of ALL_PAGES) {
    for (const sec of await sectionsOf(p)) {
      const head = sec.heading.toLowerCase();
      const low = (sec.heading + " " + sec.text).toLowerCase();
      if (!terms.every((t) => low.includes(t) || p.title.toLowerCase().includes(t))) continue;
      const at = sec.text.toLowerCase().indexOf(terms[0]);
      const snip = at >= 0 ? sec.text.slice(Math.max(0, at - 60), at + 140).trim() : sec.text.slice(0, 140).trim();
      const inHead = terms.every((t) => head.includes(t));
      const count = terms.reduce((n, t) => n + low.split(t).length - 1, 0);
      hits.push({ p, sec, snip, score: (inHead ? 1000 : 0) + count });
    }
  }
  hits.sort((a, b) => b.score - a.score);
  const shown = hits.slice(0, 40);

  let html = "";
  if (stepHits.length) {
    html +=
      "<h2>Pipeline steps</h2>" +
      stepHits
        .map(
          (st) =>
            `<p class="help-hit"><a href="#help/${st.target.replace("#", "/")}" data-help="${st.target}"><b>${mark(st.name, terms)}</b></a> <span class="hint">· pipeline step</span><br><span class="hint">${esc(st.desc)}</span></p>`
        )
        .join("");
  }
  if (shown.length) {
    html +=
      `<h2>${hits.length} matching section(s)</h2>` +
      shown
        .map((h) => {
          const target = h.sec.id ? `${h.p.id}#${h.sec.id}` : h.p.id;
          const label = h.sec.id ? `${esc(h.p.title)} › ${mark(h.sec.heading, terms)}` : esc(h.p.title);
          return `<p class="help-hit"><a href="#help/${target.replace("#", "/")}" data-help="${target}">${label}</a><br><span class="hint">…${mark(h.snip, terms)}…</span></p>`;
        })
        .join("");
  }
  if (!html) {
    html = `<h2>No match for “${esc(q)}”</h2><p class="hint">Try a shorter term, for example “baseline”, “Shirley”, “export”. Press <kbd>Esc</kbd> to clear.</p>`;
  }
  content.innerHTML = html;
}

// ---------------------------------------------------------------- in-app "Help" links

function addContextLinks() {
  const panels = ["tab-uploads", "tab-raw", "tab-spa"].map((id) => document.getElementById(id)).filter(Boolean);
  for (const panel of panels) {
    for (const el of panel.querySelectorAll(".section-title, .subsection-title")) {
      if (el.querySelector(".help-ctx") || el.dataset.helpCtx === "off") continue;
      const text = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.nodeValue).join("").trim() || el.textContent.trim();
      let target = CONTEXT_LINKS[text];
      if (text === "Plot") target = panel.id === "tab-raw" ? "r-raw" : "r-datasets#the-plot-card";
      if (!target) continue;
      const a = document.createElement("a");
      a.className = "help-ctx";
      a.href = `#help/${target.replace("#", "/")}`;
      a.dataset.helpOpen = target;
      a.title = "Open the Help page for this section";
      a.setAttribute("aria-label", `Help: ${text}`);
      a.textContent = "Help ↗";
      el.appendChild(a);
    }
  }
}

function initContextLinks() {
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a.help-ctx");
    if (!a) return;
    ev.preventDefault();
    ev.stopPropagation();
    window.openSpecFlowHelp(a.dataset.helpOpen);
  });
  let timer = null;
  const run = () => {
    clearTimeout(timer);
    timer = setTimeout(addContextLinks, 150);
  };
  new MutationObserver(run).observe(document.getElementById("appContent") || document.body, { childList: true, subtree: true });
  run();
}

// ---------------------------------------------------------------- public API

export function openHelp(pageId, anchor, opts = {}) {
  root = document.getElementById("help-root");
  if (!root) return;
  if (!built) buildShell();
  if (pageId) return showPage(pageId, anchor, opts);
  if (current) {
    writeRoute(current, null, true);
    return;
  }
  const r = routeFromHash();
  let id = r?.id;
  let last = null;
  try {
    last = localStorage.getItem(LAST_KEY);
  } catch (e) {
    /* storage unavailable */
  }
  return showPage(id || (PAGE_IDS.has(last) ? last : "start"), r?.anchor, { push: false, ...opts, replace: true }).then(() => {
    if (!r?.id) writeRoute(current, null, true);
  });
}

window.openSpecFlowHelp = (pageId) => {
  const panel = document.getElementById("tab-help");
  if (!panel?.classList.contains("active")) document.querySelector('#tabs .tab[data-tab="help"]')?.click();
  if (pageId) {
    const [id, anchor] = String(pageId).split("#");
    openHelp(id, anchor, { push: true });
  }
};

window.addEventListener("popstate", onHashChange);
window.addEventListener("hashchange", onHashChange);
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initContextLinks);
else initContextLinks();
// A shared link (#help/...) opens straight into Help.
if (/^#help/.test(window.location.hash)) {
  const go = () => document.querySelector('#tabs .tab[data-tab="help"]')?.click();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go);
  else setTimeout(go, 0);
}
