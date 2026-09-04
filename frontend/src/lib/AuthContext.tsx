/**
 * AuthContext — lightweight React context for the authenticated user.
 *
 * Wraps the existing getToken / clearToken / fetchMe primitives so any
 * component can read the current user without prop-drilling.
 *
 * Rules:
 * - Never stores passwords or raw tokens in context state.
 * - Token lives in localStorage (existing razorgrowth.token key).
 * - Context state holds only the decoded user object from /api/auth/me.
 * - logout() clears the token and resets state.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { getToken, clearToken } from "./auth";
import { fetchMe } from "./api";
import type { MeResponse } from "../types/api";

interface AuthState {
  user: MeResponse | null;
  loading: boolean;
}

interface AuthContextValue extends AuthState {
  /** Refresh the current-user data from /api/auth/me */
  refresh: () => Promise<void>;
  /** Clear token, reset state, call onLogout callback */
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({
  children,
  onLogout,
}: {
  children: ReactNode;
  onLogout?: () => void;
}) {
  const [state, setState] = useState<AuthState>({ user: null, loading: true });

  const refresh = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setState({ user: null, loading: false });
      return;
    }
    try {
      const me = await fetchMe();
      setState({ user: me, loading: false });
    } catch {
      // Invalid/expired token — clear it silently
      clearToken();
      setState({ user: null, loading: false });
    }
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setState({ user: null, loading: false });
    onLogout?.();
  }, [onLogout]);

  // Load user on mount
  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ ...state, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

/** Use the authenticated user context. Must be inside <AuthProvider>. */
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
