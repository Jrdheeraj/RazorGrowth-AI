/**
 * Foreground — nearest plane: near sidewalk edge, lamps with warm night
 * cones, bench, hydrant, hedge and flowers. Sits IN FRONT of the road,
 * closing the depth stack.
 */
const VB_BOTTOM = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 1440 810",
  preserveAspectRatio: "xMidYMax slice",
} as const;

export function ForegroundLayer() {
  return (
    <svg className="env-layer env-foreground" {...VB_BOTTOM} aria-hidden="true">

      {/* near sidewalk strip */}
      <rect x="0" y="760" width="1440" height="50" fill="var(--walk-b)" />

      {/* lamp posts stand on the near sidewalk */}
      <g>
        <ellipse cx="242" cy="756" rx="26" ry="5" fill="#301B12" opacity="0.2" />
        <rect x="237" y="588" width="10" height="168" fill="#301B12" />
        <path d="M242 588 q0 -20 22 -22" stroke="#301B12" strokeWidth="7" strokeLinecap="round" fill="none" />
        <circle cx="268" cy="570" r="10" fill="#F6C489" style={{ opacity: "var(--lamps)" }} />
        {/* warm cone onto the street below */}
        <path d="M250 578 L206 760 H334 Z" fill="#F6C489"
          style={{ opacity: "calc(var(--lamps) * 0.12)" }} />
      </g>

      <g>
        <ellipse cx="1196" cy="756" rx="26" ry="5" fill="#301B12" opacity="0.2" />
        <rect x="1191" y="592" width="10" height="164" fill="#301B12" />
        <path d="M1196 592 q0 -20 22 -22" stroke="#301B12" strokeWidth="7" strokeLinecap="round" fill="none" />
        <circle cx="1222" cy="574" r="10" fill="#F6C489" style={{ opacity: "var(--lamps)" }} />
        <path d="M1200 582 L1158 760 H1288 Z" fill="#F6C489"
          style={{ opacity: "calc(var(--lamps) * 0.11)" }} />
      </g>

      {/* bench */}
      <g stroke="#301B12" strokeWidth="3">
        <ellipse cx="360" cy="758" rx="52" ry="7" fill="#301B12" opacity="0.15" stroke="none" />
        <rect x="320" y="706" width="84" height="10" rx="3" fill="#C9855B" />
        <rect x="326" y="716" width="72" height="7" rx="3" fill="#B7744E" />
        <rect x="328" y="723" width="8" height="34" fill="#301B12" />
        <rect x="388" y="723" width="8" height="34" fill="#301B12" />
      </g>

      {/* hydrant */}
      <g stroke="#301B12" strokeWidth="3">
        <ellipse cx="948" cy="758" rx="26" ry="5" fill="#301B12" opacity="0.15" stroke="none" />
        <rect x="938" y="722" width="20" height="34" rx="6" fill="#D97757" />
        <rect x="932" y="732" width="32" height="8" rx="4" fill="#D97757" />
        <circle cx="948" cy="718" r="7" fill="#C85F43" />
      </g>

      {/* hedge + flowers along the very front */}
      <rect x="0" y="782" width="1440" height="28" fill="#35664A" />
      <g stroke="#2A5239" strokeWidth="6" strokeLinecap="round" fill="none">
        <path d="M180 800 q8 -36 0 -56" />
        <path d="M212 802 q-6 -30 10 -48" />
        <path d="M1240 800 q10 -40 -2 -64" />
        <path d="M1272 802 q14 -32 32 -46" />
        <path d="M640 802 q6 -28 -4 -44" />
      </g>
      <g>
        {[[86, 782], [156, 786], [508, 784], [580, 787], [868, 784], [1042, 787], [1330, 783]].map(([x, y], i) => (
          <g key={i}>
            <line x1={x} y1={y + 14} x2={x} y2={y} stroke="#356648" strokeWidth="3.2" />
            <circle cx={x} cy={y - 3} r={i % 2 ? 5 : 6}
              fill={i % 3 === 1 ? "#F6C489" : "#D97757"} />
            <circle cx={x} cy={y - 3} r={1.8} fill="#FFF3DF" opacity="0.85" />
          </g>
        ))}
      </g>
    </svg>
  );
}
