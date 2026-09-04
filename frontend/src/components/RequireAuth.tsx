/**
 * RequireAuth — wraps routes that need an authenticated user.
 *
 * If no token is present it redirects to /login immediately (before any
 * API call), preserving the intended destination so the user can be
 * returned there after login in the future.
 *
 * If a token exists but /api/auth/me fails (expired/invalid), AuthContext
 * clears the token on the next refresh cycle and the guard fires on the
 * next render.
 */
import { Navigate, useLocation } from "react-router-dom";
import { isAuthenticated } from "../lib/auth";
import type { ReactNode } from "react";

interface RequireAuthProps {
  children: ReactNode;
}

export function RequireAuth({ children }: RequireAuthProps) {
  const location = useLocation();

  if (!isAuthenticated()) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  return <>{children}</>;
}
