/**
 * UserAvatar — initials-based avatar for authenticated users.
 *
 * The backend does not currently support profile-photo uploads.
 * This component generates a deterministic colour and initials from the
 * user's full_name or email. When a photo field is added to the backend,
 * pass `src` to render it instead.
 *
 * Usage:
 *   <UserAvatar email="alice@example.com" fullName="Alice Smith" size={36} />
 */
import type { CSSProperties } from "react";

// Deterministic colour from a string — cycles through the editorial palette
const PALETTE = [
  { bg: "#d97757", text: "#21130e" }, // coral
  { bg: "#3e7d58", text: "#f7ebd7" }, // green-deep
  { bg: "#a94f38", text: "#f7ebd7" }, // coral-deep
  { bg: "#301b12", text: "#f7ebd7" }, // choc-800
  { bg: "#70b88a", text: "#21130e" }, // green
  { bg: "#3a2117", text: "#cdb49a" }, // choc-700
];

function pickColour(seed: string) {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) & 0xffff;
  }
  return PALETTE[hash % PALETTE.length];
}

function initials(fullName: string | null | undefined, email: string): string {
  if (fullName && fullName.trim()) {
    const parts = fullName.trim().split(/\s+/);
    return parts.length >= 2
      ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
      : parts[0].slice(0, 2).toUpperCase();
  }
  // Fall back to first two chars of the email local part
  const local = email.split("@")[0] ?? "";
  return local.slice(0, 2).toUpperCase();
}

interface UserAvatarProps {
  email: string;
  fullName?: string | null;
  /** src for an actual photo — reserved for when backend supports uploads */
  src?: string | null;
  size?: number;
  className?: string;
  style?: CSSProperties;
}

export function UserAvatar({
  email,
  fullName,
  src,
  size = 36,
  className,
  style,
}: UserAvatarProps) {
  const colour = pickColour(email);
  const label = initials(fullName, email);

  const base: CSSProperties = {
    width: size,
    height: size,
    flexShrink: 0,
    borderRadius: "var(--radius-control)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontFamily: "var(--font-mono)",
    fontSize: Math.max(10, Math.round(size * 0.36)),
    fontWeight: 700,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    userSelect: "none",
    overflow: "hidden",
    border: "1px solid var(--line-soft)",
    ...style,
  };

  if (src) {
    return (
      <img
        src={src}
        alt={label}
        aria-label={`Avatar for ${fullName ?? email}`}
        className={className}
        style={{ ...base, objectFit: "cover" }}
        width={size}
        height={size}
      />
    );
  }

  return (
    <span
      role="img"
      aria-label={`Avatar for ${fullName ?? email}`}
      className={className}
      style={{ ...base, background: colour.bg, color: colour.text }}
    >
      {label}
    </span>
  );
}
