/**
 * StreetSurface — the ground plane, painted in strict depth order:
 *
 *     far sidewalk (buildings stand on its far edge)
 *     → curb
 *     → road (in front of sidewalk, never touching buildings)
 *
 * Colours are atmosphere-driven so day/night changes tone without
 * moving a single object.
 */
const VB_BOTTOM = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 1440 810",
  preserveAspectRatio: "xMidYMax slice",
} as const;

export function StreetSurfaceLayer() {
  return (
    <svg className="env-layer env-street" {...VB_BOTTOM} aria-hidden="true">
      {/* far sidewalk — buildings sit behind this line */}
      <rect x="0" y="648" width="1440" height="58" fill="var(--walk-a)" />
      <rect x="0" y="648" width="1440" height="5" fill="#301B12" opacity="0.28" />
      {/* paving joints */}
      <g stroke="#301B12" strokeWidth="2" opacity="0.12">
        <line x1="120" y1="650" x2="112" y2="704" />
        <line x1="360" y1="650" x2="354" y2="704" />
        <line x1="600" y1="650" x2="596" y2="704" />
        <line x1="840" y1="650" x2="838" y2="704" />
        <line x1="1080" y1="650" x2="1080" y2="704" />
        <line x1="1320" y1="650" x2="1324" y2="704" />
      </g>
      {/* near-sidewalk shading strip */}
      <rect x="0" y="692" width="1440" height="14" fill="var(--walk-b)" />

      {/* curb */}
      <rect x="0" y="704" width="1440" height="7" fill="#301B12" opacity="0.55" />
      <rect x="0" y="704" width="1440" height="3" fill="var(--walk-b)" opacity="0.7" />

      {/* road */}
      <rect x="0" y="711" width="1440" height="99" fill="var(--road-a)" />
      <rect x="0" y="762" width="1440" height="48" fill="var(--road-b)" />
      {/* gutter shading along the curb + one manhole */}
      <rect x="0" y="711" width="1440" height="8" fill="#000000" opacity="0.10" />
      <ellipse cx="1010" cy="748" rx="20" ry="7" fill="#301B12" opacity="0.35" />
      <ellipse cx="1010" cy="748" rx="15" ry="5" fill="none" stroke="#F1E6C8" strokeWidth="1.6" opacity="0.25" />

      {/* centre dashes */}
      <g stroke="#FFF3DF" strokeWidth="5"
        opacity="calc(0.14 + var(--daylight) * 0.16)"
        strokeDasharray="36 52">
        <line x1="-20" y1="740" x2="1460" y2="740" />
      </g>
    </svg>
  );
}
