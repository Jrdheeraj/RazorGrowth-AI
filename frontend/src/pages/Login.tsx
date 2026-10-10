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

const IconUserPlus = () => (
  <FieldIcon>
    <circle cx="10" cy="8" r="3.6" />
    <path d="M3.5 20c0-3.6 2.9-5.8 6.5-5.8 1.4 0 2.7.3 3.7 1" />
    <path d="M18.5 14.5v6M15.5 17.5h6" />
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

const IconChart = () => (
  <FieldIcon>
    <path d="M4 20V4" />
    <path d="M4 20h16" />
    <path d="M8.5 16v-5M13 16V7.5M17.5 16v-3" />
  </FieldIcon>
);

const IconUsers = () => (
  <FieldIcon>
    <circle cx="9" cy="8" r="3.5" />
    <path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" />
    <circle cx="17" cy="9" r="2.6" />
    <path d="M16 14.2c2.8.3 5.5 2.3 5.5 5.3" />
  </FieldIcon>
);

const IconZap = () => (
  <FieldIcon>
    <path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2z" />
  </FieldIcon>
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
      <div className="rg-login__wrap">
        <div className="rg-login__panel">
          {/* ── LEFT: brand story + illustration ─────────────────────── */}
          <div className="rg-login__brand">
            <p className="rg-login__eyebrow">
              <span>Razorgrowth AI</span>
              <span className="rg-login__eyebrow-rule" aria-hidden="true" />
            </p>

            <h1 className="rg-login__headline">
              <span className="rg-login__line">Your next stage</span>
              <span className="rg-login__line">
                of <em className="rg-login__growth">growth</em>
              </span>
              <span className="rg-login__line">starts here.</span>
            </h1>

            <p className="rg-login__sub">
              One workspace for AI-powered commerce, products, marketing and
              real business growth.
            </p>

            <ul className="rg-login__features">
              <li className="rg-login__feature">
                <span className="rg-login__feature-icon" aria-hidden="true">
                  <IconChart />
                </span>
                <span className="rg-login__feature-text">
                  <strong>Boost Revenue</strong>
                  <span>Turn insights into sales.</span>
                </span>
              </li>
              <li className="rg-login__feature">
                <span className="rg-login__feature-icon" aria-hidden="true">
                  <IconUsers />
                </span>
                <span className="rg-login__feature-text">
                  <strong>Smarter Customers</strong>
                  <span>AI agents find real opportunities.</span>
                </span>
              </li>
              <li className="rg-login__feature">
                <span className="rg-login__feature-icon" aria-hidden="true">
                  <IconZap />
                </span>
                <span className="rg-login__feature-text">
                  <strong>Autonomous Growth</strong>
                  <span>Plan, execute and scale.</span>
                </span>
              </li>
            </ul>

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
              <span className="rg-login__titlebar-name">
                {mode === "login" ? "login.app" : "register.app"}
              </span>
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
                  <IconUser />
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
                  <IconUserPlus />
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
                      {showPw ? <IconEyeOff /> : <IconEye />}
                    </button>
                  </span>
                  {mode === "signup" && (
                    <span className="rg-login__hint">
                      Min 12 chars · at least one letter and one digit
                    </span>
                  )}
                </label>

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
          <Link to="/">← Razorgrowth AI</Link>
        </p>
      </div>
    </section>
  );
}
