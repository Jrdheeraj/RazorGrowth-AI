/**
 * Thought-bubble collision layout for the pixel-art office.
 *
 * WHY THIS EXISTS
 * ---------------
 * Bubbles are absolutely positioned in world space above each avatar. Two
 * avatars standing near each other produced two overlapping clouds — the
 * "4 recommendation(s) prepared" cloud and the "Blocked" cloud literally
 * covered one another and hid the office behind them.
 *
 * The previous resolver had three defects that all ended in overlap:
 *   1. it only ever pushed a bubble UP, so a stack ran off the top of the map;
 *   2. `ThoughtBubble.setPosition` then CLAMPED that upward push back into the
 *      world, silently undoing the resolver's work;
 *   3. it gave up after 12 iterations with 13 agents on the floor, with no
 *      signal that it had failed.
 *
 * This module does the placement as a PURE function so it can be unit-tested
 * without a GPU or a DOM: given the base rects, the world size and the
 * priority of each bubble, return a collision-free rect for every one.
 *
 * GUARANTEES
 *  - no two returned rects overlap;
 *  - every returned rect lies fully inside the world (never clipped away);
 *  - a bubble that cannot be placed anywhere is reported as `null` so the
 *    caller can hide that one rather than stacking it on another;
 *  - critical bubbles (approval gates, blocked runs) are placed first, so when
 *    the floor is crowded the operator-critical state survives and ordinary
 *    chatter is the thing that gets dropped.
 */

/** A rectangle in world space. */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** A bubble awaiting placement. */
export interface BubbleItem {
  id: string;
  /** Where the bubble would sit if nothing were in the way. */
  base: Rect;
  /** Operator-critical state (approval gate, blocked run) wins placement. */
  critical: boolean;
}

/** A resolved placement: `rect` is null when the bubble could not be placed. */
export interface Placement {
  id: string;
  rect: Rect | null;
}

const GAP = 2;

/** Offsets tried around the base rect, nearest-first. */
const CANDIDATE_OFFSETS: ReadonlyArray<{ dx: number; dy: number }> = [
  { dx: 0, dy: -1 },
  { dx: 0, dy: 1 },
  { dx: -1, dy: 0 },
  { dx: 1, dy: 0 },
  { dx: -1, dy: -1 },
  { dx: 1, dy: -1 },
  { dx: -1, dy: 1 },
  { dx: 1, dy: 1 },
  { dx: 0, dy: -2 },
  { dx: 0, dy: 2 },
  { dx: -2, dy: -1 },
  { dx: 2, dy: -1 },
  { dx: -2, dy: 1 },
  { dx: 2, dy: 1 },
  { dx: -2, dy: 0 },
  { dx: 2, dy: 0 },
  { dx: -1, dy: -2 },
  { dx: 1, dy: -2 },
  { dx: -1, dy: 2 },
  { dx: 1, dy: 2 },
];

function overlaps(a: Rect, b: Rect): boolean {
  return (
    a.x < b.x + b.w + GAP &&
    a.x + a.w + GAP > b.x &&
    a.y < b.y + b.h + GAP &&
    a.y + a.h + GAP > b.y
  );
}

function insideWorld(rect: Rect, worldW: number, worldH: number): boolean {
  if (worldW <= 0 || worldH <= 0) return true; // bounds unknown — do not constrain
  return (
    rect.x >= 0 &&
    rect.y >= 0 &&
    rect.x + rect.w <= worldW &&
    rect.y + rect.h <= worldH
  );
}

/**
 * Resolve every bubble to a collision-free, in-bounds rect.
 *
 * @param items bubbles to place (order does not matter; priority does)
 * @param world  world size in px; `{w:0,h:0}` means "unknown", and placement
 *               is then only required to avoid overlap
 */
export function resolveBubblePlacements(
  items: BubbleItem[],
  world: { w: number; h: number },
): Placement[] {
  // Critical first; within a tier, top-most bubble first so the visual
  // reading order matches the scene's depth order.
  const ordered = [...items].sort(
    (a, b) =>
      Number(b.critical) - Number(a.critical) ||
      b.base.y - a.base.y ||
      a.base.x - b.base.x,
  );

  const placed: Rect[] = [];
  const results = new Map<string, Rect | null>();

  for (const item of ordered) {
    const { w, h } = item.base;
    let chosen: Rect | null = null;

    // Try the natural position first, then the offset ring.
    for (const off of [{ dx: 0, dy: 0 }, ...CANDIDATE_OFFSETS]) {
      const rect: Rect = {
        x: item.base.x + off.dx * (w + GAP),
        y: item.base.y + off.dy * (h + GAP),
        w,
        h,
      };
      if (!insideWorld(rect, world.w, world.h)) continue;
      if (placed.some((p) => overlaps(rect, p))) continue;
      chosen = rect;
      break;
    }

    if (chosen) placed.push(chosen);
    results.set(item.id, chosen);
  }

  return items.map((item) => ({ id: item.id, rect: results.get(item.id) ?? null }));
}

/** Test helper: true when no two rects in the list intersect (with GAP). */
export function hasNoOverlap(rects: Rect[]): boolean {
  for (let i = 0; i < rects.length; i += 1) {
    for (let j = i + 1; j < rects.length; j += 1) {
      if (overlaps(rects[i], rects[j])) return false;
    }
  }
  return true;
}

/** Test helper: true when every rect lies fully inside the world. */
export function allInsideWorld(
  rects: Rect[],
  world: { w: number; h: number },
): boolean {
  return rects.every((r) => insideWorld(r, world.w, world.h));
}