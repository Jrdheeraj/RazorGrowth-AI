import type { StageId, WorkflowStep } from "./workflowData";

interface WorkflowStepsProps {
  steps: readonly WorkflowStep[];
  activeId: StageId;
  onSelect: (id: StageId) => void;
}

export function WorkflowSteps({ steps, activeId, onSelect }: WorkflowStepsProps) {
  return (
    <div className="workflow-steps" role="tablist" aria-label="Growth loop stages">
      {steps.map((step, index) => {
        const isActive = step.id === activeId;

        return (
          <button
            key={step.id}
            type="button"
            className={`workflow-step${isActive ? " is-active" : ""}`}
            role="tab"
            aria-selected={isActive}
            aria-controls={`workflow-stage-${step.id}`}
            onClick={() => onSelect(step.id)}
          >
            <span className="workflow-step__mark" aria-hidden="true" />
            <span className="workflow-step__number">{step.number}</span>
            <span className="workflow-step__label">{step.label}</span>
            {index < steps.length - 1 && <span className="workflow-step__line" aria-hidden="true" />}
          </button>
        );
      })}
    </div>
  );
}
