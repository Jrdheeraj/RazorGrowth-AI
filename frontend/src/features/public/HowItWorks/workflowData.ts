export type StageId =
  | "direction"
  | "coordination"
  | "execution"
  | "plan"
  | "approval"
  | "action"
  | "learn";

export type StatusTone = "ok" | "accent" | "idle";

export interface WorkflowStep {
  id: StageId;
  number: string;
  label: string;
  eyebrow: string;
  title: string;
  description: string;
}

export const WORKFLOW_STEPS: readonly WorkflowStep[] = [
  {
    id: "direction",
    number: "01",
    label: "DIRECTION",
    eyebrow: "YOU",
    title: "Set the direction.",
    description: "You define the goal, priorities, and constraints. Your AI team takes it from there.",
  },
  {
    id: "coordination",
    number: "02",
    label: "COORDINATION",
    eyebrow: "MANAGER AGENT",
    title: "The manager turns direction into work.",
    description: "The brief becomes assigned work, clear dependencies, and tracked progress.",
  },
  {
    id: "execution",
    number: "03",
    label: "EXECUTION",
    eyebrow: "SPECIALIST AGENTS",
    title: "Specialists work in parallel.",
    description: "Marketing, product, design, and software agents share context as they complete their tasks.",
  },
  {
    id: "plan",
    number: "04",
    label: "PLAN",
    eyebrow: "RECOMMENDATION",
    title: "The team turns findings into a recommendation.",
    description: "The proposal includes rationale, impact estimates, and guardrails before anything runs.",
  },
  {
    id: "approval",
    number: "05",
    label: "APPROVAL",
    eyebrow: "HUMAN CONTROL",
    title: "You make the final call.",
    description: "Review the recommendation, ask questions, approve it, request changes, or reject it.",
  },
  {
    id: "action",
    number: "06",
    label: "ACTION",
    eyebrow: "BOUNDED EXECUTION",
    title: "Approved work executes within bounds.",
    description: "Actions run exactly as approved, with budget, duration, and KPI constraints recorded.",
  },
  {
    id: "learn",
    number: "07",
    label: "LEARN",
    eyebrow: "MEMORY",
    title: "Every outcome becomes context for the next cycle.",
    description: "Results are measured against the estimate and fed back into the next direction.",
  },
] as const;

export const TASK_QUEUE = [
  "Audience analysis",
  "Campaign brief",
  "Creative concepts",
  "Technical spec",
] as const;

export const AGENT_ROWS = [
  { label: "MARKETING", detail: "Audience analysis", state: "COMPLETE", tone: "ok" as const },
  { label: "PRODUCT", detail: "Campaign brief", state: "READY", tone: "ok" as const },
  { label: "DESIGNER", detail: "3 concepts", state: "READY", tone: "accent" as const },
  { label: "SOFTWARE", detail: "Landing page", state: "IN PROGRESS", tone: "accent" as const },
] as const;

export const LOOP_SUMMARY = [
  "Direction",
  "Coordination",
  "Execution",
  "Plan",
  "Approval",
  "Action",
  "Learn",
] as const;
