import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createRegionSet,
  deleteRegionSet,
  getChemicalStates,
  getLineMarkers,
  getReferenceMarkers,
  listRegionSets,
  postSurveyDetect,
  regionSetCsvUrl,
  type ChemicalStateEntry,
  type LineMarker,
  type ReferenceMarkerGroup,
  type RegionSet,
} from "./api";
import { fetchBlob } from "../lib/http";
import {
  MARKER_COLORS,
  PERIODIC_ROWS,
  figureFirstSpectrum,
  figureXRange,
  lineMarker,
  parseRegionLine,
  pickLibraryLine,
  referenceMarker,
  windowsFromPeaks,
  type PeakRow,
  type PlotMarker,
} from "./identification";

type Props = {
  /** Current Prepare figure (survey or narrow scan / fit stack). */
  fig: any;
  /** XPS region of the fitting step (e.g. "Co2pspectrum1"), used to preset the chemical-state element and line. */
  region: string | null;
  datasetId: string | null;
  onMarkers: (markers: PlotMarker[]) => void;
};

function PeriodicPicker({ available, selected, onToggle }: { available: Set<string>; selected: Set<string>; onToggle: (el: string) => void }) {
  return (
    <div data-testid="periodic-picker" style={{ display: "grid", gridTemplateColumns: "repeat(18, 1fr)", gap: 2, maxWidth: 560 }}>
      {PERIODIC_ROWS.flatMap((row, ri) =>
        row.map((el, ci) =>
          el ? (
            <button
              key={`${ri}-${ci}`}
              type="button"
              className={`mini${selected.has(el) ? " active" : ""}`}
              disabled={!available.has(el)}
              onClick={() => onToggle(el)}
              title={available.has(el) ? el : `${el}: no handbook lines`}
              style={{ padding: "1px 0", fontSize: 10, minWidth: 0, opacity: available.has(el) ? 1 : 0.35 }}
            >
              {el}
            </button>
          ) : (
            <span key={`${ri}-${ci}`} />
          )
        )
      )}
    </div>
  );
}

async function download(url: string, filename: string) {
  const blob = await fetchBlob(url);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/**
 * X2 identification: survey line markers + peak detection + region sets, chemical-state reference markers for narrow
 * scans (selected compounds only, display only) and a browser of the chemical-state library. Markers are drawn on the
 * Prepare plot through ``onMarkers``.
 */
export function IdentificationPanel({ fig, region, datasetId, onMarkers }: Props) {
  const [tab, setTab] = useState<"survey" | "states" | "library">("survey");
  const [err, setErr] = useState<string | null>(null);

  // ---- element availability (library) ----
  const [libElements, setLibElements] = useState<Set<string>>(new Set());
  useEffect(() => {
    void getLineMarkers({ include_auger: false })
      .then((r) => setLibElements(new Set(r.markers.map((m) => m.element))))
      .catch(() => undefined);
  }, []);

  // ---- survey ----
  const [elements, setElements] = useState<Set<string>>(new Set());
  const [showLines, setShowLines] = useState(false);
  const [hv, setHv] = useState("");
  const [lineList, setLineList] = useState<LineMarker[]>([]);
  const [linesNote, setLinesNote] = useState<string | null>(null);
  const [prom, setProm] = useState("3");
  const [tol, setTol] = useState("2");
  const [rows, setRows] = useState<PeakRow[]>([]);
  const [showPeaks, setShowPeaks] = useState(true);
  const [halfWidth, setHalfWidth] = useState("10");
  const [setName, setSetName] = useState("");
  const [sets, setSets] = useState<RegionSet[]>([]);
  const [busy, setBusy] = useState(false);

  const xr = useMemo(() => figureXRange(fig), [fig]);
  const hvNum = hv.trim() === "" ? undefined : Number(hv);

  useEffect(() => {
    if (!showLines || !xr) {
      setLineList([]);
      return;
    }
    let live = true;
    void getLineMarkers({ be_min: xr[0], be_max: xr[1], photon_energy_eV: hvNum && hvNum > 0 ? hvNum : undefined })
      .then((r) => {
        if (!live) return;
        setLineList(r.markers);
        setLinesNote(r.note);
      })
      .catch((e) => live && setErr(String((e as Error)?.message ?? e)));
    return () => {
      live = false;
    };
  }, [showLines, xr?.[0], xr?.[1], hvNum]);

  const refreshSets = useCallback(() => {
    void listRegionSets()
      .then((r) => setSets(r.items))
      .catch(() => undefined);
  }, []);
  useEffect(() => {
    refreshSets();
  }, [refreshSets]);

  async function detect() {
    const sp = figureFirstSpectrum(fig);
    if (!sp) {
      setErr("No spectrum to analyse: plot a survey first.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const r = await postSurveyDetect({
        x: sp.x,
        y: sp.y,
        prominence_pct: Number(prom) > 0 ? Number(prom) : 3,
        tolerance_eV: Number(tol) > 0 ? Number(tol) : 2,
        photon_energy_eV: hvNum && hvNum > 0 ? hvNum : null,
      });
      const wanted = elements;
      setRows(
        r.peaks.map((p) => {
          const pool = [p.match, ...p.alternatives].filter(Boolean) as NonNullable<typeof p.match>[];
          const match = (wanted.size ? pool.find((c) => wanted.has(c.element)) : pool[0]) ?? null;
          return { peak: p, match, include: match != null };
        })
      );
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function saveSet() {
    const regions = windowsFromPeaks(rows, Number(halfWidth) > 0 ? Number(halfWidth) : 10);
    if (!setName.trim() || !regions.length) {
      setErr("Name the region set and include at least one matched peak.");
      return;
    }
    try {
      await createRegionSet({
        name: setName.trim(),
        regions,
        source: { dataset_id: datasetId, prominence_pct: Number(prom), tolerance_eV: Number(tol), half_width_eV: Number(halfWidth) },
      });
      setSetName("");
      setErr(null);
      refreshSets();
    } catch (e) {
      setErr(String((e as Error)?.message ?? e));
    }
  }

  // ---- chemical-state reference markers ----
  const parsed = useMemo(() => parseRegionLine(region), [region]);
  const [element, setElement] = useState("");
  const [line, setLine] = useState("");
  const [groups, setGroups] = useState<ReferenceMarkerGroup[]>([]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    if (parsed) {
      setElement(parsed.element);
      setLine(parsed.line);
      setChosen([]);
    }
  }, [parsed?.element, parsed?.line]);
  useEffect(() => {
    if (!element.trim()) {
      setGroups([]);
      return;
    }
    let live = true;
    void getReferenceMarkers(element.trim())
      .then((r) => live && setGroups(r.compounds))
      .catch(() => live && setGroups([]));
    return () => {
      live = false;
    };
  }, [element]);
  const lines = useMemo(() => [...new Set(groups.map((g) => g.line))], [groups]);
  const activeLine = pickLibraryLine(lines, line);
  const shownGroups = groups.filter((g) => g.line === activeLine && (!filter || g.compound.toLowerCase().includes(filter.toLowerCase())));
  const keyOf = (g: ReferenceMarkerGroup) => `${g.line}|${g.compound}`;

  // ---- library browser ----
  const [q, setQ] = useState("");
  const [libEl, setLibEl] = useState("");
  const [prov, setProv] = useState("");
  const [entries, setEntries] = useState<ChemicalStateEntry[]>([]);
  const [picked, setPicked] = useState<ChemicalStateEntry[]>([]);
  useEffect(() => {
    if (tab !== "library") return;
    const t = window.setTimeout(() => {
      void getChemicalStates({ element: libEl.trim() || undefined, q: q.trim() || undefined, provenance: prov || undefined })
        .then((r) => setEntries(r.entries.slice(0, 300)))
        .catch((e) => setErr(String((e as Error)?.message ?? e)));
    }, 250);
    return () => window.clearTimeout(t);
  }, [tab, q, libEl, prov]);

  // ---- markers for the plot ----
  const markers = useMemo<PlotMarker[]>(() => {
    const out: PlotMarker[] = [];
    if (showLines) {
      const pool = elements.size ? lineList.filter((m) => elements.has(m.element)) : lineList;
      out.push(...pool.slice(0, 120).map(lineMarker));
    }
    if (showPeaks) {
      for (const r of rows) {
        if (!r.include) continue;
        out.push({
          kind: "peak",
          label: r.match ? `${r.match.label} ${r.peak.be_eV.toFixed(1)}` : r.peak.be_eV.toFixed(1),
          x: r.peak.be_eV,
          color: "#e67e22",
          detail: r.match ? `${r.match.label}, offset ${r.match.delta_eV.toFixed(2)} eV${r.match.in_library_range ? "" : " (outside library range)"}` : "unmatched",
        });
      }
    }
    chosen.forEach((k, i) => {
      const g = groups.find((q2) => keyOf(q2) === k);
      if (g) out.push(referenceMarker(g, MARKER_COLORS[i % MARKER_COLORS.length]!));
    });
    picked.forEach((e, i) =>
      out.push({
        kind: "ref",
        label: `${e.compound} ${e.value_eV}`,
        x: e.value_eV,
        color: MARKER_COLORS[(chosen.length + i) % MARKER_COLORS.length]!,
        detail: `${e.element} ${e.line} ${e.compound}${e.phase ? " (" + e.phase + ")" : ""}: ${e.value_eV} eV [${e.provenance ?? ""}]`,
      })
    );
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showLines, lineList, elements, showPeaks, rows, chosen, groups, picked]);
  useEffect(() => {
    onMarkers(markers);
  }, [markers, onMarkers]);

  const tabBtn = (id: typeof tab, label: string) => (
    <button type="button" className={`mini${tab === id ? " active" : ""}`} onClick={() => setTab(id)} data-testid={`id-tab-${id}`}>
      {label}
    </button>
  );

  return (
    <details data-testid="identification-panel" style={{ fontSize: 12, marginBottom: 8 }}>
      <summary style={{ cursor: "pointer", fontWeight: 700 }}>
        Identification: element lines, chemical states{markers.length ? ` (${markers.length} markers on the plot)` : ""}
      </summary>
      <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
        <div className="row" style={{ gap: 6 }}>
          {tabBtn("survey", "Survey")}
          {tabBtn("states", "Chemical states")}
          {tabBtn("library", "Library")}
          {markers.length ? (
            <button
              type="button"
              className="mini"
              onClick={() => {
                setShowLines(false);
                setRows([]);
                setChosen([]);
                setPicked([]);
              }}
            >
              Clear markers
            </button>
          ) : null}
        </div>
        {err ? <div className="err">{err}</div> : null}

        {tab === "survey" ? (
          <div style={{ display: "grid", gap: 6 }}>
            <div className="hint" style={{ margin: 0 }}>
              Markers come from the chemical-state library (PHI Handbook + Biesinger), so only the lines tabulated there exist; a
              missing marker does not mean the element is absent. Detection matches peak positions only.
            </div>
            <PeriodicPicker
              available={libElements}
              selected={elements}
              onToggle={(el) =>
                setElements((s) => {
                  const n = new Set(s);
                  if (n.has(el)) n.delete(el);
                  else n.add(el);
                  return n;
                })
              }
            />
            <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <label className="inline" style={{ margin: 0 }}>
                <input type="checkbox" checked={showLines} onChange={(e) => setShowLines(e.target.checked)} data-testid="id-show-lines" /> Show element lines
                {elements.size ? ` (${[...elements].join(", ")})` : " (all)"}
              </label>
              <label className="inline" style={{ margin: 0 }} title="Needed to place Auger lines on the binding-energy axis">
                hν (eV)
                <input type="number" value={hv} onChange={(e) => setHv(e.target.value)} placeholder="Auger only" style={{ width: 90 }} />
              </label>
              {elements.size ? (
                <button type="button" className="mini" onClick={() => setElements(new Set())}>
                  All elements
                </button>
              ) : null}
            </div>
            {showLines && linesNote ? <div className="hint" style={{ margin: 0 }}>{lineList.length} lines in view. {linesNote}</div> : null}
            <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <label className="inline" style={{ margin: 0 }}>
                Prominence %
                <input type="number" min="0.1" step="0.5" value={prom} onChange={(e) => setProm(e.target.value)} style={{ width: 60 }} />
              </label>
              <label className="inline" style={{ margin: 0 }}>
                Match ± eV
                <input type="number" min="0.1" step="0.5" value={tol} onChange={(e) => setTol(e.target.value)} style={{ width: 60 }} />
              </label>
              <button type="button" className="mini" onClick={() => void detect()} disabled={busy} data-testid="id-detect">
                {busy ? "Detecting…" : "Detect peaks"}
              </button>
              {rows.length ? (
                <label className="inline" style={{ margin: 0 }}>
                  <input type="checkbox" checked={showPeaks} onChange={(e) => setShowPeaks(e.target.checked)} /> Label on plot
                </label>
              ) : null}
            </div>
            {rows.length ? (
              <div style={{ maxHeight: 240, overflow: "auto" }} data-testid="id-peaks">
                <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      <th />
                      <th align="right">BE (eV)</th>
                      <th align="right">Height</th>
                      <th align="right">Prom. %</th>
                      <th align="left">Assignment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => {
                      const pool = [r.peak.match, ...r.peak.alternatives].filter(Boolean) as NonNullable<typeof r.peak.match>[];
                      return (
                        <tr key={i}>
                          <td>
                            <input
                              type="checkbox"
                              checked={r.include}
                              disabled={!r.match}
                              onChange={(e) => setRows((rs) => rs.map((x, j) => (j === i ? { ...x, include: e.target.checked } : x)))}
                            />
                          </td>
                          <td align="right">{r.peak.be_eV.toFixed(1)}</td>
                          <td align="right">{r.peak.height.toFixed(0)}</td>
                          <td align="right">{r.peak.prominence_pct.toFixed(1)}</td>
                          <td>
                            <select
                              value={r.match?.label ?? ""}
                              onChange={(e) =>
                                setRows((rs) =>
                                  rs.map((x, j) => {
                                    if (j !== i) return x;
                                    const m = pool.find((c) => c.label === e.target.value) ?? null;
                                    return { ...x, match: m, include: m != null };
                                  })
                                )
                              }
                            >
                              <option value="">(unassigned)</option>
                              {pool.map((c) => (
                                <option key={c.label} value={c.label}>
                                  {c.label} ({c.delta_eV >= 0 ? "+" : ""}
                                  {c.delta_eV.toFixed(1)}
                                  {c.in_library_range ? "" : ", outside range"})
                                </option>
                              ))}
                            </select>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
            {rows.length ? (
              <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                <label className="inline" style={{ margin: 0 }} title="Region windows are centred on the measured peak">
                  Window ± eV
                  <input type="number" min="1" value={halfWidth} onChange={(e) => setHalfWidth(e.target.value)} style={{ width: 60 }} />
                </label>
                <input value={setName} onChange={(e) => setSetName(e.target.value)} placeholder="Region set name" style={{ width: 150 }} data-testid="id-set-name" />
                <button type="button" className="mini" onClick={() => void saveSet()} data-testid="id-save-set">
                  Create region set from included peaks
                </button>
              </div>
            ) : null}
            {sets.length ? (
              <div data-testid="id-region-sets" style={{ display: "grid", gap: 2 }}>
                <b>Saved region sets</b>
                {sets.map((s) => (
                  <div key={s.set_id} className="row" style={{ gap: 6, alignItems: "center" }}>
                    <span style={{ flex: 1 }}>
                      {s.name} <span className="hint">({s.n_regions} regions: {s.regions.map((r) => r.label).join(", ")})</span>
                    </span>
                    <button type="button" className="mini" onClick={() => void download(regionSetCsvUrl(s.set_id), `region_set_${s.name}.csv`).catch((e) => setErr(String(e?.message ?? e)))}>
                      CSV
                    </button>
                    <button type="button" className="mini danger" onClick={() => void deleteRegionSet(s.set_id).then(refreshSets)}>
                      ✕
                    </button>
                  </div>
                ))}
                <div className="hint" style={{ margin: 0 }}>
                  Region sets list element-line windows only; sensitivity factors and atomic % come with quantification (not built yet).
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {tab === "states" ? (
          <div style={{ display: "grid", gap: 6 }}>
            <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <label className="inline" style={{ margin: 0 }}>
                Element
                <input value={element} onChange={(e) => setElement(e.target.value)} style={{ width: 56 }} data-testid="id-element" />
              </label>
              <label className="inline" style={{ margin: 0 }}>
                Line
                <select value={activeLine ?? ""} onChange={(e) => setLine(e.target.value)}>
                  {lines.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter compounds" style={{ width: 130 }} />
              {chosen.length ? (
                <button type="button" className="mini" onClick={() => setChosen([])}>
                  Hide all ({chosen.length})
                </button>
              ) : null}
            </div>
            <div className="hint" style={{ margin: 0 }}>
              {parsed ? `Preset from region ${region}. ` : ""}Tick the compounds to show: a line at the median binding energy with the min–max
              spread of the library entries shaded. Markers are display only.
            </div>
            <div style={{ maxHeight: 220, overflow: "auto", display: "grid", gap: 1 }} data-testid="id-compounds">
              {shownGroups.map((g) => (
                <label key={keyOf(g)} className="inline" style={{ margin: 0, gap: 6 }} title={g.provenance.join(", ")}>
                  <input
                    type="checkbox"
                    checked={chosen.includes(keyOf(g))}
                    onChange={(e) => setChosen((c) => (e.target.checked ? [...c, keyOf(g)] : c.filter((k) => k !== keyOf(g))))}
                  />
                  <span style={{ width: 150, fontWeight: g.elemental ? 700 : 400 }}>{g.compound}</span>
                  <span>{g.median_eV.toFixed(2)} eV</span>
                  <span className="hint" style={{ margin: 0 }}>
                    {g.max_eV > g.min_eV ? `${g.min_eV.toFixed(2)}–${g.max_eV.toFixed(2)} · ` : ""}
                    {g.n_entries} entr{g.n_entries === 1 ? "y" : "ies"}
                  </span>
                </label>
              ))}
              {!shownGroups.length ? <div className="hint">No library entries for this element/line.</div> : null}
            </div>
          </div>
        ) : null}

        {tab === "library" ? (
          <div style={{ display: "grid", gap: 6 }}>
            <div className="row" style={{ gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <input value={libEl} onChange={(e) => setLibEl(e.target.value)} placeholder="Element" style={{ width: 70 }} />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Compound / phase" style={{ width: 150 }} data-testid="id-lib-q" />
              <select value={prov} onChange={(e) => setProv(e.target.value)}>
                <option value="">All sources</option>
                <option value="phi_handbook">PHI Handbook</option>
                <option value="biesinger_thesis">Biesinger thesis</option>
                <option value="biesinger_lit_compile">Biesinger (literature)</option>
              </select>
              <span className="hint" style={{ margin: 0 }}>
                {entries.length} shown{entries.length === 300 ? " (first 300)" : ""}; tick a row to mark it on the plot
              </span>
            </div>
            <div style={{ maxHeight: 260, overflow: "auto" }}>
              <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }} data-testid="id-lib-table">
                <thead>
                  <tr>
                    <th />
                    <th align="left">El.</th>
                    <th align="left">Line</th>
                    <th align="left">Compound</th>
                    <th align="left">Phase</th>
                    <th align="right">eV</th>
                    <th align="right">FWHM</th>
                    <th align="left">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((e, i) => {
                    const on = picked.some((p) => p === e);
                    return (
                      <tr key={i}>
                        <td>
                          <input type="checkbox" checked={on} disabled={e.energy_kind !== "binding"} onChange={(ev) => setPicked((p) => (ev.target.checked ? [...p, e] : p.filter((x) => x !== e)))} />
                        </td>
                        <td>{e.element}</td>
                        <td>{e.line}</td>
                        <td>{e.compound}</td>
                        <td>{e.phase ?? ""}</td>
                        <td align="right">{e.value_eV}{e.energy_kind === "kinetic" ? " KE" : ""}</td>
                        <td align="right">{e.fwhm_eV ?? ""}</td>
                        <td>{e.provenance ?? ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </details>
  );
}
