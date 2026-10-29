// Help tab: static HTML fragments under /static/help/pages/, rendered into #help-root.
// Pages are plain HTML (no build step). Cross-links use <a data-help="page-id#anchor">.

const PAGES_BASE = "/static/help/pages/";

export const HELP_SECTIONS = [
  {
    title: "Tutorials",
    pages: [
      { id: "start", title: "Start here: how SpecFlow works" },
      { id: "t-vibrational", title: "1 · SERS / Raman: files to correlation" },
      { id: "t-xps", title: "2 · XPS: calibrate, fit, compare" },
      { id: "t-maps", title: "3 · Maps and time series" },
      { id: "t-reuse", title: "4 · Reuse, share and export" },
      { id: "t-mcp", title: "5 · Work with an AI assistant (MCP)" },
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
      { id: "r-mcp", title: "MCP server: setup" },
      { id: "r-mcp-tools", title: "MCP server: tools and safety" },
      { id: "r-troubleshooting", title: "Troubleshooting" },
      { id: "r-glossary", title: "Glossary" },
    ],
  },
];

const ALL_PAGES = HELP_SECTIONS.flatMap((s) => s.pages);
const cache = new Map();
let root = null;
let current = null;
let built = false;

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

function textOf(html) {
  const d = document.createElement("div");
  d.innerHTML = html;
  return d.textContent.replace(/\s+/g, " ").trim();
}

function slug(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function buildShell() {
  root.innerHTML = `
    <aside class="help-nav" aria-label="Help navigation">
      <input id="helpSearch" class="help-search" type="search" placeholder="Search the guide…" aria-label="Search the guide" />
      <div id="helpNavList"></div>
    </aside>
    <article class="help-body">
      <div id="helpToc" class="help-toc" hidden></div>
      <div id="helpContent" class="help-content"></div>
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
      a.href = "#";
      a.className = "help-nav-link";
      a.dataset.help = p.id;
      a.textContent = p.title;
      list.appendChild(a);
    }
  }
  root.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-help]");
    if (!a) return;
    ev.preventDefault();
    const [id, anchor] = a.dataset.help.split("#");
    showPage(id, anchor);
  });
  const search = root.querySelector("#helpSearch");
  let timer = null;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => runSearch(search.value.trim()), 180);
  });
  built = true;
}

function setActive(id) {
  for (const a of root.querySelectorAll(".help-nav-link")) {
    a.classList.toggle("active", a.dataset.help === id);
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
  const used = new Set();
  toc.innerHTML = "<span>On this page:</span>";
  for (const h of heads) {
    let s = h.id || slug(h.textContent) || "section";
    while (used.has(s)) s += "-x";
    used.add(s);
    h.id = s;
    const a = document.createElement("a");
    a.href = `#${s}`;
    a.textContent = h.textContent;
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      h.scrollIntoView({ behavior: "smooth", block: "start" });
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
  if (prev) pager.innerHTML += `<a href="#" data-help="${prev.id}">← ${prev.title}</a>`;
  else pager.innerHTML += "<span></span>";
  if (next) pager.innerHTML += `<a href="#" data-help="${next.id}">${next.title} →</a>`;
}

export async function showPage(id, anchor) {
  if (!ALL_PAGES.some((p) => p.id === id)) id = "start";
  const content = root.querySelector("#helpContent");
  root.querySelector("#helpSearch").value = "";
  content.innerHTML = '<p class="hint">Loading…</p>';
  const html = await loadPage(id);
  content.innerHTML = html;
  current = id;
  setActive(id);
  buildToc(content);
  renderPager(id);
  const target = anchor ? content.querySelector(`#${CSS.escape(anchor)}`) : null;
  if (target) target.scrollIntoView({ block: "start" });
  else root.scrollIntoView({ block: "start" });
}

async function runSearch(q) {
  if (!q) return showPage(current || "start");
  const content = root.querySelector("#helpContent");
  root.querySelector("#helpToc").hidden = true;
  root.querySelector("#helpPager").innerHTML = "";
  content.innerHTML = '<p class="hint">Searching…</p>';
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  const hits = [];
  for (const p of ALL_PAGES) {
    const text = textOf(await loadPage(p.id));
    const low = text.toLowerCase();
    if (!terms.every((t) => low.includes(t) || p.title.toLowerCase().includes(t))) continue;
    const at = low.indexOf(terms[0]);
    const snip = at >= 0 ? text.slice(Math.max(0, at - 60), at + 140) : text.slice(0, 140);
    const count = terms.reduce((n, t) => n + low.split(t).length - 1, 0);
    hits.push({ p, snip, count });
  }
  hits.sort((a, b) => b.count - a.count);
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
  content.innerHTML = hits.length
    ? `<h2>${hits.length} page(s) match “${esc(q)}”</h2>` +
      hits
        .map(
          (h) =>
            `<p class="help-hit"><a href="#" data-help="${h.p.id}">${esc(h.p.title)}</a><br><span class="hint">…${esc(h.snip)}…</span></p>`
        )
        .join("")
    : `<h2>No page matches “${esc(q)}”</h2><p class="hint">Try a shorter term, e.g. “baseline”, “Shirley”, “export”.</p>`;
}

export function openHelp(pageId) {
  root = document.getElementById("help-root");
  if (!root) return;
  if (!built) buildShell();
  if (pageId || !current) showPage(pageId || "start");
}

window.openSpecFlowHelp = (pageId) => {
  document.querySelector('#tabs .tab[data-tab="help"]')?.click();
  if (pageId) {
    const [id, anchor] = String(pageId).split("#");
    openHelp();
    showPage(id, anchor);
  }
};
