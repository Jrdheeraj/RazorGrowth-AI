/**
 * Sky layers — gradient sky, travelling sun, rising moon, stars.
 * Geometry is static; only atmosphere variables change.
 */
const VB_TOP = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 1440 810",
  preserveAspectRatio: "xMidYMin slice",
} as const;

export function SkyLayer() {
  return <div className="env-layer env-sky" aria-hidden="true" />;
}

export function StarsLayer() {
  const dots: Array<[number, number, number]> = [
    [96, 64, 2], [210, 128, 1.5], [338, 58, 2.2], [470, 150, 1.6],
    [588, 74, 2], [704, 36, 1.7], [826, 118, 2.3], [952, 62, 1.5],
    [1074, 140, 2], [1190, 84, 1.8], [1302, 152, 2.1], [1396, 60, 1.6],
    [282, 208, 1.4], [512, 236, 1.3], [742, 196, 1.5], [1006, 226, 1.4],
    [1244, 244, 1.3], [1420, 190, 1.5],
  ];
  return (
    <svg className="env-layer env-stars" {...VB_TOP} aria-hidden="true">
      <g fill="#F1E6C8">
        {dots.map(([x, y, r], i) => (
          <circle key={i} cx={x} cy={y} r={r}
            className={i % 3 === 0 ? "tw" : undefined}
            style={i % 3 === 0 ? { animationDelay: `${(i * 0.53) % 3.4}s` } : undefined} />
        ))}
      </g>
    </svg>
  );
}

export function CelestialLayer() {
  return (
    <div className="env-layer env-celestial" aria-hidden="true">
      <div className="env-sun-halo" />
      <div className="env-sun" />
      <div className="env-moon" />
    </div>
  );
}
