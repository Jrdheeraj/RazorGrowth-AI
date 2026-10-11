import type { FormEvent } from "react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { login, register } from "../lib/api";
import { setToken } from "../lib/auth";
import { useAuth } from "../lib/AuthContext";
import loginArt from "../assets/illustrations/Login_Background.png";
import "./Login.css";

/**
 * /login — two-column authentication experience.
 *
 * LEFT:  brand story (eyebrow, headline, supporting copy, three feature
 *        highlights) anchored by the saved `Login_Background.png`
 *        illustration rendered with object-fit: contain.
 * RIGHT: cream authentication card with a dark `login.app` title bar,
 *        Log in / Create account tabs, and the real auth form.
 *
 * AUTH BEHAVIOR IS UNCHANGED:
 * LOGIN:  POST /api/auth/login  → store token → refresh → /profile
 * SIGNUP: POST /api/auth/register → auto-login → refresh → /profile
 *
 * Password policy (enforced by backend):
 *   - Minimum 12 characters
 *   - At least one letter
 *   - At least one digit
 *
 * Intentionally omitted (no backend support exists):
 *   - "Forgot password?" link — no recovery endpoint in api.ts/backend.
 *   - Google sign-in button — repo OAuth covers Google Ads integrations
 *     only; there is no user-level Google sign-in flow to connect.
 */
type Mode = "login" | "signup";

/* ── Inline outline icons (1.8px stroke, currentColor — no new dep) ─────── */

function FieldIcon({ children }: { children: React.ReactNode }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

const IconUser = () => (
  <FieldIcon>
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5" />
  </FieldIcon>
);

const IconMail = () => (
  <FieldIcon>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="m3.5 7 8.5 6 8.5-6" />
  </FieldIcon>
);

const IconLock = () => (
  <FieldIcon>
    <rect x="5" y="10" width="14" height="10" rx="2" />
    <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    <circle cx="12" cy="15" r="1.2" fill="currentColor" stroke="none" />
  </FieldIcon>
);

const IconEye = () => (
  <FieldIcon>
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" />
    <circle cx="12" cy="12" r="3" />
  </FieldIcon>
);

const IconEyeOff = () => (
  <FieldIcon>
    <path d="M4 4l16 16" />
    <path d="M10.6 6c.5-.1.9-.1 1.4-.1 6 0 9.5 6.1 9.5 6.1a17 17 0 0 1-3 3.4M6.6 6.9A16 16 0 0 0 2.5 12S6 18.5 12 18.5c1.1 0 2.2-.2 3.1-.6" />
  </FieldIcon>
);

/* Solid user for the "Log in" tab (reference shows a filled glyph) */

const IconUserSolid = () => (
  <svg
    width="18"
    height="18"
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
    focusable="false"
  >
    <circle cx="12" cy="8" r="4" />
    <path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5v.5H4V21z" />
  </svg>
);

const IconUsers = () => (
  <FieldIcon>
    <circle cx="9" cy="8" r="3.5" />
    <path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" />
    <circle cx="17" cy="9" r="2.6" />
    <path d="M16 14.2c2.8.3 5.5 2.3 5.5 5.3" />
  </FieldIcon>
);

/* Official multicolor "G" for the Google button (inline SVG, no new dep) */

const IconGoogle = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path
      fill="#4285F4"
      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z"
    />
    <path
      fill="#34A853"
      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
    />
    <path
      fill="#FBBC05"
      d="M5.84 14.1a7.16 7.16 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84z"
    />
    <path
      fill="#EA4335"
      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
    />
  </svg>
);

/* Terracotta spark strokes after "starts here." (reference detail) */

const SparkMarks = () => (
  <svg
    className="rg-login__spark"
    width="30"
    height="30"
    viewBox="0 0 30 30"
    fill="none"
    aria-hidden="true"
    focusable="false"
  >
    <path d="M11 4.5 8.5 12" stroke="#D94B2F" strokeWidth="3" strokeLinecap="round" />
    <path d="M21 8.5 15.5 15" stroke="#D94B2F" strokeWidth="3" strokeLinecap="round" />
    <path d="M22 19.5h-6" stroke="#D94B2F" strokeWidth="3" strokeLinecap="round" />
  </svg>
);

export function Login() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [mode, setMode] = useState<Mode>("login");

  const [email, setEmail]       = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [showPw, setShowPw]     = useState(false);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [info, setInfo]         = useState<string | null>(null);

  // Reset form state when switching tabs
  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setInfo(null);
    setShowPw(false);
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
    <section className="rg-login" aria-labelledby="login-heading">
      {/* Layer 1 — the single continuous illustrated scene: `position: fixed`
          at `inset: 0`, so it starts at the very top of the viewport and runs
          behind the navbar AND the whole composition, with no seam. It is
          decorative only (`pointer-events: none`) and sits at z-index 0,
          below the shared navbar (z 40) and below `.rg-login__wrap` (z 1).
          The navbar component itself is untouched. */}
      <div className="rg-login__bg" aria-hidden="true" />
      <div className="rg-login__wrap">
        <div className="rg-login__panel">
          {/* ── LEFT: brand story + illustration ─────────────────────── */}
          <div className="rg-login__brand">
            <p className="rg-login__eyebrow">
              <span>RAZORGROWTH AI</span>
              <span className="rg-login__eyebrow-rule" aria-hidden="true" />
            </p>

            <h1 className="rg-login__headline">
              <span className="rg-login__line">Your next stage</span>
              <span className="rg-login__line">
                of <em className="rg-login__growth">growth</em>
              </span>
              <span className="rg-login__line">
                starts here.
                <SparkMarks />
              </span>
            </h1>

            <div className="rg-login__art">
              <img
                src={loginArt}
                alt="RazorGrowth AI storefront at sunset — a friendly robot with headphones works on a laptop beside product, marketing, customer and analytics boards and a growth chart"
                loading="eager"
              />
            </div>
          </div>

          {/* ── RIGHT: authentication card ───────────────────────────── */}
          <div className="rg-login__auth">
            <div className="rg-login__titlebar">
              <span className="rg-login__titlebar-name">login.app</span>
              <span className="rg-login__dots" aria-hidden="true">
                <span className="rg-login__dot rg-login__dot--terra" />
                <span className="rg-login__dot rg-login__dot--warm" />
                <span className="rg-login__dot rg-login__dot--muted" />
              </span>
            </div>

            <div className="rg-login__body">
              <p className="rg-login__body-eyebrow">Workspace access</p>
              <h2 id="login-heading" className="rg-login__heading">
                {mode === "login" ? "Welcome back." : "Create your account."}
              </h2>
              <p className="rg-login__lede">
                {mode === "login"
                  ? "Sign in to open your RazorGrowth workspace."
                  : "New to RazorGrowth AI? Set up your workspace in seconds."}
              </p>

              {/* Tabs */}
              <div className="rg-login__tabs" role="tablist" aria-label="Authentication mode">
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === "login"}
                  className={
                    mode === "login" ? "rg-login__tab is-active" : "rg-login__tab"
                  }
                  onClick={() => switchMode("login")}
                >
                  <IconUserSolid />
                  <span>Log in</span>
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={mode === "signup"}
                  className={
                    mode === "signup" ? "rg-login__tab is-active" : "rg-login__tab"
                  }
                  onClick={() => switchMode("signup")}
                >
                  <IconUsers />
                  <span>Create account</span>
                </button>
              </div>

              <form className="rg-login__form" onSubmit={onSubmit} noValidate={false}>
                {/* Full name — signup only (required by register API contract) */}
                {mode === "signup" && (
                  <label className="rg-login__label">
                    <span className="rg-login__label-text">Full name</span>
                    <span className="rg-login__control">
                      <span className="rg-login__control-icon" aria-hidden="true">
                        <IconUser />
                      </span>
                      <input
                        type="text"
                        name="full_name"
                        autoComplete="name"
                        value={fullName}
                        onChange={(e) => setFullName(e.target.value)}
                        className="rg-login__input"
                        placeholder="Your name"
                      />
                    </span>
                  </label>
                )}

                <label className="rg-login__label">
                  <span className="rg-login__label-text">Email</span>
                  <span className="rg-login__control">
                    <span className="rg-login__control-icon" aria-hidden="true">
                      <IconMail />
                    </span>
                    <input
                      type="email"
                      name="email"
                      autoComplete="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="rg-login__input"
                      placeholder="yourname@example.com"
                    />
                  </span>
                </label>

                <label className="rg-login__label">
                  <span className="rg-login__label-text">Password</span>
                  <span className="rg-login__control">
                    <span className="rg-login__control-icon" aria-hidden="true">
                      <IconLock />
                    </span>
                    <input
                      type={showPw ? "text" : "password"}
                      name="password"
                      autoComplete={mode === "login" ? "current-password" : "new-password"}
                      required
                      minLength={mode === "signup" ? 12 : 1}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="rg-login__input rg-login__input--with-toggle"
                      placeholder="Enter your password"
                    />
                    <button
                      type="button"
                      className="rg-login__pw-toggle"
                      aria-label={showPw ? "Hide password" : "Show password"}
                      aria-pressed={showPw}
                      onClick={() => setShowPw((v) => !v)}
                    >
                      {showPw ? <IconEye /> : <IconEyeOff />}
                    </button>
                  </span>
                  {mode === "signup" && (
                    <span className="rg-login__hint">
                      Min 12 chars · at least one letter and one digit
                    </span>
                  )}
                </label>

                {/* Forgot password — login mode only (no recovery endpoint
                    exists in the API, so this surfaces an honest notice
                    instead of a fake flow) */}
                {mode === "login" && (
                  <div className="rg-login__forgot-row">
                    <button
                      type="button"
                      className="rg-login__forgot"
                      onClick={() => {
                        setError(null);
                        setInfo(
                          "Password reset isn't available for this workspace yet — please sign in with your current password."
                        );
                      }}
                    >
                      Forgot password?
                    </button>
                  </div>
                )}

                <button
                  type="submit"
                  className="rg-login__submit"
                  disabled={loading}
                >
                  {loading
                    ? mode === "login" ? "Signing in…" : "Creating account…"
                    : mode === "login" ? "Log in to workspace →" : "Create account →"}
                </button>

                {/* Error */}
                {error && (
                  <div role="alert" className="rg-login__alert rg-login__alert--error">
                    {error}
                  </div>
                )}

                {/* Info */}
                {info && (
                  <div role="status" className="rg-login__alert rg-login__alert--info">
                    {info}
                  </div>
                )}

                {/* Alternative sign-in — login mode only, per the reference.
                    No user-level Google OAuth exists in the API (repo OAuth
                    covers Google Ads integrations only), so this surfaces an
                    honest notice instead of a fake flow. */}
                {mode === "login" && (
                  <>
                    <div className="rg-login__or" aria-hidden="true">
                      <span>OR CONTINUE WITH</span>
                    </div>
                    <button
                      type="button"
                      className="rg-login__google"
                      onClick={() => {
                        setError(null);
                        setInfo(
                          "Google sign-in isn't connected — continue with email and password."
                        );
                      }}
                    >
                      <IconGoogle />
                      <span>Sign in with Google</span>
                    </button>
                  </>
                )}
              </form>

              <p className="rg-login__switch">
                {mode === "login" ? (
                  <>
                    New to RazorGrowth?{" "}
                    <button type="button" onClick={() => switchMode("signup")}>
                      Create an account
                    </button>
                  </>
                ) : (
                  <>
                    Already have an account?{" "}
                    <button type="button" onClick={() => switchMode("login")}>
                      Log in
                    </button>
                  </>
                )}
              </p>
            </div>
          </div>
        </div>

        <p className="rg-login__back">
          <Link to="/">← RAZORGROWTH AI</Link>
        </p>
      </div>
    </section>
  );
}
