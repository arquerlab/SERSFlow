import { Link } from "react-router-dom";

/** Shown on Prepare when URL query params carry Analyze context (dataset/session/run). */
export function AnalyzeContextBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <p className="hint" style={{ margin: "0 0 10px" }}>
      <Link to="/analyze">Open in Features &amp; statistics</Link> — dataset/session/run context was saved for that tab.
    </p>
  );
}
