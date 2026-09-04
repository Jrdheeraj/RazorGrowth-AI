/**
 * /profile — authenticated user profile & workspace hub.
 *
 * Data comes exclusively from:
 *   GET /api/auth/me        → user identity + memberships
 *   GET /api/auth/merchants → accessible workspaces
 *
 * No hardcoded user data. No fake merchant data.
 * Users without merchant membership see a clear empty workspace state.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/AuthContext";
import { fetchAccessibleMerchants } from "../lib/api";
import { UserAvatar } from "../components/UserAvatar";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import type { MerchantSummary } from "../types/api";

const QUICK_LINKS = [
  { label: "Growth Radar",     to: "/growth-radar",  desc: "Understand what's happening in your business" },
  { label: "AI Growth Team",   to: "/agents",         desc: "Let AI specialists investigate your business" },
  { label: "AI Investigations",to: "/debate",         desc: "See what your AI team found and why" },
  { label: "Checkout",         to: "/checkout",       desc: "Razorpay TEST payment flow" },
] as const;

export function ProfilePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [merchants, setMerchants] = useState<MerchantSummary[] | null>(null);
  const [merchantError, setMerchantError] = useState<string | null>(null);

  // Load accessible workspaces
  useEffect(() => {
    if (!user) return;
    fetchAccessibleMerchants()
      .then((r) => setMerchants(r.merchants))
      .catch((e) => {
        const msg: string = e instanceof Error ? e.message : "Unknown error";
        // 403 = no memberships at all — not an error, just an empty state
        if (msg.includes("403") || msg.includes("NO_MERCHANT_MEMBERSHIP") || msg.includes("MERCHANT_ACCESS")) {
          setMerchants([]);
        } else {
          setMerchantError(msg);
        }
      });
  }, [user]);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  if (!user) {
    // AuthContext is still loading — render nothing to avoid flash
    return null;
  }

  const displayName = user.full_name || user.email.split("@")[0];

  return (
    <section
      className="shell section"
      aria-labelledby="profile-heading"
      style={{ paddingBlock: "clamp(32px, 5vw, 64px)" }}
    >
      {/* ── Profile header ───────────────────────────────────────────────── */}
      <div style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 24,
        marginBottom: 32,
        flexWrap: "wrap",
      }}>
        <UserAvatar email={user.email} fullName={user.full_name} size={72} />
        <div>
          <p className="meta-label" style={{ marginBottom: 8 }}>
            ACCOUNT · PROFILE.APP
          </p>
          <h1
            id="profile-heading"
            className="display-lg"
            style={{ fontSize: "var(--text-display-md)", marginTop: 0, lineHeight: 1.1 }}
          >
            {displayName}
          </h1>
          <p style={{ color: "var(--ink-soft)", fontSize: "var(--text-small)", marginTop: 6 }}>
            {user.email}
          </p>
          <div style={{ marginTop: 10 }}>
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-meta)",
                textTransform: "uppercase",
                letterSpacing: "var(--tracking-meta)",
                color: user.status === "active" ? "var(--green-deep)" : "var(--coral-strong)",
              }}
            >
              <span style={{
                width: 7, height: 7, borderRadius: 1,
                background: user.status === "active" ? "var(--green)" : "var(--coral)",
                flexShrink: 0,
              }} />
              {user.status}
            </span>
          </div>
        </div>
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
        gap: 20,
      }}>

        {/* ── Account information ────────────────────────────────────────── */}
        <WindowPanel title="account.app">
          <p className="meta-label" style={{ marginBottom: 14 }}>ACCOUNT</p>
          <dl style={{ display: "grid", gap: 14 }}>
            <ProfileField label="Email"   value={user.email} />
            <ProfileField label="Status"  value={user.status} />
            {user.full_name && (
              <ProfileField label="Name" value={user.full_name} />
            )}
            <ProfileField
              label="User ID"
              value={user.id.slice(0, 8) + "…"}
              mono
              title={user.id}
            />
            {user.memberships && user.memberships.length > 0 && (
              <ProfileField
                label="Memberships"
                value={`${user.memberships.length} workspace${user.memberships.length !== 1 ? "s" : ""}`}
              />
            )}
          </dl>
        </WindowPanel>

        {/* ── Workspace / merchant ───────────────────────────────────────── */}
        <WindowPanel title="workspace.app">
          <p className="meta-label" style={{ marginBottom: 14 }}>WORKSPACE</p>

          {merchants === null && !merchantError && (
            <p style={{ color: "var(--ink-faint)", fontFamily: "var(--font-mono)", fontSize: "var(--text-meta)", textTransform: "uppercase", letterSpacing: "var(--tracking-meta)" }}>
              Loading…
            </p>
          )}

          {merchantError && (
            <p style={{ color: "var(--coral-strong)", fontSize: "var(--text-small)" }}>
              Could not load workspaces: {merchantError}
            </p>
          )}

          {merchants !== null && merchants.length === 0 && (
            <div style={{ padding: "4px 0", display: "flex", flexDirection: "column", gap: 14 }}>
              <div style={{
                padding: "16px 18px",
                background: "var(--paper-deep)",
                border: "1px solid var(--line-soft)",
                borderRadius: "var(--radius-window)",
                borderLeft: "3px solid var(--coral)",
              }}>
                <p style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--text-meta)",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "var(--tracking-meta)",
                  color: "var(--coral-strong)",
                  marginBottom: 8,
                }}>
                  Workspace Not Connected
                </p>
                <p style={{ fontSize: "var(--text-small)", color: "var(--ink-soft)", lineHeight: 1.6, marginBottom: 10 }}>
                  Your account isn't linked to a business workspace yet.
                  Growth Radar, AI investigations, and recommendations require a connected workspace.
                </p>
                <p style={{ fontSize: "var(--text-small)", color: "var(--ink-soft)", lineHeight: 1.5 }}>
                  To get started: ask a workspace owner to invite you via your email address,
                  or contact your RazorGrowth account manager to set up your merchant profile.
                </p>
              </div>
            </div>
          )}

          {merchants !== null && merchants.length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {merchants.map((m) => (
                <div key={m.id} style={{
                  padding: "14px 16px",
                  background: "var(--paper-deep)",
                  border: "1px solid var(--line-soft)",
                  borderRadius: "var(--radius-window)",
                  borderLeft: "3px solid var(--green)",
                }}>
                  <div style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                    flexWrap: "wrap",
                  }}>
                    <div>
                      <p style={{ fontWeight: 700, color: "var(--ink)", marginBottom: 2 }}>
                        {m.name}
                      </p>
                      <p style={{
                        fontFamily: "var(--font-mono)",
                        fontSize: "var(--text-meta)",
                        color: "var(--ink-faint)",
                        textTransform: "uppercase",
                        letterSpacing: "var(--tracking-meta)",
                      }}>
                        {m.slug}
                      </p>
                    </div>
                    <span style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "var(--text-meta)",
                      textTransform: "uppercase",
                      letterSpacing: "var(--tracking-meta)",
                      padding: "3px 8px",
                      background: "var(--green-wash)",
                      border: "1px solid var(--green)",
                      borderRadius: "var(--radius-control)",
                      color: "var(--green-deep)",
                    }}>
                      {m.role}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </WindowPanel>

        {/* ── Quick access ──────────────────────────────────────────────── */}
        <WindowPanel title="quick-access.app">
          <p className="meta-label" style={{ marginBottom: 14 }}>QUICK ACCESS</p>
          <div style={{ display: "grid", gap: 10 }}>
            {QUICK_LINKS.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 12,
                  padding: "12px 14px",
                  background: "var(--paper-deep)",
                  border: "1px solid var(--line-soft)",
                  borderRadius: "var(--radius-window)",
                  transition: "border-color 140ms, background 140ms",
                  textDecoration: "none",
                }}
                onMouseEnter={(e) => {
                  const el = e.currentTarget as HTMLElement;
                  el.style.borderColor = "var(--coral)";
                  el.style.background = "var(--coral-wash)";
                }}
                onMouseLeave={(e) => {
                  const el = e.currentTarget as HTMLElement;
                  el.style.borderColor = "var(--line-soft)";
                  el.style.background = "var(--paper-deep)";
                }}
              >
                <div>
                  <p style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: "var(--text-small)",
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "var(--tracking-meta)",
                    color: "var(--ink)",
                    marginBottom: 2,
                  }}>
                    {item.label}
                  </p>
                  <p style={{ fontSize: "var(--text-meta)", color: "var(--ink-soft)" }}>
                    {item.desc}
                  </p>
                </div>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none"
                  style={{ color: "var(--ink-faint)", flexShrink: 0 }}>
                  <path d="M3 8H13M13 8L9 4M13 8L9 12"
                    stroke="currentColor" strokeWidth="1.5" strokeLinecap="square" />
                </svg>
              </Link>
            ))}
          </div>
        </WindowPanel>

        {/* ── Account actions ───────────────────────────────────────────── */}
        <WindowPanel title="account-actions.app">
          <p className="meta-label" style={{ marginBottom: 14 }}>ACCOUNT ACTIONS</p>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p style={{
              fontFamily: "var(--font-mono)",
              fontSize: "var(--text-meta)",
              color: "var(--ink-faint)",
              textTransform: "uppercase",
              letterSpacing: "var(--tracking-meta)",
              padding: "10px 14px",
              background: "var(--paper-deep)",
              border: "1px solid var(--line-soft)",
              borderRadius: "var(--radius-window)",
            }}>
              Settings — coming in a future release
            </p>
            <Button
              type="button"
              variant="secondary"
              mono
              onClick={handleLogout}
              style={{ justifyContent: "flex-start" }}
            >
              Log out
            </Button>
          </div>
        </WindowPanel>

      </div>
    </section>
  );
}

/* ── Helper ─────────────────────────────────────────────────────────────── */

function ProfileField({
  label,
  value,
  mono = false,
  title,
}: {
  label: string;
  value: string;
  mono?: boolean;
  title?: string;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 8, alignItems: "baseline" }}>
      <dt style={{
        fontFamily: "var(--font-mono)",
        fontSize: "var(--text-meta)",
        textTransform: "uppercase",
        letterSpacing: "var(--tracking-meta)",
        color: "var(--ink-faint)",
      }}>
        {label}
      </dt>
      <dd
        title={title}
        style={{
          fontFamily: mono ? "var(--font-mono)" : undefined,
          fontSize: mono ? "var(--text-meta)" : "var(--text-small)",
          color: "var(--ink)",
          letterSpacing: mono ? "0.04em" : undefined,
          margin: 0,
          wordBreak: "break-all",
        }}
      >
        {value}
      </dd>
    </div>
  );
}
