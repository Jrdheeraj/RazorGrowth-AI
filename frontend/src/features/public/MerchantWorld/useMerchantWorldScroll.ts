import { useEffect, useRef } from "react";

export interface LayerAlphas {
  morning: number;
  midday: number;
  sunset: number;
  night: number;
  // Aliases for compatibility
  day: number;
  afternoon: number;
}

/**
 * Hermite smoothStep: soft start and end for natural crossfading.
 */
function smoothStep(t: number): number {
  return t * t * (3 - 2 * t);
}

function clamp(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

/**
 * computeLayerAlphas — Maps vertical scroll progress (0..1) to the 4 Gemini scenes:
 *   N = 4 layers (Morning, Midday, Sunset, Night)
 *   pos = progress * (N - 1)  [0..3]
 *
 * Gemini crossfade formula:
 *   - Morning is base layer (always 1.0)
 *   - Midday fades in: ease(clamp((pos - 0 - 0.15) / 0.7))
 *   - Sunset fades in: ease(clamp((pos - 1 - 0.15) / 0.7))
 *   - Night fades in: ease(clamp((pos - 2 - 0.15) / 0.7))
 *
 * Provides smooth, reversible transitions with zero dips or double-exposures.
 */
export function computeLayerAlphas(progress: number, prefersReducedMotion = false): LayerAlphas {
  const p = clamp(progress);

  if (prefersReducedMotion) {
    if (p < 0.25) return { morning: 1, midday: 0, sunset: 0, night: 0, day: 1, afternoon: 0 };
    if (p < 0.55) return { morning: 1, midday: 1, sunset: 0, night: 0, day: 1, afternoon: 1 };
    if (p < 0.80) return { morning: 1, midday: 1, sunset: 1, night: 0, day: 1, afternoon: 1 };
    return { morning: 1, midday: 1, sunset: 1, night: 1, day: 1, afternoon: 1 };
  }

  const N = 4;
  const pos = p * (N - 1); // 0..3

  const midday = smoothStep(clamp((pos - 0 - 0.15) / 0.7));
  const sunset = smoothStep(clamp((pos - 1 - 0.15) / 0.7));
  const night = smoothStep(clamp((pos - 2 - 0.15) / 0.7));

  return {
    morning: 1,
    midday,
    sunset,
    night,
    day: 1,
    afternoon: midday,
  };
}

export interface UseMerchantWorldScrollRefs {
  morningRef?: React.RefObject<HTMLDivElement | null>;
  middayRef?: React.RefObject<HTMLDivElement | null>;
  sunsetRef?: React.RefObject<HTMLDivElement | null>;
  nightRef?: React.RefObject<HTMLDivElement | null>;
  // Backwards compatibility with previous ref names
  dayRef?: React.RefObject<HTMLDivElement | null>;
  afternoonRef?: React.RefObject<HTMLDivElement | null>;
}

/**
 * useMerchantWorldScroll:
 *   - Direct passive scroll listener with requestAnimationFrame.
 *   - Buttery inertia smoothing: current += (target - current) * 0.14.
 *   - Direct DOM style mutations on refs for 0 React re-renders.
 *   - Hides inactive layers (visibility: hidden) to eliminate GPU compositing overhead.
 *   - Full cleanup on unmount.
 */
export function useMerchantWorldScroll(refs: UseMerchantWorldScrollRefs) {
  const currentRef = useRef<number>(0);
  const targetRef = useRef<number>(0);
  const rafIdRef = useRef<number | null>(null);

  useEffect(() => {
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const mornEl = refs.morningRef?.current || refs.dayRef?.current;
    const midEl = refs.middayRef?.current || refs.afternoonRef?.current;
    const sunEl = refs.sunsetRef?.current;
    const nightEl = refs.nightRef?.current;

    const applyAlphas = (progress: number) => {
      const alphas = computeLayerAlphas(progress, prefersReducedMotion);

      if (mornEl) {
        mornEl.style.opacity = alphas.morning.toFixed(3);
      }
      if (midEl) {
        midEl.style.opacity = alphas.midday.toFixed(3);
        midEl.style.visibility = alphas.midday <= 0.001 ? "hidden" : "visible";
      }
      if (sunEl) {
        sunEl.style.opacity = alphas.sunset.toFixed(3);
        sunEl.style.visibility = alphas.sunset <= 0.001 ? "hidden" : "visible";
      }
      if (nightEl) {
        nightEl.style.opacity = alphas.night.toFixed(3);
        nightEl.style.visibility = alphas.night <= 0.001 ? "hidden" : "visible";
      }
    };

    const readTarget = () => {
      const docHeight = document.documentElement.scrollHeight;
      const winHeight = window.innerHeight;
      const max = docHeight - winHeight;
      targetRef.current = max > 0 ? clamp(window.scrollY / max) : 0;
    };

    const tick = () => {
      if (prefersReducedMotion) {
        currentRef.current = targetRef.current;
        applyAlphas(currentRef.current);
        rafIdRef.current = null;
        return;
      }

      const diff = targetRef.current - currentRef.current;
      currentRef.current += diff * 0.14; // Buttery inertia interpolation

      if (Math.abs(diff) < 0.0002) {
        currentRef.current = targetRef.current;
      }

      applyAlphas(currentRef.current);

      if (currentRef.current !== targetRef.current) {
        rafIdRef.current = requestAnimationFrame(tick);
      } else {
        rafIdRef.current = null;
      }
    };

    const onScroll = () => {
      readTarget();
      if (rafIdRef.current === null) {
        rafIdRef.current = requestAnimationFrame(tick);
      }
    };

    // Initial pass
    readTarget();
    currentRef.current = targetRef.current;
    applyAlphas(currentRef.current);

    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });

    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [refs]);
}

