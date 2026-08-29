import type { CSSProperties } from "react";

export interface SectionWindowHeaderProps {
  eyebrow: string;
  title: string;
  accentTitle: string;
  description: string;
  windowTitle?: string;
  id?: string;
  titleMaxWidth?: string;
  ledeMaxWidth?: string;
  compact?: boolean;
}

type SectionHeaderStyle = CSSProperties &
  Record<"--section-title-max" | "--section-lede-max", string>;

export function SectionWindowHeader({
  eyebrow,
  title,
  accentTitle,
  description,
  windowTitle = "razorgrowth — welcome.app",
  id,
  titleMaxWidth = "36ch",
  ledeMaxWidth = "66ch",
  compact = false,
}: SectionWindowHeaderProps) {
  return (
    <div
      className={`section-window-header${compact ? " section-window-header--compact" : ""}`}
      style={ {
        "--section-title-max": titleMaxWidth,
        "--section-lede-max": ledeMaxWidth,
      } as SectionHeaderStyle }
    >
      <header className="section-window-header__titlebar" aria-hidden="true">
        <span className="section-window-header__filename">{windowTitle}</span>
        <span className="section-window-header__controls">
          <span className="section-window-header__control section-window-header__control--coral" />
          <span className="section-window-header__control section-window-header__control--gray" />
          <span className="section-window-header__control section-window-header__control--muted" />
        </span>
      </header>
      <div className="section-window-header__body">
        <p className="meta-label">{eyebrow}</p>
        <h2 id={id} className="display-lg">
          {title}
          {!compact && <br />}
          <span className="accent-word">{accentTitle}</span>
        </h2>
        <p className="page-lede">
          {description}
        </p>
      </div>
    </div>
  );
}
