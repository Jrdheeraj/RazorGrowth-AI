/** Clouds — slow organic drift, tinted by daylight. */
const VB_TOP = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 1440 810",
  preserveAspectRatio: "xMidYMin slice",
} as const;

const CLOUDS = [
  { x: 180, y: 110, s: 1.15, dur: 96 },
  { x: 620, y: 66, s: 0.85, dur: 124, delay: -30 },
  { x: 980, y: 148, s: 1.0, dur: 108, delay: -60 },
  { x: 1290, y: 78, s: 0.7, dur: 140, delay: -18 },
];

export function CloudsLayer() {
  return (
    <svg className="env-layer env-clouds" {...VB_TOP} aria-hidden="true">
      <defs>
        <g id="rgw-cloud">
          <ellipse cx="-38" cy="6" rx="40" ry="16" fill="#00000010" />
          <ellipse cx="0" cy="-4" rx="64" ry="22" fill="var(--cloud-c)" />
          <ellipse cx="44" cy="-14" rx="44" ry="19" fill="var(--cloud-c2)" />
          <ellipse cx="10" cy="-18" rx="34" ry="16" fill="var(--cloud-c)" />
        </g>
      </defs>
      {CLOUDS.map((c, i) => (
        <g key={i} className="drift"
          style={{ animationDuration: `${c.dur}s`, animationDelay: `${c.delay ?? 0}s` }}>
          <use href="#rgw-cloud" transform={`translate(${c.x} ${c.y}) scale(${c.s})`} />
        </g>
      ))}
    </svg>
  );
}
