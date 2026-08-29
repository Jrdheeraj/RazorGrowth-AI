import type { FormEvent } from "react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { WindowPanel } from "../components/WindowPanel";
import { Button, ButtonLink } from "../components/Button";

/**
 * /login — dedicated login page (Phase 1 visual scaffold).
 * The form is rendered in the final layout; submission wiring, token
 * handling and redirects are Phase 3.
 */
export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    // Wired in Phase 3 — lib/api.login() + redirect into /app.
  };

  return (
    <section className="shell section" aria-labelledby="login-heading">
      <div
        style={{
          maxWidth: 520,
          marginInline: "auto",
          paddingBlock: "clamp(32px, 6vw, 72px) 0",
        }}
      >
        <p className="meta-label" style={{ marginBottom: 14 }}>
          WORKSPACE ACCESS · LOGIN.APP
        </p>
        <WindowPanel title="login.app">
          <h1 id="login-heading" className="display-md" style={{ fontSize: "var(--text-display-md)" }}>
            Welcome back.
          </h1>
          <p style={{ color: "var(--ink-soft)", marginTop: 8, fontSize: "var(--text-small)" }}>
            Sign in to open your RazorGrowth workspace.
          </p>

          <form onSubmit={onSubmit} style={{ marginTop: 24, display: "grid", gap: 18 }}>
            <label style={{ display: "grid", gap: 7 }}>
              <span className="meta-label">Email</span>
              <input
                type="email"
                name="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="field"
              />
            </label>
            <label style={{ display: "grid", gap: 7 }}>
              <span className="meta-label">Password</span>
              <input
                type="password"
                name="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="field"
              />
            </label>
            <Button type="submit" variant="primary" mono>
              Log in
            </Button>
          </form>

          <hr className="meta-rule" style={{ marginBlock: 22 }} />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: 10,
              alignItems: "center",
            }}
          >
            <a
              href="#forgot"
              onClick={(e) => e.preventDefault()}
              style={{ fontSize: "var(--text-small)", color: "var(--ink-faint)" }}
            >
              Forgot password?
            </a>
            <ButtonLink to="/" variant="ghost-dark" size="sm">
              Back to website
            </ButtonLink>
          </div>
        </WindowPanel>

        <p style={{ textAlign: "center", marginTop: 18 }}>
          <Link to="/" className="meta-label">
            ← RAZORGROWTH AI
          </Link>
        </p>
      </div>
    </section>
  );
}
