import { Link, useNavigate } from "react-router-dom";
import { scrollToSection } from "../lib/scroll";
import { StatusIndicator } from "./StatusIndicator";

/** Deep-chocolate editorial footer with mono metadata columns. */
export function SiteFooter() {
  const navigate = useNavigate();

  const handleWhoItsForClick = (e: React.MouseEvent) => {
    e.preventDefault();
    const found = scrollToSection("who-its-for");
    if (!found) {
      navigate("/", { state: { scrollTo: "who-its-for" } });
    }
  };

  return (
    <footer className="site-footer theme-dark">
      <div className="shell site-footer__inner">
        <div className="site-footer__brand">
          <span className="wordmark" style={{ color: "var(--cream-text)" }}>
            RazorGrowth&nbsp;AI
          </span>
          <p>
            A team of AI growth agents that research, plan and execute your
            merchant growth workflows — while humans stay firmly in control.
          </p>
          <p className="meta-label" style={{ marginTop: 16 }}>
            <StatusIndicator tone="ok" pulse label="System online" />
            ALL SYSTEMS · HUMAN APPROVAL ACTIVE
          </p>
        </div>

        <div>
          <h2 className="site-footer__heading">Product</h2>
          <div className="site-footer__links">
            <Link to="/">Home</Link>
            <button
              type="button"
              className="site-footer__link-btn"
              onClick={handleWhoItsForClick}
            >
              Who it's for
            </button>
            <Link to="/demo">Demo</Link>
            <Link to="/docs">Docs</Link>
          </div>
        </div>

        <div>
          <h2 className="site-footer__heading">Workspace</h2>
          <div className="site-footer__links">
            <Link to="/app/radar">Growth radar</Link>
            <Link to="/app/opportunities">Opportunities</Link>
            <Link to="/app/actions">Approvals</Link>
            <Link to="/app/agents">AI agents</Link>
          </div>
        </div>

        <div>
          <h2 className="site-footer__heading">Trust</h2>
          <div className="site-footer__links">
            <Link to="/docs#security">Security model</Link>
            <Link to="/docs#approval">Human approval</Link>
            <Link to="/docs#tenancy">Tenant isolation</Link>
            <Link to="/login">Login</Link>
          </div>
        </div>
      </div>

      <div className="shell site-footer__bottom">
        <span>RAZORGROWTH AI — GROWTH / AGENTS / APPROVAL</span>
        <span>© {new Date().getFullYear()} · GUARDRAILS ON</span>
      </div>
    </footer>
  );
}
