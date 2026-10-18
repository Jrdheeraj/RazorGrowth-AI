import { Link } from "react-router-dom";
import { WindowPanel } from "../../../components/WindowPanel";
import { SectionWindowHeader } from "../../../components/SectionWindowHeader";
import { useReveal } from "../../../lib/useReveal";
import "./Docs.css";

const DOCS_TOPICS = [
  {
    tag: "01 · CONCEPTS",
    title: "AI Growth Operating System",
    desc: "How ManagerAgent coordinates specialist agents (Marketing, Product, Design, Software) and produces unified opportunities.",
    linkTo: "/agents",
    linkText: "Read Agent Architecture →",
  },
  {
    tag: "02 · SECURITY",
    title: "Tenant Isolation & Permissions",
    desc: "Every database query, action, and telemetry signal is strictly scoped to the authenticated merchant workspace. Zero cross-tenant leakage.",
    linkTo: "/profile",
    linkText: "View Security Context →",
  },
  {
    tag: "03 · APPROVAL GATE",
    title: "Bounded Action Contracts",
    desc: "Every proposed action enforces explicit Will Do / Will Not Do boundaries and hard monetary ceilings. No self-execution is permitted.",
    linkTo: "/actions",
    linkText: "Review Action Contracts →",
  },
  {
    tag: "04 · TRACEABILITY",
    title: "Immutable Audit Trails",
    desc: "Cryptographic logging tracks the initiator, deliberating agents, approval timestamps, and execution outcomes for every transaction.",
    linkTo: "/actions",
    linkText: "Inspect Audit Schema →",
  },
] as const;

export function Docs() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <section id="docs" className="shell section" aria-labelledby="docs-heading">
      <SectionWindowHeader
        id="docs-heading"
        eyebrow="ARCHITECTURE & TRANSPARENCY · SYSTEM MANUAL"
        title="Understand how"
        accentTitle="the system works."
        description="RazorGrowth AI pairs autonomous intelligence with rigorous governance. Explore our architecture, tenant boundaries, and human-in-the-loop safety design."
        windowTitle="razorgrowth — documentation.app"
      />

      <div ref={reveal} className="reveal">
        <WindowPanel title="docs — architecture_index.md" flush>
          <div style={{ padding: "clamp(16px, 3vw, 24px)" }}>
            <div className="docs-grid">
              {DOCS_TOPICS.map((topic) => (
                <article key={topic.tag} className="docs-card">
                  <span className="docs-card__tag">{topic.tag}</span>
                  <h3 className="docs-card__title">{topic.title}</h3>
                  <p className="docs-card__desc">{topic.desc}</p>
                  <Link to={topic.linkTo} className="docs-card__link">
                    {topic.linkText}
                  </Link>
                </article>
              ))}
            </div>
          </div>
        </WindowPanel>
      </div>
    </section>
  );
}
