# RazorGrowth AI — Full-Screen Merchant World Simulation
## Screen Audit & Dimension Specification

**Phase:** Audit & specification only. No implementation performed.
**Branch:** `main` (working tree left exactly as found — 67 pre-existing modified/untracked entries, unchanged).
**Date:** 2026-10-18

---

## 0. Method, provenance, and honesty statement

### What was measured, and how

All numbers labelled **MEASURED** were read from a live render of the real
application at `http://localhost:5199` (Vite dev server, `frontend/`, port 5199),
driven by the **already-installed Google Chrome** over the DevTools Protocol.
No new npm dependency was installed. Scripts were written to
`%LOCALAPPDATA%\Temp\opencode\rg-audit\` — **not** into the repository.

Viewport emulation used `Emulation.setDeviceMetricsOverride` with
`deviceScaleFactor: 1`, `force-color-profile: srgb`, scrollbars hidden.

| What | How it was read |
|---|---|
| Element geometry | `getBoundingClientRect()` on non-SVG elements |
| SVG layer transform | **`getScreenCTM()`** on the `<svg>` roots (a, d, e, f) — *not* `getBoundingClientRect()`, which returns ink boxes for SVG and gave wrong answers on the first pass; those wrong values were discarded and re-measured* |
| Section offsets | `getBoundingClientRect().top + window.scrollY` |
| Computed styles | `getComputedStyle()` |
| Scroll/atmosphere state | `:root` custom properties after a forced `load` re-dispatch |
| Screenshots | `Page.captureScreenshot`, plus a second pass with page chrome hidden to isolate the scene |

`window.innerWidth/innerHeight` equalled `documentElement.clientWidth/clientHeight`
at every target, so no scrollbar or zoom compensation was in play.

### What was *not* measured

- No Lighthouse / paint-timing / FPS profiling was run. All performance
  statements in §H are **CODE-DERIVED**, not profiled.
- No real touch device, no Safari/Firefox. Chrome only.
- No measurement of other routes (`/agents`, `/checkout`, …) — out of scope, and
  none of them mount `GlobalEnvironment`.

### Estimates vs measurements

- Everything in **§B** is **MEASURED**.
- The scene-occlusion percentages in **§F.6** are **COMPUTED** from measured
  element rectangles (method stated inline). They are arithmetic on real
  numbers, not browser-reported.
- Recommendations in **§C–§G** are **ENGINEERING JUDGEMENT** built on the
  measurements.

### The reference image

The repo contains no merchant-world raster reference. The closest match is
`frontend/src/assets/homepage.png` — a **1891 × 910 PNG screenshot of the current
homepage**, last modified 2026-10-16. It is **not referenced anywhere in the
source tree** (verified by grep across `frontend/`); it is a dead asset that
documents the current look: flat-vector cream/terracotta merchant street,
floating dark-chocolate nav bar in front, cream hero window.

> ⚠️ **Assumption flagged:** I treated that PNG as the "approved visual
> reference". If you attached a *different* merchant-world image in chat that
> never reached my context, re-send it and I will re-check §G against it. Every
> dimension in this report is derived from the live site, so §A–§F stand
> regardless; only §G's visual-direction language would change.

---

## A. Current implementation

### A.1 Rendering path (Home → background → nav)

```
main.tsx
  └─ App.tsx  <Routes> → <Route element={<PublicLayout/>}> → path="/" → <Home/>
       └─ PublicLayout.tsx
            ├─ <a class="skip-link">
            ├─ <SiteHeader/>            ← nav, OUTSIDE the env subtree
            ├─ <main id="main-content"> ← <Outlet/> → <Home/>
            │    └─ Home.tsx
            │         ├─ <div class="world-page">
            │         │    ├─ <GlobalEnvironment/>   ← the merchant world
            │         │    │    └─ useWorldScroll(true)
            │         │    │    └─ <div class="world-env" role="presentation">
            │         │    │         └─ <EnvironmentScene/>  (imports environment.css)
            │         │    │              └─ <div class="env-stack" aria-hidden>
            │         │    │                   Sky / Stars / Celestial / Clouds / City /
            │         │    │                   MerchantDistrict / StreetSurface / Commerce /
            │         │    │                   Delivery / Foreground   ← 10 layers
            │         │    ├─ <Hero/>
            │         │    └─ <div class="world-column">
            │         │         8 × <div class="readable"> + <Manifesto class="band-navy">
            │         └─ (end world-page)
            └─ <SiteFooter/>
```

**There is no raster background image on the Home page.** The "current ordinary
background illustration" is 100% inline SVG + CSS gradients, authored in
`frontend/src/features/public/Environment/`.

### A.2 The exact implementation responsible for day → night

**`frontend/src/features/public/Environment/useWorldScroll.ts`** — the engine.
This is the file the task asked to identify.

| Aspect | Implementation |
|---|---|
| Source event | native `window` `scroll`, registered `{ passive: true }` (line 128) |
| Read | `window.scrollY` → `timeAt(waypoints, y)` (lines 117–120) |
| Waypoints | measured live from section anchors: `y = max(lastY, sectionTop − 0.6 × innerHeight)` (`measureWaypoints`, lines 43–58) |
| Mapping | piecewise-linear `t` over 10 anchors (lines 24–35), `TRIGGER = 0.6` (line 38) |
| Easing | `requestAnimationFrame` loop, exponential approach `SMOOTHING = 0.14`/frame, stops at `EPSILON = 0.0006` (lines 19–20, 100–111) |
| Output | ~22 CSS custom properties written to `document.documentElement` (lines 92–94) |
| React re-renders | **zero** while scrolling (no `setState`; refs only) |
| Re-measure | `resize` + `load` listeners (lines 129, 131) |
| Reduced motion | `prefers-reduced-motion: reduce` → one static frame, **no listeners registered at all** (lines 86–90) |
| Output colour ramp | **`scenes.ts`** — `ATMOSPHERE[]` (10 keyframes) interpolated in `sampleWorld()` |
| Output layer composition | **`environment.css`** — `.env-*` classes consuming the variables |

`scenes.ts` also exports 7 narrative `CHAPTERS` (morning / day / warm / golden /
sunset / dusk / night) that are **label-only** — `chapterId` is computed and
returned but never consumed by any component. Documented, not rendered.

### A.3 Scene layer geometry (authoring space)

Every SVG layer uses the identical authoring box:

```
viewBox = "0 0 1440 810"          →  1440 × 810 design units, 16:9
```

| Layer | `preserveAspectRatio` | Parallax class | Max translate |
|---|---|---|---|
| Sky | — (CSS `<div>` gradient) | — | 0 |
| Stars | `xMidYMin slice` | *(none)* | 0 |
| Celestial (sun/moon) | — (CSS `<div>`s) | — | 0 |
| Clouds | `xMidYMin slice` | *(none, has `drift` keyframes)* | 0 |
| City | `xMidYMax slice` | `.env-city` | −10 px |
| MerchantDistrict | `xMidYMax slice` | `.env-district` | −14 px |
| Street | `xMidYMax slice` | `.env-street` | −14 px |
| Commerce | `xMidYMax slice` | `.env-commerce` | −14 px |
| Delivery | `xMidYMax slice` | `.env-delivery` | −14 px |
| Foreground | `xMidYMax slice` | `.env-foreground` | −24 px |

`--par-scale` = `1` / `0.5` (≤900 px) / `0.4` (≤768 px) / `0` (reduced motion).

**Measured landmark positions** in the 1440 × 810 design space (from source):

| Landmark | design y | % of height |
|---|---:|---:|
| Cloud band | 66–148 | 8.1–18.3% |
| Distant skyline tops | 366–446 | 45.2–55.1% |
| Horizon / verge top | **502** | **62.0%** |
| Building bases | 650 | 80.2% |
| Far sidewalk top | **648** | **80.0%** |
| Curb | 704 | 86.9% |
| Road top | 711 | 87.8% |
| Near sidewalk top | 760 | 93.8% |
| Hedge top | 782 | 96.5% |
| Frame bottom | 810 | 100% |
| Main storefront body | ~300–655 | 37–81% |
| Lamp posts | 568–756 | 70–93% |
| Delivery bike / scooter | 658–690 | 81–85% |

### A.4 Container, stacking, and positioning rules (verbatim)

`environment.css:9–15`
```css
.world-env { position: fixed; inset: 0; z-index: 0;
             overflow: hidden; pointer-events: none; }
```

`environment.css:18–28`
```css
.world-page   { position: relative; }             /* z-index: auto → NO stacking context */
.world-column { position: relative; z-index: 1;
                display: grid; grid-template-columns: minmax(0, 1fr);
                gap: clamp(28px, 5vw, 64px);
                padding: clamp(28px,5vw,64px) clamp(10px,2.5vw,28px) 0; }
```

`environment.css:51–55`
```css
.env-stack, .env-layer { position: absolute; inset: 0; }   /* ← no width/height */
```

`global.css:46–48`
```css
body { overflow-x: hidden; }
```

`components.css:315–322`
```css
.site-header { position: sticky; top: 0; z-index: var(--z-header /* 40 */);
               background: transparent;
               padding: 8px clamp(12px, 2vw, 28px); }
```

### A.5 Navigation (for §E cross-reference — not modified)

`.site-header__inner` — `min-height: 80px`, `max-width: 1840px`,
`background: #2B190F`, `border: 1px solid #4B3427`, `border-radius: 18px`,
`padding: 8px 20px`, `box-shadow: 0 14px 34px rgba(0,0,0,.35), 0 2px 8px rgba(0,0,0,.25)`.
Below 1200 px: `min-height: 68px`, `radius: 16px`. Below 1500 px: `padding: 8px 14px`.
`.navbar--home` is applied on `/` and **deliberately renders identically** to
other routes — `components.css:348–351` states there is intentionally no
transparent override.

### A.6 Sections below the hero

`Home.tsx:51–64` — inside `.world-column`, in order:
`HomeWhoItsFor`, `HowItWorks`, `ProductShowcase`, `Agents`, `Workflow`, `Demo`,
then `<Manifesto/>` (full-width `.band-navy`, navy `#10182b`), then `Docs`,
`FinalCTA`. 8 of the 9 are wrapped in `<div class="readable">`.

`environment.css:150–177` — **readability contract**: every sheet is *opaque*
(`background: var(--paper)`), `border-radius: 3px`, offset print shadow
`6px 6px 0 rgba(33,19,14,.08)`, and the comment is explicit:
*"solid printed-paper sheets … No blur, no translucency, no frosted veils."*

---

## B. Measured viewport matrix

**All values MEASURED.** `dpr = 1` throughout (Chrome emulation).

### B.1 Master matrix

| | Standard laptop | Full HD | Typical laptop | Large desktop | Tablet landscape | Tablet portrait | Mobile | Small mobile |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Viewport (CSS px)** | **1366 × 768** | **1920 × 1080** | **1440 × 900** | **2560 × 1440** | **1024 × 768** | **768 × 1024** | **390 × 844** | **360 × 800** |
| Aspect ratio | 1.7786 | 1.7778 | **1.6000** | 1.7778 | **1.3333** | **0.7500** | **0.4621** | **0.4500** |
| 1. CSS viewport W × H | 1366 × 768 | 1920 × 1080 | 1440 × 900 | 2560 × 1440 | 1024 × 768 | 768 × 1024 | 390 × 844 | 360 × 800 |
| 2. Nav block height | 96 | 96 | 96 | 96 | 84 | 84 | 84 | 84 |
| 3. Nav position | sticky, `top:0`, `z:40` | ← | ← | ← | ← | ← | ← | ← |
| 4. Hero container H (doc) | 710.1 | 880 | 828 | 880 | 706.5 | 723.3 | 772.1 | 808.2 |
| 5. Nav visible space behind | 96 (bar 8–88) | ← | ← | ← | 84 (bar 8–76) | ← | ← | ← |
| 6. `.world-env` canvas | 1366 × 768 | 1920 × 1080 | 1440 × 900 | 2560 × 1440 | 1024 × 768 | 768 × 1024 | 390 × 844 | 360 × 800 |
| 6b. **Actual SVG layer box** | 1366 × 768.4 | 1920 × 1080 | **1440 × 810** ⚠ | 2560 × 1440 | **1024 × 576** ⚠ | **768 × 432** ⚠ | **390 × 219.4** ⚠ | **360 × 202.5** ⚠ |
| 6c. Unpainted band at bottom | 0 | 0 | **90 px** | 0 | **192 px** | **592 px** | **624.6 px** | **597.5 px** |
| 7. Main content width | 1200 | 1200 | 1200 | 1200 | 1024 | 768 | 390 | 360 |
| 7b. `.readable` sheet W / x | 1304 / 31 | 1304 / 308 | 1304 / 68 | 1304 / 628 | 972.8 / 25.6 | 752 / 8 | 374 / 8 | 344 / 8 |
| 7c. Left+right scene gutter | 31 each | 308 each | 68 each | 628 each | 25.6 each | 8 each | 8 each | 8 each |
| 8. Document height | 7596 | 7824 | 7726 | 7824 | 7890 | 7450 | 9410 | 9744 |
| 8b. Scroll length (px) | 6828 | 6744 | 6826 | 6384 | 7122 | 6426 | 8566 | 8944 |
| 9. Horizontal overflow | none | none | none | none | none | none | none | none |
| 10. `body overflow-x` | hidden | hidden | hidden | hidden | hidden | hidden | hidden | hidden |
| 11. Breakpoint behaviour | full nav | full nav | full nav | full nav | hamburger | hamburger | hamburger | hamburger |
| 12. Nav overlays scene? | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** |

### B.2 Navigation bar box (MEASURED)

| Viewport | bar x | bar width | bar height | bar y-range | `--header-height` token |
|---|---:|---:|---:|---|---:|
| 1366 × 768 | 27.3 | 1311.4 | 80 | 8 → 88 | 96 px |
| 1920 × 1080 | 40 | 1840 | 80 | 8 → 88 | 96 px |
| 1440 × 900 | 28 | 1384 | 80 | 8 → 88 | 96 px |
| 2560 × 1440 | 360 | 1840 | 80 | 8 → 88 | 96 px |
| 1024 × 768 | 20.5 | 983.1 | 68 | 8 → 76 | 96 px ⚠ token says 96, actual 84 |
| 768 × 1024 | 15.4 | 737.3 | 68 | 8 → 76 | 96 px ⚠ |
| 390 × 844 | 12 | 366 | 68 | 8 → 76 | 96 px ⚠ |
| 360 × 800 | 12 | 336 | 68 | 8 → 76 | 96 px ⚠ |

⚠ `--header-height: 96px` (`tokens.css:88`) is correct for ≥1200 px but
**overstates the real 84 px** below 1200 px. This is the anchor for
`scroll-margin-top` (`global.css:157–160`) and for the mobile panel's
`max-height`, so section headings currently land 12 px lower than needed on
mobile. Worth a separate ticket; not a simulation blocker.

### B.3 Scene landmarks in real viewport pixels (MEASURED via `getScreenCTM()`)

Current 1440 × 810 / `xMidYMax slice` mapping:

| Viewport | scale | design px visible | verge (62.0%) | sidewalk (80.0%) | curb (86.9%) | road (87.8%) | near-walk (93.8%) | hedge (96.5%) | frame bottom |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1366 × 768 | 0.9486 | 1440 × 809.6 | 476.2 | 614.7 | 667.8 | 674.5 | 720.9 | 741.8 | 768.4 |
| 1920 × 1080 | 1.3333 | 1440 × 810 | 669.3 | 864 | 938.7 | 948 | 1013.3 | 1042.7 | 1080 |
| 1440 × 900 | 1.0000 | 1440 × **810 of 900** | 502 | 648 | 704 | 711 | 760 | 782 | **810** ⚠ |
| 2560 × 1440 | 1.7778 | 1440 × 810 | 892.4 | 1152 | 1251.6 | 1264 | 1351.1 | 1390.2 | 1440 |
| 1024 × 768 | 0.7111 | 1440 × 576 of 768 | 357 | 460.8 | 500.6 | 505.6 | 540.4 | 556.1 | **576** ⚠ |
| 768 × 1024 | 0.5333 | 1440 × 432 of 1024 | 267.7 | 345.6 | 375.5 | 379.2 | 405.3 | 417.1 | **432** ⚠ |
| 390 × 844 | 0.2708 | 1440 × **219.4 of 844** | 136 | 175.5 | 190.7 | 192.6 | 205.8 | 211.8 | **219.4** ⚠ |
| 360 × 800 | 0.2500 | 1440 × **202.5 of 800** | 125.5 | 162 | 176 | 177.8 | 190 | 195.5 | **202.5** ⚠ |

### B.4 🔴 Root-cause finding — the SVG layers do not fill the viewport

`.env-layer { position: absolute; inset: 0; }` with **no `width`/`height`** and
**no `preserveAspectRatio` override on the box**. An `<svg>` with a `viewBox` is a
*replaced element* with an intrinsic aspect ratio. With `left:0; right:0; top:0;
bottom:0; width:auto; height:auto`, the width resolves to the inset width, but
`height:auto` resolves to the **intrinsic** height — the box collapses to
`width ÷ (1440/810)`. `bottom` is then over-constrained and ignored.

Measured proof — `clientWidth × clientHeight` of `.env-street`:

```
1440 × 900   →  1440 × 810     (90 px of viewport never painted)
1024 × 768   →  1024 × 576     (192 px never painted)
 768 × 1024  →   768 × 432     (592 px never painted)
 390 × 844   →   390 × 219.4   (624.6 px never painted)
 360 × 800   →   360 × 202.5   (597.5 px never painted)
```

It only looks correct at 1366 × 768, 1920 × 1080 and 2560 × 1440, where
`width ÷ 1.7778` happens to be ≥ viewport height.

The visible symptom is severe: **on mobile the entire merchant street is
compressed into the top 219 px of an 844 px screen** and the remaining 625 px is
nothing but the `.env-sky` CSS gradient. The scene is effectively invisible at
exactly the breakpoints where it matters most. `.env-sky` survives because it is
a plain `<div>`, not an SVG — which is why the collapsed area still shows *a*
colour and the failure is easy to mistake for "the scene is just sparse".

> This is the single highest-value thing to fix, and the fix (`.env-layer
> { width: 100%; height: 100%; }`) must land **before or with** any new
> artwork, or the artwork will be cropped the same wrong way.

### B.5 🔴 Second finding — parallax lifts layers off the bottom edge

`.env-* { transform: translate3d(0, calc(var(--par-*) * var(--par-scale) * -Npx), 0) }`
moves layers **up** with scroll. Measured layer bottoms at full scroll
(`p = 1`, `--par-scale: 1`):

| Layer | translate | screen bottom @1920×1080 | gap to viewport bottom |
|---|---:|---:|---:|
| `.env-sky` | 0 | 1080 | 0 |
| `.env-stars` | 0 | 1080 | 0 |
| `.env-city` | −10.0 | 1070.0 | −10.0 |
| `.env-district` | −19.6 | 1060.4 | −19.6 |
| `.env-street` | −19.6 | 1060.4 | −19.6 |
| `.env-foreground` | **−52.8** | 1027.2 | **−52.8** |

So at night, a **~20–53 px strip along the bottom of the viewport** falls back
through to `.env-sky`. Combined with B.4 this is a compounding error.
**Any replacement artwork must be over-scanned by ≥ 6% bottom margin** (or the
parallax amplitudes reduced) so this seam can never appear.

---

## C. Recommended master artwork specification

### C.1 Verdict on architecture: **layered, not a single image**

A single full-bleed raster is **not viable**, and the measurements prove why.

`.world-env` is `position: fixed; inset: 0`, so the artwork must `cover` *any*
viewport. Target aspects span **0.450 → 1.779**, a 3.95× range. With `cover` +
centre anchor on a 16:9 master:

| Viewport | aspect | horizontal design-px cropped | survives? |
|---|---:|---:|---|
| 2560 × 1440 | 1.778 | 0 | ✅ |
| 1920 × 1080 | 1.778 | 0 | ✅ |
| 1366 × 768 | 1.779 | 0 | ✅ |
| 1440 × 900 | 1.600 | 0 (crops 90 px of sky instead) | ✅ |
| 1024 × 768 | 1.333 | 360 (25%, 180 each side) | ✅ |
| 768 × 1024 | 0.750 | 832 (57.8%, 416 each side) | ❌ storefront lost |
| 390 × 844 | 0.462 | 1065 (74.0%, 533 each side) | ❌ |
| 360 × 800 | 0.450 | 1075 (74.7%, 538 each side) | ❌ |

At 0.45 aspect you keep the **central 25%** of the artwork. The storefront, the
hero subject and every sign are gone. This is exactly the "do not stretch /
crop desktop artwork onto mobile" failure the brief warns about.

**Recommendation: keep the existing layered architecture and swap the vector
geometry for raster layers.** The engine (`useWorldScroll` → CSS vars) is sound
and orthogonal to the art; only `layers/*.tsx` need replacing. Benefits:

- Geometry stays pixel-identical across time-of-day → **no positional jumping**
  (a hard requirement in Phase 5).
- `mix-blend-mode` / `opacity` driven by the existing `--lamps`, `--daylight`,
  `--sky-*` vars do the lighting for free.
- Each layer can be sized/tuned independently per breakpoint.

### C.2 Proposed layer stack

| # | Layer | Asset | Role | Day→Night treatment |
|---|---|---|---|---|
| 1 | Sky | **keep CSS gradient** | `--sky-t/m/l` | already continuous; costs nothing |
| 2 | Stars | keep SVG or CSS radial-gradients | `--stars`, `--moon-o` | already continuous |
| 3 | Celestial | **keep CSS `<div>`**s | `--sun-x/y/o` | already continuous |
| 4 | Clouds | raster 1× strip, transparent | soft depth | tint + opacity via `--daylight` |
| 5 | Distant city | **raster alpha**, wide strip | skyline silhouette | tint via `--city-c`, `opacity` |
| 6 | Mid district + verge | **raster alpha** | shop row, grass plane | `--grass-a/b`, lamp glow |
| 7 | Street surface | **raster alpha** | sidewalk, curb, road | `--walk-a/b`, `--road-a/b` |
| 8 | Commerce | **raster alpha** | storefront, parcels, signage | **`--lamps`** drives shop glow |
| 9 | Delivery | keep SVG or raster | bicycle, scooter | static |
| 10 | Foreground | **raster alpha** | near walk, lamps, hedge, bench | **`--lamps`** drives cones |
| **11** | **Night lights plate** | **NEW — raster, transparent** | lit windows, signs, streetlights, headlights, spill | `opacity: var(--lamps)` |

**Layers 1–4 and 9 should not be regenerated.** They are already continuous,
free, resolution-independent, and driven by live CSS variables. Regenerating them
as raster buys nothing and costs payload. Spend the generation budget on
layers **5–8, 10 and 11**.

### C.3 Master landscape scene — exact dimensions

| Property | Value |
|---|---|
| **Master canvas** | **2560 × 1440 px** |
| Aspect ratio | **16 : 9** (1.7778) |
| Relationship to existing design space | exactly `1440 × 810 × 1.7778` — the current authoring grid, upscaled |
| Why not larger | 2560 × 1440 is the **largest target viewport**; beyond that you are paying for pixels that are then occluded (see §F.6) |
| **Minimum practical resolution** | **1920 × 1080** (1×) — below this, 2560-wide displays and 1440p laptops show softness |
| **2× / retina asset** | **5120 × 2880** — AVIF/WebP + JPEG fallback |
| Generator output needed | ≥ **2048 × 1152** (2K 16:9). If your Google workflow can emit 4K, generate 4096 × 2304 and **downscale** — downscaling beats upscaling for photographic realism |
| Format | **AVIF** (primary) → **WebP** → **JPEG q82** fallback |
| Colour | sRGB. Layer alphas as **WebP lossless / PNG-8** where flat colour matters |
| Full-bleed? | **Yes** — edge to edge, no gutters, no rounded frame, no baked shadow |

### C.4 Geometry contract — the master MUST match these landmarks

If the artwork is authored at 2560 × 1440, every existing landmark must sit at
`(1440/810) × design_y`, so the current layer maths and parallax amplitudes
keep working unchanged:

| Landmark | design y (of 810) | **master y (of 1440)** | % |
|---|---:|---:|---:|
| Sky / nav band ends | 0 → 180 | **0 → 320** | 0–22.2% (nav safe, see C.5) |
| Cloud band | 66–148 | 117–263 | 8.1–18.3% |
| Distant skyline tops | 366–446 | 651–793 | 45.2–55.1% |
| **Horizon / verge top** | **502** | **893** | **62.0%** |
| Building bases | 650 | 1156 | 80.2% |
| **Far sidewalk top** | **648** | **1152** | **80.0%** |
| **Curb** | **704** | **1252** | **86.9%** |
| **Road top** | **711** | **1264** | **87.8%** |
| Near sidewalk top | 760 | 1351 | 93.8% |
| Hedge top | 782 | 1390 | 96.5% |
| Frame bottom | 810 | 1440 | 100% |
| Main storefront body | 300–655 | 533–1164 | 37–81% |
| Lamp posts | 568–756 | 1010–1344 | 70–93% |

**Non-negotiable:** the horizon at **y = 893** and the sidewalk at **y = 1152**.
If the generated artwork's horizon drifts, every layer mis-registers and the
road will cut through the buildings — the exact defect
`EnvironmentScene.tsx:14–20` was written to prevent.

### C.5 Safe areas (derived from measured nav geometry)

The nav bar's height in screen px, converted into master px at each target's
`cover` scale:

| Viewport | cover scale | nav band (screen px) | **nav band (master px)** |
|---|---:|---:|---:|
| 1366 × 768 | 0.5336 | 96 | **180** |
| 1440 × 900 | 0.6250 | 96 | 154 |
| 1920 × 1080 | 0.7500 | 96 | 128 |
| 2560 × 1440 | 1.0000 | 96 | 96 |
| 1024 × 768 | 0.5333 | 84 | 158 |

### 🔴 **NAV SAFE BAND = top 180 px of the 1440-tall master (12.5%)**

- No signage, no text, no logos, no key focal detail, no high-contrast edges.
- This must be **soft, low-frequency sky** — it is also the region that gets
  cropped first on every non-16:9 viewport.
- Below 1200 px the bar shrinks to 68 px, so 180 px is comfortably conservative.
- Horizontally the bar spans **2.0% → 98.0%** of the width at 1366/1440/1024 px
  and **14.1% → 85.9%** at 2560 px — i.e. effectively full width. Treat the
  whole 12.5% band as nav, not just the middle.

### C.6 Safe areas — bottom and sides

- **Bottom over-scan: ≥ 60 px (4.2%) of master height is expendable.** §B.5
  proves parallax lifts the foreground layer 52.8 px at 1920 × 1080. Keep the
  lowest 60 px free of anything you need to read (no signage, no kerb markings).
- **Bottom 3.5% (y 1390–1440)** = hedge / kerb zone — deliberately busy texture,
  safe to crop.
- **Horizontal:** no fixed safe margin is required for the *landscape* master
  because 1024 × 768 is the narrowest landscape target and it only crops 180
  px (12.5%) per side. Put nothing essential within **x < 200 px** or
  **x > 2360 px** of the 2560-wide master.

### C.7 Where foreground content overlays the background

Measured overlay zones at 1440 × 900 (the archetype; other viewports in §B.1):

| Zone | Measured extent | Scene visibility there |
|---|---|---|
| Nav bar | x 28–1412, y 8–88 | **0% — fully covered** |
| Hero main window | ≈ x 160–880, y ≈ 180–750 | 0% |
| Hero floating windows | ≈ x 810–1320 (3 cards) | 0% |
| Hero top strip | y 96–180, full width | **100% visible** |
| Hero right margin | x 1320–1440 | visible (narrow) |
| Hero bottom strip | y 750–924 | visible |
| `.readable` sheets | x 68–1372 (1304 wide), 8 of 9 sections | 0% |
| Inter-sheet gaps | 64 px tall × full width | visible |
| Side gutters below hero | 68 px each side | visible |

### C.8 Scaling / cropping behaviour to specify

| Breakpoint | Technique |
|---|---|
| ≥ 1200 px (desktop) | `background-size: cover; background-position: 50% 100%;` (bottom-anchored) |
| 900–1199 px (small tablet landscape) | identical; cover crops 25% of width — safe per C.6 |
| ≤ 899 px and aspect ≥ 1.0 (tablet portrait) | **switch to the portrait master**, do not crop 16:9 |
| ≤ 767 px or aspect < 1.0 | portrait master, `background-position: 50% 78%` |

**`object-fit: cover` + `object-position: 50% 100%`** if implemented with
`<img>`; **`background-size: cover` + `background-position: center bottom`** if
with `background-image`. Bottom anchor is essential — it keeps the horizon and
sidewalk registered while letting expendable sky crop from the top.

---

## D. Responsive adaptation strategy

### D.1 The rule

**Do not stretch. Do not centre-crop 16:9 onto a portrait viewport. Use a second
artwork.**

`cover` preserves aspect ratio (no stretch) but destroys composition below
~1.0 aspect. At 0.45 aspect you retain 25% of the width. The storefront — the
entire point of the scene — is outside the crop at every mobile target.

### D.2 Portrait master — exact dimensions

| Property | Value |
|---|---|
| **Portrait canvas** | **1170 × 2532 px** |
| Aspect | 9 : 19.42 (0.4621) — exactly 390 × 844 @ 3× |
| Coverage | 390 × 844 (0.4621) ✅ · 360 × 800 (0.4500) ✅ near-exact · 768 × 1024 (0.7500) via horizontal crop |
| Minimum practical | 780 × 1688 (390 × 844 @ 2×) |
| Generator output needed | ≥ **1024 × 2048** |
| Format | AVIF → WebP → JPEG |
| Nav safe band | top **260 px** (84 screen px ÷ 0.3231 scale → 260 master px, 10.3%) |
| Horizon | **62.0% → y = 1570 px** (keep the same world geometry) |
| Far sidewalk | **80.0% → y = 2026 px** |
| Bottom over-scan | ≥ **80 px** |
| Anchor | `background-position: 50% 78%` |

The portrait master is a **recomposition, not a crop** — same street, same
buildings, same storefront, camera pulled back and rotated to a taller framing
so the geometry reads vertically. It must be generated as its own composition
(the tool cannot reliably re-frame a 16:9 input), but it must obey the *same*
geometry contract at its own scale so the layer stack behaves identically.

### D.3 Per-category plan

| Category | Viewports | Artwork | Notes |
|---|---|---|---|
| **Large desktop** | 2560 × 1440 | 2560 × 1440 @1×, 5120 × 2880 @2× | 1:1 with master; no crop |
| **Full HD / laptop** | 1920 × 1080, 1440 × 900, 1366 × 768 | same asset, downscaled | 1440 × 900 crops 90 px of sky from top — inside nav band, invisible |
| **Tablet landscape** | 1024 × 768 | same asset | crops 180 px per side; storefront centred survives |
| **Tablet portrait** | 768 × 1024 | portrait master, horizontal crop | aspect 0.75 vs 0.462 → crops 617 px (26%) horizontally, symmetric, storefront centred |
| **Mobile / small** | 390 × 844, 360 × 800 | portrait master, near 1:1 | no crop at all |

**Minimum asset set: 4 files.**

```
scene-landscape-2560x1440.avif     (1× desktop master)
scene-landscape-5120x2880.avif     (2×, optional)
scene-portrait-1170x2532.avif      (mobile master)
scene-lights-{landscape,portrait}.webp   (transparent night plates)
```

### D.4 Layered repositioning as the fallback

If a portrait generation proves unreliable, the alternative is **not** cropping:
scale the landscape master to `background-size: auto 100%` on portrait so the
**full width** fits, let `.env-sky` paint above and a `.env-ground` strip below.
The scene then occupies a horizontal band in the lower third, sky above. This is
honest and non-destructive, but it wastes ~50% of a tall phone screen on
gradient. **Prefer the portrait master.**

---

## E. Navigation layering specification

### E.1 Current state — Phase 3 is already ~80% satisfied

Measured, not assumed:

- `.world-env` is `position: fixed; inset: 0; z-index: 0` — it spans the full
  viewport at all 8 targets, **including behind the nav**.
- `.site-header` is `position: sticky; top: 0; z-index: 40;
  background: transparent` — the header *shell* is transparent; only the inner
  `.site-header__inner` bar (80/68 px, `#2B190F`, radius 18/16, drop shadow) is
  opaque.
- `.world-page` is `position: relative` with `z-index: auto`, so it creates
  **no stacking context**. `.world-column { z-index: 1 }` and
  `.hero__stage { z-index: 1 }` therefore compete directly with `.world-env`
  (`z: 0`) and `.site-header` (`z: 40`) **in the root stacking context**.
- Result: **scene (0) → page content (1) → nav (40)**. The nav already floats in
  front of the scene. Verified in screenshots at all 8 viewports.
- `.site-footer { position: relative; z-index: 1 }` also already sits above the
  fixed world.
- `components.css:348–351` confirms `navbar--home` is intentionally identical to
  the default dark-brown bar — there is no transparent variant to conflict with.

**No navigation change is required to satisfy the overlay requirement.** The
work is entirely on the scene side.

### E.2 Stacking context map (as measured)

```
root stacking context
├── z 0    .world-env        position:fixed  inset:0        ← scene
│            └── .env-stack   position:absolute inset:0
│                 └── .env-layer × 10   (siblings, DOM order = paint order)
├── z 1    .hero__stage      position:relative
├── z 1    .world-column     position:relative
│            └── .readable    position:relative  z-index:1 (children)
├── z 1    .site-footer      position:relative
└── z 40   .site-header      position:sticky                  ← nav, on top
             ├── .site-header__inner  (1840 max, the visible bar)
             └── .mobile-menu  z-index: 39 (--z-mobile-menu)
```

### E.3 Required z-index allocation going forward

| Layer | z-index | position |
|---|---:|---|
| `.world-env` + all scene layers | **0** | `fixed` |
| page content (`.hero__stage`, `.world-column`, `.site-footer`) | 1 | `relative` |
| `.site-header` | **40** (unchanged `--z-header`) | `sticky` (unchanged) |
| `.mobile-menu` panel | 39 (unchanged `--z-mobile-menu`) | `absolute` |
| AI Team dropdown / profile menu | 200 (unchanged) | `absolute` |

**Rules:**
1. **Do not raise `.world-env` above 0** and **do not introduce a stacking
   context on `.world-page`** (e.g. `transform`, `filter`, `opacity < 1`,
   `isolation`, `will-change`, `contain: paint`). Any of those would trap
   `.world-column`'s `z-index: 1` *inside* `.world-page`, and since
   `.world-page` is `position: relative; z-index: auto`, it would then paint
   **below** `.world-env` and the entire page would be buried under the scene.
   This is the #1 implementation trap.
2. **Do not give `.env-layer` a z-index.** Depth is already expressed by DOM
   order. Adding `z-index` inside `.env-stack` is fine (they are siblings in the
   same context), but there is no reason to.
3. **The night-lights plate must be the last child of `.env-stack`** so it
   composites above all geometry, and must carry
   `pointer-events: none; mix-blend-mode: screen;` (or `plus-lighter`) so it
   adds light rather than painting over.

### E.4 Keeping the nav legible at every hour

The nav bar is `#2B190F` with `#FFF3E1` text and `#D65A38` accents. Against the
existing atmosphere ramp that is always legible, because the ramp never produces
anything near `#2B190F` except at deep night (`--sky-t: #182036`, `--city-c:
#212b43` at `p = 1`) — where contrast is *highest*, not lowest.

Concrete guidance for the new artwork:

- **Nav band (top 180 px of master) must stay mid-to-high luminance and
  low-contrast.** Against the brightest morning sky (`#F4DDB6`, luminance ≈ 0.85)
  the `#2B190F` bar reads perfectly. Do not put a bright cloud edge or a
  highlight there.
- **Do not bake any drop shadow or dark gradient into the top 180 px** — the bar
  already carries `0 14px 34px rgba(0,0,0,.35)`. A second shadow doubles up and
  muddies the bar edge against the sky.
- **No scrim behind the nav.** The bar is opaque and rounded; it does not need
  one. Adding a scrim would darken the sky through the entire day and fight the
  `--sky-*` ramp.
- **Rounded corners matter.** `border-radius: 18px` (16px < 1200 px) means the
  corners of the nav band show sky. Keep those four corner regions of the master
  clean and low-frequency — no hard building edges or signs at the extreme top
  left/right.

### E.5 Preventing flicker / disappearance

| Risk | Mitigation |
|---|---|
| Nav hidden behind scene | Enforce rule E.3.1; add a regression check that `.world-page` computes `z-index: auto` and has no `transform`/`filter`/`opacity` |
| Nav flicker on scroll | Nav does **not** re-render on scroll (`useWorldScroll` uses refs). Do not add scroll-driven React state to `SiteHeader`. |
| Nav flicker during mobile panel | `SiteHeader` sets `document.body.style.overflow = "hidden"` while open (lines 321–327). A body overflow change can relayout `100dvh` and shift the sticky header by the scrollbar delta. Add `scrollbar-gutter: stable` if flicker is observed. |
| Nav overlapping content | `section[id], div[id] { scroll-margin-top: calc(var(--header-height) + 16px) }` (`global.css:157–160`) already reserves space. Note the token is 96 px but the real bar is 84 px below 1200 px — a 12 px over-reserve on mobile, harmless. |
| Dropdown clipped by the scene | `.ai-menu` / `.rg-profile__menu` use `z-index: 200` inside `.site-header` (`z: 40`) — no stacking context is created by `position: relative` + `z-index: 40`? **`z-index: 40` on a positioned element DOES create a stacking context**, so the dropdowns are contained within the header's context at level 40. They still paint above `.world-env` (0). ✅ No fix needed. |

---

## F. Day-to-night transition specification

### F.1 Mechanism (unchanged, and it should stay unchanged)

`useWorldScroll` is correct and performant. **Do not rewrite it.** Specifically
preserve:

- native scroll + `{ passive: true }` — no scroll hijacking
- section-anchor waypoints, **not** raw scroll fraction (see F.4)
- the rAF ease (`0.14` / `ε 0.0006`) and its self-stopping loop
- zero React re-renders while scrolling
- `resize` + `load` re-measure
- `prefers-reduced-motion` → single static frame, no listeners

### F.2 Scene layers and which variable drives each

| Layer | Day→Night driver | Continuity guarantee |
|---|---|---|
| Sky gradient | `--sky-t` / `--sky-m` / `--sky-l` (3-stop `linear-gradient`) | continuous; no geometry |
| Stars | `--stars` opacity + `twinkle` keyframes | continuous |
| Sun | `--sun-x` (24→92%), `--sun-y` (58→130%), `--sun-o` (0.9→0) | **moves off-frame below y = 130%** |
| Moon | `--moon-o` (0.12→1) | continuous |
| Clouds | `opacity: calc(0.55 + var(--daylight) * 0.35)` | continuous |
| Distant city | `--city-c` fill + `--lamps` window glow | continuous |
| Mid district | `--grass-a/b`, `--lamps` | continuous |
| Street | `--walk-a/b`, `--road-a/b`, centre-dash `opacity: calc(0.14 + var(--daylight) * 0.16)` | continuous |
| Commerce | `--stock`, `--stock-extra`, `--store-open`, `--lamps` | **discrete** at `p ≥ 0.94` (sign flips to closed) |
| Delivery | static | — |
| Foreground | `--lamps` on lamp bulbs + cones | continuous |
| **Night plate (new)** | `opacity: var(--lamps)` | continuous |

### F.3 Transition boundaries — measured

`t` is the atmosphere timeline position. Chapter ranges and keyframe positions
are both in `scenes.ts`; anchor→`t` mapping is in `useWorldScroll`.

| Chapter | `t` range | Atmosphere keyframes inside |
|---|---|---|
| morning — "Opening up" | 0.00 – 0.22 | `p = 0.00` |
| day — "Business as usual" | 0.22 – 0.40 | `p = 0.24` |
| warm — "Warm afternoon" | 0.40 – 0.55 | `p = 0.42` |
| golden — "Golden hour" | 0.55 – 0.66 | `p = 0.56` |
| sunset — "Sunset" | 0.66 – 0.84 | `p = 0.66`, `0.76`, `0.82` |
| dusk — "Lights come on" | 0.84 – 0.93 | `p = 0.88` |
| night — "Night operations" | 0.93 – 1.00 | `p = 0.93`, `1.00` |

Measured scroll trigger per anchor (`scrollY` at which `t` reaches the anchor
value), from live section offsets:

| Anchor | `t` | 1366×768 | 1920×1080 | 1440×900 | 2560×1440 | 1024×768 | 768×1024 | 390×844 | 360×800 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| home | 0.02 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| who-its-for | 0.24 | 458.3 | 441 | 497 | 225 | 422.9 | 244.6 | 394.7 | 457.2 |
| how-it-works | 0.42 | 1484.4 | 1527.7 | 1529.2 | 1311.7 | 1821.3 | 1610.1 | 2736.7 | 2862.6 |
| product | 0.56 | 2524.9 | 2579.1 | 2575.9 | 2363.1 | 2895.3 | 2677.1 | 4000.4 | 4172.4 |
| agents | 0.66 | 3176.8 | 3231 | 3227.8 | 3015 | 3645.7 | 3379.9 | 4916.3 | 5132.8 |
| workflow | 0.76 | 3823.8 | 3878 | 3874.8 | 3662 | 4480.2 | 4109.1 | 5822.9 | 6039.4 |
| demo | 0.82 | 4433.2 | 4487.4 | 4484.2 | 4271.4 | 5027.9 | 4585.9 | 6451.4 | 6690.3 |
| manifesto | 0.88 | 5046.1 | 5100.3 | 5097 | 4884.3 | 5579.1 | 5042.1 | 6966.6 | 7230.8 |
| docs | 0.93 | 5714 | 5768.2 | 5765 | 5552.2 | 6143.3 | 5658.8 | 7590.2 | 7905.1 |
| cta | 1.00 | 6489.1 | 6543.3 | 6540.1 | **6327.3** | 6856.7 | 6286.6 | 8298.9 | 8636.2 |
| *max scroll* | — | 6828 | 6744 | 6826 | **6384** | 7122 | 6426 | 8566 | 8944 |
| *head-room* | — | 339 | 201 | 286 | **57** ⚠ | 265 | 139 | 267 | 308 |

⚠ **At 2560 × 1440 the night state (`t = 1`) is reached only 57 px before the
bottom of the scroll** — full night barely lands. Cause: the document height is
width-capped (7824 px, identical to 1920), so a taller viewport compresses the
whole scroll. If night must be fully realised on large displays, either add a
taller closing section or remap the `cta` anchor below 1.0 (e.g. `0.97`) so the
ramp completes earlier. Flag for decision; not a blocker.

### F.4 🔴 Time-of-day is NOT proportional to scroll

Measured `--daylight` at identical scroll *fractions*:

| Viewport | `--daylight` @ 0% | @ 50% | @ 100% | who-its-for height |
|---|---:|---:|---:|---:|
| 1920 × 1080 | 0.850 | **0.689** | 0.000 | 924.7 |
| 1440 × 900 | 0.850 | **0.680** | 0.000 | 870.2 |
| 390 × 844 | 0.850 | **0.775** | 0.000 | **2272** |

At half-scroll, desktop is already deep golden hour while **mobile is still
morning**. This is by design — the anchor mapping ties time to *narrative
beats*, not pixels — but it means **the day→night curve differs by up to ~0.10
`daylight` units between breakpoints at the same scroll position**. Any
artwork must be authored so that it reads correctly across the whole
0.85 → 0.00 range in *any* of these curves. Do not design key frames against a
single viewport's curve.

### F.5 Recommended transition model — how to keep geometry from jumping

**Rule 1 — one geometry plate, two lighting states.** Never swap between
separate day/afternoon/sunset/night *scene* images. Four full frames at
5120 × 2880 is ~4 MB before compression, guarantees registration error, and is
exactly what causes buildings to "jump". Instead:

- **Base plate**: the neutral/daylight artwork. Static. Never changes.
- **Night plate**: transparent, identical camera and geometry, containing only
  emissive content (lit windows, signs, streetlamp bulbs and cones, shop spill,
  car headlights, road reflections). Cross-faded with
  `opacity: var(--lamps)`.
- **Ambient tint**: a flat `mix-blend-mode: multiply` (or `color`) layer whose
  colour is `var(--sky-m)` and whose opacity is `calc(1 - var(--daylight))`.
  This is what turns warm daylight into cool blue night without touching geometry.
- **Sun/moon**: keep the existing CSS `<div>`s. They are free and continuous.

> **Generation discipline:** the night plate must be produced from the base plate
> by **image-to-image / inpainting on the base image itself** — never generated
> independently from the same text prompt. Two independent generations of the
> same prompt will not register. This is the single most important instruction
> in the whole brief.

**Rule 2 — never key geometry to time.** The CSS variables that drive *position*
are only `--sun-x/y`. Buildings, road, sidewalk, hedge, lamps, storefront and
delivery props must reference **no time-dependent variable at all**. The existing
code already satisfies this; preserve it.

**Rule 3 — parallax must not expose an edge.** Before wiring new rasters:
- fix `.env-layer { width: 100%; height: 100%; }` (§B.4), and
- give every parallaxed layer ≥ 6% bottom over-scan (§C.6), or reduce the
  amplitudes.

**Rule 4 — sub-pixel shimmer.** `--sun-x/y` are written every rAF frame as
`toFixed(2)` percentages. At 2560 px that is a sub-pixel position change per
frame, which can shimmer. Round to whole pixels, or write them only when the
value changes by ≥ 1 px.

### F.6 🔴 How much of the artwork will actually be seen

**COMPUTED** from measured element rectangles (opaque `.readable` sheets at
measured width × measured section height, plus measured hero window areas;
divided by `viewport width × documentElement.scrollHeight`). Not
browser-reported.

| Viewport | Sheets covered | Hero covered | **Total occluded** | **Scene visible** |
|---|---:|---:|---:|---:|
| 2560 × 1440 | 38.1% | ~3.1% | ~41% | **~59%** |
| 1920 × 1080 | 46.8% | ~4.2% | ~51% | **~49%** |
| 1440 × 900 | 62.5% | ~5.2% | ~68% | **~32%** |
| 1366 × 768 | 66.5% | ~4.9% | ~71% | **~29%** |
| 1024 × 768 | 70.1% | ~6.2% | ~76% | **~24%** |
| 768 × 1024 | 76.0% | ~9.5% | ~86% | **~14%** |
| 390 × 844 | 79.1% | ~8.1% | ~87% | **~13%** |
| 360 × 800 | 78.8% | ~8.2% | ~87% | **~13%** |

This follows directly from `environment.css:150–168` ("solid printed-paper
sheets … No blur, no translucency"), which is an intentional, documented
readability decision.

> **Design implication you must decide before generating.** A photoreal,
> immersive merchant world will be **~87% occluded on mobile and ~68% on a
> typical laptop**. Whatever you generate, the *visible* zones are:
> 1. the hero band (top strip, right margin, bottom strip),
> 2. the side gutters (8 px on mobile — effectively nothing),
> 3. the 20–64 px inter-sheet gaps.
>
> **Therefore: put the visual payoff in the hero band and the inter-sheet gaps.**
> On mobile, if you want the scene to actually register, one of these has to
> give — most likely reducing `.readable` sheet opacity or height. I have **not**
> changed anything; this is a decision for you.

---

## G. Google AI artwork-generation specification

> Copy-paste brief. Dimensions, landmark positions and safe areas are derived
> from §B measurements, so they are exact for this site.

### G.1 Master generation prompt

```
A wide, calm, photoreal 3D-rendered illustration of a single Indian neighbourhood
merchant street at eye level, viewed straight on from across the road — like a
high-end matte-painting matte for a premium SaaS landing page. One continuous
street; nothing else.

CAMERA AND FRAMING
- Straight-on, orthographic-feeling perspective, eye level about 2 m, no tilt.
- Strictly horizontal composition. The street runs left to right across the
  full width. Nothing converges toward a vanishing point.
- Depth is expressed ONLY as stacked horizontal bands, never as diagonal
  perspective lines.

EXACT FRAME GEOMETRY (do not deviate — the layer stack registers on these)
- Canvas 2560 x 1440 px (16:9).
- Sky occupies y = 0 to 893. Soft, low-frequency, uncluttered.
- The horizon line (top of the grass verge) sits at exactly y = 893 (62.0% of
  the canvas height).
- Buildings stand ON the horizon: their bases end at y = 1152. Buildings must
  never extend below y = 1152.
- Far sidewalk / pavement band: y = 1152 to 1252.
- Kerb / curb edge: y = 1252 to 1264.
- Road: y = 1264 to 1351.
- Near pavement: y = 1351 to 1390.
- Hedge / low planting at the very front: y = 1390 to 1440.
- The road must NOT touch or overlap any building. Buildings end at the far
  pavement line; pavement, kerb and road sit in front of them.

SAFE AREAS — MUST BE KEPT CLEAR
- TOP 180 PX (y = 0 to 180, the top 12.5%): a floating dark-chocolate
  navigation bar sits here. Keep this band as soft, calm, mid-to-high
  luminance sky only. Absolutely NO signage, NO text, NO shopfronts, NO hard
  edges, NO building tops, NO bright highlights, NO text-like marks. Keep the
  four extreme corners clean — the nav bar is rounded.
- BOTTOM 60 PX (y = 1380 to 1440): expendable over-scan. Busy hedge and kerb
  texture only, nothing readable.
- LEFT 200 PX and RIGHT 200 PX: no essential detail; these get cropped on
  narrower viewports.

SUBJECT AND ELEMENTS (left to right)
- Far-left: a small street-corner kiosk with a striped awning, a couple of
  hanging paper bags, and a simple bicycle leaning on a rack.
- Left-centre: a two-storey shop house with a pitched tiled roof, two upper
  windows, a ground-floor door.
- CENTRE, the hero subject: the main storefront. A single, clearly readable,
  wide ground-floor shop with a flat canopy and a retractable striped awning,
  a large glass display window showing neat shelves of boxed goods, a hanging
  rectangular shop sign above the door, and a stack of plain cardboard parcels
  on the pavement beside the entrance. The storefront occupies x = 700 to 1900
  and y = 533 to 1164. It is the focal point and must be legible.
- Right of the storefront: a two-storey townhouse with a chimney and three
  upper windows, then a small shop with a flat roof.
- Far-right: a narrow two-storey building, partly cropped by the frame edge.
- Background: a hazy, low-contrast distant city skyline sitting on the horizon,
  plus a row of simple stylised trees behind the shop row.
- Mid-ground: a wide grass verge between the horizon and the pavement, with a
  few evenly spaced trees.
- Street furniture, all simple and unbranded: two street lamps (one at about
  x = 500, one at about x = 2150), a bench, a fire hydrant, a bicycle and a
  parked scooter on the pavement.
- Road: a clean two-lane asphalt road with a dashed centre line and one
  manhole cover. No vehicles, no people, no moving objects.

STYLE
- Calm, premium, editorial — closer to a high-end architectural visualisation
  than to a cartoon or a game asset.
- Soft, natural, late-afternoon light with long gentle shadows falling toward
  the viewer.
- Restrained, warm palette pulled from the site palette: cream #F7EBD7 and
  #FFF3DF walls, terracotta / coral #D97757 and #C85F43 awnings and signage,
  warm brown #B77F5B and #A9684F roofs, sage green #7BA57F verge,
  deep chocolate #301B12 for all outlines, window frames, poles and kerb lines.
  Keep roughly 70% of the frame in the cream/terracotta family so it sits
  naturally behind the site's cream content sheets.
- Flat-ish graphic realism: simplified forms, clean edges, minimal texture
  noise. It must read as a background, not compete with foreground UI.
- Every element gets a crisp, consistent, dark chocolate outline (about 3 px at
  1440-wide, so about 5 px at 2560). No painterly or photoreal noise.

MOOD
- Early morning, shops just opening. Quiet, orderly, hopeful, unhurried.
  No people. Life is told through architecture and objects only.

ABSOLUTELY NO
- No text, no words, no letters, no numbers, no logos, no watermarks anywhere.
- No people, no faces, no silhouettes of people.
- No vehicles in motion, no traffic.
- No neon, no cyberpunk, no night, no sunset in this base plate.
- No vignette, no border, no frame, no rounded corners baked in.
- No blur, no depth-of-field, no lens effects.
```

### G.2 Night-lights plate — generation instructions

**Critical: derive from the accepted base image, not from a text prompt.**

```
[Image-to-image / edit the accepted base plate]

Keep every building, kerb, road marking, tree, lamp post, bench, hydrant,
bicycle, scooter and parcel EXACTLY where it is. Change nothing about geometry,
framing, camera, or canvas size.

Remove or fully darken all direct sunlight, sky reflection and daylight shading.
Everything not listed below must become near-black ambient shadow.

Add ONLY emissive light, same 2560 x 1440 canvas, on a fully transparent
background:
- Warm interior glow behind the main storefront's glass display window
  (roughly x 700-1900, y 700-1160), spilling onto the pavement below it.
- A warm lit sign box above the storefront door.
- Lit upper-floor windows in the townhouse and the two flanking shop houses —
  about half the windows lit, the rest dark.
- Both street lamps: a warm bulb and a soft cone of light falling onto the
  pavement and road beneath them.
- Warm pinpoints across the distant city skyline.
- A cool blue-white moonlight ambient on all upward-facing horizontal surfaces
  (pavement tops, awning tops, kerb).
- Faint warm reflections of the lit windows and lamps on the wet-looking road.

Light colour: warm amber #F6C489 for artificial sources; cool blue #C9D4E8 for
moonlight. Keep it tasteful and low-brightness — this plate will be composited
at partial opacity and must not blow out.
```

Export as **transparent WebP lossless or PNG-8**, 2560 × 1440.

### G.3 Portrait master prompt (mobile)

Same world, same geometry contract, recomposed for a tall frame:

```
The same single merchant neighbourhood street, rendered for a tall 9:19.4
portrait canvas, 1170 x 2532 px. Same style, same palette, same lighting
mood, same clean dark-chocolate outlines.

REFRAMED FOR PORTRAIT:
- Pull the camera back and up slightly so the full street reads in a tall
  frame. Show more sky above the rooflines and more of the road below.
- Keep the main storefront centred horizontally (x centred, roughly
  x = 180 to 990) so it survives any small horizontal crop.
- Stacked horizontal bands again, no converging perspective.

EXACT GEOMETRY:
- Canvas 1170 x 2532.
- Horizon / top of the grass verge at y = 1570 (62.0%).
- Building bases end at y = 2026.
- Far pavement: y = 2026 to 2138.
- Kerb: y = 2138 to 2152.
- Road: y = 2152 to 2271.
- Near pavement: y = 2271 to 2320.
- Hedge at the front: y = 2320 to 2452.
- Bottom 80 px (y 2452-2532) is expendable over-scan: hedge/kerb texture only.

SAFE AREA:
- Top 260 px (top 10.3%) must be calm, soft, uncluttered sky only. A dark
  navigation bar floats here. No signage, no text, no building tops, no hard
  edges.

Same subject list, same "no text / no people / no logos / no vehicles" rules.
Repeat the full night-lights edit on this plate too, same method.
```

### G.4 Generation parameters

| Item | Value |
|---|---|
| Master output | ≥ 2048 × 1152 (2K). Prefer 4096 × 2304 and **downscale**. |
| Final landscape master | 2560 × 1440 (1×), 5120 × 2880 (2×) |
| Final portrait master | 1170 × 2532 (1× equivalent 390 × 844 @ 3×); 780 × 1688 @ 2× |
| Aspect ratio control | Pass **16:9** and **9:19.4** explicitly; do not rely on the model's default 1:1 |
| Negative prompt | `text, letters, words, signage text, watermark, logo, people, faces, vehicles, traffic, neon, cyberpunk, night, blurry, vignette, frame, border, rounded corners, fisheye, distorted perspective, tilted horizon` |
| Style strength | Medium. High style strength drifts from the strict geometry contract |
| Seed | **Fix and record the seed.** Re-run the night edit against the *same* base image rather than re-generating |
| Iteration | Generate 6–10 variants, pick on **horizon alignment first**, aesthetic second |

### G.5 Acceptance checklist for every generated asset

- [ ] Horizon at exactly 62.0% of canvas height (± 0.5%)
- [ ] Building bases terminate at the far-pavement line; **road never touches a building**
- [ ] Top safe band (180 px landscape / 260 px portrait) contains no text, signage, or hard detail
- [ ] Bottom over-scan present (60 px / 80 px)
- [ ] Storefront legible and centred
- [ ] **Zero** text, letters, numbers, logos or watermarks anywhere
- [ ] **Zero** people or faces
- [ ] Palette within the site's cream/terracotta/chocolate family (≈70% cream-terracotta)
- [ ] Consistent dark-chocolate outlines across all elements
- [ ] Night plate geometry **pixel-registers** with the base plate (diff them)
- [ ] Horizon reads as level — no tilt

---

## H. Implementation risks

Ordered by severity. **R1–R3 are pre-existing defects that will corrupt the new
artwork if not fixed first.**

| # | Risk | Evidence | Severity | Mitigation |
|---|---|---|---|---|
| **R1** | **`.env-layer` collapses to `width ÷ 1.778`** — new artwork cropped/scaled wrong at 1440×900, 1024×768, 768×1024, 390×844, 360×800. Mobile shows only the top 219 px of the scene. | §B.4, MEASURED | 🔴 Critical | `.env-layer { position:absolute; inset:0; width:100%; height:100%; }`. Fix **before** wiring artwork. |
| **R2** | **Parallax exposes the bottom edge.** Foreground lifts 52.8 px at full scroll; a 20–53 px strip falls back to sky. | §B.5, MEASURED | 🔴 Critical | ≥ 6% bottom over-scan on every parallaxed layer, or reduce `--par-*` amplitudes. |
| **R3** | **Stacking-context trap.** Any `transform`/`filter`/`opacity<1`/`isolation`/`contain:paint`/`will-change` on `.world-page` traps `.world-column`'s `z-index:1` and buries the whole page under the scene. | §E.2, code-derived | 🔴 Critical | Never add those properties to `.world-page`. Add a regression test. |
| **R4** | **Scene is ~87% occluded on mobile, ~68% on a typical laptop.** A photoreal immersive scene may read as "barely there" — or as a bug. | §F.6, COMPUTED | 🔴 High | Decide the sheet treatment **before** generating. Cheapest: keep opaque sheets, but ensure the hero band and inter-sheet gaps carry the visual weight. |
| **R5** | **Portrait crop destroys the composition.** `cover` on 16:9 at 0.45 aspect keeps 25% of the width. | §C.1, computed | 🔴 High | Separate portrait master (§D.2). Never stretch; never centre-crop 16:9 onto portrait. |
| **R6** | **Night plate mis-registration → buildings appear to jump.** Independent day/night generations will never align. | §F.5 | 🟠 High | Generate the night plate by **editing the base image**, never from the same prompt. Diff-verify registration. |
| **R7** | **Payload.** A 5120 × 2880 AVIF + 1170 × 2532 AVIF + two night plates could reach 3–5 MB. | estimate | 🟠 High | Ship 1× by default; promote 2× via `<picture>` + `srcset`. Night plates as lossy WebP. Lazy-load the portrait set. Budget: **≤ 1.2 MB total on first paint.** |
| **R8** | **Per-frame style recalc.** `write()` sets ~22 custom properties on `documentElement` every rAF frame during easing. Each invalidates style for the whole document, and `--lamps`/`--daylight` drive SVG `fill` + `opacity`, forcing re-raster of large layers. | `useWorldScroll.ts:92–94`, code-derived (**not profiled**) | 🟠 High | Keep the night plate on `opacity`/`will-change: opacity` only. Scope variables to `.world-env` instead of `:root` so recalc is contained. Promote the 2× plate only for high-DPR + large viewport. |
| **R9** | **Sub-pixel shimmer.** `--sun-x/y` written every frame as `toFixed(2)` %; sub-pixel changes shimmer on the sun/moon. | `scenes.ts:154–155`, code-derived | 🟡 Medium | Quantise to whole pixels, or skip the write when unchanged. |
| **R10** | **Sticky-nav jitter from the mobile panel's `document.body.style.overflow` toggle.** Can relayout `100dvh` and shift the bar by the scrollbar delta. | `SiteHeader.tsx:321–327`, code-derived | 🟡 Medium | `scrollbar-gutter: stable` on `html`, or use `overscroll-behavior` + a scroll lock that preserves gutter width. |
| **R11** | **`--header-height: 96px` is wrong below 1200 px** (real bar is 84 px), affecting `scroll-margin-top` and the mobile panel's `max-height`. | §B.2, MEASURED | 🟡 Medium | Introduce a `--header-height: 84px` override in the `@media (max-width: 1199px)` block. Independent of the simulation. |
| **R12** | **Full night never lands at 2560 × 1440** — only 57 px of head-room past the `cta` trigger. | §F.3, MEASURED | 🟡 Medium | Remap the `cta` anchor to ≈ 0.97, or add a taller closing section. |
| **R13** | **Colour-management drift between generated rasters and the CSS sky gradient.** Seam where a raster layer meets `.env-sky`. | judgment | 🟡 Medium | Generate sky-matching reference swatches; sample the rendered `.env-sky` at `--sky-t/m/l` extremes and match the layer edges to those exact hexes. |
| **R14** | **Accessibility — contrast.** A brighter, more "realistic" scene could reduce contrast of `--ink-soft #5B4232` text wherever it shows through. | judgment | 🟡 Medium | Any text placed directly on the scene (currently none — all content sits on opaque `.readable` sheets) must be ≥ 4.5:1. Re-check if R4 is addressed by making sheets translucent. |
| **R15** | **Accessibility — reduced motion.** Already handled: `prefers-reduced-motion: reduce` gives one static frame and `--par-scale: 0`. | `useWorldScroll.ts:86–90`, `environment.css:77` | 🟢 Low | Preserve. Verify the night plate still resolves correctly in the static frame. |
| **R16** | **`overflow-x: hidden` on `body`** masks real overflow instead of preventing it. Any raster wider than its container will be silently clipped. | `global.css:46–48` | 🟢 Low | Keep layers strictly inset; do not rely on the clip. |
| **R17** | **OneDrive sync churn.** During the audit Vite logged HMR updates for `ActionsPage.tsx`, `AuthContext.tsx`, `ActionsPage.css` etc. that I did not author — almost certainly the repo being synced from `OneDrive/Documents`. | dev-server log | 🟢 Low | Be aware your working tree is being touched externally; `git status` showed the same 67 entries before and after the audit. |

---

## I. Open decisions for you

1. **Reference image** — confirm `frontend/src/assets/homepage.png` (1891 × 910, unreferenced) is the intended visual reference, or re-send the merchant-world image. (§0)
2. **Occlusion strategy (R4)** — with ~87% of the page covered by opaque cream sheets on mobile, do you want the sheets to stay fully opaque, or open them up so the new scene can breathe? This changes the artwork brief materially.
3. **Portrait master (R5)** — approve the separate 1170 × 2532 portrait artwork, or fall back to layered repositioning?
4. **R1/R2 fixes** — these are pre-existing bugs in `.env-layer` sizing and parallax over-scan. Do you want them fixed in the same change as the artwork, or as a separate first PR?
5. **Night plate approach (R6)** — confirm your Google workflow supports image-to-image / masked editing of the accepted base plate. If it only does text-to-image, the day→night transition must fall back to CSS-only lighting (tint + `filter` + emissive CSS gradients), which is less convincing but cannot mis-register.
6. **R12** — adjust the `cta` anchor so full night lands on 2560 × 1440?

---

**No implementation was performed.** The working tree is byte-identical to how
I found it: 67 pre-existing modified/untracked entries, `main` branch, no new
dependencies, no backend or agent logic touched, `frontend/src/assets/homepage.png`
untouched.