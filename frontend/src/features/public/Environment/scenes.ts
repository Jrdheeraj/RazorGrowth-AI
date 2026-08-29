/**
 * SCENES — the v3.1 storyboard.
 *
 * One continuous merchant street, one day. Scroll drives TIME only;
 * geometry never changes. The neighbourhood tells the story through
 * architecture and objects: a shop that opens, stock that grows,
 * windows and lamps that light up at night. No characters.
 */

/* ── Chapters (documented; informational labels) ─────────────────────── */
export const CHAPTERS = [
  { id: "morning",  label: "Opening up",            range: [0.00, 0.22] },
  { id: "day",      label: "Business as usual",     range: [0.22, 0.40] },
  { id: "warm",     label: "Warm afternoon",        range: [0.40, 0.55] },
  { id: "golden",   label: "Golden hour",           range: [0.55, 0.66] },
  { id: "sunset",   label: "Sunset",                range: [0.66, 0.84] },
  { id: "dusk",     label: "Lights come on",        range: [0.84, 0.93] },
  { id: "night",    label: "Night operations",      range: [0.93, 1.00] },
] as const;

/* ── Atmosphere keyframes ─────────────────────────────────────────────── */

export interface AtmoStop {
  p: number;
  skyTop: string; skyMid: string; skyLow: string;
  sunX: number; sunY: number; sunO: number;
  moonO: number; stars: number;
  cityColor: string;
  daylight: number;             // 1 day → 0 deep night
  lamps: number;                // artificial light energy
  walkA: string; walkB: string; // sidewalk tones
  roadA: string; roadB: string; // asphalt tones
  grassA: string; grassB: string;
}

/**
 * Cinematic clock. The scroll engine (useWorldScroll) maps page scroll to
 * this timeline via SECTION ANCHORS, so the values below correspond to
 * moments in the page flow:
 *
 *   0.00 hero · morning          0.42 how-it-works · warm afternoon
 *   0.24 who-its-for · day       0.56 product · golden hour
 *   0.66 agents · late golden    0.76 workflow · sunset
 *   0.82 demo · deep sunset      0.87 manifesto · dusk (lamps on)
 *   0.91 docs · evening begins   1.00 final CTA · full night
 */
export const ATMOSPHERE: readonly AtmoStop[] = [
  // MORNING — pale gold, quiet
  { p: 0.00, skyTop: "#F4DDB6", skyMid: "#F5CC9E", skyLow: "#F0BC92",
    sunX: 24, sunY: 58, sunO: 0.9, moonO: 0.12, stars: 0.05,
    cityColor: "#C99A76", daylight: 0.85, lamps: 0.28,
    walkA: "#EBD9AE", walkB: "#DEC79A", roadA: "#8C7A66", roadB: "#77675A",
    grassA: "#7BA57F", grassB: "#587F5E" },
  // DAY — clear and bright
  { p: 0.24, skyTop: "#FAF0DB", skyMid: "#F7E3BE", skyLow: "#F4CF9F",
    sunX: 44, sunY: 32, sunO: 0.85, moonO: 0, stars: 0,
    cityColor: "#CD9E77", daylight: 1, lamps: 0.05,
    walkA: "#F2E2BC", walkB: "#E4CF9F", roadA: "#978571", roadB: "#80705F",
    grassA: "#82B086", grassB: "#5F8A65" },
  // WARM AFTERNOON — amber creeping in
  { p: 0.42, skyTop: "#F8E4B8", skyMid: "#F4CE9E", skyLow: "#EFB488",
    sunX: 54, sunY: 34, sunO: 0.9, moonO: 0, stars: 0,
    cityColor: "#C79A73", daylight: 0.95, lamps: 0.1,
    walkA: "#EFDCAC", walkB: "#E0C894", roadA: "#917E6A", roadB: "#7B6B5B",
    grassA: "#7EA97F", grassB: "#5B8662" },
  // GOLDEN HOUR — long amber light
  { p: 0.56, skyTop: "#F4D2A0", skyMid: "#EDB285", skyLow: "#E59D74",
    sunX: 64, sunY: 46, sunO: 0.95, moonO: 0, stars: 0,
    cityColor: "#BB8C6C", daylight: 0.8, lamps: 0.32,
    walkA: "#EAD19F", walkB: "#D9BA86", roadA: "#84705C", roadB: "#6F5E51",
    grassA: "#75997B", grassB: "#55785C" },
  // LATE GOLDEN — sun sinking toward the rooftops
  { p: 0.66, skyTop: "#EFC08C", skyMid: "#E39E77", skyLow: "#D68A6C",
    sunX: 70, sunY: 58, sunO: 0.92, moonO: 0, stars: 0.04,
    cityColor: "#AE8068", daylight: 0.72, lamps: 0.45,
    walkA: "#E4C795", walkB: "#D1B07E", roadA: "#7D6A57", roadB: "#68584C",
    grassA: "#6F9376", grassB: "#507357" },
  // SUNSET — coral/violet, sun meeting the horizon
  { p: 0.76, skyTop: "#E39A72", skyMid: "#CE7E6C", skyLow: "#A96660",
    sunX: 78, sunY: 74, sunO: 0.62, moonO: 0.08, stars: 0.12,
    cityColor: "#8F6560", daylight: 0.58, lamps: 0.72,
    walkA: "#CBA98E", walkB: "#B5937B", roadA: "#6E5C51", roadB: "#59493F",
    grassA: "#61816C", grassB: "#46604E" },
  // DEEP SUNSET — ember sky, first stars
  { p: 0.82, skyTop: "#C67F6E", skyMid: "#9F6363", skyLow: "#74525C",
    sunX: 83, sunY: 90, sunO: 0.3, moonO: 0.25, stars: 0.3,
    cityColor: "#6E5055", daylight: 0.42, lamps: 0.88,
    walkA: "#B2927F", walkB: "#96796E", roadA: "#5D4E49", roadB: "#4A3F41",
    grassA: "#527061", grassB: "#3A5450" },
  // DUSK / LAMPS — purple-blue, town lights up (manifesto band)
  { p: 0.88, skyTop: "#5C4668", skyMid: "#453D5F", skyLow: "#333650",
    sunX: 87, sunY: 106, sunO: 0, moonO: 0.55, stars: 0.55,
    cityColor: "#3F3A55", daylight: 0.22, lamps: 1,
    walkA: "#8B7E86", walkB: "#6E6472", roadA: "#4A4456", roadB: "#3A3648",
    grassA: "#3E5464", grassB: "#2C3F50" },
  // EVENING — deep violet, windows bright (documentation turning point)
  { p: 0.93, skyTop: "#33405F", skyMid: "#26314e", skyLow: "#1b2440",
    sunX: 89, sunY: 118, sunO: 0, moonO: 0.8, stars: 0.8,
    cityColor: "#2b3350", daylight: 0.1, lamps: 1,
    walkA: "#6B7189", walkB: "#525a74", roadA: "#3d4560", roadB: "#2f3850",
    grassA: "#31445c", grassB: "#233349" },
  // NIGHT — deep navy, quiet autonomous town
  { p: 1, skyTop: "#182036", skyMid: "#121a2e", skyLow: "#0d1424",
    sunX: 92, sunY: 130, sunO: 0, moonO: 1, stars: 1,
    cityColor: "#212b43", daylight: 0, lamps: 1,
    walkA: "#565E74", walkB: "#414A60", roadA: "#333B52", roadB: "#272F44",
    grassA: "#283750", grassB: "#1c2a40" },
];

/* ── helpers ──────────────────────────────────────────────────────────── */

const hexToRgb = (h: string): [number, number, number] => {
  const s = h.replace("#", "");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
};

const mix = (a: string, b: string, t: number) => {
  const A = hexToRgb(a); const B = hexToRgb(b);
  return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(",")})`;
};

const L = (a: number, b: number, t: number) => a + (b - a) * t;

/** eased plateau: 0 before a-fade, 1 inside [a,b], eased edges */
function ramp(p: number, a: number, b: number, fade = 0.05): number {
  const ease = (t: number) => t * t * (3 - 2 * t);
  if (p <= a - fade) return 0;
  if (p >= b + fade) return 0;
  if (p < a) return ease((p - (a - fade)) / fade);
  if (p > b) return 1 - ease((p - b) / fade);
  return 1;
}

export interface WorldState { vars: Record<string, string | number>; chapterId: string }

/** Everything the renderer needs for time-of-day p ∈ [0,1]. */
export function sampleWorld(pRaw: number): WorldState {
  const p = Math.min(1, Math.max(0, pRaw));

  let i = 0;
  while (i < ATMOSPHERE.length - 2 && p > ATMOSPHERE[i + 1].p) i++;
  const A = ATMOSPHERE[i];
  const B = ATMOSPHERE[i + 1];
  const t = Math.min(1, Math.max(0, (p - A.p) / (B.p - A.p || 1)));

  const chapter = CHAPTERS.find((c) => p >= c.range[0] && p < c.range[1])
    ?? CHAPTERS[CHAPTERS.length - 1];

  const vars: Record<string, string | number> = {
    // atmosphere
    "--sky-t": mix(A.skyTop, B.skyTop, t),
    "--sky-m": mix(A.skyMid, B.skyMid, t),
    "--sky-l": mix(A.skyLow, B.skyLow, t),
    "--sun-x": `${L(A.sunX, B.sunX, t).toFixed(2)}%`,
    "--sun-y": `${L(A.sunY, B.sunY, t).toFixed(2)}%`,
    "--sun-o": L(A.sunO, B.sunO, t).toFixed(3),
    "--moon-o": L(A.moonO, B.moonO, t).toFixed(3),
    "--stars": L(A.stars, B.stars, t).toFixed(3),
    "--city-c": mix(A.cityColor, B.cityColor, t),
    "--daylight": L(A.daylight, B.daylight, t).toFixed(3),
    "--lamps": L(A.lamps, B.lamps, t).toFixed(3),
    "--walk-a": mix(A.walkA, B.walkA, t),
    "--walk-b": mix(A.walkB, B.walkB, t),
    "--road-a": mix(A.roadA, B.roadA, t),
    "--road-b": mix(A.roadB, B.roadB, t),
    "--grass-a": mix(A.grassA, B.grassA, t),
    "--grass-b": mix(A.grassB, B.grassB, t),

    // ── object behaviour (no characters — objects only) ──
    "--stock": ramp(p, 0.16, 0.82, 0.06).toFixed(3),     // parcels accumulate during business hours
    "--stock-extra": ramp(p, 0.58, 0.94).toFixed(3),     // momentum: top of the stack fills in
    "--store-open": p < 0.94 ? 1 : 0,                    // plaque flips to closed for the night

    // parallax (deliberately tiny — depth, not spectacle)
    "--par-city": (p * 1.0).toFixed(4),
    "--par-street": (p * 1.4).toFixed(4),
    "--par-front": (p * 2.2).toFixed(4),
  };

  return { vars, chapterId: chapter.id };
}

/* defaults so first paint is already a valid world */
export function defaultVars(): Record<string, string | number> {
  return sampleWorld(0.06).vars;
}
