/**
 * Shared live-status vocabulary for the AI Team command centre.
 *
 * Lives in its own module so the presentation mapping
 * (`agentStatusMapping.ts`) can be unit-tested without importing the whole
 * AgentsPage React tree.
 */

export type AgentLiveStatus =
  | "IDLE"
  | "WAITING"
  | "WORKING"
  | "THINKING"
  | "TOOL_CALL"
  | "ANALYZING"
  | "COMMUNICATING"
  | "COMPLETED"
  | "BLOCKED"
  | "ERROR"
  | "NEEDS_APPROVAL";

export type AgentTone = "neutral" | "ok" | "accent";