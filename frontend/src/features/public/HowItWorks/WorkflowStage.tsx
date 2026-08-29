import { StatusIndicator } from "../../../components/StatusIndicator";
import {
  AGENT_ROWS,
  LOOP_SUMMARY,
  TASK_QUEUE,
  type StageId,
  type WorkflowStep,
} from "./workflowData";

interface WorkflowStageProps {
  activeStep: WorkflowStep;
}

export function WorkflowStage({ activeStep }: WorkflowStageProps) {
  return (
    <div
      key={activeStep.id}
      id={`workflow-stage-${activeStep.id}`}
      className="workflow-stage"
      role="tabpanel"
      aria-label={activeStep.label}
    >
      <div className="workflow-stage__intro">
        <span className="workflow-stage__eyebrow">{activeStep.eyebrow}</span>
        <h3>{activeStep.title}</h3>
        <p>{activeStep.description}</p>
      </div>

      <StageBody id={activeStep.id} />
    </div>
  );
}

function StageBody({ id }: { id: StageId }) {
  switch (id) {
    case "direction":
      return <DirectionStage />;
    case "coordination":
      return <CoordinationStage />;
    case "execution":
      return <ExecutionStage />;
    case "plan":
      return <PlanStage />;
    case "approval":
      return <ApprovalStage />;
    case "action":
      return <ActionStage />;
    case "learn":
      return <LearnStage />;
  }
}

function DirectionStage() {
  return (
    <div className="stage-grid stage-grid--three">
      <InfoBlock label="BRIEF" value="Grow high-value customer revenue this quarter." featured />
      <InfoBlock label="PRIORITY" value="Retention + expansion" />
      <InfoBlock label="OWNER" value="You" />
    </div>
  );
}

function CoordinationStage() {
  return (
    <div className="coordination-layout">
      <div className="manager-chain" aria-label="Manager workflow">
        {["Brief received", "Tasks created", "Specialists assigned", "Progress tracked"].map((item, index) => (
          <div key={item} className="manager-chain__item">
            <span>{item}</span>
            {index < 3 && <span className="manager-chain__arrow" aria-hidden="true">-&gt;</span>}
          </div>
        ))}
      </div>
      <div className="task-queue">
        {TASK_QUEUE.map((task) => (
          <div key={task} className="task-row">
            <StatusIndicator tone="accent" pulse label="created" />
            <span>{task}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ExecutionStage() {
  return (
    <div className="agent-grid">
      {AGENT_ROWS.map((agent) => (
        <div key={agent.label} className="agent-row">
          <StatusIndicator tone={agent.tone} pulse={agent.state === "IN PROGRESS"} label={agent.state} />
          <div>
            <span className="agent-row__label">{agent.label}</span>
            <span className="agent-row__detail">{agent.detail}</span>
          </div>
          <span className="agent-row__state">{agent.state}</span>
        </div>
      ))}
    </div>
  );
}

function PlanStage() {
  return (
    <div className="plan-stage">
      <div className="recommendation-panel">
        <div>
          <span className="recommendation-panel__label">EXPANSION CAMPAIGN</span>
          <p>Target: High-value segment</p>
        </div>
        <div className="recommendation-panel__score">
          <strong>87</strong>
          <span>/ 100</span>
        </div>
      </div>
      <div className="metrics-row">
        <InfoBlock label="PROJECTED IMPACT" value="+34% usage" />
        <InfoBlock label="GUARDRAILS" value="INR 45,000 budget · 14 days · +18% revenue KPI" />
      </div>
    </div>
  );
}

function ApprovalStage() {
  return (
    <div className="approval-stage">
      <div className="approval-card">
        <StatusIndicator tone="accent" pulse label="recommendation ready" />
        <div>
          <span className="approval-card__state">RECOMMENDATION READY</span>
          <strong>Expansion Campaign</strong>
          <p>Human approval is required before any bounded action runs.</p>
        </div>
      </div>
      <div className="approval-actions" aria-label="Decision options">
        <button type="button">REQUEST CHANGES</button>
        <button type="button" className="approval-actions__primary">APPROVE</button>
      </div>
    </div>
  );
}

function ActionStage() {
  return (
    <div className="stage-grid stage-grid--three">
      <InfoBlock label="APPROVED" value="Campaign launched" featured />
      <InfoBlock label="BUDGET" value="INR 45,000" />
      <InfoBlock label="STATUS" value="Executing" statusTone="ok" />
    </div>
  );
}

function LearnStage() {
  return (
    <div className="learn-stage">
      <div className="learn-loop" aria-label="Learning loop">
        {["ESTIMATE", "RESULT", "COMPARE", "LEARN"].map((item, index) => (
          <div key={item} className="learn-loop__item">
            <span>{item}</span>
            {index < 3 && <span aria-hidden="true">-&gt;</span>}
          </div>
        ))}
      </div>
      <div className="return-note">
        <StatusIndicator tone="accent" pulse label="context returned" />
        <span>Context returns to Direction for the next cycle.</span>
      </div>
    </div>
  );
}

function InfoBlock({
  label,
  value,
  featured = false,
  statusTone,
}: {
  label: string;
  value: string;
  featured?: boolean;
  statusTone?: "ok" | "accent" | "idle";
}) {
  return (
    <div className={`info-block${featured ? " info-block--featured" : ""}`}>
      <span className="info-block__label">
        {statusTone && <StatusIndicator tone={statusTone} pulse={statusTone !== "idle"} label={label} />}
        {label}
      </span>
      <strong>{value}</strong>
    </div>
  );
}
