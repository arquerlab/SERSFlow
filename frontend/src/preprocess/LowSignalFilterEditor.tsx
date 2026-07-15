import { useEffect, useMemo, useRef, useState } from "react";
import { DraftNumberInput } from "../lib/draftInputs";
import { PlotlyWrapper, type PlotlyFigure } from "../legacy-wrappers/PlotlyWrapper";
import { runPipeline, previewSessionQc, type SpectrumRef, type SessionQcPreviewResponse, type SpectrumSeries } from "./api";
import { DEFAULT_GUARDRAILS } from "./runController";

type LowSignalFilterParams = {
  metric?: "mean" | "median" | "integrated" | "max" | "percentile";
  threshold?: number;
  percentile?: number;
  action?: "exclude" | "flag";
};

function ParamLabel({ label, description }: { label: string; description?: string }) {
  return (
    <span className="param-label">
      <span>{label}</span>
      {description ? (
        <button type="button" className="param-help" title={description} aria-label={`${label}: ${description}`}>
          ?
        </button>
      ) : null}
    </span>
  );
}

function toNumber(v: unknown, fallback: number) {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function histogramFigure(resp: SessionQcPreviewResponse): PlotlyFigure | null {
  const bins = resp.histogram?.bins ?? [];
  const counts = resp.histogram?.counts ?? [];
  if (!bins.length || counts.length + 1 !== bins.length) return null;
  const centers = counts.map((_, i) => (bins[i]! + bins[i + 1]!) / 2);

  const thr = resp.threshold;
  const positiveEdges = bins.filter((b) => Number.isFinite(b) && b > 0);
  const minPositive = positiveEdges.length ? Math.min(...positiveEdges) : null;
  const maxPositive = positiveEdges.length ? Math.max(...positiveEdges) : null;
  const canLog = minPositive != null && maxPositive != null && maxPositive > minPositive;

  let xaxis: Record<string, any> = { title: "Metric value" };
  let xs = centers.slice();
  let widths: number[] | undefined;
  let thresholdLineX = thr;

  if (canLog) {
    const logEdges = bins.map((b) => Math.log10(b > 0 ? b : minPositive!));
    xs = counts.map((_, i) => (logEdges[i]! + logEdges[i + 1]!) / 2);
    widths = counts.map((_, i) => Math.max(1e-6, (logEdges[i + 1]! - logEdges[i]!) * 0.9));
    thresholdLineX = Number.isFinite(thr) && thr > 0 ? Math.log10(thr) : Math.log10(minPositive!);

    const minPow = Math.floor(Math.log10(minPositive!));
    const maxPow = Math.ceil(Math.log10(maxPositive!));
    const tickvals: number[] = [];
    const ticktext: string[] = [];
    for (let p = minPow; p <= maxPow; p += 1) {
      const raw = 10 ** p;
      tickvals.push(p);
      ticktext.push(raw >= 1000 ? raw.toExponential(0).replace("+", "") : String(raw));
    }
    xaxis = {
      title: "Metric value",
      tickmode: "array",
      tickvals,
      ticktext,
    };
  }

  const layout: Record<string, any> = {
    margin: { l: 40, r: 20, t: 10, b: 40 },
    height: 220,
    xaxis,
    yaxis: { title: "Count" },
    bargap: 0.12,
    shapes: Number.isFinite(thresholdLineX)
      ? [
          {
            type: "line",
            x0: thresholdLineX,
            x1: thresholdLineX,
            y0: 0,
            y1: 1,
            yref: "paper",
            line: { color: "rgba(220,100,100,0.9)", width: 2, dash: "dot" },
          },
        ]
      : [],
  };

  return {
    data: [
      {
        type: "bar",
        x: xs,
        y: counts,
        width: widths,
        marker: { color: "rgba(120,170,255,0.75)" },
        customdata: centers.map((c, i) => [bins[i]!, bins[i + 1]!, c]),
        hovertemplate: "range=%{customdata[0]:.4g}-%{customdata[1]:.4g}<br>center=%{customdata[2]:.4g}<br>count=%{y}<extra></extra>",
      },
    ],
    layout,
  };
}

export function LowSignalFilterEditor({
  sessionId,
  stepId,
  params,
  onChange,
  ensurePipelineSaved,
  datasetSpectra,
}: {
  sessionId: string;
  stepId: string;
  params: Record<string, unknown>;
  onChange: (next: Record<string, unknown>) => void;
  ensurePipelineSaved: () => Promise<void>;
  datasetSpectra: SpectrumRef[];
}) {
  const p = params as LowSignalFilterParams;
  const metric = p.metric ?? "median";
  const threshold = toNumber(p.threshold, 0);
  const percentile = toNumber(p.percentile, 10);
  const action = p.action ?? "exclude";

  const [preview, setPreview] = useState<SessionQcPreviewResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const debounceRef = useRef<number | null>(null);
  const overlayAbortRef = useRef<AbortController | null>(null);
  const overlayDebounceRef = useRef<number | null>(null);
  const overlayCacheRef = useRef<Map<number, SpectrumSeries[]>>(new Map());
  const [overlayFig, setOverlayFig] = useState<PlotlyFigure | null>(null);

  const spectrumRefById = useMemo(() => {
    const m = new Map<string, SpectrumRef>();
    for (const s of datasetSpectra) m.set(s.spectrum_id, s);
    return m;
  }, [datasetSpectra]);

  const stepParams = useMemo(
    () => ({
      metric,
      threshold,
      percentile,
      action,
    }),
    [metric, threshold, percentile, action]
  );

  useEffect(() => {
    if (!sessionId || !stepId) return;
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      void (async () => {
        try {
          await ensurePipelineSaved();
          const resp = await previewSessionQc(sessionId, { scope: "all", step_id: stepId, step_params: stepParams });
          setPreview(resp);
          setErr(null);
        } catch (e) {
          setPreview(null);
          setErr(String((e as Error)?.message ?? e));
        }
      })();
    }, 250);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [sessionId, stepId, stepParams]);

  const fig = useMemo(() => (preview ? histogramFigure(preview) : null), [preview]);

  const binEdges = preview?.histogram?.bins ?? [];

  useEffect(() => {
    overlayAbortRef.current?.abort();
    overlayCacheRef.current.clear();
    setOverlayFig(null);
  }, [preview]);

  const handleHover = (event: any) => {
    if (!preview || !binEdges.length) return;
    const point = event?.points?.[0];
    const pointNumber = point?.pointNumber;
    if (pointNumber == null) return;
    const binIdx = Number(pointNumber);
    if (!Number.isFinite(binIdx) || binIdx < 0 || binIdx >= binEdges.length - 1) return;
    const lo = binEdges[binIdx]!;
    const hi = binEdges[binIdx + 1]!;

    // Debounce overlay fetching while hovering.
    if (overlayDebounceRef.current) window.clearTimeout(overlayDebounceRef.current);
    overlayDebounceRef.current = window.setTimeout(() => {
      void (async () => {
        const maxOverlay = Math.min(DEFAULT_GUARDRAILS.maxPlotSpectraHardCap, 12);
        const matching = preview.scores
          .filter((r) => r.score != null && Number.isFinite(r.score))
          .filter((r) => {
            const v = r.score!;
            const lastBin = binIdx === binEdges.length - 2;
            return v >= lo && (lastBin ? v <= hi : v < hi);
          })
          .slice(0, maxOverlay);

        const ids = matching.map((m) => m.spectrum_id);
        if (!ids.length) {
          setOverlayFig(null);
          return;
        }

        const cached = overlayCacheRef.current.get(binIdx);
        if (cached) {
          setOverlayFig({
            data: cached.map((it) => ({
              type: "scatter",
              mode: "lines",
              x: it.x,
              y: it.y,
              name: it.spectrum_id,
            })),
            layout: {
              xaxis: { title: { text: "Raman Shift (cm⁻¹)" } },
              yaxis: { title: { text: "Intensity (counts)" } },
              height: 220,
              legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
              margin: { l: 60, r: 20, t: 20, b: 95 },
            },
          });
          return;
        }

        const inputs = ids
          .map((id) => spectrumRefById.get(id))
          .filter((x): x is SpectrumRef => Boolean(x));
        if (!inputs.length) return;

        overlayAbortRef.current?.abort();
        const ac = new AbortController();
        overlayAbortRef.current = ac;

        try {
          const out = (await runPipeline(
            {
              inputs,
              pipeline: { steps: [] },
              return: { kind: "final" },
              up_to_step: null,
              cache_namespace: sessionId,
            },
            { signal: ac.signal }
          )) as { items: SpectrumSeries[] };

          overlayCacheRef.current.set(binIdx, out.items ?? []);
          setOverlayFig({
            data: (out.items ?? []).map((it) => ({
              type: "scatter",
              mode: "lines",
              x: it.x,
              y: it.y,
              name: it.spectrum_id,
            })),
            layout: {
              xaxis: { title: { text: "Raman Shift (cm⁻¹)" } },
              yaxis: { title: { text: "Intensity (counts)" } },
              height: 220,
              legend: { orientation: "h", yanchor: "top", y: -0.25, xanchor: "center", x: 0.5 },
              margin: { l: 60, r: 20, t: 20, b: 95 },
            },
          });
        } catch (e) {
          if ((e as any)?.name === "AbortError") return;
          setOverlayFig(null);
        }
      })();
    }, 120);
  };

  return (
    <div style={{ display: "grid", gap: "8px" }}>
      <label className="inline" style={{ justifyContent: "space-between" }}>
        <ParamLabel
          label="metric"
          description="Which whole-spectrum signal statistic is computed per spectrum. Low values typically indicate a failed acquisition (laser off/blocked, etc.)."
        />
        <select
          value={metric}
          onChange={(e) => onChange({ ...params, metric: e.target.value })}
        >
          <option value="mean">mean intensity</option>
          <option value="median">median intensity</option>
          <option value="integrated">integrated intensity</option>
          <option value="max">maximum intensity</option>
          <option value="percentile">intensity percentile</option>
        </select>
      </label>

      {metric === "percentile" ? (
        <label className="inline" style={{ justifyContent: "space-between" }}>
          <ParamLabel
            label="percentile"
            description="Only used when metric=percentile. Example: 10 means the 10th percentile intensity of the spectrum is used as the signal metric."
          />
          <DraftNumberInput
            min={0}
            max={100}
            value={percentile}
            onChange={(n) => {
              if (n != null) onChange({ ...params, percentile: n });
            }}
          />
        </label>
      ) : null}

      <label className="inline" style={{ justifyContent: "space-between" }}>
        <ParamLabel
          label="threshold"
          description="Spectra with metric below this value are considered low-signal (and will be flagged/excluded depending on action)."
        />
        <DraftNumberInput
          value={threshold}
          onChange={(n) => {
            if (n != null) onChange({ ...params, threshold: n });
          }}
        />
      </label>

      <label className="inline" style={{ justifyContent: "space-between" }}>
        <ParamLabel
          label="action"
          description="exclude removes spectra from downstream steps/exports for this session (does not modify the dataset on disk). flag keeps them but marks them as affected in the preview."
        />
        <select value={action} onChange={(e) => onChange({ ...params, action: e.target.value })}>
          <option value="exclude">exclude</option>
          <option value="flag">flag</option>
        </select>
      </label>

      {err ? <div className="err">{err}</div> : null}
      {preview ? (
        <>
          <div className="hint">
            Affected: <b>{preview.summary.flagged_count}</b> / {preview.summary.total} (
            {preview.summary.flagged_pct.toFixed(1)}%)
            {preview.histogram.nonfinite ? ` • non-finite: ${preview.histogram.nonfinite}` : ""}
          </div>
          <PlotlyWrapper
            figure={fig}
            previousFigure={null}
            plotStyle={{ mode: "overlay", stackSep: 0 }}
            ghostOverlayEnabled={false}
            className="plot"
            onPlotHover={handleHover}
          />
          {overlayFig ? <PlotlyWrapper figure={overlayFig} previousFigure={null} plotStyle={{ mode: "overlay", stackSep: 0 }} ghostOverlayEnabled={false} className="plot" /> : null}
        </>
      ) : (
        <div className="hint">No preview yet.</div>
      )}
    </div>
  );
}

