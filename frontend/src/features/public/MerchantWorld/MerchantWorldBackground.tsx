import { useEffect, useRef } from "react";
import morningImg from "../../../assets/illustrations/gemini-morning.jpeg";
import middayImg from "../../../assets/illustrations/gemini-midday.jpeg";
import sunsetImg from "../../../assets/illustrations/gemini-sunset.jpeg";
import nightImg from "../../../assets/illustrations/gemini-night.jpeg";
import { useMerchantWorldScroll } from "./useMerchantWorldScroll";
import "./merchantWorldBackground.css";

/**
 * MerchantWorldBackground — Full-screen Gemini Day-to-Night background
 * with buttery smooth, reversible scroll-driven transitions.
 *
 * Four Gemini-generated 2560x1440 assets:
 *   1. gemini-morning.jpeg — Morning street scene
 *   2. gemini-midday.jpeg  — Bright midday street scene
 *   3. gemini-sunset.jpeg  — Warm sunset golden hour
 *   4. gemini-night.jpeg   — Atmospheric night scene
 *
 * All layers are pre-decoded on mount so zero frames stall or stutter on scroll.
 */
export function MerchantWorldBackground() {
  const morningRef = useRef<HTMLDivElement>(null);
  const middayRef = useRef<HTMLDivElement>(null);
  const sunsetRef = useRef<HTMLDivElement>(null);
  const nightRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Eagerly pre-decode all images up front as specified in Gemini's script
    const sources = [morningImg, middayImg, sunsetImg, nightImg];
    sources.forEach((src) => {
      const img = new Image();
      img.src = src;
      if (img.decode) {
        img.decode().catch(() => {});
      }
    });
  }, []);

  useMerchantWorldScroll({
    morningRef,
    middayRef,
    sunsetRef,
    nightRef,
  });

  return (
    <div className="merchant-world-env" role="presentation" aria-hidden="true">
      {/* Layer 1 — Morning (Base Layer, always fully opaque) */}
      <div ref={morningRef} className="merchant-layer merchant-layer--morning">
        <img
          src={morningImg}
          alt="RazorGrowth AI street at morning"
          className="merchant-layer__img"
          loading="eager"
          decoding="async"
        />
      </div>

      {/* Layer 2 — Midday */}
      <div ref={middayRef} className="merchant-layer merchant-layer--midday">
        <img
          src={middayImg}
          alt="RazorGrowth AI street at midday"
          className="merchant-layer__img"
          loading="eager"
          decoding="async"
        />
      </div>

      {/* Layer 3 — Sunset */}
      <div ref={sunsetRef} className="merchant-layer merchant-layer--sunset">
        <img
          src={sunsetImg}
          alt="RazorGrowth AI street at sunset"
          className="merchant-layer__img"
          loading="eager"
          decoding="async"
        />
      </div>

      {/* Layer 4 — Night */}
      <div ref={nightRef} className="merchant-layer merchant-layer--night">
        <img
          src={nightImg}
          alt="RazorGrowth AI street at night"
          className="merchant-layer__img"
          loading="eager"
          decoding="async"
        />
      </div>

      {/* Layer 5 — Readability scrim: a light warm-cream wash that ties the
          artwork to the RazorGrowth cream palette. Sits above the four scene
          layers, below every piece of page content, and never intercepts input. */}
      <div className="merchant-world-scrim" />
    </div>
  );
}

