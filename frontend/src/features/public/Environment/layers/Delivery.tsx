/**
 * Delivery — fulfilment as objects: a delivery scooter parked on the
 * sidewalk by the district houses. No riders, no moving characters —
 * the town works through its things.
 */
const VB_BOTTOM = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 1440 810",
  preserveAspectRatio: "xMidYMax slice",
} as const;

export function DeliveryLayer() {
  return (
    <svg className="env-layer env-delivery" {...VB_BOTTOM} aria-hidden="true">
      {/* parked scooter by the houses (static, always) */}
      <g className="scooter-parked">
        <ellipse cx="1102" cy="690" rx="40" ry="7" fill="#301B12" opacity="0.14" />
        <path d="M1078 676 h34" stroke="#D97757" strokeWidth="7" strokeLinecap="round" />
        <path d="M1082 676 q-2 -16 -14 -22" stroke="#301B12" strokeWidth="5" strokeLinecap="round" fill="none" />
        <circle cx="1084" cy="684" r="10" fill="none" stroke="#301B12" strokeWidth="4" />
        <circle cx="1116" cy="684" r="10" fill="none" stroke="#301B12" strokeWidth="4" />
        <rect x="1086" y="658" width="22" height="13" rx="2" fill="#D9B98A" stroke="#301B12" strokeWidth="2.5" />
      </g>
    </svg>
  );
}
