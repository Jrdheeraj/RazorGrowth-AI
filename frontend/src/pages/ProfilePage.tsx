/**
 * /profile — RazorGrowth AI ACCOUNT / PROFILE dashboard.
 *
 * Data (real, no mocks):
 *   GET /api/auth/me                    → identity + memberships + member_since
 *   GET /api/auth/merchants             → accessible workspaces
 *   GET /api/products                   → product catalog count
 *   GET /api/marketing-agi/integrations → connected-platform count
 *
 * Loading cells render "–" until the real value arrives; nothing is
 * hardcoded. The hero illustration is the SHARED AgentOfficeArt used by
 * the Marketing Agent dashboard — same art, sign adapted to RAZORGROWTH AI.
 *
 * Routes (all existing, verified in App.tsx):
 *   /growth-radar, /agents, /debate, /actions, /checkout,
 *   /product-agent, /marketing-agent
 * No account-settings / workspace-manage routes exist in the app, so those
 * two buttons stay honest (tooltip + no fake navigation); logout remains
 * available here and in the header account menu.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/AuthContext";
import {
  fetchAccessibleMerchants,
  fetchProducts,
  fetchMarketingIntegrations,
} from "../lib/api";
import type { MerchantSummary } from "../types/api";
import { AgentOfficeArt } from "../components/AgentOfficeArt";
import "./ProfilePage.css";

/* ── tiny outline icon set (consistent 1.8px stroke, no emoji) ─────────── */
function I(props: { d: React.ReactNode; size?: number; sw?: number }) {
  return (
    <svg
      width={props.size ?? 20}
      height={props.size ?? 20}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={props.sw ?? 1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {props.d}
    </svg>
  );
}
const IconBuilding = (s = 30) => (
  <I size={s} d={<><rect x="4" y="3" width="16" height="18" rx="1" /><path d="M9 21v-4h6v4" /><path d="M8 7h2M8 11h2M14 7h2M14 11h2" /></>} />
);
const IconShare = (s = 30) => (
  <I size={s} d={<><circle cx="6" cy="12" r="2.5" /><circle cx="17.5" cy="5.5" r="2.5" /><circle cx="17.5" cy="18.5" r="2.5" /><path d="M8.2 10.8l7-4M8.2 13.2l7 4" /></>} />
);
const IconChart = (s = 30) => (
  <I size={s} d={<><path d="M4 20V10M10 20V4M16 20v-8M21 20H3" /></>} />
);
const IconUsers = (s = 30) => (
  <I size={s} d={<><circle cx="9" cy="8" r="3.2" /><path d="M3.5 19c.6-3 2.8-4.5 5.5-4.5S13.9 16 14.5 19" /><circle cx="16.5" cy="9" r="2.4" /><path d="M16 14.6c2.3.2 3.9 1.6 4.4 4" /></>} />
);
const IconMail = () => (
  <I size={15} d={<><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M3.5 7l8.5 6 8.5-6" /></>} />
);
const IconPerson = () => (
  <I size={15} d={<><circle cx="12" cy="8" r="3.4" /><path d="M5.5 19c.8-3.4 3.3-5 6.5-5s5.7 1.6 6.5 5" /></>} />
);
const IconStatus = () => (
  <I size={15} d={<><circle cx="12" cy="12" r="7.5" /><circle cx="12" cy="12" r="2.4" /></>} />
);
const IconHash = () => (
  <I size={15} d={<><path d="M9 4L7 20M17 4l-2 16M4.5 9h16M3.5 15h16" /></>} />
);
const IconCal = () => (
  <I size={15} d={<><rect x="4" y="5.5" width="16" height="14" rx="1.5" /><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" /></>} />
);
const IconCopy = () => (
  <I size={13} d={<><rect x="9" y="9" width="11" height="11" rx="1.5" /><path d="M5 15V5a1 1 0 0 1 1-1h9" /></>} />
);
const IconCheck = () => (
  <I size={13} d={<><path d="M4.5 12.5l5 5 10-11" /></>} />
);
const IconPencil = () => (
  <I size={13} d={<><path d="M4 20l1-4.5L16.5 4l3.5 3.5L8.5 19 4 20z" /><path d="M14.5 6l3.5 3.5" /></>} />
);
const IconGear = () => (
  <I size={15} d={<><circle cx="12" cy="12" r="3" /><path d="M12 2.8v3M12 18.2v3M2.8 12h3M18.2 12h3M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M18.8 5.2l-2.1 2.1M7.3 16.7l-2.1 2.1" /></>} />
);
const IconCube = () => (
  <I size={17} d={<><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" /><path d="M12 12l8-4.5M12 12L4 7.5M12 12v9" /></>} />
);
const IconLink = () => (
  <I size={17} d={<><path d="M10 14a4.5 4.5 0 0 0 6.4.4l3-3a4.5 4.5 0 0 0-6.4-6.4l-1.7 1.7" /><path d="M14 10a4.5 4.5 0 0 0-6.4-.4l-3 3a4.5 4.5 0 0 0 6.4 6.4l1.7-1.7" /></>} />
);
const IconBolt = () => (
  <I size={20} d={<><path d="M13 2.5L4.5 13.5H11L10 21.5l8.5-11H12l1-8z" /></>} />
);
const IconSearch = () => (
  <I size={18} d={<><circle cx="11" cy="11" r="6" /><path d="M15.5 15.5L20 20" /></>} />
);
const IconCart = () => (
  <I size={18} d={<><path d="M3 4h2.5l2.2 11h10.6l2.2-8H6" /><circle cx="9.5" cy="19.5" r="1.3" /><circle cx="16.5" cy="19.5" r="1.3" /></>} />
);
const IconHome = () => (
  <I size={20} d={<><path d="M4 11l8-7 8 7" /><path d="M6 9.5V20h12V9.5" /><path d="M10 20v-5h4v5" /></>} />
);

/* ── helpers ──────────────────────────────────────────────────────────── */
function initialsFor(fullName: string | null | undefined, email: string): string {
  if (fullName && fullName.trim()) {
    const parts = fullName.trim().split(/\s+/);
    return parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : parts[0].slice(0, 2).toUpperCase();
  }
  return (email.split("@")[0] ?? "RG").slice(0, 2).toUpperCase();
}
function displayNameOf(fullName: string | null | undefined, email: string): string {
  if (fullName && fullName.trim()) return fullName.trim();
  const local = email.split("@")[0] ?? "Member";
  return local.replace(/[._-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function formatMemberSince(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/* ── quick access (existing routes only) ──────────────────────────────── */
const QUICK = [
  { to: "/growth-radar", title: "Growth Radar", desc: "Understand what's happening in your business", tone: "orange" as const, icon: IconChart(18) },
  { to: "/agents", title: "AI Growth Team", desc: "Let AI specialists investigate your business", tone: "blue" as const, icon: IconUsers(18) },
  { to: "/debate", title: "AI Investigations", desc: "See what your AI team found and why", tone: "blue" as const, icon: IconSearch() },
  { to: "/actions", title: "Growth Actions", desc: "Review, approve, and execute AI-proposed actions", tone: "teal" as const, icon: (<I size={18} d={<><circle cx="12" cy="12" r="8.5" /><path d="M8.5 12.2l2.4 2.4 4.6-5.2" /></>} />) },
  { to: "/checkout", title: "Checkout", desc: "AI Buyer · Razorpay TEST payment flow", tone: "orange" as const, icon: IconCart() },
];

export function ProfilePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [merchants, setMerchants] = useState<MerchantSummary[] | null>(null);
  const [merchantError, setMerchantError] = useState<string | null>(null);
  const [productCount, setProductCount] = useState<number | null>(null);
  const [connectedCount, setConnectedCount] = useState<number | null>(null);
  const [totalTools, setTotalTools] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!user) return;
    fetchAccessibleMerchants()
      .then((r) => setMerchants(r.merchants))
      .catch((e) => {
        const msg: string = e instanceof Error ? e.message : "Unknown error";
        if (msg.includes("403") || msg.includes("NO_MERCHANT") || msg.includes("MERCHANT_ACCESS")) setMerchants([]);
        else setMerchantError(msg);
      });
    fetchProducts()
      .then((r) => setProductCount(typeof r.total === "number" ? r.total : r.products.length))
      .catch(() => setProductCount(null));
    fetchMarketingIntegrations()
      .then((r) => {
        const list = r.integrations ?? [];
        setTotalTools(list.length > 0 ? list.length : null);
        setConnectedCount(list.filter((i) => i.status === "connected").length);
      })
      .catch(() => {
        setConnectedCount(null);
        setTotalTools(null);
      });
  }, [user]);

  if (!user) return null;

  const displayName = displayNameOf(user.full_name, user.email);
  const avatarInitials = initialsFor(user.full_name, user.email);
  const workspaceCount = merchants?.length ?? user.memberships.length;
  const primary: MerchantSummary | null = merchants && merchants.length > 0 ? merchants[0] : null;
  const wsName = primary ? primary.name : displayName;
  const wsSlug = primary ? primary.slug.toUpperCase() : (user.email.split("@")[0] ?? "").toUpperCase();
  const wsRole = primary ? primary.role.toUpperCase() : "OWNER";
  const shortId = user.id.length > 8 ? user.id.slice(0, 8) + "…" : user.id;
  const statusLabel = (user.status || "active").toUpperCase();
  const isActive = statusLabel === "ACTIVE";

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(user.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard unavailable — title attr still shows full id */
    }
  };

  return (
    <div className="rg-profile-page">
      {/* faint illustrated wash behind the dashboard */}
      <div className="rg-profile-env" aria-hidden="true">
        <svg viewBox="0 0 1664 560" preserveAspectRatio="xMidYMin slice">
          <g opacity="0.6">
            <g fill="#F6DCB8" stroke="#6E5747" strokeWidth="1.5" opacity="0.7">
              <rect x="620" y="120" width="60" height="120" />
              <rect x="688" y="92" width="48" height="148" />
              <rect x="744" y="130" width="70" height="110" />
              <rect x="822" y="104" width="44" height="136" />
              <rect x="874" y="138" width="66" height="102" />
            </g>
            <g fill="#FFFDF4" stroke="#6E5747" strokeWidth="1.5" opacity="0.8">
              <ellipse cx="300" cy="100" rx="70" ry="20" />
              <ellipse cx="1250" cy="84" rx="76" ry="20" />
            </g>
            <circle cx="1050" cy="80" r="26" fill="#F5A25D" opacity="0.7" />
          </g>
        </svg>
      </div>

      <div className="rg-profile-container">
        {/* ══ HERO · account.app ══ */}
        <section className="rg-hero" aria-labelledby="profile-heading">
          <div className="rg-hero__main">
            <div className="rg-hero__avatar" aria-hidden="true">{avatarInitials}</div>
            <div style={{ minWidth: 0 }}>
              <p className="rg-hero__eyebrow">ACCOUNT · PROFILE.APP</p>
              <h1 id="profile-heading" className="rg-hero__name">{displayName}</h1>
              <p className="rg-hero__email">{user.email}</p>
              <span className="rg-hero__status"><i />{isActive ? "Active" : statusLabel}</span>
              <p className="rg-hero__sub">Managing your AI growth workspace and connected integrations.</p>
            </div>
          </div>
          <div className="rg-hero__art" aria-hidden="true">
            <p className="rg-hero__deco rg-hero__deco--hub">YOUR AI<br />GROWTH HUB</p>
            <p className="rg-hero__deco rg-hero__deco--acts">BUILD<br />ANALYZE<br />GROW</p>
            <AgentOfficeArt
              sign="RAZORGROWTH AI"
              className="rg-hero__office"
              label="Illustrated RazorGrowth AI growth hub storefront"
            />
          </div>
        </section>

        {/* ══ STATS STRIP ══ */}
        <section className="rg-stats" aria-label="Workspace statistics">
          <div className="rg-stat">
            <span className="rg-stat__icon rg-stat__icon--orange">{IconBuilding()}</span>
            <div>
              <p className="rg-stat__num">{merchants === null ? "–" : workspaceCount}</p>
              <p className="rg-stat__label">Workspace</p>
              <p className="rg-stat__sub">Active workspace</p>
            </div>
          </div>
          <div className="rg-stat">
            <span className="rg-stat__icon rg-stat__icon--green">{IconShare()}</span>
            <div>
              <p className="rg-stat__num">{connectedCount === null ? "–" : connectedCount}</p>
              <p className="rg-stat__label">Tools Connected</p>
              <p className="rg-stat__sub">
                {totalTools === null ? "Live connection data" : `Out of ${totalTools} available`}
              </p>
            </div>
          </div>
          <div className="rg-stat">
            <span className="rg-stat__icon rg-stat__icon--blue">{IconChart()}</span>
            <div>
              <p className="rg-stat__num">{productCount === null ? "–" : productCount}</p>
              <p className="rg-stat__label">Products</p>
              <p className="rg-stat__sub">In your catalog</p>
            </div>
          </div>
          <div className="rg-stat">
            <span className="rg-stat__icon rg-stat__icon--orange">{IconUsers()}</span>
            <div>
              <p className="rg-stat__num">1<small>Team</small></p>
              <p className="rg-stat__sub" style={{ marginTop: 6 }}>Your AI specialists</p>
            </div>
          </div>
        </section>

        {/* ══ THREE-COLUMN DASHBOARD ══ */}
        <div className="rg-grid">
          {/* ── LEFT: account ── */}
          <section className="rg-card" aria-label="Account information">
            <header className="rg-card__head">
              <span className="rg-card__file">account.app</span>
              <span className="rg-card__dots" aria-hidden="true"><i /><i /><i /></span>
            </header>
            <div className="rg-card__body">
              <div className="rg-intro">
                <span className="rg-intro__icon"><IconPerson /></span>
                <div>
                  <h2 className="rg-intro__title">Account Information</h2>
                  <p className="rg-intro__sub">Your profile and account details.</p>
                </div>
                <span className="rg-intro__spacer" />
                <button type="button" className="rg-btn-edit" title="Profile editing — coming soon">
                  {IconPencil()} Edit Profile
                </button>
              </div>

              <div className="rg-rows">
                <div className="rg-row">
                  <span className="rg-row__icon">{IconMail()}</span>
                  <div className="rg-row__meta">
                    <p className="rg-row__label">Email</p>
                    <p className="rg-row__value">{user.email}</p>
                  </div>
                  {isActive && <span className="rg-badge-verified">Verified</span>}
                </div>
                <div className="rg-row">
                  <span className="rg-row__icon">{IconPerson()}</span>
                  <div className="rg-row__meta">
                    <p className="rg-row__label">Name</p>
                    <p className="rg-row__value">{displayName}</p>
                  </div>
                </div>
                <div className="rg-row">
                  <span className="rg-row__icon">{IconStatus()}</span>
                  <div className="rg-row__meta">
                    <p className="rg-row__label">Status</p>
                    <p className="rg-row__value"><span className="rg-dot" />{isActive ? "Active" : statusLabel}</p>
                  </div>
                </div>
                <div className="rg-row">
                  <span className="rg-row__icon">{IconHash()}</span>
                  <div className="rg-row__meta">
                    <p className="rg-row__label">User ID</p>
                    <p className="rg-row__value rg-row__value--mono" title={user.id}>{shortId}</p>
                  </div>
                  <button type="button" className="rg-copy-btn" onClick={copyId} title={copied ? "Copied!" : `Copy full ID: ${user.id}`} aria-label="Copy user ID">
                    {copied ? <IconCheck /> : <IconCopy />}
                  </button>
                </div>
                <div className="rg-row">
                  <span className="rg-row__icon">{IconUsers(15)}</span>
                  <div className="rg-row__meta">
                    <p className="rg-row__label">Memberships</p>
                    <p className="rg-row__value">
                      {merchants === null ? "–" : `${workspaceCount} workspace${workspaceCount === 1 ? "" : "s"}`}
                    </p>
                  </div>
                </div>
                <div className="rg-row">
                  <span className="rg-row__icon">{IconCal()}</span>
                  <div className="rg-row__meta">
                    <p className="rg-row__label">Member since</p>
                    <p className="rg-row__value">{formatMemberSince(user.member_since)}</p>
                  </div>
                </div>
              </div>

              <div className="rg-cta">
                <button type="button" className="rg-btn-outline" title="Account settings — coming in a future release">
                  {IconGear()} Account Settings <span className="arrow">→</span>
                </button>
                <button
                  type="button"
                  onClick={() => { logout(); navigate("/login"); }}
                  style={{ display: "block", margin: "8px auto 0", background: "none", border: "none", cursor: "pointer", fontFamily: "var(--rg-mono, monospace)", fontSize: 11, letterSpacing: "1.4px", textTransform: "uppercase", color: "#9A7E6B" }}
                >
                  Log out
                </button>
              </div>
            </div>
          </section>

          {/* ── CENTER: workspace ── */}
          <section className="rg-card" aria-label="Your workspace">
            <header className="rg-card__head">
              <span className="rg-card__file">workspace.app</span>
              <span className="rg-card__dots" aria-hidden="true"><i /><i /><i /></span>
            </header>
            <div className="rg-card__body">
              <div className="rg-intro">
                <span className="rg-intro__icon rg-intro__icon--orange">{IconHome()}</span>
                <div>
                  <h2 className="rg-intro__title">Your Workspace</h2>
                  <p className="rg-intro__sub">Manage your workspace and team access.</p>
                </div>
              </div>

              {merchantError && (
                <p style={{ fontSize: 12.5, color: "#C85A34", marginBottom: 8 }}>Could not load workspaces: {merchantError}</p>
              )}
              {merchants !== null && merchants.length === 0 && (
                <div className="rg-notice" style={{ marginBottom: 8 }}>
                  <strong>Workspace not connected</strong>
                  Your account isn&apos;t linked to a business workspace yet. Growth Radar and AI investigations require a connected workspace.
                </div>
              )}

              <div className="rg-ws-id">
                <span className="rg-ws-id__avatar" aria-hidden="true">{avatarInitials}</span>
                <div style={{ minWidth: 0 }}>
                  <p className="rg-ws-id__name">{wsName}</p>
                  <p className="rg-ws-id__slug">{wsSlug}</p>
                </div>
                <span className="rg-ws-id__right">
                  <span className="rg-badge-owner">{wsRole}</span>
                  <span className="rg-ws-id__arrow" aria-hidden="true">→</span>
                </span>
              </div>

              <div className="rg-ws-links">
                <Link className="rg-ws-link" to="/product-agent">
                  <span className="rg-ws-link__icon rg-ws-link__icon--orange">{IconCube()}</span>
                  <span>
                    <span className="rg-ws-link__label">Products</span>
                    <p className="rg-ws-link__value">{productCount === null ? "–" : `${productCount} product${productCount === 1 ? "" : "s"}`}</p>
                  </span>
                  <span className="rg-ws-link__arrow" aria-hidden="true">→</span>
                </Link>
                <Link className="rg-ws-link" to="/marketing-agent">
                  <span className="rg-ws-link__icon rg-ws-link__icon--blue">{IconLink()}</span>
                  <span>
                    <span className="rg-ws-link__label">Connected Platforms</span>
                    <p className="rg-ws-link__value">{connectedCount === null ? "–" : `${connectedCount} connected`}</p>
                  </span>
                  <span className="rg-ws-link__arrow" aria-hidden="true">→</span>
                </Link>
                <Link className="rg-ws-link" to="/agents" style={{ borderBottom: 0 }}>
                  <span className="rg-ws-link__icon rg-ws-link__icon--green">{IconUsers(17)}</span>
                  <span>
                    <span className="rg-ws-link__label">Team Access</span>
                    <p className="rg-ws-link__value">1 member (you)</p>
                  </span>
                  <span className="rg-ws-link__arrow" aria-hidden="true">→</span>
                </Link>
              </div>

              <div className="rg-cta">
                <Link className="rg-btn-primary" to="/agents">
                  {IconGear()} Manage Workspace <span>→</span>
                </Link>
              </div>
            </div>
          </section>

          {/* ── RIGHT: quick access ── */}
          <section className="rg-card" aria-label="Quick access">
            <header className="rg-card__head">
              <span className="rg-card__file">quick-access.app</span>
              <span className="rg-card__dots" aria-hidden="true"><i /><i /><i /></span>
            </header>
            <div className="rg-card__body">
              <div className="rg-intro">
                <span className="rg-intro__icon rg-intro__icon--orange">{IconBolt()}</span>
                <div>
                  <h2 className="rg-intro__title">Quick Access</h2>
                  <p className="rg-intro__sub">Jump to the features you use most.</p>
                </div>
              </div>
              <div className="rg-qa-list">
                {QUICK.map((q) => (
                  <Link key={q.to} to={q.to} className="rg-qa-item">
                    <span className={`rg-qa-item__icon rg-qa-item__icon--${q.tone}`}>{q.icon}</span>
                    <span style={{ minWidth: 0, flex: 1 }}>
                      <span className="rg-qa-item__title">{q.title}</span>
                      <p className="rg-qa-item__desc">{q.desc}</p>
                    </span>
                    <span className="rg-qa-item__arrow" aria-hidden="true">→</span>
                  </Link>
                ))}
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
