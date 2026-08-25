import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

// API base URL comes from environment configuration only.
// Empty string ⇒ same-origin requests; override with VITE_API_BASE_URL.
const API_BASE: string = import.meta.env.VITE_API_BASE_URL ?? "";

interface Action {
  id: string;
  merchant_id: string;
  action_type: string;
  status: string;
  input_payload?: any;
  output_payload?: any;
  error_code?: string;
  error_message?: string;
  completed_at?: string;
  created_at: string;
}

interface AuditEvent {
  id: string;
  event_type: string;
  actor_type: string;
  actor_id?: string;
  payload?: any;
  created_at: string;
}

const TERMINAL_STATUSES = ["completed", "failed", "rejected"];

async function api<T = any>(path: string): Promise<T> {
  const res = await fetch(API_BASE + path, { credentials: "include" });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ? String(detail.detail) : "API error " + res.status);
  }
  return res.json();
}

async function apiPost<T = any>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(API_BASE + path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    const d = detail?.detail;
    throw new Error(typeof d === "string" ? d : d?.error ? `${d.error}` : "API error " + res.status);
  }
  return res.json();
}

function App() {
  const [merchantId] = React.useState<string>("");
  const [actions, setActions] = React.useState<Action[]>([]);
  const [selectedAction, setSelectedAction] = React.useState<Action | null>(null);
  const [auditEvents, setAuditEvents] = React.useState<AuditEvent[] | null>(null);
  const [loading, setLoading] = React.useState<boolean>(false);
  const [error, setError] = React.useState<string | null>(null);

  const loadActions = React.useCallback(async () => {
    const qs = merchantId ? `?merchant_id=${encodeURIComponent(merchantId)}` : "";
    try {
      const body = await api<{ actions: Action[] }>("/api/actions" + qs);
      setActions(body.actions);
      setError(null);
    } catch (e) {
      setError("Could not load actions: " + (e instanceof Error ? e.message : String(e)));
    }
  }, [merchantId]);

  React.useEffect(() => {
    loadActions();
  }, [loadActions]);

  const openAction = async (a: Action) => {
    setSelectedAction(a);
    setAuditEvents(null);
    try {
      const body = await api<{ audit_events: AuditEvent[] }>(
        `/api/actions/${a.id}/audit`
      );
      setAuditEvents(body.audit_events);
    } catch (e) {
      // Audit history is supplementary — show a clear message but keep working
      setAuditEvents([]);
      setError("Could not load audit history: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const canApprove = selectedAction?.status === "requested";
  const canReject = selectedAction?.status === "requested";
  const canExecute = selectedAction?.status === "approved";

  const refreshSelected = async () => {
    if (!selectedAction) return;
    try {
      const fresh = await api<Action>(`/api/actions/${selectedAction.id}`);
      setSelectedAction(fresh);
    } catch {
      setSelectedAction(null);
    }
  };

  const handleApprove = async () => {
    if (!selectedAction || loading) return;
    setLoading(true);
    setError(null);
    try {
      await apiPost(`/api/actions/${selectedAction.id}/approve`);
      await loadActions();
      await refreshSelected();
    } catch (e) {
      setError("Approval failed: " + (e instanceof Error ? e.message : String(e)));
    } finally {
      setLoading(false);
    }
  };

  const handleReject = async () => {
    if (!selectedAction || loading) return;
    setLoading(true);
    setError(null);
    try {
      await apiPost(`/api/actions/${selectedAction.id}/reject`);
      await loadActions();
      await refreshSelected();
    } catch (e) {
      setError("Rejection failed: " + (e instanceof Error ? e.message : String(e)));
    } finally {
      setLoading(false);
    }
  };

  const handleExecute = async () => {
    if (!selectedAction || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await apiPost<{
        action_id: string;
        status: string;
        message: string;
        result?: any;
      }>(`/api/actions/${selectedAction.id}/execute`);

      if (res.status === "completed") {
        await loadActions();
        await refreshSelected();
      } else {
        // The backend never reports success it did not perform — surface as-is
        setError("Execution finished in state: " + res.status);
        await loadActions();
        await refreshSelected();
      }
    } catch (e) {
      setError(
        "Execution failed: " +
          (e instanceof Error ? e.message : String(e)) +
          " — the action was not performed."
      );
      await loadActions();
    } finally {
      setLoading(false);
    }
  };

  const pendingCount = actions.filter((a) => a.status === "requested").length;
  const approvedCount = actions.filter((a) => a.status === "approved").length;

  return (
    <main className="shell">
      <header>
        <div>
          <p className="eyebrow">RAZORGROWTH AI</p>
          <h1>Merchant Growth Command Center</h1>
          <p className="muted">Review, approve and execute AI-proposed growth actions.</p>
        </div>
        <div className="status">TEST MODE</div>
      </header>

      <section className="metrics">
        <div>
          <span>Actions listed</span>
          <strong>{actions.length}</strong>
          <small>all statuses</small>
        </div>
        <div>
          <span>Pending approval</span>
          <strong>{pendingCount}</strong>
          <small>awaiting review</small>
        </div>
        <div>
          <span>Approved</span>
          <strong>{approvedCount}</strong>
          <small>ready to execute</small>
        </div>
        <div>
          <span>Completed</span>
          <strong>{actions.filter((a) => a.status === "completed").length}</strong>
          <small>executed safely</small>
        </div>
      </section>

      {error && (
        <section className="panel" role="alert">
          <p className="error">{error}</p>
        </section>
      )}

      <section className="panel">
        <div className="panelHead">
          <div>
            <p className="eyebrow">AI GROWTH ENGINE</p>
            <h2>Proposed actions</h2>
          </div>
          <button onClick={() => loadActions()} disabled={loading} className="primary">
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>

        {actions.length === 0 ? (
          <p className="muted">No actions found. Run AI analysis first.</p>
        ) : (
          <div>
            {actions.map((a) => (
              <article className="opportunity" key={a.id}>
                <div className="op-header">
                  <span className="tag">
                    {a.action_type.replace(/_/g, " ").toUpperCase()}
                  </span>
                  <small>
                    {a.created_at ? new Date(a.created_at).toLocaleDateString() : ""}
                  </small>
                </div>
                <div className="op-details">
                  <h3>{a.action_type.replace(/_/g, " ").toUpperCase()}</h3>
                  <p className="muted">
                    Status: {selectedAction?.id === a.id ? selectedAction.status : a.status}
                  </p>
                  {a.error_message && <p className="muted error">{a.error_message}</p>}
                </div>
                <div className="op-actions">
                  <button onClick={() => openAction(a)} disabled={loading} className="primary">
                    View
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {selectedAction && (
        <section className="panel" style={{ marginTop: 32 }}>
          <div className="panelHead">
            <div>
              <p className="eyebrow">Action Details</p>
              <h2>{selectedAction.action_type.replace(/_/g, " ").toUpperCase()}</h2>
            </div>
            <button onClick={() => setSelectedAction(null)} className="secondary">
              Close
            </button>
          </div>

          <p>
            Status: <strong>{selectedAction.status}</strong>
            {selectedAction.completed_at && <> · Completed {new Date(selectedAction.completed_at).toLocaleString()}</>}
          </p>

          {selectedAction.input_payload && (
            <details open>
              <summary>Input payload</summary>
              <pre>{JSON.stringify(selectedAction.input_payload, null, 2)}</pre>
            </details>
          )}

          {selectedAction.output_payload && (
            <details>
              <summary>Execution result</summary>
              <pre>{JSON.stringify(selectedAction.output_payload, null, 2)}</pre>
            </details>
          )}

          {(selectedAction.error_code || selectedAction.error_message) && (
            <p className="error">
              {selectedAction.error_code ? `${selectedAction.error_code}: ` : ""}
              {selectedAction.error_message}
            </p>
          )}

          <div style={{ marginTop: 16 }}>
            {canApprove && (
              <>
                <button onClick={handleApprove} disabled={loading} className="primary">
                  {loading ? "Approving..." : "Approve"}
                </button>{" "}
                <button onClick={handleReject} disabled={loading} className="secondary">
                  {loading ? "Rejecting..." : "Reject"}
                </button>
              </>
            )}
            {canExecute && (
              <button onClick={handleExecute} disabled={loading} className="primary">
                {loading ? "Executing..." : "Execute"}
              </button>
            )}
            {TERMINAL_STATUSES.includes(selectedAction.status) && (
              <span className="muted">Already {selectedAction.status}</span>
            )}
          </div>

          <details style={{ marginTop: 16 }}>
            <summary>Audit history{auditEvents ? ` (${auditEvents.length})` : ""}</summary>
            {auditEvents === null ? (
              <p className="muted">Loading audit history...</p>
            ) : auditEvents.length === 0 ? (
              <p className="muted">No audit events recorded yet.</p>
            ) : (
              <ul>
                {auditEvents.map((e) => (
                  <li key={e.id}>
                    <code>{e.event_type}</code> by {e.actor_type}
                    {e.actor_id ? ` (${e.actor_id})` : ""} ·{" "}
                    {new Date(e.created_at).toLocaleString()}
                  </li>
                ))}
              </ul>
            )}
          </details>
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
