/* Regression test for the OAuth callback result handling.
 *
 * Guards the Phase 7/Phase 11 contract: the backend OAuth callback never
 * renders a Google/Meta payload — it redirects to the frontend with only
 * integration / status / a WHITELISTED code, and this module is the single
 * place that turns that code into merchant copy.
 *
 * Asserts:
 *  1. The account-not-linked result renders friendly copy with NO raw
 *     Google diagnostics (no NOT_ADS_USER, no 401/UNAUTHENTICATED, no
 *     endpoint names) — the exact bug this flow was opened for.
 *  2. An unknown / non-whitelisted code can never leak to the merchant.
 *  3. Missing or partial callback params produce no banner at all.
 *  4. The Google Ads customer id selector only ever forwards digits.
 *
 * Zero-dependency: compiled with the project's own tsc and executed with
 * plain node (`npm run test:oauth`). Fails with a non-zero exit code.
 */
import {
  GOOGLE_ADS_OAUTH_MESSAGES,
  googleCustomerSelector,
  integrationOauthMessage,
  oauthResultMessage,
  parseIntegrationCallback,
} from "../integrationOauth.js";

let failures = 0;

function check(name: string, actual: string, expected: string): void {
  if (actual !== expected) {
    failures += 1;
    console.error(`FAIL ${name}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`);
  } else {
    console.log(`ok   ${name}`);
  }
}

function checkNoRawGoogle(name: string, text: string): void {
  const forbidden = [
    "NOT_ADS_USER",
    "UNAUTHENTICATED",
    "HTTP 401",
    "401",
    "listAccessibleCustomers",
    "authenticationError",
    "requestError",
    "GOOGLE_ACCOUNT_NOT_LINKED_TO_ADS",
    "developers.google.com",
  ];
  const hit = forbidden.find((f) => text.includes(f));
  if (hit) {
    failures += 1;
    console.error(`FAIL ${name} — raw Google diagnostic leaked: ${JSON.stringify(hit)}\n  text: ${text}`);
  } else {
    console.log(`ok   ${name}`);
  }
}

/* ── 1. Account not linked (the reported bug) ─────────────────────── */
const notLinked = oauthResultMessage(
  "?integration=google_ads&status=error&code=GOOGLE_ADS_ACCOUNT_NOT_LINKED",
);
if (!notLinked || notLinked.ok !== false) {
  failures += 1;
  console.error(`FAIL not_linked renders an error banner, got ${JSON.stringify(notLinked)}`);
} else {
  console.log("ok   not_linked renders an error banner");
}
check(
  "not_linked copy is merchant-facing",
  (notLinked as { text: string }).text,
  GOOGLE_ADS_OAUTH_MESSAGES.GOOGLE_ADS_ACCOUNT_NOT_LINKED,
);
checkNoRawGoogle("not_linked has no raw Google diagnostics", (notLinked as { text: string }).text);

/* ── 2. Whitelisted codes → dedicated copy ────────────────────────── */
check(
  "auth_failed message",
  integrationOauthMessage("google_ads", "GOOGLE_ADS_AUTHENTICATION_FAILED"),
  GOOGLE_ADS_OAUTH_MESSAGES.GOOGLE_ADS_AUTHENTICATION_FAILED,
);
check(
  "expired state tells the merchant to start again",
  integrationOauthMessage("google_ads", "OAUTH_STATE_EXPIRED"),
  GOOGLE_ADS_OAUTH_MESSAGES.OAUTH_STATE_EXPIRED,
);
check(
  "missing configuration points at platform setup",
  integrationOauthMessage("google_ads", "MISSING_CONFIGURATION"),
  GOOGLE_ADS_OAUTH_MESSAGES.MISSING_CONFIGURATION,
);

/* ── 3. Non-whitelisted codes can never reach the merchant ────────── */
const sneaky = oauthResultMessage(
  "?integration=google_ads&status=error&code=INTERNAL_SECRET_LEAK_123",
);
if (!sneaky || sneaky.ok !== false) {
  failures += 1;
  console.error(`FAIL unknown code still renders an error banner, got ${JSON.stringify(sneaky)}`);
} else {
  console.log("ok   unknown code still renders an error banner");
}
checkNoRawGoogle("unknown code is not echoed back", (sneaky as { text: string }).text);
check(
  "unknown code is dropped to null by the parser",
  String(parseIntegrationCallback("?integration=google_ads&status=error&code=NOT_ADS_USER").code),
  "null",
);

/* ── 4. Partial / missing params → no banner ──────────────────────── */
check("no params -> null", String(oauthResultMessage("")), "null");
check(
  "success without integration -> null",
  String(oauthResultMessage("?status=connected")),
  "null",
);
check(
  "error without code -> generic fallback",
  (oauthResultMessage("?integration=google_ads&status=error") as { text: string }).text,
  "✕ Connection could not be completed. Please try again.",
);

/* ── 5. Connected status renders the success banner ───────────────── */
const okMsg = oauthResultMessage("?integration=google_ads&status=connected");
if (!okMsg || okMsg.ok !== true) {
  failures += 1;
  console.error(`FAIL connected renders a success banner, got ${JSON.stringify(okMsg)}`);
} else {
  console.log("ok   connected renders a success banner");
}
checkNoRawGoogle("success banner carries no payload", okMsg ? okMsg.text : "");

/* ── 6. Customer id selector is digits-only ───────────────────────── */
check("selector keeps digits", googleCustomerSelector("1234567890") as string, "1234567890");
check("selector strips dashes", googleCustomerSelector("1234-567-890") as string, "1234567890");
check("selector drops letters", String(googleCustomerSelector("act_123456")), "undefined");
check("selector drops short values", String(googleCustomerSelector("123")), "undefined");
check("selector handles empty", String(googleCustomerSelector("")), "undefined");

if (failures > 0) {
  throw new Error(`${failures} integrationOauth check(s) failed`);
}
console.log("integrationOauth: all checks passed");
