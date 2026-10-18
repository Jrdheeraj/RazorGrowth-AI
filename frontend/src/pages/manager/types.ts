/**
 * Types for Manager Agent dashboard view models.
 */

export interface ExecutionStepItem {
  num: string;
  step: string;
  specialist: string;
  specialistKey: string;
  task: string;
  status: "Completed" | "In Progress" | "Pending" | "Failed";
  duration: string;
}

export interface ApprovalQueueItem {
  id: string;
  actionTitle: string;
  actionType: string;
  agent: string;
  agentKey: string;
  createdText: string;
  status: "Pending" | "In Review" | "Approved";
  actionId?: string;
}

export interface ManagerDecisionItem {
  id: string;
  decision: string;
  details: string;
  time: string;
  type: "success" | "info" | "warning";
}

export interface TeamActivityItem {
  id: string;
  time: string;
  agent: string;
  agentKey: string;
  activity: string;
}

export interface MetricCardData {
  title: string;
  value: string | number;
  label: string;
  trend: string;
  trendPositive?: boolean;
  bars: number[];
  accentColor: string;
  icon: string;
}
