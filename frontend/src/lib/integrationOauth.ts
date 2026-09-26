/**
 * OAuth callback result handling for marketing integrations.
 *
 * The backend OAuth callback never returns provider payloads — it redirects
 * here with exactly three safe query params: `integration`, `status`
 * (connected|error) and a whitelisted application `code`. This module maps
 * that code back to merchant-facing copy (never raw Google/Meta errors).
 */

export interface IntegrationCallback {
  integration: string | null;
  status: "connected" | "error" | null;
  code: string | null;
}

export interface ConnMsg {
  ok: boolean;
  text: string;
}

const SAFE_CODES = new Set([
  "GOOGLE_ADS_ACCOUNT_NOT_LINKED",
  "GOOGLE_ADS_AUTHENTICATION_FAILED",
  "AUTH_EXPIRED",
  "AUTH_REVOKED",
  "OAUTH_SCOPE_INSUFFICIENT",
  "GOOGLE_2SV_REQUIRED",
  "INSUFFICIENT_PERMISSIONS",
  "ACCOUNT_NOT_FOUND",
  "INVALID_CREDENTIALS",
  "MISSING_CONFIGURATION",
  "OAUTH_DENIED",
  "OAUTH_STATE_INVALID",
  "OAUTH_STATE_EXPIRED",
  "MISSING_CALLBACK_PARAMS",
  "RATE_LIMITED",
  "NETWORK_ERROR",
  "TIMEOUT",
  "MALFORMED_RESPONSE",
  "PROVIDER_ERROR",
  "CONNECTION_FAILED",
]);

/** Whitelisted code → merchant-facing message (Google Ads). */
export const GOOGLE_ADS_OAUTH_MESSAGES: Record<string, string> = {
  GOOGLE_ADS_ACCOUNT_NOT_LINKED:
    "✕ Your Google account isn't linked to a Google Ads account. Create or add access to one, then reconnect.",
  GOOGLE_ADS_AUTHENTICATION_FAILED:
    "✕ Google Ads authentication could not be completed. Please reconnect your Google account.",
  AUTH_EXPIRED: "✕ Your Google authorization expired. Please reconnect.",
  AUTH_REVOKED: "✕ Google access was revoked. Please reconnect.",
  OAUTH_SCOPE_INSUFFICIENT:
    "✕ Google Ads access was not approved. Reconnect and approve the requested permissions.",
  GOOGLE_2SV_REQUIRED:
    "✕ This Google account needs 2-Step Verification before it can authorize API access. Enable it, then reconnect.",
  MISSING_CONFIGURATION:
    "✕ Google Ads is not fully configured on this platform yet. Ask an admin to finish the setup, then try again.",
  INSUFFICIENT_PERMISSIONS:
    "✕ This Google account has insufficient Google Ads API access. Check access in the Google Ads API Center, then reconnect.",
  ACCOUNT_NOT_FOUND: "✕ The selected Google Ads customer could not be found. Verify the customer ID, then reconnect.",
  OAUTH_DENIED: "✕ Google sign-in was cancelled or declined. Start the connection again.",
  OAUTH_STATE_INVALID:
    "✕ The sign-in link expired or was already used. Start the connection again.",
  OAUTH_STATE_EXPIRED: "✕ The sign-in link expired. Start the connection again.",
  MISSING_CALLBACK_PARAMS: "✕ Google did not complete the sign-in. Start the connection again.",
  RATE_LIMITED: "✕ Too many attempts. Wait a moment, then try again.",
  NETWORK_ERROR: "✕ Network error while talking to Google. Check your connection and try again.",
  TIMEOUT: "✕ Google took too long to respond. Please try again.",
  MALFORMED_RESPONSE: "✕ Google returned an unexpected response. Please try again.",
  PROVIDER_ERROR: "✕ Google Ads could not be reached. Please try again.",
  CONNECTION_FAILED: "✕ Google Ads connection could not be completed. Please try again.",
};

const GENERIC_OAUTH_MESSAGES: Record<string, string> = {
  OAUTH_DENIED: "✕ The provider declined the sign-in. Start the connection again.",
  OAUTH_STATE_INVALID: "✕ The sign-in link expired or was already used. Start the connection again.",
  OAUTH_STATE_EXPIRED: "✕ The sign-in link expired. Start the connection again.",
  MISSING_CALLBACK_PARAMS: "✕ The provider did not complete the sign-in. Start the connection again.",
  MISSING_CONFIGURATION: "✕ This integration is not configured on this platform yet.",
  NETWORK_ERROR: "✕ Network error while talking to the provider. Check your connection and try again.",
  CONNECTION_FAILED: "✕ Connection could not be completed. Please try again.",
};

/** Message for a callback code; falls back to the status-based copy. */
export function integrationOauthMessage(integration: string | null, code: string | null): string {
  const maps: Record<string, Record<string, string>> = { google_ads: GOOGLE_ADS_OAUTH_MESSAGES };
  const known = integration ? maps[integration] : undefined;
  const lookup = known ?? GENERIC_OAUTH_MESSAGES;
  if (code && SAFE_CODES.has(code) && lookup[code]) return lookup[code];
  if (code && known && SAFE_CODES.has(code)) {
    // Known safe code for this integration with no dedicated copy yet.
    return `✕ Google Ads connection failed (${code}). Please try again.`;
  }
  if (code && !SAFE_CODES.has(code)) {
    // Never render an unvetted server string.
    return "✕ Google Ads connection could not be completed. Please try again.";
  }
  return "✕ Connection could not be completed. Please try again.";
}

/** Read + validate the OAuth redirect params. Never throws. */
export function parseIntegrationCallback(search: string): IntegrationCallback {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const integration = params.get("integration");
  const rawStatus = params.get("status");
  const rawCode = params.get("code");
  const status = rawStatus === "connected" || rawStatus === "error" ? rawStatus : null;
  return {
    integration: integration && integration.trim() ? integration.trim() : null,
    status,
    // Only surface whitelisted codes; anything else is dropped to null so the
    // caller can fall back to generic copy.
    code: rawCode && SAFE_CODES.has(rawCode) ? rawCode : null,
  };
}

/** Normalize the Customer ID typed in the connect form.
 * Returns undefined when it isn't a plausible Google Ads customer id, so a
 * junk value never travels into the signed OAuth state. */
export function googleCustomerSelector(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim();
  if (!/^[0-9-]+$/.test(trimmed)) return undefined;
  const digits = trimmed.replace(/[^0-9]/g, "");
  return digits.length >= 4 && digits.length <= 20 ? digits : undefined;
}

/** Build the banner shown after an OAuth round-trip (null = nothing to show). */
export function oauthResultMessage(search: string): ConnMsg | null {
  const cb = parseIntegrationCallback(search);
  if (!cb.integration || !cb.status) return null;
  if (cb.status === "connected") {
    return {
      ok: true,
      text: "✓ Connected. Credentials stored securely and verified live.",
    };
  }
  return { ok: false, text: integrationOauthMessage(cb.integration, cb.code) };
}
