import { useEffect, useState } from "react";
import {
  fetchAgentRuns,
} from "../../lib/api";
import type {
  AgentRunRow,
  PersonalizationDecisionRow,
} from "../../types/api";
import { StatusChip } from "../../components/StatusIndicator";
import { Button } from "../../components/Button";

const ACTIVITY_LIMIT = 20;

interface ActivityFeedProps {
  merchantId?: string;
  windowDays?: number;
}

interface ActivityItem {
  id: string;
  agent: string;
  status: string;
  objective: string | null;
  opportunities_created: number;
  actions_proposed: number;
  insights_generated: number;
  signals_detected: number;
  timestamp: string;
}

function formatActivityTime(iso: string | null | undefined): string {
  if (!iso) return "Just now";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 45) return "Just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}

function activityStatusLabel(status: string | null | undefined): string {
  if (!status) return "IDLE";
  switch (status) {
    case "running": return "Running…";
    case "completed": return "Completed";
    case "partial": return "Partial";
    case "failed": return "Failed";
    case "blocked": return "Blocked";
    case "replan_required": return "Replan needed";
    case "approval_required": return "Awaiting approval";
    default: return status;
  }
}

function activityChipLabel(status: string | null | undefined): "neutral" | "ok" | "accent" {
  if (!status) return "neutral";
  switch (status) {
    case "completed": return "ok";
    case "running": return "accent";
    case "failed": return "neutral";
    case "blocked": return "neutral";
    case "replan_required": return "accent";
    case "approval_required": return "accent";
    default: return "neutral";
  }
}

export function ActivityFeed({ merchantId, windowDays = 30 }: ActivityFeedProps) {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const resp = await fetchAgentRuns(ACTIVITY_LIMIT);
        if (!cancelled && resp.runs) {
          const runs: ActivityItem[] = resp.runs.map((r: AgentRunRow) => ({
            id: r.id,
            agent: r.agent_name,
            status: r.status,
            objective: r.mode ? `Mode: ${r.mode}` : null,
            opportunities_created: r.opportunities_created ?? 0,
            actions_proposed: r.actions_proposed ?? 0,
            insights_generated: r.insights_generated ?? 0,
            signals_detected: r.signals_detected ?? 0,
            timestamp: r.started_at || r.completed_at || "",
          }));
          setItems(runs);
        }
      } catch (e) {
        console.error("Activity feed load error:", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [merchantId, windowDays]);

  if (loading) return <div className="activity-loading">Loading activity feed...</div>;

  if (items.length === 0) return (
    <div className="activity-empty">
      No agent runs yet — start an AI Team analysis to see activity.
    </div>
  );

  return (
    <div className="activity-feed">
      <h3 className="activity-feed__title">Recent Activity</h3>
      <div className="activity-feed__list">
        {items
          .sort((a, b) => (b.timestamp ? new Date(b.timestamp).getTime() : 0) - (a.timestamp ? new Date(a.timestamp).getTime() : 0))
          .map((item) => (
            <div key={item.id} className="activity-feed__item">
              <span className="activity-feed__agent">{item.agent}</span>
              <span className="activity-feed__status">
                <StatusChip tone={activityChipLabel(item.status)}>{activityStatusLabel(item.status)}</StatusChip>
              </span>
              <span className="activity-feed__objective">
                {item.objective ? `"${item.objective}"` : "No objective"}
              </span>
              <div className="activity-feed__metrics">
                <span>📈 {item.opportunities_created} opps</span>
                <span>💡 {item.actions_proposed} proposals</span>
                <span>📊 {item.insights_generated} insights</span>
                <span>🔅 {item.signals_detected} signals</span>
              </div>
              <span className="activity-feed__time">{formatActivityTime(item.timestamp)}</span>
            </div>
          ))}
      </div>
    </div>
  );
}