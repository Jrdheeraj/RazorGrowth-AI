/**
 * SiteHeader — sticky top navigation.
 *
 * Unauthenticated: shows Login + Get Started buttons.
 * Authenticated:   shows NavUserMenu (avatar + dropdown) instead.
 *
 * Section links that have no `route` smooth-scroll on the home page;
 * those with a `route` navigate directly.
 *
 * Below the desktop breakpoint the nav collapses into a hamburger panel
 * (`#mobile-menu`). The panel is driven by the `hidden` attribute, closes on
 * navigation / Escape / outside click / close button, traps the page scroll
 * while open and returns focus to the toggle when dismissed with Escape.
 */
import { useEffect, useRef, useState } from "react";
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
  { id: "who-its-for",  label: "Who it's for" },
  { id: "how-it-works", label: "How it works" },
  { id: "growth-radar", label: "Radar",        route: "/growth-radar" },
  { id: "agents",       label: "AI Team",      route: "/agents" },
  { id: "debate",       label: "Debates",      route: "/debate" },
  { id: "actions",      label: "Actions",      route: "/actions" },
  { id: "checkout",     label: "Checkout",     route: "/checkout" },
] as const;

/** Must match the CSS breakpoint that swaps `.site-nav` for `.nav-toggle`. */
const DESKTOP_NAV_QUERY = "(min-width: 1200px)";

export function SiteHeader() {
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate  = useNavigate();
  const location  = useLocation();
  const { user }  = useAuth();
  const headerRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const menuRef   = useRef<HTMLDivElement>(null);

  // Close mobile menu on route change
  useEffect(() => { setMenuOpen(false); }, [location.pathname]);

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
    if (item.id === "home") {
      location.pathname === "/" ? scrollToTop() : navigate("/");
      return;
    }
    if (item.route) { navigate(item.route); return; }
    const found = scrollToSection(item.id);
    if (!found) navigate("/", { state: { scrollTo: item.id } });
  };

  return (
    <header className="site-header" ref={headerRef}>
      <div className="shell site-header__inner">
        {/* Wordmark */}
        <Link
          to="/"
          className="wordmark"
          aria-label="RazorGrowth AI — back to top"
          onClick={(e) => { e.preventDefault(); goToSection({ id: "home", label: "Home", route: "/" }); }}
        >
          RazorGrowth&nbsp;AI
          <span className="wordmark__badge">AI TEAM</span>
        </Link>

        {/* Desktop nav */}
        <nav className="site-nav" aria-label="Primary">
          {SECTION_LINKS.map((item) =>
            item.route ? (
              <Link
                key={item.id}
                to={item.route}
                className={
                  location.pathname === item.route
                    ? "site-nav__link is-active"
                    : "site-nav__link"
                }
                aria-current={location.pathname === item.route ? "page" : undefined}
                onClick={() => goToSection(item)}
              >
                {item.label}
              </Link>
            ) : (
              <button
                key={item.id}
                type="button"
                className="site-nav__link"
                onClick={() => goToSection(item)}
              >
                {item.label}
              </button>
            )
          )}

          {/* Auth state */}
          {user ? (
            <NavUserMenu />
          ) : (
            <>
              <Link to="/login" className="site-nav__link">Login</Link>
              <span className="site-nav__cta">
                <Link to="/login" className="btn btn--primary btn--sm">Get started</Link>
              </span>
            </>
          )}
        </nav>

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
                  location.pathname === item.route
                    ? "mobile-menu__item is-active"
                    : "mobile-menu__item"
                }
                aria-current={location.pathname === item.route ? "page" : undefined}
                onClick={() => goToSection(item)}
              >
                {item.label}
              </Link>
            ) : (
              <button
                key={item.id}
                type="button"
                className="mobile-menu__item"
                onClick={() => goToSection(item)}
              >
                {item.label}
              </button>
            )
          )}

          {user ? (
            <>
              <Link to="/profile" className="mobile-menu__item" onClick={() => setMenuOpen(false)}>
                Profile
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
                Login
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
