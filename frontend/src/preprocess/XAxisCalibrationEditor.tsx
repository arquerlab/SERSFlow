import { useEffect, useMemo, useState } from "react";
import { DraftNumberInput } from "../lib/draftInputs";
import { TickDropdown } from "./TickDropdown";
import { fetchDatasetFilterFields, type FilterFieldCatalogItem } from "./api";
import type { EditorStep } from "./editorTypes";
import {
  earlierFittingStepOptions,
  fittingPosKeysForStep,
  isValenceBandRegionName,
  normalizeXAxisCalibrationParams,
  type XAxisCalibrationParams,
  type XAxisReferenceFilter,
} from "./xAxisCalibrationUtils";

type Props = {
  datasetId: string | null;
  techniqueFamily?: "vibrational" | "xps";
  steps: EditorStep[];
  selectedStep: EditorStep;
  params: XAxisCalibrationParams;
  onChange: (next: XAxisCalibrationParams) => void;
};

export function XAxisCalibrationEditor({
  datasetId,
  steps,
  selectedStep,
  params,
  onChange,
}: Props) {
  const [fields, setFields] = useState<FilterFieldCatalogItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const method = params.method;
  const isSingle = method === "single_reference_band" || method === "reference_peak";
  const isGrouped = method === "grouped_reference_band";
  const fittingStepOptions =
    isSingle || isGrouped ? earlierFittingStepOptions(steps, selectedStep.id) : [];
  const selectedFittingOpt = fittingStepOptions.find(({ step }) => step.id === params.fitting_step_id);
  const posKeyOptions = selectedFittingOpt ? fittingPosKeysForStep(selectedFittingOpt.step) : [];
  const fittingRegion = String((selectedFittingOpt?.step.params as any)?.xps_region || "").trim();
  const singleIsValence = isSingle && isValenceBandRegionName(fittingRegion);

  useEffect(() => {
    if (!datasetId) {
      setFields([]);
      return;
    }
    let cancelled = false;
    fetchDatasetFilterFields(datasetId)
      .then((res) => {
        if (!cancelled) {
          setFields(res.fields || []);
          setErr(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setErr(String((e as Error)?.message ?? e));
      });
    return () => {
      cancelled = true;
    };
  }, [datasetId]);

  const categoricalFields = useMemo(
    () => fields.filter((f) => f.kind === "categorical"),
    [fields]
  );

  function patch(partial: Partial<XAxisCalibrationParams>) {
    onChange({ ...params, ...partial });
  }

  function setFilters(next: XAxisReferenceFilter[]) {
    patch({ reference_filters: next });
  }

  function onFittingStepChange(nextId: string) {
    const opt = fittingStepOptions.find(({ step }) => step.id === nextId);
    const nextKeys = opt ? fittingPosKeysForStep(opt.step) : [];
    const region = String((opt?.step.params as any)?.xps_region || "").trim();
    patch({
      fitting_step_id: nextId,
      pos_key: nextKeys.includes(params.pos_key) ? params.pos_key : nextKeys[0] ?? "",
      reference_region: params.reference_region || region,
    });
  }

  function renderFittingControls(opts: { showTarget: boolean; keyLabel: string }) {
    return (
      <>
        <label className="inline" style={{ justifyContent: "space-between" }}>
          fitting step
          <select value={params.fitting_step_id} onChange={(e) => onFittingStepChange(String(e.target.value || ""))}>
            <option value="">Select fitting step…</option>
            {fittingStepOptions.map(({ step, index }) => {
              const region = String((step.params as any)?.xps_region || "").trim();
              const nComp = Array.isArray((step.params as any)?.components)
                ? (step.params as any).components.length
                : 0;
              const suffix = region
                ? ` (${region})`
                : nComp
                  ? ` (${nComp} component${nComp === 1 ? "" : "s"})`
                  : "";
              return (
                <option key={step.id} value={step.id}>
                  Step {index + 1}: fitting{suffix}
                </option>
              );
            })}
          </select>
        </label>
        {!fittingStepOptions.length ? (
          <div className="hint">Add or move an enabled fitting step before this calibration step.</div>
        ) : null}

        <label className="inline" style={{ justifyContent: "space-between" }}>
          {opts.keyLabel}
          <select
            value={params.pos_key}
            onChange={(e) => patch({ pos_key: String(e.target.value || "") })}
            disabled={!params.fitting_step_id || !posKeyOptions.length}
          >
            <option value="">Select key…</option>
            {posKeyOptions.map((key) => (
              <option key={key} value={key}>
                {key}
              </option>
            ))}
          </select>
        </label>
        {params.fitting_step_id && !posKeyOptions.length ? (
          <div className="hint">Selected fitting step has no peak position / Fermi center parameters.</div>
        ) : null}

        {opts.showTarget ? (
          <label className="inline" style={{ justifyContent: "space-between" }}>
            target_x
            <DraftNumberInput
              value={params.target_x}
              onChange={(n) => {
                if (n != null) patch({ target_x: n });
              }}
            />
          </label>
        ) : (
          <div className="hint">Valence / Fermi reference → target fixed at 0 eV.</div>
        )}
      </>
    );
  }

  const filters = params.reference_filters ?? [];

  return (
    <div style={{ display: "grid", gap: "8px" }}>
      {err ? <div className="err">{err}</div> : null}

      {isSingle ? (
        <div style={{ display: "grid", gap: "8px" }}>
          <div className="hint">
            Filters select reference spectra. If several match, their measured positions are averaged and
            that one offset is applied to all spectra.
          </div>
          {filters.map((clause, i) => {
            const def = fields.find((f) => f.id === clause.field) || null;
            return (
              <div key={i} className="row" style={{ gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
                <label className="inline" style={{ margin: 0 }}>
                  Filter by
                  <select
                    value={clause.field}
                    onChange={(e) => {
                      const id = e.target.value;
                      const f = fields.find((x) => x.id === id);
                      const next = [...filters];
                      next[i] = {
                        field: id,
                        op: f?.kind === "numeric" ? ">=" : "in",
                        values: [],
                        value: f?.min,
                      };
                      setFilters(next);
                    }}
                  >
                    <option value="">Select field…</option>
                    {fields.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.label}
                      </option>
                    ))}
                  </select>
                </label>
                {def?.kind === "categorical" ? (
                  <TickDropdown
                    label="Values"
                    options={def.values ?? []}
                    selected={clause.values ?? []}
                    emptySummary="None selected"
                    onChange={(vals) => {
                      const next = [...filters];
                      next[i] = { ...clause, op: "in", values: vals };
                      setFilters(next);
                    }}
                  />
                ) : def?.kind === "numeric" ? (
                  <DraftNumberInput
                    value={clause.value ?? null}
                    onChange={(n) => {
                      const next = [...filters];
                      next[i] = { ...clause, value: n ?? undefined };
                      setFilters(next);
                    }}
                  />
                ) : null}
                <button
                  type="button"
                  className="mini danger"
                  onClick={() => setFilters(filters.filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              </div>
            );
          })}
          <button
            type="button"
            className="mini"
            onClick={() => setFilters([...filters, { field: "", op: "in", values: [] }])}
            disabled={!datasetId}
          >
            Add reference filter
          </button>
          {!datasetId ? <div className="hint">Load a dataset to pick filter fields.</div> : null}
          {method === "reference_peak" ? (
            <div className="hint">Legacy method id — prefer “single reference band”.</div>
          ) : null}

          {renderFittingControls({
            showTarget: !singleIsValence,
            keyLabel: "position / center key",
          })}
        </div>
      ) : null}

      {isGrouped ? (
        <div style={{ display: "grid", gap: "8px" }}>
          <label className="inline" style={{ justifyContent: "space-between" }}>
            group by
            <select
              value={params.group_by}
              onChange={(e) => patch({ group_by: String(e.target.value || "") })}
            >
              <option value="">Select metadata field…</option>
              {categoricalFields.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
          {!params.group_by ? <div className="hint">Choose a metadata field to form groups.</div> : null}

          <label className="inline" style={{ justifyContent: "space-between" }}>
            reference mode
            <select
              value={params.reference_mode}
              onChange={(e) =>
                patch({
                  reference_mode: e.target.value === "valence_band" ? "valence_band" : "core_level",
                })
              }
            >
              <option value="core_level">core level (one offset per group)</option>
              <option value="valence_band">valence band (per-region Fermi partner)</option>
            </select>
          </label>

          {params.reference_mode === "core_level" ? (
            <div style={{ display: "grid", gap: "8px" }}>
              <label className="inline" style={{ justifyContent: "space-between" }}>
                reference region
                <input
                  type="text"
                  value={params.reference_region || fittingRegion}
                  onChange={(e) => patch({ reference_region: e.target.value })}
                  placeholder={fittingRegion || "e.g. C1s"}
                  style={{ width: "140px" }}
                  title="Spectrum region used as the group reference (defaults to fitting step region)"
                />
              </label>
              {renderFittingControls({
                showTarget: true,
                keyLabel: "position key",
              })}
            </div>
          ) : null}

          {params.reference_mode === "valence_band" ? (
            <div style={{ display: "grid", gap: "8px" }}>
              <div className="hint">
                Each core-level region R uses a valence partner in the same group whose name contains the
                normalized R token and vb/valence/fermi (e.g. O1s ↔ vb-O1s). Unpaired regions are left
                unshifted.
              </div>
              {renderFittingControls({
                showTarget: false,
                keyLabel: "Fermi center key",
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function xAxisParamsFromStep(
  step: EditorStep,
  techniqueFamily: "vibrational" | "xps"
): XAxisCalibrationParams {
  return normalizeXAxisCalibrationParams(step.params as Record<string, unknown>, techniqueFamily);
}
