/**
 * /debate — Review your AI Growth Team's investigations.
 *
 * Merchant-friendly wrapper around AgentDebatePage.
 * Workflow position: AI Team → [Start Investigation] → [this page]
 */
import { AgentDebatePage } from "../features/public/Agents/AgentDebatePage";

export function DebatePage() {
  return <AgentDebatePage />;
}
