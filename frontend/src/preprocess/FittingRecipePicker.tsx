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
  defaultFittingEditorParams,
  isPeakComponentType,
  isXpsBgComponentType,
  migrateFittingParamsToEditor,
  setBandAmplitudeAutos,
  uniqueComponentIdAgainst,
  type FittingEditorParams,
  type FittingParamLink,
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

export function recipeIdsOf(fp: FittingEditorParams): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const push = (s: string) => {
    const t = s.trim();
    if (!t || seen.has(t)) return;
    seen.add(t);
    out.push(t);
  };
  for (const id of fp.recipe_ids ?? []) push(String(id ?? ""));
  push(String(fp.recipe_id ?? ""));
  return out;
}

function nonBgComponentIds(fp: FittingEditorParams): string[] {
  return fp.components
    .filter((c) => !isXpsBgComponentType(c.component_type))
    .map((c) => String(c.component_id ?? "").trim())
    .filter(Boolean);
}

/** True when the editor looks like an untouched default single gaussian. */
export function isDefaultFittingEditor(fp: FittingEditorParams): boolean {
  if (fp.components.length !== 1) return false;
  const c = fp.components[0]!;
  if (c.component_type !== "gaussian") return false;
  if ((fp.param_links ?? []).length > 0) return false;
  if (recipeIdsOf(fp).length > 0) return false;
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
      recipe_pass_energy: applied.recipe_pass_energy ?? undefined,
    },
    catalog
  );
  const rid = String(applied.recipe_id ?? "").trim();
  const peakIds = nonBgComponentIds(migrated);
  const ratios = String(applied.initial_area_ratios ?? "").trim();
  const base: FittingEditorParams = {
    ...migrated,
    output_mode: current.output_mode,
    fill_opacity: current.fill_opacity,
    initial_guess_mode: "default",
    recipe_id: rid,
    recipe_ids: rid ? [rid] : [],
    recipe_components: rid && peakIds.length ? { [rid]: peakIds } : {},
    recipe_pass_energy: applied.recipe_pass_energy ?? undefined,
    fit_min_x: current.fit_min_x ?? null,
    fit_max_x: current.fit_max_x ?? null,
    initial_area_ratios: ratios,
  };
  // Recipe apply: enable band amp Auto so chord+ratio guess runs on next fit.
  return setBandAmplitudeAutos(base, true);
}

/** Append peaks from a second recipe; skip backgrounds; rename colliding ids. */
export function appendRecipeApplyIntoEditor(
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
      recipe_pass_energy: applied.recipe_pass_energy ?? undefined,
    },
    catalog
  );

  const used = new Set<string>();
  for (const c of current.components) {
    const id = String(c.component_id ?? "").trim();
    if (id) used.add(id.toLowerCase());
  }

  const idMap = new Map<string, string>();
  const addedComps = migrated.components
    .filter((c) => !isXpsBgComponentType(c.component_type))
    .map((c) => {
      const oldId = String(c.component_id ?? "").trim() || "p";
      const newId = uniqueComponentIdAgainst(oldId, used);
      idMap.set(oldId, newId);
      idMap.set(oldId.toLowerCase(), newId);
      return { ...c, component_id: newId };
    });

  if (!addedComps.length) {
    throw new Error("Added recipe contributed no non-background components");
  }

  const remap = (cid: string): string => idMap.get(cid) ?? idMap.get(cid.toLowerCase()) ?? cid;
  const known = new Set(
    [...current.components, ...addedComps].map((c) => String(c.component_id ?? "").trim())
  );
  const remappedLinks: FittingParamLink[] = (migrated.param_links ?? [])
    .map((l) => ({
      ...l,
      source_component_id: remap(l.source_component_id),
      target_component_id: remap(l.target_component_id),
    }))
    .filter((l) => known.has(l.source_component_id) && known.has(l.target_component_id));

  const existingIds = recipeIdsOf(current);
  const rid = String(applied.recipe_id ?? "").trim();
  const recipe_ids = rid && !existingIds.includes(rid) ? [...existingIds, rid] : [...existingIds];
  const recipe_components = { ...(current.recipe_components ?? {}) };
  if (rid) {
    recipe_components[rid] = addedComps.map((c) => c.component_id);
  }

  const addedRatios = String(applied.initial_area_ratios ?? "").trim();
  const curRatios = String(current.initial_area_ratios ?? "").trim();
  let initial_area_ratios = curRatios;
  if (addedRatios) {
    initial_area_ratios = curRatios ? `${curRatios}:${addedRatios}` : addedRatios;
  }

  const base: FittingEditorParams = {
    ...current,
    components: [...current.components, ...addedComps],
    param_links: [...(current.param_links ?? []), ...remappedLinks],
    xps_region: String(current.xps_region ?? "").trim() || migrated.xps_region || "",
    recipe_id: recipe_ids[0] ?? rid,
    recipe_ids,
    recipe_components,
    recipe_pass_energy: applied.recipe_pass_energy ?? current.recipe_pass_energy,
    initial_guess_mode: "default",
    initial_area_ratios,
  };
  return setBandAmplitudeAutos(base, true);
}

/** Remove one stacked recipe and the peaks it contributed (shared baseline kept if others remain). */
export function removeRecipeFromEditor(
  current: FittingEditorParams,
  recipeId: string,
  catalog: FittingComponentSpecPublic[] | undefined
): FittingEditorParams {
  const rid = recipeId.trim();
  if (!rid) return current;
  const owned = new Set((current.recipe_components?.[rid] ?? []).map((x) => x.trim()).filter(Boolean));
  const recipe_ids = recipeIdsOf(current).filter((id) => id !== rid);
  const recipe_components = { ...(current.recipe_components ?? {}) };
  delete recipe_components[rid];

  if (!recipe_ids.length) {
    const cleared = defaultFittingEditorParams(catalog);
    return {
      ...cleared,
      output_mode: current.output_mode,
      fill_opacity: current.fill_opacity,
      fit_min_x: current.fit_min_x ?? null,
      fit_max_x: current.fit_max_x ?? null,
      xps_region: current.xps_region ?? "",
    };
  }

  const dropIds = owned.size
    ? owned
    : new Set<string>(); // unknown ownership: only drop provenance, keep components
  const components = current.components.filter((c) => {
    const id = String(c.component_id ?? "").trim();
    if (!id) return true;
    if (isXpsBgComponentType(c.component_type)) return true;
    return !dropIds.has(id);
  });
  const keepIds = new Set(components.map((c) => String(c.component_id ?? "").trim()).filter(Boolean));
  const param_links = (current.param_links ?? []).filter(
    (l) => keepIds.has(l.source_component_id) && keepIds.has(l.target_component_id)
  );

  const stillHasPeaks = components.some((c) => !isXpsBgComponentType(c.component_type));
  if (!stillHasPeaks) {
    const cleared = defaultFittingEditorParams(catalog);
    return {
      ...cleared,
      output_mode: current.output_mode,
      fill_opacity: current.fill_opacity,
      fit_min_x: current.fit_min_x ?? null,
      fit_max_x: current.fit_max_x ?? null,
      xps_region: current.xps_region ?? "",
    };
  }

  return {
    ...current,
    components,
    param_links,
    recipe_id: recipe_ids[0] ?? "",
    recipe_ids,
    recipe_components,
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
  const loadedRecipeIds = recipeIdsOf(fittingParams);
  const multiRecipes = loadedRecipeIds.length > 1;

  const activeRecipes = useMemo(() => {
    return loadedRecipeIds.map((id) => {
      const it = items.find((x) => x.id === id);
      return {
        id,
        label: it?.label ?? id,
        peakCount: (fittingParams.recipe_components?.[id] ?? []).length,
      };
    });
  }, [loadedRecipeIds, items, fittingParams.recipe_components]);

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

  const selectedId = loadedRecipeIds.length === 1 ? loadedRecipeIds[0]! : "";
  const selectedItem = items.find((it) => it.id === selectedId);
  const passEnergies = selectedItem?.pass_energies?.length
    ? selectedItem.pass_energies
    : !multiRecipes && fittingParams.recipe_pass_energy
      ? [fittingParams.recipe_pass_energy]
      : [];

  function defaultPassEnergy(item: FittingRecipeIndexItem): number | undefined {
    return preferPassEnergy(item.pass_energies ?? [], preferredPassEnergy);
  }

  async function loadRecipe(
    id: string,
    passEnergy?: number,
    mode: "replace" | "add" | "auto" = "auto"
  ) {
    let resolved: "replace" | "add" = mode === "auto" ? "replace" : mode;
    if (mode === "auto" && !isDefaultFittingEditor(fittingParams)) {
      const add = window.confirm(
        `Current fitting already has components.\n\n` +
          `OK = ADD peaks from ${id} (no extra baseline)\n` +
          `Cancel = choose Replace or abort`
      );
      if (add) {
        resolved = "add";
      } else {
        const replace = window.confirm(`Replace all peaks with recipe ${id}?`);
        if (!replace) return;
        resolved = "replace";
      }
    }

    setBusy(true);
    setErr(null);
    try {
      const applied = await applyFittingRecipe(id, {
        pass_energy: passEnergy,
        include_background: resolved === "replace",
        preferred_pass_energy: preferredPassEnergy ?? undefined,
      });
      const next =
        resolved === "add"
          ? appendRecipeApplyIntoEditor(fittingParams, applied, fittingCatalog)
          : mergeRecipeApplyIntoEditor(fittingParams, applied, fittingCatalog);
      const notes = [...(applied.warnings ?? [])];
      if (resolved === "add") {
        notes.push(`Added peaks from ${id} (background skipped)`);
      }
      setWarnings(notes);
      setQuery("");
      setOpen(false);
      onApply(next, notes);
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  function onPick(item: FittingRecipeIndexItem) {
    void loadRecipe(item.id, defaultPassEnergy(item), "auto");
  }

  function onPassEnergyChange(pe: number) {
    if (!selectedId || multiRecipes) return;
    void loadRecipe(selectedId, pe, "replace");
  }

  function onRemoveRecipe(id: string) {
    const next = removeRecipeFromEditor(fittingParams, id, fittingCatalog);
    setWarnings([`Removed recipe ${id}`]);
    onApply(next, [`Removed recipe ${id}`]);
  }

  if (!enabled) return null;

  return (
    <div style={{ display: "grid", gap: "8px" }}>
      <div className="hint" style={{ fontWeight: 800 }}>
        XPS fitting recipe
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(180px, 1.2fr) minmax(160px, 1fr)",
          gap: "12px",
          alignItems: "start",
        }}
      >
        {/* Left: search / browse */}
        <div style={{ display: "grid", gap: "6px", minWidth: 0 }}>
          <div className="hint">Search / browse</div>
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
          <div style={{ position: "relative", width: "100%" }}>
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
          <label className="inline" style={{ justifyContent: "space-between" }}>
            Pass energy (eV)
            <select
              value={!multiRecipes ? (fittingParams.recipe_pass_energy ?? "") : ""}
              disabled={!selectedId || busy || passEnergies.length === 0 || multiRecipes}
              onChange={(e) => {
                const pe = Number(e.target.value);
                if (Number.isFinite(pe)) onPassEnergyChange(pe);
              }}
              style={{ width: "100px" }}
              title={
                multiRecipes
                  ? "Pass energy re-apply is disabled while multiple recipes are loaded"
                  : undefined
              }
            >
              <option value="">—</option>
              {passEnergies.map((pe) => (
                <option key={pe} value={pe}>
                  {pe}
                </option>
              ))}
            </select>
          </label>
          {multiRecipes ? (
            <div className="hint">PE locked with multiple recipes (remove extras or Replace).</div>
          ) : null}
        </div>

        {/* Right: active recipes */}
        <div style={{ display: "grid", gap: "6px", minWidth: 0 }}>
          <div className="hint">Active recipes</div>
          {activeRecipes.length === 0 ? (
            <div className="hint" style={{ opacity: 0.8 }}>
              None loaded — pick a recipe on the left.
            </div>
          ) : (
            <div style={{ display: "grid", gap: "4px" }}>
              {activeRecipes.map((r, idx) => (
                <div
                  key={r.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "8px",
                    padding: "4px 8px",
                    borderRadius: "8px",
                    border: "1px solid var(--border)",
                    background: "rgba(255,255,255,0.03)",
                  }}
                >
                  <div style={{ minWidth: 0, flex: "1 1 auto" }}>
                    <div style={{ fontWeight: 700, fontSize: "12px", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {idx === 0 ? "Base · " : "Added · "}
                      {r.label}
                    </div>
                    <div className="hint" style={{ fontSize: "11px" }}>
                      <code>{r.id}</code>
                      {r.peakCount ? ` · ${r.peakCount} peak${r.peakCount === 1 ? "" : "s"}` : ""}
                      {idx === 0 && fittingParams.recipe_pass_energy != null
                        ? ` · PE ${fittingParams.recipe_pass_energy}`
                        : ""}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="mini danger"
                    disabled={busy}
                    title={`Remove ${r.id}`}
                    onClick={() => onRemoveRecipe(r.id)}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

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
