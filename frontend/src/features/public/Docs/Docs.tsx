import { WindowPanel } from "../../../components/WindowPanel";
import { ButtonLink } from "../../../components/Button";

/** #docs — documentation index section (expanded guides later). */
export function Docs() {
  return (
    <section id="docs" className="shell section" aria-labelledby="docs-heading">
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">DOCS · README_FIRST.TXT</p>
        <h2 id="docs-heading" className="display-lg" style={{ marginTop: 10 }}>
          Documentation.
        </h2>
      </div>

      <WindowPanel title="docs — index.md" flush>
        <ul style={{ display: "grid", gap: 0 }}>
          {[
            ["01 · CONCEPTS", "Agents, opportunities, bounded actions and the human gate."],
            ["02 · SECURITY", "Tenant isolation, roles, and why agents can never approve or execute on their own."],
            ["03 · APPROVAL", "What happens between a proposal and an executed action — and the audit trail in between."],
            ["04 · YOUR DATA", "Every record is scoped to your merchant; no cross-tenant leaks."],
          ].map(([tag, copy], i) => (
            <li
              key={tag}
              style={{
                padding: "16px clamp(18px, 3vw, 30px)",
                borderTop: i === 0 ? "none" : "1px solid var(--line-soft)",
              }}
            >
              <span className="meta-label">{tag}</span>
              <p style={{ marginTop: 6, color: "var(--ink-soft)", fontSize: "var(--text-small)" }}>{copy}</p>
            </li>
          ))}
        </ul>
      </WindowPanel>
    </section>
  );
}
