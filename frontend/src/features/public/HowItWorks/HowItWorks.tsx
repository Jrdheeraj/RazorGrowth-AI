import { useMemo, useState } from "react";
import { useReveal } from "../../../lib/useReveal";
import "./HowItWorks.css";
import { WorkflowHeader } from "./WorkflowHeader";
import { WorkflowSteps } from "./WorkflowSteps";
import { WorkflowWindow } from "./WorkflowWindow";
import { WORKFLOW_STEPS, type StageId } from "./workflowData";

export function HowItWorks() {
  const reveal = useReveal<HTMLDivElement>();
  const [activeId, setActiveId] = useState<StageId>("coordination");
  const activeStep = useMemo(
    () => WORKFLOW_STEPS.find((step) => step.id === activeId) ?? WORKFLOW_STEPS[0],
    [activeId],
  );

  return (
    <section id="how-it-works" className="shell section hiw-section" aria-labelledby="hiw-heading">
      <WorkflowHeader />

      <div ref={reveal} className="reveal">
        <div className="hiw-operating-loop">
          <WorkflowSteps steps={WORKFLOW_STEPS} activeId={activeId} onSelect={setActiveId} />
          <WorkflowWindow activeStep={activeStep} activeId={activeId} />
        </div>
      </div>
    </section>
  );
}
