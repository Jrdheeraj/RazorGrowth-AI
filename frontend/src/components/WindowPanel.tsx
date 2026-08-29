import type { ReactNode } from "react";

/**
 * WindowPanel — the core visual primitive.
 * A rectangular application window with a dark monospace title bar,
 * three small square controls, thin border and offset print shadow.
 */
export interface WindowPanelProps {
  /** Monospace filename shown in the title bar, e.g. "growth-radar.app" */
  title: string;
  /** Optional leading dot color variant for the first control */
  tone?: "choc" | "navy";
  /** Render panel body on a dark surface */
  dark?: boolean;
  /** Remove body padding (tables, full-bleed content) */
  flush?: boolean;
  className?: string;
  children: ReactNode;
}

export function WindowPanel({
  title,
  tone = "choc",
  dark = false,
  flush = false,
  className,
  children,
}: WindowPanelProps) {
  const classes = [
    "window",
    dark ? (tone === "navy" ? "window--dark" : "window--choc") : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section className={classes} aria-label={title}>
      <header
        className={[
          "window__titlebar",
          tone === "navy" ? "window__titlebar--navy" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <span className="window__filename">{title}</span>
        <span className="window__controls" aria-hidden="true">
          <span className="window__control window__control--coral" />
          <span className="window__control window__control--gray" />
          <span className="window__control window__control--muted" />
        </span>
      </header>
      <div
        className={[
          "window__body",
          flush ? "window__body--flush" : "",
          dark ? "window__body--dark" : "",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {children}
      </div>
    </section>
  );
}
