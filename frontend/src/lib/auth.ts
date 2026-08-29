/**
 * Minimal token store for the authenticated workspace.
 * Phase 3 builds the full session flow on top of these primitives.
 */

const TOKEN_KEY = "razorgrowth.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage unavailable — session stays in-memory only */
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}
