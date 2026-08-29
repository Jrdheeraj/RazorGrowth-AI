import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { scrollToSection, scrollToTop } from "../lib/scroll";

/**
 * Section anchors of the single-page public website.
 * Navbar items scroll; they never route.
 */
interface SectionLink {
  id: string;
  label: string;
  route?: string;
}

const SECTION_LINKS: readonly SectionLink[] = [
  { id: "home", label: "Home", route: "/" },
  { id: "who-its-for", label: "Who it's for" },
  { id: "how-it-works", label: "How it works" },
  { id: "demo", label: "Demo" },
  { id: "docs", label: "Docs" },
] as const;

/**
 * Public-site top navigation.
 * Cream bar · wordmark left · mono uppercase anchor links · Login + Get
 * started (router links) · collapsible clean menu on mobile that closes
 * after scrolling to the chosen section.
 */
export function SiteHeader() {
  const [menuOpen, setMenuOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  // Close the mobile menu whenever the route changes.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  /**
   * Navigate to a section or route.
   * - Home ("/"): scroll to top or navigate home
   * - Other sections: scroll to section on home, or navigate home + scroll
   */
  const goToSection = (item: SectionLink) => {
    setMenuOpen(false);

    // No dedicated routes - all sections scroll on home page
    if (item.id === "home") {
      if (location.pathname === "/") {
        scrollToTop();
      } else {
        navigate("/");
      }
      return;
    }

    const found = scrollToSection(item.id);
    if (!found) {
      navigate("/", { state: { scrollTo: item.id } });
    }
  };

  return (
    <header className="site-header">
      <div className="shell site-header__inner">
        <Link
          to="/"
          className="wordmark"
          aria-label="RazorGrowth AI — back to top"
          onClick={(e) => {
            e.preventDefault();
            goToSection({ id: "home", label: "Home", route: "/" });
          }}
        >
          RazorGrowth&nbsp;AI
          <span className="wordmark__badge">AI TEAM</span>
        </Link>

        <nav className="site-nav" aria-label="Primary">
          {SECTION_LINKS.map((item) => (
            item.route ? (
              <Link
                key={item.id}
                to={item.route}
                className="site-nav__link"
                aria-label={`Go to ${item.label} page`}
                onClick={() => goToSection(item)}
              >
                {item.label}
              </Link>
            ) : (
              <button
                key={item.id}
                type="button"
                className="site-nav__link"
                aria-label={`Scroll to ${item.label} section`}
                onClick={() => goToSection(item)}
              >
                {item.label}
              </button>
            )
          ))}
          <Link to="/login" className="site-nav__link">
            Login
          </Link>
          <span className="site-nav__cta">
            <Link to="/login" className="btn btn--primary btn--sm">
              Get started
            </Link>
          </span>
        </nav>

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

      <div id="mobile-menu" className="mobile-menu" hidden={!menuOpen}>
        <nav className="shell mobile-menu__list" aria-label="Mobile">
          {SECTION_LINKS.map((item) => (
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
          ))}
          <Link
            to="/login"
            className="mobile-menu__item"
            onClick={() => setMenuOpen(false)}
          >
            Login
          </Link>
          <div className="mobile-menu__actions">
            <Link
              to="/login"
              className="btn btn--primary btn--sm"
              onClick={() => setMenuOpen(false)}
            >
              Get started
            </Link>
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => goToSection({ id: "home", label: "Home", route: "/" })}
            >
              Back to top
            </button>
          </div>
        </nav>
      </div>
    </header>
  );
}
