import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import {
  applyFittingRecipe,
  listFittingRecipeIndex,
  listFittingRecipesCatalog,
  type FittingRecipeApplyResponse,
  type FittingRecipeIndexItem,
} from "./api";
import {
  isPeakComponentType,
  migrateFittingParamsToEditor,
  type FittingEditorParams,
} from "./fittingUtils";
import type { FittingComponentSpecPublic } from "./api";
import { preferPassEnergy } from "./passEnergyUtils";

const INDEX_LIMIT = 200;
const DROPDOWN_CAP = 25;

/** Normalize for fuzzy match: "C 1s" / "C1s" / "C_1s" → "c1s". */
function normalizeRecipeNeedle(s: string): string {
  return s.trim().toLowerCase().replace(/[\s_\-/]+/g, "");
}

function filterIndex(items: FittingRecipeIndexItem[], q: string): FittingRecipeIndexItem[] {
  const raw = q.trim().toLowerCase();
  if (!raw) {
    // Browse mode: first DROPDOWN_CAP items from the index (stable catalog order).
    return items.slice(0, DROPDOWN_CAP);
  }
  const needle = normalizeRecipeNeedle(raw);
  const matched = items.filter((it) => {
    const parts = [
      it.label,
      it.compound,
      it.element,
      it.region,
      it.id,
      it.source_table ?? "",
      ...(it.aliases ?? []),
    ];
    const hay = parts.join(" ").toLowerCase();
    const hayNorm = normalizeRecipeNeedle(parts.join(" "));
    return hay.includes(raw) || (needle.length > 0 && hayNorm.includes(needle));
  });
  return matched.slice(0, DROPDOWN_CAP);
}

/** True when the editor looks like an untouched default single gaussian. */
export function isDefaultFittingEditor(fp: FittingEditorParams): boolean {
  if (fp.components.length !== 1) return false;
  const c = fp.components[0]!;
  if (c.component_type !== "gaussian") return false;
  if ((fp.param_links ?? []).length > 0) return false;
  if (String(fp.recipe_id ?? "").trim()) return false;
  const id = String(c.component_id ?? "").trim();
  return !id || id === "p1";
}

export function mergeRecipeApplyIntoEditor(
  current: FittingEditorParams,
  applied: FittingRecipeApplyResponse,
  catalog: FittingComponentSpecPublic[] | undefined
): FittingEditorParams {
  const migrated = migrateFittingParamsToEditor(
    {
      components: applied.components,
      p0: applied.p0,
      bounds_lower: applied.bounds_lower,
      bounds_upper: applied.bounds_upper,
      vary: applied.vary,
      param_links: applied.param_links,
      xps_region: applied.xps_region,
      recipe_id: applied.recipe_id,
      recipe_pass_energy: applied.recipe_pass_energy,
    },
    catalog
  );
  return {
    ...migrated,
    output_mode: current.output_mode,
    fill_opacity: current.fill_opacity,
    initial_guess_mode: current.initial_guess_mode,
    recipe_id: applied.recipe_id,
    recipe_pass_energy: applied.recipe_pass_energy,
  };
}

type Props = {
  fittingParams: FittingEditorParams;
  fittingCatalog: FittingComponentSpecPublic[] | undefined;
  enabled: boolean;
  preferredPassEnergy?: number | null;
  onApply: (next: FittingEditorParams, warnings: string[]) => void;
};

export function FittingRecipePicker({
  fittingParams,
  fittingCatalog,
  enabled,
  preferredPassEnergy,
  onApply,
}: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [showMethods, setShowMethods] = useState(false);
  const blurTimer = useRef<number | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [panelPos, setPanelPos] = useState<{ top: number; left: number; width: number } | null>(null);

  const indexQ = useQuery({
    queryKey: ["xps-fitting-recipes-index"],
    queryFn: () => listFittingRecipeIndex({ limit: INDEX_LIMIT }),
    enabled,
    staleTime: Infinity,
  });

  const methodsQ = useQuery({
    queryKey: ["xps-fitting-recipes-methods"],
    queryFn: () => listFittingRecipesCatalog({ include_methods: true }),
    enabled: enabled && showMethods,
    staleTime: Infinity,
  });

  const items = indexQ.data?.items ?? [];
  const matches = useMemo(() => filterIndex(items, query), [items, query]);
  const showPanel = open && matches.length > 0;

  useLayoutEffect(() => {
    if (!showPanel) {
      setPanelPos(null);
      return;
    }
    const place = () => {
      const el = inputRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const maxH = 220;
      const gap = 2;
      const spaceBelow = window.innerHeight - r.bottom - 8;
      const openUp = spaceBelow < Math.min(maxH, 120) && r.top > spaceBelow;
      setPanelPos({
        top: openUp ? Math.max(8, r.top - maxH - gap) : r.bottom + gap,
        left: Math.max(8, Math.min(r.left, window.innerWidth - r.width - 8)),
        width: r.width,
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [showPanel, matches.length, query]);

  const elementChips = useMemo(() => {
    const set = new Set<string>();
    for (const it of items) {
      const el = String(it.element || "").trim();
      if (el) set.add(el);
    }
    return [...set].sort().slice(0, 12);
  }, [items]);

  const selectedId = String(fittingParams.recipe_id ?? "").trim();
  const selectedItem = items.find((it) => it.id === selectedId);
  const passEnergies = selectedItem?.pass_energies?.length
    ? selectedItem.pass_energies
    : fittingParams.recipe_pass_energy
      ? [fittingParams.recipe_pass_energy]
      : [];

  function defaultPassEnergy(item: FittingRecipeIndexItem): number | undefined {
    return preferPassEnergy(item.pass_energies ?? [], preferredPassEnergy);
  }

  async function loadRecipe(id: string, passEnergy?: number, skipConfirm?: boolean) {
    if (!skipConfirm && !isDefaultFittingEditor(fittingParams)) {
      const ok = window.confirm(`Replace current peaks with recipe ${id}?`);
      if (!ok) return;
    }
    setBusy(true);
    setErr(null);
    try {
      const applied = await applyFittingRecipe(id, {
        pass_energy: passEnergy,
        include_background: true,
        preferred_pass_energy: preferredPassEnergy ?? undefined,
      });
      const next = mergeRecipeApplyIntoEditor(fittingParams, applied, fittingCatalog);
      setWarnings(applied.warnings ?? []);
      setQuery(applied.recipe_id);
      setOpen(false);
      onApply(next, applied.warnings ?? []);
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  function onPick(item: FittingRecipeIndexItem) {
    void loadRecipe(item.id, defaultPassEnergy(item), false);
  }

  function onPassEnergyChange(pe: number) {
    if (!selectedId) return;
    void loadRecipe(selectedId, pe, true);
  }

  if (!enabled) return null;

  return (
    <div style={{ display: "grid", gap: "6px" }}>
      <div className="hint" style={{ fontWeight: 800 }}>
        XPS fitting recipe
      </div>
      {elementChips.length ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
          {elementChips.map((el) => (
            <button
              key={el}
              type="button"
              className="mini"
              disabled={busy}
              onClick={() => {
                setQuery(el);
                setOpen(true);
                setHighlight(0);
              }}
              title={`Filter recipes for ${el}`}
            >
              {el}
            </button>
          ))}
        </div>
      ) : null}
      <label className="inline" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <span className="hint">Search / browse</span>
        <div style={{ position: "relative", width: "260px" }}>
          <input
            ref={inputRef}
            type="text"
            value={query}
            placeholder="Browse or type C 1s, NiO…"
            disabled={busy || indexQ.isLoading}
            onChange={(e) => {
              setQuery(e.target.value);
              setOpen(true);
              setHighlight(0);
            }}
            onFocus={() => {
              if (blurTimer.current) window.clearTimeout(blurTimer.current);
              setOpen(true);
            }}
            onBlur={() => {
              blurTimer.current = window.setTimeout(() => setOpen(false), 150);
            }}
            onKeyDown={(e) => {
              if (!open || matches.length === 0) return;
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setHighlight((h) => Math.min(h + 1, matches.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setHighlight((h) => Math.max(h - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                const item = matches[highlight];
                if (item) onPick(item);
              } else if (e.key === "Escape") {
                setOpen(false);
              }
            }}
            style={{ width: "100%" }}
            title="Focus with empty query to browse; type to search"
          />
          {showPanel && panelPos
            ? createPortal(
                <div
                  role="listbox"
                  style={{
                    position: "fixed",
                    zIndex: 10050,
                    left: panelPos.left,
                    top: panelPos.top,
                    width: panelPos.width,
                    maxHeight: "220px",
                    overflow: "auto",
                    padding: "4px 0",
                    borderRadius: "12px",
                    background: "#12182a",
                    color: "var(--text)",
                    border: "1px solid var(--border)",
                    boxShadow: "0 10px 28px rgba(0, 0, 0, 0.55)",
                  }}
                >
                  {!query.trim() ? (
                    <div className="hint" style={{ padding: "4px 10px" }}>
                      Browse (top {DROPDOWN_CAP})
                    </div>
                  ) : null}
                  {matches.map((it, i) => (
                    <button
                      key={it.id}
                      type="button"
                      className="mini"
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        border: "none",
                        borderRadius: 0,
                        color: "var(--text)",
                        background: i === highlight ? "rgba(255,255,255,0.12)" : "transparent",
                        fontWeight: i === highlight ? 700 : 400,
                      }}
                      onMouseDown={(ev) => ev.preventDefault()}
                      onClick={() => onPick(it)}
                      onMouseEnter={() => setHighlight(i)}
                    >
                      {it.label}
                      {it.pass_energies?.length ? (
                        <span className="hint"> · PE {it.pass_energies.join("/")}</span>
                      ) : null}
                    </button>
                  ))}
                </div>,
                document.body
              )
            : null}
        </div>
      </label>
      <label className="inline" style={{ justifyContent: "space-between" }}>
        Pass energy (eV)
        <select
          value={fittingParams.recipe_pass_energy ?? ""}
          disabled={!selectedId || busy || passEnergies.length === 0}
          onChange={(e) => {
            const pe = Number(e.target.value);
            if (Number.isFinite(pe)) onPassEnergyChange(pe);
          }}
          style={{ width: "100px" }}
        >
          <option value="">—</option>
          {passEnergies.map((pe) => (
            <option key={pe} value={pe}>
              {pe}
            </option>
          ))}
        </select>
      </label>
      <button type="button" className="mini" onClick={() => setShowMethods((v) => !v)}>
        {showMethods ? "Hide method defaults" : "Show method defaults / charge-ref"}
      </button>
      {showMethods ? (
        <div className="hint" style={{ maxHeight: 160, overflow: "auto", whiteSpace: "pre-wrap" }}>
          {methodsQ.isLoading ? "Loading…" : null}
          {methodsQ.isError ? String((methodsQ.error as Error)?.message ?? methodsQ.error) : null}
          {(methodsQ.data?.method_defaults ?? []).map((m) => (
            <div key={m.id} style={{ marginBottom: 8 }}>
              <strong>
                Ch.{m.chapter} {m.id}
              </strong>
              {m.background ? ` · BG ${m.background}` : ""}
              {m.charge_ref && Object.keys(m.charge_ref).length
                ? ` · charge_ref ${JSON.stringify(m.charge_ref)}`
                : ""}
              {m.default_lineshape ? `\n default LS: ${JSON.stringify(m.default_lineshape)}` : ""}
              {m.metal_lineshape ? `\n metal LS: ${JSON.stringify(m.metal_lineshape)}` : ""}
              <div>
                <button
                  type="button"
                  className="mini"
                  disabled={busy}
                  onClick={() => {
                    const peakCount = countPeakComponents(fittingParams);
                    if (peakCount > 0) {
                      const ok = window.confirm(
                        `Apply chapter ${m.chapter} method defaults as notes only?\n` +
                          `This will not overwrite your ${peakCount} peak component(s).`
                      );
                      if (!ok) return;
                    }
                    const notes: string[] = [
                      `Method defaults (${m.id}): charge_ref ${JSON.stringify(m.charge_ref ?? {})}`,
                    ];
                    if (m.default_lineshape) {
                      notes.push(`default lineshape hint: ${JSON.stringify(m.default_lineshape)}`);
                    }
                    if (m.metal_lineshape) {
                      notes.push(`metal lineshape hint: ${JSON.stringify(m.metal_lineshape)}`);
                    }
                    if (m.background) {
                      notes.push(`preferred background: ${m.background}`);
                    }
                    setWarnings(notes);
                    onApply(fittingParams, notes);
                  }}
                >
                  Apply notes (no overwrite)
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : null}
      {selectedId ? (
        <div className="hint">
          Loaded: <code>{selectedId}</code>
          {fittingParams.recipe_pass_energy != null ? ` @ ${fittingParams.recipe_pass_energy} eV` : ""}
        </div>
      ) : null}
      {busy ? <div className="hint">Loading recipe…</div> : null}
      {indexQ.isError ? (
        <div className="err">Could not load recipe index: {String((indexQ.error as Error)?.message ?? indexQ.error)}</div>
      ) : null}
      {err ? <div className="err">{err}</div> : null}
      {warnings.length ? <div className="hint">Warnings: {warnings.join("; ")}</div> : null}
    </div>
  );
}

/** Count peak components (exclude XPS backgrounds / poly). */
export function countPeakComponents(fp: FittingEditorParams): number {
  return fp.components.filter((c) => isPeakComponentType(c.component_type)).length;
}
