import { useEffect, useId, useRef, useState } from "react";

export type TickDropdownProps = {
  label?: string;
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  /** Shown when nothing is selected (e.g. "All regions"). */
  emptySummary?: string;
  disabled?: boolean;
  title?: string;
  /**
   * `select` matches workspace <select> chrome (for toolbars next to action buttons).
   * `button` keeps the compact mini action look.
   */
  appearance?: "button" | "select";
};

/**
 * Compact multi-select: summary trigger + checkbox panel.
 */
export function TickDropdown({
  label,
  options,
  selected,
  onChange,
  emptySummary = "All",
  disabled,
  title,
  appearance = "button",
}: TickDropdownProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const listId = useId();
  const selectedSet = new Set(selected);
  const asSelect = appearance === "select";

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const el = rootRef.current;
      if (!el) return;
      if (e.target instanceof Node && !el.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const summary =
    selected.length === 0
      ? emptySummary
      : selected.length <= 2
        ? selected.join(", ")
        : `${selected.length} selected`;

  function toggle(v: string) {
    if (selectedSet.has(v)) onChange(selected.filter((x) => x !== v));
    else onChange([...selected, v]);
  }

  const trigger = (
    <button
      type="button"
      className={asSelect ? undefined : "mini"}
      disabled={disabled || options.length === 0}
      aria-expanded={open}
      aria-controls={listId}
      aria-haspopup="listbox"
      onClick={() => setOpen((x) => !x)}
      style={
        asSelect
          ? {
              width: "auto",
              minWidth: "160px",
              maxWidth: "280px",
              padding: "10px 12px",
              borderRadius: "12px",
              border: "1px solid var(--border)",
              background: "rgba(0, 0, 0, 0.18)",
              color: "var(--text)",
              textAlign: "left",
              cursor: disabled || options.length === 0 ? "not-allowed" : "pointer",
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "10px",
            }
          : undefined
      }
    >
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{summary}</span>
      {asSelect ? <span aria-hidden="true" style={{ opacity: 0.7, fontSize: "11px" }}>▾</span> : null}
    </button>
  );

  return (
    <div
      ref={rootRef}
      className="tick-dropdown"
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        gap: label && !asSelect ? undefined : "8px",
        // Raise whole control above later siblings (upload picker, cards) while open.
        zIndex: open ? 300 : undefined,
      }}
      title={title}
    >
      {asSelect ? (
        <label className="inline" style={{ margin: 0, display: "inline-flex", alignItems: "center", gap: "8px" }}>
          {label ? <span>{label}</span> : null}
          {trigger}
        </label>
      ) : (
        <>
          {label ? (
            <span className="hint" style={{ marginRight: "6px" }}>
              {label}
            </span>
          ) : null}
          {trigger}
        </>
      )}
      {open ? (
        <div
          id={listId}
          role="listbox"
          aria-multiselectable="true"
          className="tick-dropdown-panel"
          style={{
            position: "absolute",
            zIndex: 1,
            top: "calc(100% + 4px)",
            left: 0,
            minWidth: "min(240px, 80vw)",
            maxHeight: "220px",
            overflow: "auto",
            padding: "8px",
            borderRadius: "12px",
            // Fully opaque: parent .card uses backdrop-filter blur; translucent panels look washed out.
            background: "#12182a",
            color: "var(--text)",
            border: "1px solid var(--border)",
            boxShadow: "0 10px 28px rgba(0, 0, 0, 0.55)",
          }}
        >
          <div className="row" style={{ marginBottom: "6px", gap: "6px" }}>
            <button type="button" className="mini" onClick={() => onChange([])} disabled={!selected.length}>
              Clear
            </button>
          </div>
          {options.map((opt) => (
            <label
              key={opt}
              className="inline"
              style={{
                display: "flex",
                gap: "8px",
                alignItems: "center",
                margin: "2px 0",
                color: "var(--text)",
                cursor: "pointer",
              }}
            >
              <input type="checkbox" checked={selectedSet.has(opt)} onChange={() => toggle(opt)} />
              <span style={{ fontFamily: "var(--mono)", fontSize: "12px", color: "var(--text)" }}>{opt}</span>
            </label>
          ))}
          {!options.length ? <div className="hint">No options</div> : null}
        </div>
      ) : null}
    </div>
  );
}
