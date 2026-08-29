/** Tiny square status indicator — the product's pulse. */

type Tone = "ok" | "accent" | "idle";

export interface StatusIndicatorProps {
  tone: Tone;
  /** Subtle pulse for live/running states */
  pulse?: boolean;
  label?: string;
}

export function StatusIndicator({ tone, pulse = false, label }: StatusIndicatorProps) {
  return (
    <span
      className={`status-dot status-dot--${tone}${pulse ? " status-dot--pulse" : ""}`}
      role="img"
      aria-label={label ?? tone}
    />
  );
}

/**
 * Monospace status chip — APPROVAL REQUIRED · RUNNING · AGENT ONLINE.
 */
export interface StatusChipProps {
  tone?: "neutral" | "ok" | "accent";
  pulse?: boolean;
  children: string;
}

export function StatusChip({ tone = "neutral", pulse = false, children }: StatusChipProps) {
  const cls =
    tone === "ok"
      ? "status-chip status-chip--ok"
      : tone === "accent"
        ? "status-chip status-chip--accent"
        : "status-chip";
  return (
    <span className={cls}>
      <StatusIndicator
        tone={tone === "ok" ? "ok" : tone === "accent" ? "accent" : "idle"}
        pulse={pulse}
        label=""
      />
      {children}
    </span>
  );
}
