import { EnvironmentScene } from "./EnvironmentScene";
import { useWorldScroll } from "./useWorldScroll";

/**
 * GlobalEnvironment — the persistent living commerce world behind the
 * RazorGrowth homepage. Fixed to the viewport, pointer-transparent,
 * scroll-driven, zero React re-renders while scrolling.
 */
export function GlobalEnvironment() {
  useWorldScroll(true);

  return (
    <div className="world-env" role="presentation">
      <EnvironmentScene />
    </div>
  );
}
