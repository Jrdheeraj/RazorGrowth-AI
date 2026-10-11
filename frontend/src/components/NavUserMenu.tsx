/**
 * NavUserMenu — avatar button + account dropdown for the site header.
 *
 * Replaces "Login / Get started" when the user is authenticated.
 * Closes on outside click and on route change.
 *
 * Premium styling (scoped classes in styles/components.css):
 * green square avatar, dark-brown trigger, brown border, rounded corners.
 * All account entries, auth logic and logout behavior are unchanged —
 * only the visual treatment was updated for the navbar redesign.
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
  { label: "Growth Actions", to: "/actions" },
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
    <div ref={menuRef} className="rg-profile">
      {/* Avatar trigger */}
      <button
        type="button"
        className="rg-profile__trigger"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`Account menu for ${displayName}`}
      >
        <UserAvatar
          email={user.email}
          fullName={user.full_name}
          size={44}
          style={{
            background: "#347A57",
            color: "#FFF4E2",
            borderRadius: 10,
            border: "1px solid rgba(43,25,15,0.25)",
          }}
        />
        <span className="rg-profile__name">{displayName}</span>
        {/* Chevron */}
        <svg
          width="12" height="12" viewBox="0 0 12 12" fill="none"
          className="rg-profile__chev"
          data-open={open ? "true" : "false"}
          aria-hidden="true"
          focusable="false"
        >
          <path d="M2.5 4.5L6 8L9.5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div
          role="menu"
          aria-label="Account menu"
          className="rg-profile__menu"
        >
          {/* User identity header */}
          <div className="rg-profile__identity">
            <UserAvatar
              email={user.email}
              fullName={user.full_name}
              size={38}
              style={{
                background: "#347A57",
                color: "#FFF4E2",
                borderRadius: 10,
                border: "1px solid rgba(43,25,15,0.25)",
              }}
            />
            <div className="rg-profile__identity-text">
              <div className="rg-profile__identity-name">
                {user.full_name || "—"}
              </div>
              <div className="rg-profile__identity-email">
                {user.email}
              </div>
            </div>
          </div>

          {/* Navigation items */}
          <div role="group" className="rg-profile__group">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                role="menuitem"
                onClick={() => setOpen(false)}
                className="rg-profile__item"
              >
                {item.label}
              </Link>
            ))}
          </div>

          {/* Logout */}
          <div className="rg-profile__foot">
            <button
              type="button"
              role="menuitem"
              onClick={handleLogout}
              className="rg-profile__logout"
            >
              Log out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
