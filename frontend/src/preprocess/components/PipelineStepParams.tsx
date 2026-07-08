import type { ReactNode } from "react";

/** Scrollable right pane wrapper for pipeline step parameters. */
export function PipelineStepParams({ children }: { children: ReactNode }) {
  return <div className="pipeline-step-params-inner">{children}</div>;
}
