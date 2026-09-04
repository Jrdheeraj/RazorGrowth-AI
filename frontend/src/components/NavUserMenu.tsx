/**
 * NavUserMenu — avatar button + account dropdown for the site header.
 *
 * Replaces "Login / Get started" when the user is authenticated.
 * Closes on outside click and on route change.
 */
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/AuthContext";
import { UserAvatar } from "./UserAvatar";

const NAV_ITEMS = [
  { label: "Profile",        to: "/profile" },
  { label: "Growth Radar",   to: "/growth-radar" },
  { label: "AI Team",        to: "/agents" },
  { label: "Agent Debates",  to: "/debate" },
  { label: "Checkout",       to: "/checkout" },
] as const;

export function NavUserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const navigate = useNavigate();

  // Close on route change
  useEffect(() => setOpen(false), [location.pathname]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handler(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open]);

  if (!user) return null;

  const handleLogout = () => {
    setOpen(false);
    logout();
    navigate("/login");
  };

  const displayName = user.full_name || user.email.split("@")[0];

  return (
    <div ref={menuRef} style={{ position: "relative" }}>
      {/* Avatar trigger */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`Account menu for ${displayName}`}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          background: "none",
          border: "1px solid var(--line-soft)",
          borderRadius: "var(--radius-control)",
          padding: "4px 10px 4px 4px",
          cursor: "pointer",
          transition: "border-color 140ms, background 140ms",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = "var(--line)";
          (e.currentTarget as HTMLElement).style.background = "var(--paper-deep)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLElement).style.borderColor = "var(--line-soft)";
          (e.currentTarget as HTMLElement).style.background = "none";
        }}
      >
        <UserAvatar email={user.email} fullName={user.full_name} size={28} />
        <span style={{
          fontFamily: "var(--font-mono)",
          fontSize: "var(--text-meta)",
          fontWeight: 600,
          letterSpacing: "var(--tracking-meta)",
          textTransform: "uppercase",
          color: "var(--ink)",
          maxWidth: 120,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {displayName}
        </span>
        {/* Chevron */}
        <svg
          width="10" height="10" viewBox="0 0 10 10" fill="none"
          style={{
            marginLeft: 2,
            transform: open ? "rotate(180deg)" : "none",
            transition: "transform 140ms",
            color: "var(--ink-faint)",
            flexShrink: 0,
          }}
        >
          <path d="M1.5 3.5L5 7L8.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="square" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div
          role="menu"
          aria-label="Account menu"
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            right: 0,
            minWidth: 220,
            background: "var(--paper-bright)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-window)",
            boxShadow: "var(--shadow-window)",
            zIndex: 200,
            overflow: "hidden",
          }}
        >
          {/* User identity header */}
          <div style={{
            padding: "14px 16px",
            borderBottom: "1px solid var(--line-soft)",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}>
            <UserAvatar email={user.email} fullName={user.full_name} size={34} />
            <div style={{ minWidth: 0 }}>
              <div style={{
                fontWeight: 700,
                fontSize: "var(--text-small)",
                color: "var(--ink)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>
                {user.full_name || "—"}
              </div>
              <div style={{
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-meta)",
                color: "var(--ink-faint)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}>
                {user.email}
              </div>
            </div>
          </div>

          {/* Navigation items */}
          <div role="group" style={{ padding: "6px 0" }}>
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                role="menuitem"
                onClick={() => setOpen(false)}
                style={{
                  display: "block",
                  padding: "9px 16px",
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--text-meta)",
                  fontWeight: 500,
                  letterSpacing: "var(--tracking-meta)",
                  textTransform: "uppercase",
                  color: "var(--ink-soft)",
                  transition: "background 120ms, color 120ms",
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.background = "var(--paper-deep)";
                  (e.currentTarget as HTMLElement).style.color = "var(--ink)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.background = "transparent";
                  (e.currentTarget as HTMLElement).style.color = "var(--ink-soft)";
                }}
              >
                {item.label}
              </Link>
            ))}
          </div>

          {/* Logout */}
          <div style={{ borderTop: "1px solid var(--line-soft)", padding: "6px 0" }}>
            <button
              type="button"
              role="menuitem"
              onClick={handleLogout}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "9px 16px",
                background: "none",
                border: "none",
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-meta)",
                fontWeight: 600,
                letterSpacing: "var(--tracking-meta)",
                textTransform: "uppercase",
                color: "var(--coral-strong)",
                cursor: "pointer",
                transition: "background 120ms",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLElement).style.background = "var(--coral-wash)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLElement).style.background = "none";
              }}
            >
              Log out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
