/**
 * Local product photography + name/SKU -> photo resolver.
 *
 * This module is NOT a catalog. It holds no product prices, stock levels,
 * counts, trends or merchandising flags - every product fact lives in the
 * backend `products` table and reaches the UI through the real APIs
 * (GET /api/products, GET /api/product-agi/catalog). Nothing here can be
 * mistaken for business data.
 *
 * It exists for one reason: the backend `products` table has no image column,
 * so the UI resolves each REAL product to its REAL local photo here. Both
 * Checkout and the Product Agent workstation use `catalogImageFor`.
 *
 * A product that matches no known photo returns null, and the UI shows an
 * honest "Image unavailable" state rather than another product's photo.
 *
 * Image sources / licenses (frontend demo use, verify before production):
 *  - webcam.jpg ......... Unsplash photo 1762681290673 (webcam on monitor)
 *  - usb-c-hub.jpg ...... Unsplash photo 1760376789478 (multi-port USB hub)
 *  - laptop-stand.jpg ... Wikimedia Commons "File:Laptop stand.jpg" (CC BY-SA)
 *  - keyboard.jpg ....... Unsplash photo 1618384887929 (compact keyboard)
 *  - speaker.jpg ........ Unsplash photo 1608043152269 (portable speaker)
 *  - earbuds.jpg ........ Unsplash photo 1606220945770 (wireless earbuds)
 *  - headphone-case.jpg . Wikimedia Commons "Bose QC25 with Carry Case" (CC BY-SA)
 *  - usb-c-cable.jpg .... Wikimedia Commons "USB-C cable 2017 A" (CC0/ CC BY-SA)
 *  - headphones.jpg ..... Unsplash photo 1583394838336 (over-ear headphones)
 *  - mousepad.jpg ....... Pexels photo 27467770 (leather desk mat workspace)
 * Unsplash images: Unsplash License. Pexels images: Pexels License.
 */

import webcamImg from "../assets/products/webcam.jpg";
import hubImg from "../assets/products/usb-c-hub.jpg";
import standImg from "../assets/products/laptop-stand.jpg";
import keyboardImg from "../assets/products/keyboard.jpg";
import speakerImg from "../assets/products/speaker.jpg";
import earbudsImg from "../assets/products/earbuds.jpg";
import caseImg from "../assets/products/headphone-case.jpg";
import cableImg from "../assets/products/usb-c-cable.jpg";
import headphonesImg from "../assets/products/headphones.jpg";
import mousepadImg from "../assets/products/mousepad.jpg";

/* ── Backend-product → real-photo resolution ─────────────────────────────
 *
 * Three layers, each returning one of the 10 existing assets. Nothing is
 * invented:
 *
 *   1. exact normalized name (the seeded catalog hits here),
 *   2. SKU keyword (stable across renames: SKU-WEBCAM-001 → webcam photo),
 *   3. distinctive name tokens ("HD Pro Webcam 4K" → webcam photo).
 *
 * Normalization is unicode-safe (NFKC + dash/space folding) so invisible
 * character differences can never blank a product image.
 */

export type CatalogImageKey =
  | "webcam"
  | "hub"
  | "stand"
  | "keyboard"
  | "speaker"
  | "earbuds"
  | "case"
  | "cable"
  | "headphones"
  | "mousepad";

const IMAGE_BY_KEY: Record<CatalogImageKey, string> = {
  webcam: webcamImg,
  hub: hubImg,
  stand: standImg,
  keyboard: keyboardImg,
  speaker: speakerImg,
  earbuds: earbudsImg,
  case: caseImg,
  cable: cableImg,
  headphones: headphonesImg,
  mousepad: mousepadImg,
};

function normalizeProductText(value: string | null | undefined): string {
  return (value ?? "")
    .normalize("NFKC")
    .replace(/[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uFE58\uFE63\uFF0D]/g, "-")
    .replace(/[\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200A\u200B\u202F\u205F\u3000]/g, " ")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

const IMAGE_KEY_BY_EXACT_NAME = new Map<string, CatalogImageKey>(
  (
    [
      ["1080p USB Webcam", "webcam"],
      ["7-in-1 USB-C Hub", "hub"],
      ["Aluminium Laptop Stand", "stand"],
      ["Mechanical Wireless Keyboard", "keyboard"],
      ["Portable Bluetooth Speaker", "speaker"],
      ["Premium Earbuds", "earbuds"],
      ["Protective Headphone Case", "case"],
      ["USB-C Braided Cable 2m", "cable"],
      ["Wireless Headphones", "headphones"],
      ["XL Desk Mousepad", "mousepad"],
    ] as Array<[string, CatalogImageKey]>
  ).map(([name, key]) => [normalizeProductText(name), key]),
);

/** Stable SKU keywords — keep longest/most-specific first. */
const SKU_IMAGE_KEYS: Array<[string, CatalogImageKey]> = [
  ["headphones", "headphones"],
  ["mousepad", "mousepad"],
  ["keyboard", "keyboard"],
  ["speaker", "speaker"],
  ["earbuds", "earbuds"],
  ["webcam", "webcam"],
  ["stand", "stand"],
  ["cable", "cable"],
  ["hub", "hub"],
  ["case", "case"],
];

/** Distinctive name tokens — multi-word / most-specific first. */
const NAME_IMAGE_KEYS: Array<[string, CatalogImageKey]> = [
  ["headphone case", "case"],
  ["case", "case"],
  ["mouse pad", "mousepad"],
  ["headphones", "headphones"],
  ["headphone", "headphones"],
  ["webcam", "webcam"],
  ["mousepad", "mousepad"],
  ["keyboard", "keyboard"],
  ["speaker", "speaker"],
  ["earbuds", "earbuds"],
  ["earbud", "earbuds"],
  ["stand", "stand"],
  ["cable", "cable"],
  ["hub", "hub"],
];

/** Which real photo belongs to this backend product, if any. */
export function catalogImageKeyFor(
  name: string | null | undefined,
  sku: string | null | undefined,
): CatalogImageKey | null {
  const n = normalizeProductText(name);
  if (n) {
    const exact = IMAGE_KEY_BY_EXACT_NAME.get(n);
    if (exact) return exact;
  }
  const s = normalizeProductText(sku);
  if (s) {
    const paddedSku = ` ${s} `;
    for (const [keyword, key] of SKU_IMAGE_KEYS) {
      if (paddedSku.includes(` ${keyword} `)) return key;
    }
  }
  if (n) {
    const padded = ` ${n} `;
    for (const [token, key] of NAME_IMAGE_KEYS) {
      if (padded.includes(` ${token} `)) return key;
    }
  }
  return null;
}

/** The product's REAL local photo URL, or null when genuinely unknown. */
export function catalogImageFor(
  name: string | null | undefined,
  sku: string | null | undefined,
): string | null {
  const key = catalogImageKeyFor(name, sku);
  return key ? IMAGE_BY_KEY[key] : null;
}