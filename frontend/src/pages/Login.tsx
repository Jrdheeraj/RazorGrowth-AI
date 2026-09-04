import type { FormEvent } from "react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { WindowPanel } from "../components/WindowPanel";
import { Button, ButtonLink } from "../components/Button";
import { login, register } from "../lib/api";
import { setToken } from "../lib/auth";
import { useAuth } from "../lib/AuthContext";

/**
 * /login — authentication page with Login and Sign Up tabs.
 *
 * LOGIN:  POST /api/auth/login  → store token → redirect to /growth-radar
 * SIGNUP: POST /api/auth/register → then auto-login → redirect to /growth-radar
 *
 * Password policy (enforced by backend):
 *   - Minimum 12 characters
 *   - At least one letter
 *   - At least one digit
 */
type Mode = "login" | "signup";

export function Login() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [mode, setMode] = useState<Mode>("login");

  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [info, setInfo]         = useState<string | null>(null);

  // Reset form state when switching tabs
  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setInfo(null);
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setInfo(null);

    try {
      if (mode === "login") {
        // Existing user: exchange credentials for token
        const response = await login(email, password);
        setToken(response.access_token);
        await refresh();          // populate AuthContext before redirecting
        navigate("/profile");
      } else {
        // New user: register then immediately log in
        await register(email, password, fullName || undefined);
        setInfo("Account created — logging you in…");
        const response = await login(email, password);
        setToken(response.access_token);
        await refresh();          // populate AuthContext before redirecting
        navigate("/profile");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong";
      // Surface password policy violations clearly
      if (msg.includes("PASSWORD_POLICY_VIOLATION")) {
        setError(
          "Password must be at least 12 characters and contain at least one letter and one digit."
        );
      } else if (msg.includes("EMAIL_ALREADY_REGISTERED")) {
        setError("That email is already registered. Use the Login tab instead.");
      } else if (msg.includes("INVALID_CREDENTIALS")) {
        setError("Incorrect email or password.");
      } else if (msg.includes("REGISTRATION_DISABLED")) {
        setError("Account registration is currently disabled.");
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
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
          WORKSPACE ACCESS · {mode === "login" ? "LOGIN.APP" : "REGISTER.APP"}
        </p>

        <WindowPanel title={mode === "login" ? "login.app" : "register.app"}>
          {/* Tab strip */}
          <div style={{
            display: "flex",
            gap: 0,
            borderBottom: "1px solid var(--line-soft)",
            marginBottom: 24,
          }}>
            {(["login", "signup"] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => switchMode(tab)}
                style={{
                  flex: 1,
                  padding: "10px 0",
                  background: "transparent",
                  border: "none",
                  borderBottom: `2px solid ${mode === tab ? "var(--coral-strong)" : "transparent"}`,
                  marginBottom: -1,
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--text-meta)",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "var(--tracking-meta)",
                  color: mode === tab ? "var(--coral-strong)" : "var(--ink-faint)",
                  cursor: "pointer",
                  transition: "color 140ms, border-color 140ms",
                }}
              >
                {tab === "login" ? "Log In" : "Sign Up"}
              </button>
            ))}
          </div>

          <h1
            id="login-heading"
            className="display-md"
            style={{ fontSize: "var(--text-display-md)", marginTop: 0 }}
          >
            {mode === "login" ? "Welcome back." : "Create your account."}
          </h1>
          <p style={{ color: "var(--ink-soft)", marginTop: 8, fontSize: "var(--text-small)" }}>
            {mode === "login"
              ? "Sign in to open your RazorGrowth workspace."
              : "New to RazorGrowth AI? Set up your workspace in seconds."}
          </p>

          <form onSubmit={onSubmit} style={{ marginTop: 24, display: "grid", gap: 18 }}>
            {/* Full name — signup only */}
            {mode === "signup" && (
              <label style={{ display: "grid", gap: 7 }}>
                <span className="meta-label">Full Name (optional)</span>
                <input
                  type="text"
                  name="full_name"
                  autoComplete="name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="field"
                  placeholder="Your name"
                />
              </label>
            )}

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
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
                minLength={mode === "signup" ? 12 : 1}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="field"
              />
              {mode === "signup" && (
                <span style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--text-meta)",
                  color: "var(--ink-faint)",
                  letterSpacing: "var(--tracking-meta)",
                }}>
                  MIN 12 CHARS · AT LEAST ONE LETTER AND ONE DIGIT
                </span>
              )}
            </label>

            <Button type="submit" variant="primary" mono disabled={loading}>
              {loading
                ? mode === "login" ? "Signing in…" : "Creating account…"
                : mode === "login" ? "Log in"     : "Create account"}
            </Button>

            {/* Error */}
            {error && (
              <div
                role="alert"
                style={{
                  padding: "10px 14px",
                  background: "rgba(169,79,56,0.1)",
                  border: "1px solid var(--coral)",
                  borderRadius: "var(--radius-control)",
                  color: "var(--coral-strong)",
                  fontSize: "var(--text-small)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {error}
              </div>
            )}

            {/* Info */}
            {info && (
              <div
                role="status"
                style={{
                  padding: "10px 14px",
                  background: "rgba(112,184,138,0.12)",
                  border: "1px solid var(--green)",
                  borderRadius: "var(--radius-control)",
                  color: "var(--green-deep)",
                  fontSize: "var(--text-small)",
                  fontFamily: "var(--font-mono)",
                }}
              >
                {info}
              </div>
            )}
          </form>

          <hr className="meta-rule" style={{ marginBlock: 22 }} />
          <div style={{
            display: "flex",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 10,
            alignItems: "center",
          }}>
            <span style={{ fontSize: "var(--text-small)", color: "var(--ink-faint)" }}>
              {mode === "login"
                ? "No account yet? "
                : "Already have an account? "}
              <button
                type="button"
                onClick={() => switchMode(mode === "login" ? "signup" : "login")}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  color: "var(--coral)",
                  fontSize: "var(--text-small)",
                  cursor: "pointer",
                  fontFamily: "var(--font-mono)",
                  textDecoration: "underline",
                }}
              >
                {mode === "login" ? "Sign up" : "Log in"}
              </button>
            </span>
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
