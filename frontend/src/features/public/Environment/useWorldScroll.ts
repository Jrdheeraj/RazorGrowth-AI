import { useEffect, useRef } from "react";
import { sampleWorld, defaultVars } from "./scenes";

/**
 * useWorldScroll — v3.1 engine.
 *
 * native scroll → rAF → SMOOTHED time-of-day progress → CSS variables.
 *
 * - The page content scrolls NATIVELY; nothing here touches scrollTop
 *   injection, wheel events or the content column.
 * - Time-of-day is mapped through SECTION ANCHORS: each landmark section
 *   corresponds to a fixed moment on the ATMOSPHERE timeline, so the
 *   day→night transition always begins around the documentation section
 *   regardless of how tall the sections render.
 * - Progress eases toward the target (gentle inertia); the rAF loop runs
 *   ONLY while easing is in motion, and React never re-renders on scroll.
 */

const SMOOTHING = 0.14;          // per-frame approach factor
const EPSILON = 0.0006;
const DEFAULTS = defaultVars();

/** Section id → moment on the ATMOSPHERE timeline. */
const ANCHORS: ReadonlyArray<readonly [string, number]> = [
  ["home", 0.02],
  ["who-its-for", 0.24],
  ["how-it-works", 0.42],
  ["product", 0.56],
  ["agents", 0.66],
  ["workflow", 0.76],
  ["demo", 0.82],
  ["manifesto", 0.88],
  ["docs", 0.93],
  ["cta", 1],
];

/** Viewport line at which a section is considered "arrived". */
const TRIGGER = 0.6;

/** [scrollY, time] waypoints, measured from the live document. */
type Waypoints = Array<readonly [number, number]>;

function measureWaypoints(): Waypoints {
  const points: Waypoints = [[0, 0]];
  const vh = window.innerHeight;
  let lastY = 0;
  for (const [id, t] of ANCHORS) {
    const el = document.getElementById(id);
    if (!el) continue;
    const top = el.getBoundingClientRect().top + window.scrollY;
    const y = Math.max(lastY, top - vh * TRIGGER);
    lastY = y;
    points.push([y, t]);
  }
  // Not enough landmarks → fall back to plain linear mapping.
  if (points.length < 4) return [[0, 0], [Number.POSITIVE_INFINITY, 1]];
  return points;
}

function timeAt(points: Waypoints, y: number): number {
  if (y <= points[0][0]) return points[0][1];
  for (let i = 1; i < points.length; i++) {
    const [y1, t1] = points[i];
    if (y <= y1) {
      const [y0, t0] = points[i - 1];
      const span = y1 - y0;
      return span > 0 ? t0 + ((y - y0) / span) * (t1 - t0) : t1;
    }
  }
  return points[points.length - 1][1];
}

export function useWorldScroll(enabled = true) {
  const current = useRef(0.02);

  useEffect(() => {
    if (!enabled) return;
    const root = document.documentElement;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");

    // seed defaults immediately so first paint is a valid world
    for (const k in DEFAULTS) root.style.setProperty(k, String(DEFAULTS[k]));

    // Reduced motion: one coherent static frame for wherever the page
    // opens; no listeners, no animation.
    if (reduced.matches) {
      const points = measureWaypoints();
      write(sampleWorld(timeAt(points, window.scrollY)).vars);
      return;
    }

    function write(vars: Record<string, string | number>) {
      for (const k in vars) root.style.setProperty(k, String(vars[k]));
    }

    let raf = 0;
    let target = 0;
    let waypoints = measureWaypoints();

    function tick() {
      raf = 0;
      const diff = target - current.current;
      if (Math.abs(diff) < EPSILON) {
        current.current = target;
        write(sampleWorld(target).vars);
        return;                       // ease complete — loop stops
      }
      current.current += diff * SMOOTHING;
      write(sampleWorld(current.current).vars);
      raf = requestAnimationFrame(tick);
    }

    function kick() {
      if (!raf) raf = requestAnimationFrame(tick);
    }

    function readTarget() {
      target = timeAt(waypoints, window.scrollY);
      kick();
    }

    function remeasure() {
      waypoints = measureWaypoints();
      readTarget();
    }

    readTarget();
    window.addEventListener("scroll", readTarget, { passive: true });
    window.addEventListener("resize", remeasure);
    // Late layout shifts (fonts, images) settle after first paint.
    window.addEventListener("load", remeasure);
    return () => {
      window.removeEventListener("scroll", readTarget);
      window.removeEventListener("resize", remeasure);
      window.removeEventListener("load", remeasure);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [enabled]);
}
