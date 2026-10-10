/**
 * Responsive-layout CSS contract test.
 *
 * Guards the root causes of the "site breaks on phones / tablets / projectors"
 * bug class, so the layout cannot silently regress:
 *
 *  1. The mobile nav panel must be gated by the `hidden` attribute. An author
 *     rule of `.mobile-menu { display: block }` beats the UA `[hidden]` rule and
 *     leaves the menu permanently open on every viewport ≤ the breakpoint —
 *     that is exactly the "menu covers the whole screen" screenshot.
 *  2. The CSS breakpoint that swaps the hamburger for the desktop row must stay
 *     in sync with the JS constant in SiteHeader.tsx.
 *  3. The footer must be allowed to wrap (it used to be a single non-shrinking
 *     nowrap row that overflowed from ~1100px up to ~1660px).
 *  4. Grid/flex children of the home "printed sheet" must be allowed to shrink
 *     (min-width: 0 + minmax(0, 1fr)), otherwise their min-content width blows
 *     the page out horizontally on tablets.
 *  5. No layout may be sized with 100vw (scrollbar-width trap).
 *
 * Zero-dependency: plain Node, no browser required (`npm run test:responsive`).
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
let failures = 0;

function read(rel) {
  return stripComments(readFileSync(join(ROOT, rel), "utf8"));
}

function readRaw(rel) {
  return readFileSync(join(ROOT, rel), "utf8");
}

/** Remove /* … *\/ comments so prose inside them cannot satisfy a check. */
function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function ok(name, cond, detail = "") {
  if (cond) {
    console.log(`ok   ${name}`);
  } else {
    failures += 1;
    console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ""}`);
  }
}

function ruleBlock(css, selector) {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = css.match(new RegExp(`${esc}\\s*\\{([^}]*)\\}`));
  return m ? m[1] : null;
}

/** Extract the body of `@media (QUERY) { … }` using brace matching. */
function mediaBlock(css, query) {
  const esc = query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const start = css.search(new RegExp(`@media\\s*\\(${esc}\\)`));
  if (start === -1) return null;
  const open = css.indexOf("{", start);
  if (open === -1) return null;
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, i);
    }
  }
  return null;
}

function walkCss(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) walkCss(p, out);
    else if (entry.endsWith(".css")) out.push(p);
  }
  return out;
}

/* ── 1. Mobile menu visibility is driven by [hidden] ───────────────────── */
const components = read("styles/components.css");

ok(
  "mobile menu is gated by the hidden attribute",
  /\.mobile-menu:not\(\[hidden\]\)/.test(components),
  "expected `.mobile-menu:not([hidden])` in styles/components.css",
);

ok(
  "no unconditional `.mobile-menu { display: block }` (hidden would be ignored)",
  !/\.mobile-menu\s*\{[^}]*display\s*:\s*block/s.test(components),
  "an author `display: block` beats the UA `[hidden]` rule and leaves the menu open forever",
);

const menuPanel = ruleBlock(components, ".mobile-menu:not([hidden])");
ok("menu panel is absolutely positioned under the header", !!menuPanel && /position\s*:\s*absolute/.test(menuPanel));
ok(
  "menu panel caps its height at the dynamic viewport height",
  !!menuPanel && /max-height\s*:\s*calc\(100dvh/.test(menuPanel),
);
ok("menu panel scrolls internally when it is taller than the screen", !!menuPanel && /overflow-y\s*:\s*auto/.test(menuPanel));

const menuItem = ruleBlock(components, ".mobile-menu__item");
ok("menu links are at least 44px tall (touch target)", !!menuItem && /min-height\s*:\s*44px/.test(menuItem));

const menuActions = ruleBlock(components, ".mobile-menu__actions .btn");
ok("menu action buttons keep the same touch target", !!menuActions && /min-height\s*:\s*44px/.test(menuActions));

/* ── 2. CSS and JS breakpoints stay in sync ───────────────────────────── */
const header = readRaw("components/SiteHeader.tsx");
const jsQuery = header.match(/DESKTOP_NAV_QUERY\s*=\s*"\(min-width:\s*(\d+)px\)"/);
const cssMin = components.match(/@media\s*\(min-width:\s*(\d+)px\)\s*\{\s*\.mobile-menu/);
ok("SiteHeader declares DESKTOP_NAV_QUERY", !!jsQuery);
ok("components.css declares the matching desktop breakpoint", !!cssMin);
ok(
  "hamburger/desktop breakpoint matches between CSS and TS",
  !!jsQuery && !!cssMin && jsQuery[1] === cssMin[1],
  jsQuery && cssMin ? `css=${cssMin[1]} ts=${jsQuery[1]}` : "missing breakpoint declaration",
);

ok("header closes the menu on Escape", /event\.key\s*===\s*"Escape"/.test(header));
ok("header locks page scroll while the menu is open", /document\.body\.style\.overflow\s*=\s*"hidden"/.test(header));
ok("toggle exposes aria-controls", /aria-controls="mobile-menu"/.test(header));

/* ── 3. Footer wraps instead of overflowing ───────────────────────────── */
const footerBar = ruleBlock(components, ".site-footer__bar");
ok("footer bar is allowed to wrap", !!footerBar && /flex-wrap\s*:\s*wrap/.test(footerBar));

const footerNav = ruleBlock(components, ".site-footer__nav");
ok("footer nav may shrink (no flex-shrink: 0)", !!footerNav && !/flex-shrink\s*:\s*0/.test(footerNav));
ok("footer nav wraps its links", !!footerNav && /flex-wrap\s*:\s*wrap/.test(footerNav));

const footerLegal = ruleBlock(components, ".site-footer__legal");
ok("footer legal line may wrap", !!footerLegal && !/white-space\s*:\s*nowrap/.test(footerLegal));

const shell = ruleBlock(components, ".public-shell");
ok("page shell uses the dynamic viewport height", !!shell && /100dvh/.test(shell));

/* ── 4. Home "printed sheet" can shrink on narrow viewports ───────────── */
const environment = read("features/public/Environment/environment.css");
const worldColumn = ruleBlock(environment, ".world-column");
ok(
  "world column track is minmax(0, 1fr)",
  !!worldColumn && /grid-template-columns\s*:\s*minmax\(0,\s*1fr\)/.test(worldColumn),
);
const worldChildren = ruleBlock(environment, ".world-column > *");
ok("world column children opt out of min-width: auto", !!worldChildren && /min-width\s*:\s*0/.test(worldChildren));
const readable = ruleBlock(environment, ".readable");
ok("printed sheet opts out of min-width: auto", !!readable && /min-width\s*:\s*0/.test(readable));

/* ── 5. Hero floats stack before they can collide with the main window ── */
const hero = read("features/public/Hero/hero.css");
const heroStack = mediaBlock(hero, "max-width: 1023px");
ok("hero stack breakpoint exists at max-width: 1023px", !!heroStack);
ok("stacked hero stage becomes a single column", !!heroStack && /flex-direction\s*:\s*column/.test(heroStack));
ok(
  "stacked approval window returns to the normal flow",
  !!heroStack && /\.hfloat--approval\s*\{[^}]*position\s*:\s*static/s.test(heroStack),
);
ok(
  "hidden hero floats are removed (no overlap)",
  !!heroStack && /\.hfloat--log\s*,\s*\n?\s*\.hfloat--queue\s*\{\s*display\s*:\s*none/.test(heroStack),
);

/* ── 6. No layout width derived from 100vw (scrollbar trap) ───────────── */
const vwOffenders = [];
for (const file of walkCss(ROOT)) {
  const css = stripComments(readFileSync(file, "utf8"));
  if (/width\s*:[^;]*100vw/.test(css) || /calc\(\s*100vw/.test(css)) {
    vwOffenders.push(file.slice(ROOT.length + 1));
  }
}
ok("no 100vw-based widths anywhere in src styles", vwOffenders.length === 0, vwOffenders.join(", "));

/* ── 7. Display type stays fluid ──────────────────────────────────────── */
const tokens = read("styles/tokens.css");
ok(
  "section headline scale is fluid (clamp)",
  /--text-display-lg:\s*clamp\(/.test(tokens),
);

console.log(failures === 0 ? "\nresponsive layout: all checks passed" : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
