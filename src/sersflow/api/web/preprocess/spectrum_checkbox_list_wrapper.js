import React from "https://esm.sh/react@18.3.1";
import { createUploadsModel, formatFileSizeMb } from "/static/ui/uploads.js";

export function SpectrumCheckboxListWrapper({ onSelectionChange }) {
  const metaRef = React.useRef(null);
  const scrollerRef = React.useRef(null);
  const modelRef = React.useRef(null);
  const [items, setItems] = React.useState([]);
  const [query, setQuery] = React.useState("");
  const [scrollTop, setScrollTop] = React.useState(0);

  React.useEffect(() => {
    const m = createUploadsModel();
    modelRef.current = m;
    let disposed = false;
    (async () => {
      try {
        const out = await m.refreshUploadedList();
        if (disposed) return;
        setItems(out.items || []);
        if (metaRef.current) metaRef.current.textContent = `${(out.items || []).length} file(s) • ${m.getSelectedSet().size} selected`;
      } catch {
        if (disposed) return;
        setItems([]);
      }
    })();
    return () => {
      disposed = true;
      modelRef.current = null;
    };
  }, [onSelectionChange]);

  React.useEffect(() => {
    const m = modelRef.current;
    if (!m || !metaRef.current) return;
    metaRef.current.textContent = `${items.length} file(s) • ${m.getSelectedSet().size} selected`;
  }, [items]);

  const filtered = React.useMemo(() => {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => String(it.filename || "").toLowerCase().includes(q) || String(it.relative_path || "").toLowerCase().includes(q));
  }, [items, query]);

  const rowH = 28;
  const viewportH = 240;
  const overscan = 6;
  const total = filtered.length;
  const visibleCount = Math.ceil(viewportH / rowH);
  const start = Math.max(0, Math.floor(scrollTop / rowH) - overscan);
  const end = Math.min(total, start + visibleCount + overscan * 2);
  const padTop = start * rowH;
  const padBot = Math.max(0, (total - end) * rowH);

  function emitSelection() {
    const m = modelRef.current;
    if (!m) return;
    if (typeof onSelectionChange === "function") onSelectionChange(Array.from(m.getSelectedSet().values()));
    if (metaRef.current) metaRef.current.textContent = `${items.length} file(s) • ${m.getSelectedSet().size} selected`;
  }

  return React.createElement(
    "div",
    null,
    React.createElement(
      "div",
      { className: "row", style: { justifyContent: "space-between" } },
      React.createElement("div", { className: "uploads-meta", ref: metaRef }),
      React.createElement("input", {
        type: "text",
        placeholder: "Filter…",
        value: query,
        onChange: (e) => setQuery(e.target.value),
        style: { width: "200px", padding: "8px", borderRadius: "10px", border: "1px solid var(--border)", background: "rgba(0,0,0,0.18)", color: "var(--text)" },
      })
    ),
    React.createElement(
      "div",
      {
        className: "scrollbox",
        style: { maxHeight: `${viewportH}px`, padding: "0" },
        ref: scrollerRef,
        onScroll: (e) => setScrollTop(e.target.scrollTop || 0),
      },
      React.createElement(
        "div",
        { style: { paddingTop: `${padTop}px`, paddingBottom: `${padBot}px` } },
        ...filtered.slice(start, end).map((it) => {
          const rel = it.relative_path;
          const key = rel;
          const m = modelRef.current;
          const checked = m ? m.getSelectedSet().has(rel) : false;
          return React.createElement(
            "div",
            { key, className: "uploads-item", style: { height: `${rowH}px`, padding: "0 6px" } },
            React.createElement("input", {
              type: "checkbox",
              checked,
              onChange: (e) => {
                const mm = modelRef.current;
                if (!mm) return;
                mm.toggle(rel, e.target.checked);
                emitSelection();
              },
            }),
            React.createElement(
              "label",
              {
                title: `${it.filename} — ${formatFileSizeMb(it.size_bytes)}`,
                onClick: () => {
                  const mm = modelRef.current;
                  if (!mm) return;
                  mm.toggle(rel);
                  emitSelection();
                },
              },
              `${it.filename} (${formatFileSizeMb(it.size_bytes)})`
            )
          );
        })
      )
    )
  );
}

