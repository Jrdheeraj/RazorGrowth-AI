import { Navigate, Route, Routes } from "react-router-dom";
import { PublicLayout } from "./layouts/PublicLayout";
import { RequireAuth } from "./components/RequireAuth";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";
import { Checkout } from "./pages/Checkout";
import { GrowthRadar } from "./pages/GrowthRadar";
import { AgentsPage } from "./pages/AgentsPage";
import { MarketingAGIPage } from "./pages/MarketingAGIPage";
import { ProductAgentPage } from "./pages/ProductAgentPage";
import { DesignerAgentPage } from "./pages/DesignerAgentPage";
import { ManagerAgentPage } from "./pages/ManagerAgentPage";
import { SoftwareAgentPage } from "./pages/SoftwareAgentPage";
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
 *   /agents        → AI Growth Team dashboard (incl. Marketing + Product + Designer Agent entries)
 *   /manager-agent → Manager Agent autonomous growth orchestrator
 *   /manager       → redirect to /manager-agent
 *   /marketing-agent → Marketing Agent autonomous employee workstation
 *   /marketing-agi → legacy redirect to /marketing-agent
 *   /product-agent → Product Agent autonomous product-growth workstation (frontend preview)
 *   /designer-agent → Designer Agent autonomous creative workstation
 *   /software-agent → Software Agent autonomous technical feasibility workstation
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
        <Route path="/manager-agent" element={<ManagerAgentPage />} />
        <Route path="/manager"      element={<Navigate to="/manager-agent" replace />} />
        <Route path="/marketing-agent" element={<MarketingAGIPage />} />
        <Route path="/marketing-agi" element={<Navigate to="/marketing-agent" replace />} />
        <Route path="/product-agent" element={<ProductAgentPage />} />
        <Route path="/designer-agent" element={<DesignerAgentPage />} />
        <Route path="/software-agent" element={<SoftwareAgentPage />} />
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
