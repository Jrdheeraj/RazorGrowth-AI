import { Navigate, Route, Routes } from "react-router-dom";
import { PublicLayout } from "./layouts/PublicLayout";
import { RequireAuth } from "./components/RequireAuth";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { Checkout } from "./pages/Checkout";
import { GrowthRadar } from "./pages/GrowthRadar";
import { AgentsPage } from "./pages/AgentsPage";
import { MarketingAGIPage } from "./pages/MarketingAGIPage";
import { DebatePage } from "./pages/DebatePage";
import { ActionsPage } from "./pages/ActionsPage";
import { ProfilePage } from "./pages/ProfilePage";

/**
 * Application routes.
 *
 *   /              → public SaaS site
 *   /login         → login + signup page
 *   /profile       → authenticated user profile  ← RequireAuth
 *   /checkout      → AI Buyer + Razorpay TEST checkout
 *   /growth-radar  → live Growth Radar
 *   /agents        → AI Growth Team dashboard
 *   /marketing-agi → Marketing AGI autonomous employee workstation
 *   /debate        → Agent Debate detail
 *   /actions       → Growth Actions approval console + audit trail
 *   /app/*         → redirects to /login (Phase 4 workspace)
 *   *              → falls back to "/"
 */
export default function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/"             element={<Home />} />
        <Route path="/login"        element={<Login />} />
        <Route path="/checkout"     element={<Checkout />} />
        <Route path="/growth-radar" element={<GrowthRadar />} />
        <Route path="/agents"       element={<AgentsPage />} />
        <Route path="/marketing-agi" element={<MarketingAGIPage />} />
        <Route path="/debate"       element={<DebatePage />} />
        <Route path="/actions"      element={<ActionsPage />} />

        {/* Protected — redirects to /login if not authenticated */}
        <Route
          path="/profile"
          element={
            <RequireAuth>
              <ProfilePage />
            </RequireAuth>
          }
        />

        <Route path="/app/*" element={<Navigate to="/login" replace />} />
        <Route path="*"      element={<Navigate to="/"     replace />} />
      </Route>
    </Routes>
  );
}
