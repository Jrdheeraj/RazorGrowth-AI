/**
 * Distant skyline — sits ON the horizon, never moves relative to the
 * town. A handful of windows warm up at night.
 */
const VB_BOTTOM = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 1440 810",
  preserveAspectRatio: "xMidYMax slice",
} as const;

export function CityLayer() {
  return (
    <svg className="env-layer env-city" {...VB_BOTTOM} aria-hidden="true">
      <g fill="var(--city-c)" opacity="0.4">
        <rect x="150" y="392" width="64" height="116" />
        <rect x="330" y="372" width="48" height="136" />
        <rect x="540" y="384" width="70" height="124" />
        <rect x="760" y="366" width="56" height="142" />
        <rect x="960" y="380" width="66" height="128" />
        <rect x="1150" y="366" width="52" height="142" />
        <rect x="1330" y="388" width="66" height="120" />
      </g>
      <g fill="var(--city-c)">
        <rect x="96" y="430" width="86" height="80" />
        <rect x="212" y="414" width="62" height="96" />
        <rect x="300" y="444" width="46" height="66" />
        <rect x="398" y="422" width="76" height="88" />
        <rect x="508" y="446" width="52" height="64" />
        <rect x="590" y="416" width="68" height="94" />
        <rect x="692" y="440" width="50" height="70" />
        <rect x="774" y="424" width="70" height="86" />
        <rect x="876" y="448" width="48" height="62" />
        <rect x="954" y="420" width="64" height="90" />
        <rect x="1048" y="442" width="54" height="68" />
        <rect x="1130" y="412" width="74" height="98" />
        <rect x="1232" y="438" width="56" height="72" />
        <rect x="1316" y="418" width="66" height="92" />
        <rect x="1408" y="440" width="32" height="70" />
        <rect x="232" y="400" width="7" height="16" />
        <rect x="618" y="402" width="7" height="16" />
        <rect x="976" y="406" width="7" height="16" />
        <rect x="1152" y="398" width="7" height="16" />
      </g>
      {/* windows warming up after dark */}
      <g fill="#F6C489" opacity="calc(var(--lamps) * 0.85)">
        {[[118, 446], [148, 470], [232, 434], [258, 462], [418, 440], [444, 468],
          [610, 436], [636, 466], [796, 442], [822, 472], [974, 438], [998, 468],
          [1150, 430], [1178, 458], [1336, 436], [1362, 464]].map(([x, y], i) => (
          <rect key={i} x={x} y={y} width="10" height="13"
            className={i % 4 === 0 ? "win-flicker" : undefined}
            style={i % 4 === 0 ? { animationDelay: `${i * 0.9}s` } : undefined} />
        ))}
      </g>
    </svg>
  );
}
