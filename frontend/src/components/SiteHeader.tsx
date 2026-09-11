/**
 * SiteHeader — sticky top navigation.
 *
 * Unauthenticated: shows Login + Get Started buttons.
 * Authenticated:   shows NavUserMenu (avatar + dropdown) instead.
 *
 * Section links that have no `route` smooth-scroll on the home page;
 * those with a `route` navigate directly.
 */
import { useEffect, useState } from "react";
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
  { id: "marketing-agi", label: "Marketing AGI", route: "/marketing-agi" },
  { id: "debate",       label: "Debates",      route: "/debate" },
  { id: "actions",      label: "Actions",      route: "/actions" },
  { id: "checkout",     label: "Checkout",     route: "/checkout" },
] as const;

export function SiteHeader() {
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate  = useNavigate();
  const location  = useLocation();
  const { user }  = useAuth();

  // Close mobile menu on route change
  useEffect(() => { setMenuOpen(false); }, [location.pathname]);

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
    <header className="site-header">
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
                className="site-nav__link"
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

      {/* Mobile menu */}
      <div id="mobile-menu" className="mobile-menu" hidden={!menuOpen}>
        <nav className="shell mobile-menu__list" aria-label="Mobile">
          {SECTION_LINKS.map((item) =>
            item.route ? (
              <Link
                key={item.id}
                to={item.route}
                className="mobile-menu__item"
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
