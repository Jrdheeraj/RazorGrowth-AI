import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";

type Variant = "primary" | "secondary" | "ghost-dark";
type Size = "md" | "sm";

interface BaseProps {
  variant?: Variant;
  size?: Size;
  mono?: boolean;
  children: ReactNode;
}

type ButtonProps = BaseProps & ButtonHTMLAttributes<HTMLButtonElement>;
type LinkButtonProps = BaseProps &
  AnchorHTMLAttributes<HTMLAnchorElement> & { to: string };

function classesFor(
  variant: Variant,
  size: Size,
  mono: boolean,
  extra?: string,
): string {
  return [
    "btn",
    `btn--${variant}`,
    size === "sm" ? "btn--sm" : "",
    mono ? "btn--mono" : "",
    extra ?? "",
  ]
    .filter(Boolean)
    .join(" ");
}

/** Rectangular bordered button — never pill-shaped. */
export function Button({
  variant = "secondary",
  size = "md",
  mono = false,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={classesFor(variant, size, mono, className)}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Same visual language for internal router links. */
export function ButtonLink({
  variant = "secondary",
  size = "md",
  mono = false,
  className,
  children,
  to,
  ...rest
}: LinkButtonProps) {
  return (
    <Link
      to={to}
      className={classesFor(variant, size, mono, className)}
      {...rest}
    >
      {children}
    </Link>
  );
}
