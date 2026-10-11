/**
 * SiteHeader — sticky top navigation (premium dark-brown navbar).
 *
 * Unauthenticated: shows Login + Get Started buttons.
 * Authenticated:   shows NavUserMenu (avatar + dropdown) instead.
 *
 * Section links that have no `route` smooth-scroll on the home page;
 * those with a `route` navigate directly.
 *
 * Desktop: brand + AI TEAM badge | divider | icon nav (8 links in spec
 * order) | profile. The AI Team item is a split control — the label
 * navigates to /agents, the chevron opens a submenu with the existing
 * workstations (/agents overview, /product-agent, /marketing-agent).
 * No routes are invented; Research/Data agents do not exist as routes
 * and are intentionally omitted.
 *
 * No search button: the application has no search feature, so no
 * decorative button is rendered (per navbar spec §F).
 *
 * Below the desktop breakpoint the nav collapses into a hamburger panel
 * (`#mobile-menu`). The panel is driven by the `hidden` attribute, closes on
 * navigation / Escape / outside click / close button, traps the page scroll
 * while open and returns focus to the toggle when dismissed with Escape.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { scrollToSection, scrollToTop } from "../lib/scroll";
import { useAuth } from "../lib/AuthContext";
import { NavUserMenu } from "./NavUserMenu";

interface SectionLink {
  id: string;
  label: string;
  route?: string;
}

const SECTION_LINKS: readonly SectionLink[] = [
  { id: "home",         label: "Home",        route: "/" },
  { id: "who-its-for",  label: "Who It's For" },
  { id: "how-it-works", label: "How It Works" },
  { id: "growth-radar", label: "Radar",        route: "/growth-radar" },
  { id: "agents",       label: "AI Team",      route: "/agents" },
  { id: "debate",       label: "Debates",      route: "/debate" },
  { id: "actions",      label: "Actions",      route: "/actions" },
  { id: "checkout",     label: "Checkout",     route: "/checkout" },
] as const;

/** Existing AI Team destinations only — no invented routes. */
const AI_TEAM_MENU = [
  {
    to: "/agents",
    label: "AI Team Overview",
    desc: "Team dashboard",
  },
  {
    to: "/product-agent",
    label: "Product Agent",
    desc: "Product research and growth",
  },
  {
    to: "/marketing-agent",
    label: "Marketing Agent",
    desc: "Campaigns and customer growth",
  },
] as const;

const AI_TEAM_ROUTES = new Set(["/agents", "/product-agent", "/marketing-agent"]);

/** Must match the CSS breakpoint that swaps `.site-nav` for `.nav-toggle`. */
const DESKTOP_NAV_QUERY = "(min-width: 1200px)";

/* ── Inline outline icons (1.8px stroke, currentColor — no new dep) ─────── */

function NavIcon({ children }: { children: ReactNode }) {
  return (
    <svg
      className="site-nav__icon"
      width="19"
      height="19"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

const IconHome = () => (
  <NavIcon>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V21h14V9.5" />
    <path d="M9.5 21v-6h5v6" />
  </NavIcon>
);

const IconUsers = () => (
  <NavIcon>
    <circle cx="9" cy="8" r="3.5" />
    <path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" />
    <circle cx="17" cy="9" r="2.6" />
    <path d="M16 14.2c2.8.3 5.5 2.3 5.5 5.3" />
  </NavIcon>
);

const IconWorkflow = () => (
  <NavIcon>
    <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
    <circle cx="16" cy="7" r="2.2" />
    <circle cx="10" cy="17" r="2.2" />
  </NavIcon>
);

const IconRadar = () => (
  <NavIcon>
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="5" />
    <path d="M12 12 18 6" />
    <circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />
  </NavIcon>
);

const IconBot = () => (
  <NavIcon>
    <rect x="4" y="8" width="16" height="11" rx="2.5" />
    <path d="M12 8V4M12 4h.01" />
    <path d="M1.5 12v3M22.5 12v3" />
    <circle cx="9" cy="13" r="1" fill="currentColor" stroke="none" />
    <circle cx="15" cy="13" r="1" fill="currentColor" stroke="none" />
    <path d="M9.5 16h5" />
  </NavIcon>
);

const IconDebates = () => (
  <NavIcon>
    <rect x="3" y="4" width="18" height="13" rx="2" />
    <path d="M8 17v4l4-4" />
    <path d="M7 9h10M7 12.5h6" />
  </NavIcon>
);

const IconZap = () => (
  <NavIcon>
    <path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2z" />
  </NavIcon>
);

const IconCart = () => (
  <NavIcon>
    <circle cx="9" cy="20" r="1.6" />
    <circle cx="17" cy="20" r="1.6" />
    <path d="M2.5 3.5h2.5l2.6 12h10.9l2-8H6" />
  </NavIcon>
);

function IconFor(id: string) {
  switch (id) {
    case "home":         return <IconHome />;
    case "who-its-for":  return <IconUsers />;
    case "how-it-works": return <IconWorkflow />;
    case "growth-radar": return <IconRadar />;
    case "agents":       return <IconBot />;
    case "debate":       return <IconDebates />;
    case "actions":      return <IconZap />;
    case "checkout":     return <IconCart />;
    default:             return <IconHome />;
  }
}

function SparkleMark() {
  return (
    <svg
      className="wordmark__sparkle"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 2c.7 5.5 4.5 9.3 10 10-5.5.7-9.3 4.5-10 10-.7-5.5-4.5-9.3-10-10 5.5-.7 9.3-4.5 10-10z" />
    </svg>
  );
}

function ChevronDown({ open = false }: { open?: boolean }) {
  return (
    <svg
      className="site-nav__chevron"
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{ transform: open ? "rotate(180deg)" : "none" }}
    >
      <path d="M2.5 4.5 6 8l3.5-3.5" />
    </svg>
  );
}

function ChevronRight() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className="mobile-menu__chev"
    >
      <path d="M6 3.5 10.5 8 6 12.5" />
    </svg>
  );
}

export function SiteHeader() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const navigate  = useNavigate();
  const location  = useLocation();
  const { user }  = useAuth();
  const headerRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const menuRef   = useRef<HTMLDivElement>(null);
  const aiRef     = useRef<HTMLDivElement>(null);

  // Close mobile menu on route change
  useEffect(() => { setMenuOpen(false); }, [location.pathname]);

  // Close AI submenu on route change
  useEffect(() => { setAiOpen(false); }, [location.pathname]);

  // Escape closes the panel and restores focus to the toggle.
  // While open, the page behind must not scroll (modal-style panel).
  useEffect(() => {
    if (!menuOpen) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        toggleRef.current?.focus();
      }
    };
    const onPointerDown = (event: MouseEvent) => {
      if (!headerRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };

    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onPointerDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onPointerDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [menuOpen]);

  // AI submenu: close on outside click / Escape (no scroll lock — dropdown).
  useEffect(() => {
    if (!aiOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setAiOpen(false);
    };
    const onPointerDown = (event: MouseEvent) => {
      if (!aiRef.current?.contains(event.target as Node)) setAiOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onPointerDown);
    };
  }, [aiOpen]);

  // Move focus into the panel once it opens.
  useEffect(() => {
    if (!menuOpen) return;
    const first = menuRef.current?.querySelector<HTMLElement>("a, button");
    first?.focus();
  }, [menuOpen]);

  // Drop the open state when the viewport grows back to the desktop nav so a
  // stale `hidden=false` never leaves an invisible panel behind.
  useEffect(() => {
    const mq = window.matchMedia(DESKTOP_NAV_QUERY);
    const onChange = () => { if (mq.matches) setMenuOpen(false); };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const goToSection = (item: SectionLink) => {
    setMenuOpen(false);
    setAiOpen(false);
    if (item.id === "home") {
      location.pathname === "/" ? scrollToTop() : navigate("/");
      return;
    }
    if (item.route) { navigate(item.route); return; }
    const found = scrollToSection(item.id);
    if (!found) navigate("/", { state: { scrollTo: item.id } });
  };

  const isRouteActive = (route: string) => location.pathname === route;
  const isAiActive = AI_TEAM_ROUTES.has(location.pathname);
  const isHome = location.pathname === "/";

  return (
    <header className={isHome ? "site-header navbar--home" : "site-header"} ref={headerRef}>
      <div className="shell site-header__inner">
        {/* Brand */}
        <Link
          to="/"
          className="wordmark"
          aria-label="RazorGrowth AI — back to top"
          onClick={(e) => { e.preventDefault(); goToSection({ id: "home", label: "Home", route: "/" }); }}
        >
          <SparkleMark />
          <span className="wordmark__text">
            RazorGrowth&nbsp;<span className="wordmark__ai">AI</span>
          </span>
          <span className="wordmark__badge">AI TEAM</span>
        </Link>

        <span className="site-header__divider" aria-hidden="true" />

        {/* Desktop nav */}
        <nav className="site-nav" aria-label="Primary">
          {SECTION_LINKS.map((item) => {
            // AI Team — split control: label navigates, chevron opens submenu.
            if (item.id === "agents") {
              return (
                <div className="site-nav__drop" ref={aiRef} key={item.id}>
                  <span
                    className={
                      isAiActive ? "site-nav__link site-nav__link--split is-active" : "site-nav__link site-nav__link--split"
                    }
                  >
                    <Link
                      to={item.route!}
                      className="site-nav__split-label"
                      aria-current={isAiActive ? "page" : undefined}
                      onClick={() => goToSection(item)}
                    >
                      {IconFor(item.id)}
                      <span>{item.label}</span>
                    </Link>
                    <button
                      type="button"
                      className="site-nav__split-toggle"
                      aria-expanded={aiOpen}
                      aria-haspopup="menu"
                      aria-label={aiOpen ? "Close AI Team submenu" : "Open AI Team submenu"}
                      onClick={() => setAiOpen((v) => !v)}
                    >
                      <ChevronDown open={aiOpen} />
                    </button>
                  </span>
                  {aiOpen && (
                    <div className="ai-menu" role="menu" aria-label="AI Team workstations">
                      {AI_TEAM_MENU.map((sub) => (
                        <Link
                          key={sub.to}
                          to={sub.to}
                          role="menuitem"
                          className={
                            isRouteActive(sub.to) ? "ai-menu__item is-active" : "ai-menu__item"
                          }
                          onClick={() => setAiOpen(false)}
                        >
                          <span className="ai-menu__icon" aria-hidden="true">
                            {sub.to === "/product-agent" ? <IconCart /> : sub.to === "/marketing-agent" ? <IconDebates /> : <IconBot />}
                          </span>
                          <span className="ai-menu__label">{sub.label}</span>
                          <span className="ai-menu__desc">{sub.desc}</span>
                        </Link>
                      ))}
                    </div>
                  )}
                </div>
              );
            }

            return item.route ? (
              <Link
                key={item.id}
                to={item.route}
                className={
                  isRouteActive(item.route)
                    ? "site-nav__link is-active"
                    : "site-nav__link"
                }
                aria-current={isRouteActive(item.route) ? "page" : undefined}
                onClick={() => goToSection(item)}
              >
                {IconFor(item.id)}
                <span>{item.label}</span>
              </Link>
            ) : (
              <button
                key={item.id}
                type="button"
                className="site-nav__link"
                onClick={() => goToSection(item)}
              >
                {IconFor(item.id)}
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Auth state */}
        <div className="site-header__auth">
          {user ? (
            <NavUserMenu />
          ) : (
            <>
              <Link to="/login" className="site-nav__link site-nav__link--login">Login</Link>
              <span className="site-nav__cta">
                <Link to="/login" className="btn btn--primary btn--sm">Get started</Link>
              </span>
            </>
          )}
        </div>

        {/* Mobile hamburger */}
        <button
          type="button"
          className="nav-toggle"
          ref={toggleRef}
          aria-expanded={menuOpen}
          aria-controls="mobile-menu"
          aria-label={menuOpen ? "Close navigation menu" : "Open navigation menu"}
          onClick={() => setMenuOpen((v) => !v)}
        >
          <span className="nav-toggle__bar" />
          <span className="nav-toggle__bar" />
          <span className="nav-toggle__bar" />
        </button>
      </div>

      {/* Mobile menu — `hidden` is the single source of truth for visibility */}
      <div id="mobile-menu" className="mobile-menu" ref={menuRef} hidden={!menuOpen}>
        <nav className="shell mobile-menu__list" aria-label="Mobile">
          {SECTION_LINKS.map((item) =>
            item.route ? (
              <Link
                key={item.id}
                to={item.route}
                className={
                  (item.id === "agents" ? isAiActive : isRouteActive(item.route))
                    ? "mobile-menu__item is-active"
                    : "mobile-menu__item"
                }
                aria-current={(item.id === "agents" ? isAiActive : isRouteActive(item.route)) ? "page" : undefined}
                onClick={() => goToSection(item)}
              >
                <span className="mobile-menu__left">
                  {IconFor(item.id)}
                  <span>{item.label}</span>
                </span>
                <ChevronRight />
              </Link>
            ) : (
              <button
                key={item.id}
                type="button"
                className="mobile-menu__item"
                onClick={() => goToSection(item)}
              >
                <span className="mobile-menu__left">
                  {IconFor(item.id)}
                  <span>{item.label}</span>
                </span>
                <ChevronRight />
              </button>
            )
          )}

          {/* AI Team workstations — same existing destinations as desktop */}
          <p className="mobile-menu__group-label">AI Team workstations</p>
          {AI_TEAM_MENU.map((sub) => (
            <Link
              key={sub.to}
              to={sub.to}
              className={
                isRouteActive(sub.to)
                  ? "mobile-menu__item mobile-menu__item--sub is-active"
                  : "mobile-menu__item mobile-menu__item--sub"
              }
              aria-current={isRouteActive(sub.to) ? "page" : undefined}
              onClick={() => goToSection({ id: sub.to, label: sub.label, route: sub.to })}
            >
              <span className="mobile-menu__left">
                {sub.to === "/product-agent" ? <IconCart /> : sub.to === "/marketing-agent" ? <IconDebates /> : <IconBot />}
                <span>{sub.label}</span>
              </span>
              <ChevronRight />
            </Link>
          ))}

          <div className="mobile-menu__sep" aria-hidden="true" />

          {user ? (
            <>
              <Link to="/profile" className="mobile-menu__item" onClick={() => setMenuOpen(false)}>
                <span className="mobile-menu__left">
                  <IconUsers />
                  <span>Profile</span>
                </span>
                <ChevronRight />
              </Link>
              <div className="mobile-menu__actions">
                <button
                  type="button"
                  className="btn btn--secondary btn--sm"
                  onClick={() => { setMenuOpen(false); }}
                  style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-meta)" }}
                >
                  {user.full_name || user.email.split("@")[0]}
                </button>
              </div>
            </>
          ) : (
            <>
              <Link to="/login" className="mobile-menu__item" onClick={() => setMenuOpen(false)}>
                <span className="mobile-menu__left">
                  <IconUsers />
                  <span>Login</span>
                </span>
                <ChevronRight />
              </Link>
              <div className="mobile-menu__actions">
                <Link to="/login" className="btn btn--primary btn--sm" onClick={() => setMenuOpen(false)}>
                  Get started
                </Link>
              </div>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
