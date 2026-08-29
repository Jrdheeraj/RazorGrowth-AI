import { StatusIndicator } from "../../../components/StatusIndicator";
import { useReveal } from "../../../lib/useReveal";

const NIGHT_SHIFT = [
  ["Marketing Agent", "drafted campaign"],
  ["Product Agent", "wrote experiment"],
  ["Analytics Agent", "found opportunity"],
  ["Growth Agent", "prepared report"],
  ["Manager Agent", "queued review"],
] as const;

/** #manifesto — deep-navy statement band with the night_shift window. */
export function Manifesto() {
  const reveal = useReveal<HTMLDivElement>();

  return (
    <div id="manifesto" className="band-navy theme-dark">
      <section className="shell section" aria-labelledby="manifesto-heading">
        <div
          ref={reveal}
          className="reveal"
          style={{
            display: "grid",
            gap: "clamp(28px, 5vw, 64px)",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))",
            alignItems: "center",
          }}
        >
          <div>
            <p className="meta-label">MANIFESTO</p>
            <h2
              id="manifesto-heading"
              className="display-lg"
              style={{ marginTop: 12, color: "var(--cream-text)" }}
            >
              The world is building AI employees.{" "}
              <span className="accent-word">They need a place to work as a team.</span>{" "}
              RazorGrowth AI is that place.
            </h2>
          </div>

          <section className="window window--dark" aria-label="night shift activity">
            <header className="window__titlebar window__titlebar--navy">
              <span className="window__filename">night_shift — live</span>
              <span className="window__controls" aria-hidden="true">
                <span className="window__control window__control--coral" />
                <span className="window__control window__control--gray" />
                <span className="window__control window__control--muted" />
              </span>
            </header>
            <ul style={{ padding: "18px 20px", display: "grid", gap: 13 }}>
              {NIGHT_SHIFT.map(([who, what]) => (
                <li
                  key={who}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    borderBottom: "1px solid var(--line-on-dark-soft)",
                    paddingBottom: 11,
                    fontSize: "var(--text-small)",
                  }}
                >
                  <StatusIndicator tone="ok" label="active" />
                  <span style={{ color: "var(--cream-text)", fontWeight: 600, minWidth: "9.5em" }}>
                    {who}
                  </span>
                  <span style={{ color: "var(--cream-muted)" }}>{what}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </section>
    </div>
  );
}
