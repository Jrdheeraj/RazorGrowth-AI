import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { scrollToSection, scrollToTop } from "../lib/scroll";
import { GlobalEnvironment } from "../features/public/Environment/GlobalEnvironment";

import { Hero } from "../features/public/Hero/Hero";
import { HomeWhoItsFor } from "../features/public/WhoItsFor/HomeWhoItsFor";
import { HowItWorks } from "../features/public/HowItWorks/HowItWorks";
import { ProductShowcase } from "../features/public/ProductShowcase/ProductShowcase";
import { Agents } from "../features/public/Agents/Agents";
import { AgentDebateDashboard } from "../features/public/Agents/AgentDebateDashboard";
import { Workflow } from "../features/public/Workflow/Workflow";
import { Demo } from "../features/public/Demo/Demo";
import { Manifesto } from "../features/public/Manifesto/Manifesto";
import { Docs } from "../features/public/Docs/Docs";
import { FinalCTA } from "../features/public/FinalCTA/FinalCTA";

/**
 * The complete public SaaS website — ONE continuous page inside ONE
 * continuous living commerce world.
 *
 * The environment is mounted once and evolves through eight story
 * chapters (morning → activity → customers → opportunity → agents →
 * approval → growth → night) as the visitor scrolls.
 *
 * Readability: every section except the Hero and the Manifesto sits on a
 * solid printed-paper sheet (.readable) — no translucency, no blur — so
 * the world stays clearly visible around and between sections.
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
      <GlobalEnvironment />

      {/* Chapter 1 — MORNING. The hero meets the waking world directly. */}
      <Hero />

      <div className="world-column">
        <div className="readable"><HomeWhoItsFor /></div>
        <div className="readable"><HowItWorks /></div>
        <div className="readable"><ProductShowcase /></div>
        <div className="readable"><Agents /></div>
        <div className="readable"><AgentDebateDashboard /></div>
        <div className="readable"><Workflow /></div>
        <div className="readable"><Demo /></div>

        {/* NIGHT CHAPTER — solid navy statement, no scrim needed */}
        <Manifesto />

        <div className="readable"><Docs /></div>
        <div className="readable"><FinalCTA /></div>
      </div>
    </div>
  );
}
