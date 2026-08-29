import { WindowPanel } from "../../../components/WindowPanel";
import { StatusIndicator } from "../../../components/StatusIndicator";
import type { StageId, WorkflowStep } from "./workflowData";
import { LOOP_SUMMARY } from "./workflowData";
import { WorkflowStage } from "./WorkflowStage";

interface WorkflowWindowProps {
  activeStep: WorkflowStep;
  activeId: StageId;
}

export function WorkflowWindow({ activeStep, activeId }: WorkflowWindowProps) {
  return (
    <WindowPanel title="growth-loop.app" className="workflow-window">
      <div className="workflow-window__body">
        <div className="workflow-window__topline">
          <div className="workflow-window__status">
            <StatusIndicator tone="ok" pulse label="system active" />
            <span>OPERATING LOOP ACTIVE</span>
          </div>
          <span className="workflow-window__meta">6 AGENTS · HUMAN APPROVAL ON</span>
        </div>

        <div className="loop-map" aria-label="Operating loop summary">
          {LOOP_SUMMARY.map((label, index) => (
            <span
              key={label}
              className={activeId === label.toLowerCase().replace("approval", "approval") ? "is-current" : ""}
            >
              {label}
              {index < LOOP_SUMMARY.length - 1 && <small aria-hidden="true">-&gt;</small>}
            </span>
          ))}
          <span className="loop-map__return" aria-hidden="true">context returns</span>
        </div>

        <WorkflowStage activeStep={activeStep} />
      </div>
    </WindowPanel>
  );
}
