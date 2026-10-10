import { Link, useLocation, useNavigate } from "react-router-dom";
import { scrollToSection, scrollToTop } from "../lib/scroll";

/**
 * SiteFooter — the SINGLE global RazorGrowth AI website footer.
 *
 * Rendered once by PublicLayout, so every route (home, radar, agents,
 * debate, actions, checkout, marketing-agent, product-agent, profile,
 * login) shows this exact same compact system bar. No page may render
 * its own site-footer variant — page-internal section sign-offs
 * (agents-cc__footer, actions-footer, rg-footer, prod-signoff) are
 * content, not site chrome, and are unaffected.
 *
 * Spec: ~66px dark-chocolate (#24140D) bar — brand + AI TEAM badge |
 * nav (no DEBATES) | ALL SYSTEMS ACTIVE | GitHub/LinkedIn/X |
 * © 2026 + Privacy | Terms | Support.
 *
 * Links reuse EXISTING routes/sections only. There are no social URLs,
 * Privacy, Terms or Support routes configured in the app, so those
 * render as plain text (never fake destinations).
 */

interface FooterNavItem {
  id: string;
  label: string;
  route?: string;
}

/* Mirrors SiteHeader's destinations minus DEBATES (not in the spec). */
const FOOTER_NAV: readonly FooterNavItem[] = [
  { id: "home", label: "Home", route: "/" },
  { id: "who-its-for", label: "Who it's for" },
  { id: "how-it-works", label: "How it works" },
  { id: "growth-radar", label: "Radar", route: "/growth-radar" },
  { id: "agents", label: "AI Team", route: "/agents" },
  { id: "actions", label: "Actions", route: "/actions" },
  { id: "checkout", label: "Checkout", route: "/checkout" },
] as const;

function GithubIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M9 19c-4.5 1.5-4.5-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.6 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.7 1-.7 2V19" />
    </svg>
  );
}

function LinkedinIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-4 0v7h-4V8h4v2a6 6 0 0 1 2-2z" />
      <rect x="2" y="9" width="4" height="12" />
      <circle cx="4" cy="4" r="2" />
    </svg>
  );
}

function XIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" focusable="false">
      <path d="M4 4l16 16M20 4L4 20" />
    </svg>
  );
}

export function SiteFooter() {
  const navigate = useNavigate();
  const location = useLocation();

  const goTo = (item: FooterNavItem) => {
    if (item.id === "home") {
      if (location.pathname === "/") scrollToTop();
      else navigate("/");
      return;
    }
    if (item.route) {
      navigate(item.route);
      return;
    }
    if (location.pathname !== "/") {
      navigate("/", { state: { scrollTo: item.id } });
      return;
    }
    scrollToSection(item.id);
  };

  return (
    <footer className="site-footer" aria-label="Site footer">
      <div className="site-footer__bar">
        {/* 1 — Brand */}
        <span className="site-footer__brand">
          <span className="site-footer__wordmark">RazorGrowth&nbsp;AI</span>
          <span className="site-footer__badge">AI TEAM</span>
        </span>

        <span className="site-footer__sep" aria-hidden="true" />

        {/* 2 — Navigation (no DEBATES per spec) */}
        <nav className="site-footer__nav" aria-label="Footer">
          {FOOTER_NAV.map((item) =>
            item.route ? (
              <Link
                key={item.id}
                to={item.route}
                className={
                  location.pathname === item.route
                    ? "site-footer__link is-active"
                    : "site-footer__link"
                }
                aria-current={location.pathname === item.route ? "page" : undefined}
                onClick={() => goTo(item)}
              >
                {item.label}
              </Link>
            ) : (
              <button
                key={item.id}
                type="button"
                className="site-footer__link site-footer__link--btn"
                onClick={() => goTo(item)}
              >
                {item.label}
              </button>
            ),
          )}
        </nav>

        <span className="site-footer__sep" aria-hidden="true" />

        {/* 3 — System status (visual only; no health source exists) */}
        <span className="site-footer__status">
          <span className="site-footer__dot" aria-hidden="true" />
          All systems active
        </span>

        <span className="site-footer__sep" aria-hidden="true" />

        {/* 4 — Social icons (no URLs configured: text-faithful, non-link) */}
        <span className="site-footer__social" role="group" aria-label="Social links">
          <span className="site-footer__icon" role="img" aria-label="GitHub">
            <GithubIcon />
          </span>
          <span className="site-footer__icon" role="img" aria-label="LinkedIn">
            <LinkedinIcon />
          </span>
          <span className="site-footer__icon" role="img" aria-label="X">
            <XIcon />
          </span>
        </span>

        <span className="site-footer__sep" aria-hidden="true" />

        {/* 5 — Copyright / legal (no legal routes exist: plain text) */}
        <span className="site-footer__legal">
          <span>© 2026 RazorGrowth AI</span>
          <span className="site-footer__pipe" aria-hidden="true">|</span>
          <span>Privacy</span>
          <span className="site-footer__pipe" aria-hidden="true">|</span>
          <span>Terms</span>
          <span className="site-footer__pipe" aria-hidden="true">|</span>
          <span>Support</span>
        </span>
      </div>
    </footer>
  );
}
