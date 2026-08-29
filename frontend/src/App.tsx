import { Navigate, Route, Routes } from "react-router-dom";
import { PublicLayout } from "./layouts/PublicLayout";
import { Home } from "./pages/Home";
import { Login } from "./pages/Login";

/**
 * Application routes.
 *
 *   /        → the complete public SaaS website (one continuous page;
 *              navbar items smooth-scroll between section anchors)
 *   /login   → dedicated login page (the ONLY separate public route)
 *   /app/*   → authenticated workspace — guarded from Phase 3; until then
 *              it always redirects to /login
 *   *        → unknown URLs fall back to "/"
 *
 * Opening "/" never redirects to login and never shows a login gate.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<Login />} />
        <Route path="/app/*" element={<Navigate to="/login" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
