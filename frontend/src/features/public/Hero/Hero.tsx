import { useReveal } from "../../../lib/useReveal";
import { HeroMainWindow } from "./HeroMainWindow";
import { HeroFloatingWindows } from "./HeroFloatingWindows";
import "./hero.css";

/**
 * #home — Hero.
 *
 * The persistent living world (GlobalEnvironment, mounted by Home) IS the
 * hero backdrop now: morning atmosphere, the storefront and waking growth
 * signals sit directly behind the welcome.app window. No private hero
 * background layer anymore.
 */
export function Hero() {
  const stageRef = useReveal<HTMLDivElement>();

  return (
    <section id="home" className="hero" aria-label="RazorGrowth AI introduction">
      <div ref={stageRef} className="shell hero__stage reveal">
        <div className="hero__main">
          <HeroMainWindow />
        </div>
        <HeroFloatingWindows />
      </div>
    </section>
  );
}
