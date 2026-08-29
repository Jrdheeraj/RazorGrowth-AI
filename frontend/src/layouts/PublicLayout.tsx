import { Suspense } from "react";
import { Outlet } from "react-router-dom";
import { SiteHeader } from "../components/SiteHeader";
import { SiteFooter } from "../components/SiteFooter";

/**
 * Public marketing-site chrome: sticky header, routed content, footer.
 * The authenticated workspace uses its own layout (AppLayout, Phase 4).
 */
export function PublicLayout() {
  return (
    <div className="public-shell">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <SiteHeader />
      <main id="main-content" style={{ minHeight: "60vh" }}>
        <Suspense fallback={null}>
          <Outlet />
        </Suspense>
      </main>
      <SiteFooter />
    </div>
  );
}
