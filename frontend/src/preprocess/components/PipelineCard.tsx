import type { ReactNode } from "react";

type PipelineCardProps = {
  header?: ReactNode;
  stepList: ReactNode;
  paramsPanel: ReactNode;
  footer?: ReactNode;
};

export function PipelineCard({ header, stepList, paramsPanel, footer }: PipelineCardProps) {
  return (
    <div className="pipeline-card">
      {header ? <div className="pipeline-card-header">{header}</div> : null}
      <div className="pipeline-editor-body">
        <div className="pipeline-step-list-pane">{stepList}</div>
        <div className="pipeline-step-params-pane">{paramsPanel}</div>
      </div>
      {footer ? <div className="pipeline-card-footer">{footer}</div> : null}
    </div>
  );
}
