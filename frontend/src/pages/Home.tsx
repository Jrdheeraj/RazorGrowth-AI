import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { scrollToSection, scrollToTop } from "../lib/scroll";
import { MerchantWorldBackground } from "../features/public/MerchantWorld/MerchantWorldBackground";

/* Page scaffolding for the living-world Home page.
   `.world-page`, `.world-column` and the opaque `.readable` section sheets are
   used by this component only. The rules live in the Environment stylesheet,
   which is no longer pulled in automatically: the day-to-night scene moved to
   MerchantWorldBackground, so the old EnvironmentScene module that used to
   import this file is no longer part of the render tree. Without this import the
   whole stylesheet is dropped and every section renders as bare content on top
   of the background image. Keep this import. */
import "../features/public/Environment/environment.css";

import { Hero } from "../features/public/Hero/Hero";
import { ProductOverview } from "../features/public/ProductOverview/ProductOverview";
import { HomeWhoItsFor } from "../features/public/WhoItsFor/HomeWhoItsFor";
import { HowItWorks } from "../features/public/HowItWorks/HowItWorks";
import { ManagerCoordination } from "../features/public/ManagerCoordination/ManagerCoordination";
import { ProductShowcase } from "../features/public/ProductShowcase/ProductShowcase";
import { Agents } from "../features/public/Agents/Agents";
import { Workflow } from "../features/public/Workflow/Workflow";
import { ActivityTrace } from "../features/public/ActivityTrace/ActivityTrace";
import { Demo } from "../features/public/Demo/Demo";
import { Docs } from "../features/public/Docs/Docs";
import { FinalCTA } from "../features/public/FinalCTA/FinalCTA";

/**
 * The complete public SaaS website — ONE continuous page inside ONE
 * continuous living commerce world.
 *
 * Protected Hero: The hero section (HeroMainWindow, HeroFloatingWindows,
 * and the living commerce background) remains 100% intact and untouched.
 *
 * Lower Sections:
 *   1. ProductOverview — Connected workflow architecture
 *   2. HomeWhoItsFor   — Audience use cases (#who-its-for)
 *   3. HowItWorks      — Growth loop & human approval (#how-it-works)
 *   4. ManagerCoordination — ManagerAgent orchestrator & specialist dispatch
 *   5. ProductShowcase — Radar, Actions, Debates, and Workstation panels
 *   6. Agents          — Confirmed registered AI Team roster
 *   7. Workflow        — Guarded action lifecycle & contract bounds
 *   8. ActivityTrace   — Immutable audit trail & traceability
 *   9. Demo            — Interactive multi-stage product walkthrough
 *  10. Docs            — Architecture, security & trust manual
 *  11. FinalCTA        — Final call to action
 */
export function Home() {
  const location = useLocation();

  // Support "navigate home, then scroll to section" coming from other routes.
  useEffect(() => {
    const target = (location.state as { scrollTo?: string } | null)?.scrollTo;
    if (target) {
      requestAnimationFrame(() => scrollToSection(target));
    }
  }, [location.state]);

  useEffect(() => {
    if (!location.hash) scrollToTop();
  }, [location.pathname]);

  return (
    <div className="world-page">
      <MerchantWorldBackground />

      {/* Chapter 1 — MORNING HERO (Locked & Protected Region) */}
      <Hero />

      <div className="world-column">
        <div className="readable"><ProductOverview /></div>
        <div className="readable"><HomeWhoItsFor /></div>
        <div className="readable"><HowItWorks /></div>
        <div className="readable"><ManagerCoordination /></div>
        <div className="readable"><ProductShowcase /></div>
        <div className="readable"><Agents /></div>
        <div className="readable"><Workflow /></div>
        <div className="readable"><ActivityTrace /></div>
        <div className="readable"><Demo /></div>
        <div className="readable"><Docs /></div>
        <div className="readable"><FinalCTA /></div>
      </div>
    </div>
  );
}
