/**
 * /checkout — AI Buyer commerce flow (scoped visual redesign).
 *
 * An AI buyer reads the merchant's real catalog (GET /api/products),
 * selects a product, creates a Razorpay TEST order at the product's real
 * price, and completes payment through Razorpay TEST checkout.
 *
 * PRESERVED FUNCTIONALITY (untouched logic):
 *   - fetchProducts() real catalog + first-purchasable auto-select
 *   - createCheckoutSession() with the REAL catalog price
 *   - Razorpay checkout.js loading + openRazorpay() + server-side
 *     verifyPayment() before any success is claimed
 *   - modal ondismiss + payment.failed honest failure states
 *   - login_required / catalog error / empty catalog states
 *   - price rendering (₹ + Number(price).toFixed(2)) and stock rules
 *
 * VISUAL LAYER ONLY: hero + stepper + catalog chrome + purchase panel +
 * process guide + brand card + illustrated footer. The hero reuses the
 * EXACT shared illustration component from the Marketing / Product Agent
 * dashboards (components/AgentOfficeArt, sign="RAZORGROWTH AI") — same
 * composition, colors and line-art, only the sign text adapted.
 * Product images resolve
 * through the app's EXISTING local photography (data/productCatalog.ts,
 * matched by product name — the same 10 seeded products) with the same
 * initials + onError fallback the Product Agent page already uses.
 * The backend catalog carries no image field, so nothing is invented.
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { createCheckoutSession, verifyPayment, fetchProducts } from "../lib/api";
import { isAuthenticated } from "../lib/auth";
import type { ProductResponse, CheckoutSessionResponse } from "../types/api";
import { catalogImageFor } from "../data/productCatalog";
import { AgentOfficeArt } from "../components/AgentOfficeArt";
import { ProductMedia } from "../components/ProductMedia";
import { PreviewModeBanner } from "../components/PreviewModeBanner";
import razorpayLogo from "../assets/brands/razorpay.svg";
import "./Checkout.css";

/* ── Sample Showcase Products for Unauthenticated Visitors ─────────────── */

const SAMPLE_CHECKOUT_PRODUCTS: ProductResponse[] = [
  {
    id: "demo_prod_keyboard",
    merchant_id: "demo_merchant_preview",
    name: "Ergonomic Mechanical Keyboard",
    category: "Desk Accessories",
    price: 4299,
    description: "Compact mechanical keyboard with hot-swappable switches and custom sound dampening.",
    sku: "KB-MECH-01",
    stock_quantity: 42,
    active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: "demo_prod_soundbar",
    merchant_id: "demo_merchant_preview",
    name: "Studio Soundbar Pro",
    category: "Audio",
    price: 7499,
    description: "Premium spatial audio soundbar with Bluetooth 5.3 and dual subwoofers.",
    sku: "AU-SND-02",
    stock_quantity: 18,
    active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: "demo_prod_hub",
    merchant_id: "demo_merchant_preview",
    name: "Aluminum Multiport USB-C Hub",
    category: "Accessories",
    price: 1899,
    description: "8-in-1 USB-C hub with 4K HDMI, 100W Power Delivery, and Gigabit Ethernet.",
    sku: "ACC-HUB-03",
    stock_quantity: 65,
    active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: "demo_prod_headphones",
    merchant_id: "demo_merchant_preview",
    name: "Wireless ANC Over-Ear Headphones",
    category: "Audio",
    price: 5999,
    description: "Hybrid active noise cancellation with 40-hour battery life and low-latency gaming mode.",
    sku: "AU-HP-04",
    stock_quantity: 27,
    active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
];

declare global {
  interface Window {
    Razorpay: any;
  }
}

type Outcome =
  | { kind: "success"; paymentId: string | null }
  | { kind: "failed"; reason: string };

type SortKey = "recommended" | "price-asc" | "price-desc" | "name";

/* ── existing product photography: each live product resolves to its REAL
   local photo via the layered catalog resolver (exact name → SKU keyword
   → distinctive tokens, unicode-safe). Null only when no known photo
   matches — never a wrong product's photo. */
function imageForProduct(p: Pick<ProductResponse, "name" | "sku">): string | null {
  return catalogImageFor(p.name, p.sku);
}
function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/);
  return parts.length >= 2
    ? (parts[0][0] + parts[1][0]).toUpperCase()
    : name.trim().slice(0, 2).toUpperCase();
}
function inr(price: unknown): string {
  return `₹${Number(price).toFixed(2)}`;
}
function isPurchasable(p: ProductResponse): boolean {
  return p.active && p.stock_quantity > 0 && Number(p.price) > 0;
}
function catTone(category: string | null): string {
  const c = (category ?? "").toLowerCase();
  if (c.includes("audio")) return "rgco-card__cat--audio";
  if (c.includes("desk")) return "rgco-card__cat--desk";
  if (c.includes("access")) return "rgco-card__cat--accessories";
  return "rgco-card__cat--other";
}

/* ── tiny outline icons (1.8px stroke, no emoji) ───────────────────────── */
function I({ size = 16, children }: { size?: number; children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth={1.8} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}
const IconSearch = () => (<I size={14}><><circle cx="11" cy="11" r="6" /><path d="M15.5 15.5L20 20" /></></I>);
const IconShieldCheck = () => (<I size={15}><><path d="M12 3l7 2.8v5.4c0 4.4-3 7.6-7 9.3-4-1.7-7-4.9-7-9.3V5.8L12 3z" /><path d="M9 11.6l2.2 2.2 3.8-4.4" /></></I>);
const IconWallet = () => (<I size={15}><><path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h12A1.5 1.5 0 0 1 18 7.5V18a1.5 1.5 0 0 1-1.5 1.5h-12A1.5 1.5 0 0 1 3 18V7.5z" /><path d="M3 9h15" /><circle cx="16" cy="14.5" r="1" /></></I>);
const IconSpark = () => (<I size={15}><><path d="M12 3l1.7 4.6L18 9.3l-4.3 1.7L12 15.5l-1.7-4.5L6 9.3l4.3-1.7L12 3z" /><path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" /></></I>);
const IconPay = () => (<I size={15}><><rect x="3" y="6" width="18" height="13" rx="1.5" /><path d="M3 10.5h18" /><path d="M7 15h4" /></></I>);
const IconBag = () => (<I size={40}><><path d="M6 8h12l1 12.5H5L6 8z" /><path d="M9 10V6.5a3 3 0 0 1 6 0V10" /></></I>);
const IconTag = () => (<I size={13}><><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11l9 9-6.5 6.5-9-9V5.5z" /><circle cx="9" cy="9" r="1.2" /></></I>);
const IconCube = () => (<I size={13}><><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" /><path d="M12 12l8-4.5M12 12L4 7.5M12 12v9" /></></I>);
const IconHead = () => (<I size={13}><><path d="M4 14v-2a8 8 0 0 1 16 0v2" /><rect x="3" y="13.5" width="4" height="6" rx="1.2" /><rect x="17" y="13.5" width="4" height="6" rx="1.2" /></></I>);
const IconGrid = () => (<I size={13}><><rect x="4" y="4" width="7" height="7" rx="1" /><rect x="13" y="4" width="7" height="7" rx="1" /><rect x="4" y="13" width="7" height="7" rx="1" /><rect x="13" y="13" width="7" height="7" rx="1" /></></I>);
const IconChev = () => (<I size={14}><><path d="M9 5l7 7-7 7" /></></I>);
const IconCart = () => (<I size={17}><><path d="M3 4h2.5l2.2 11h10.6l2.2-8H6" /><circle cx="9.5" cy="19.5" r="1.3" /><circle cx="16.5" cy="19.5" r="1.3" /></></I>);
function catIcon(category: string) {
  const c = category.toLowerCase();
  if (c.includes("audio")) return <IconHead />;
  if (c.includes("desk")) return <IconCube />;
  if (c.includes("access")) return <IconTag />;
  return <IconGrid />;
}

const STEPS = [
  { n: 1, title: "Read Catalog", sub: "AI analyzes products" },
  { n: 2, title: "Select Product", sub: "Choose from catalog" },
  { n: 3, title: "Create Order", sub: "Razorpay test order" },
  { n: 4, title: "Test Payment", sub: "Simulate success" },
  { n: 5, title: "Result Recorded", sub: "AI logs the outcome" },
] as const;

const GUIDE = [
  { t: "Already read product catalog", s: "Analyzes real product data from your store.", icon: <IconGrid /> },
  { t: "You select a product", s: "Choose any product from the catalog.", icon: <IconTag /> },
  { t: "AI creates test order", s: "Creates a Razorpay TEST order.", icon: <IconCube /> },
  { t: "Complete test payment", s: "Use test payment details to simulate success.", icon: <IconPay /> },
  { t: "Result recorded", s: "AI logs the purchase outcome.", icon: <IconShieldCheck /> },
];

export function Checkout() {
  const navigate = useNavigate();
  const [products, setProducts] = useState<ProductResponse[] | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [session, setSession] = useState<CheckoutSessionResponse | null>(null);
  const [stage, setStage] = useState<"idle" | "creating" | "paying">("idle");
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [razorpayLoaded, setRazorpayLoaded] = useState(false);
  const [isPreview, setIsPreview] = useState(!isAuthenticated());
  /* catalog chrome state (client-side only, over the REAL list) */
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState<string>("all");
  const [sort, setSort] = useState<SortKey>("recommended");
  const [copiedCard, setCopiedCard] = useState(false);

  const handleCopyCard = (cardNum = "4100 2800 0000 1007") => {
    if (navigator?.clipboard) {
      navigator.clipboard.writeText(cardNum);
      setCopiedCard(true);
      setTimeout(() => setCopiedCard(false), 2000);
    }
  };

  /* Load the real merchant catalog. (PRESERVED) */
  useEffect(() => {
    if (!isAuthenticated()) {
      setIsPreview(true);
      setProducts(SAMPLE_CHECKOUT_PRODUCTS);
      setSelectedId(SAMPLE_CHECKOUT_PRODUCTS[0].id);
      return;
    }
    fetchProducts()
      .then((data) => {
        const list = data.products ?? [];
        setProducts(list);
        setIsPreview(false);
        // Auto-select the first purchasable product — never the ₹0
        // auto-created placeholder, which cannot be ordered (amount > 0).
        const firstPurchasable = list.find((p) => p.active && p.stock_quantity > 0 && Number(p.price) > 0);
        if (firstPurchasable) setSelectedId(firstPurchasable.id);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "";
        if (msg.includes("NOT_AUTHENTICATED") || msg.includes("TOKEN_EXPIRED") || msg.includes("401")) {
          setIsPreview(true);
          setProducts(SAMPLE_CHECKOUT_PRODUCTS);
          setSelectedId(SAMPLE_CHECKOUT_PRODUCTS[0].id);
        } else {
          setCatalogError(
            err instanceof Error ? err.message : "The product catalog could not be loaded"
          );
        }
      });
  }, []);

  /* Load Razorpay Checkout JS. (PRESERVED) */
  useEffect(() => {
    if (window.Razorpay) {
      setRazorpayLoaded(true);
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = () => setRazorpayLoaded(true);
    script.onerror = () => setError("Razorpay Checkout could not be loaded. Please try again.");
    document.body.appendChild(script);
    return () => {
      document.body.removeChild(script);
    };
  }, []);

  const selected = products?.find((p) => p.id === selectedId) ?? null;

  const startCheckout = async () => {
    if (!selected) return;
    if (!isAuthenticated() || isPreview) {
      setError("Sign in with your merchant account to connect your live store and initiate genuine Razorpay TEST orders.");
      return;
    }
    const price = Number(selected.price); // API returns a decimal string — send a clean number
    if (!(price > 0)) {
      setError("This product cannot be ordered — its price is ₹0.");
      return;
    }
    setStage("creating");
    setError(null);
    setOutcome(null);
    try {
      const data = await createCheckoutSession({
        amount: price, // real catalog price — never hardcoded
        currency: "INR",
        description: selected.name,
        customer_email: "ai-buyer@razorgrowth.test", // required by the checkout workflow
        receipt: `ai_buyer_${Date.now()}`,
      });
      setSession(data);
      setStage("idle");
    } catch {
      setError("The order could not be created. Please try again.");
      setStage("idle");
    }
  };

  const openRazorpay = () => {
    if (!session || !selected || !razorpayLoaded || !window.Razorpay) {
      setError("Razorpay Checkout is not ready yet. Please try again.");
      return;
    }

    const options = {
      key: session.key_id,
      amount: session.amount * 100, // paise
      currency: session.currency,
      name: "RazorGrowth AI",
      description: selected.name,
      order_id: session.razorpay_order_id,
      theme: { color: "#21130e" },
      prefill: {
        name: "AI Buyer",
        email: "ai-buyer@razorgrowth.test",
        contact: "9999999999",
      },
      notes: {
        payment_card: "4100 2800 0000 1007",
      },
      handler: async (response: any) => {
        // Success path — verify server-side before claiming success.
        try {
          const data = await verifyPayment({
            razorpay_order_id: response.razorpay_order_id,
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_signature: response.razorpay_signature,
          });
          if (data.verified) {
            setOutcome({ kind: "success", paymentId: data.payment_id });
            setSession(null);
          } else {
            // Verification failed — treat as failure, never fake success.
            setOutcome({
              kind: "failed",
              reason: "The payment could not be confirmed by the system.",
            });
          }
        } catch {
          setOutcome({
            kind: "failed",
            reason: "The payment could not be confirmed by the system.",
          });
        }
      },
      modal: {
        ondismiss: () => {
          // Buyer dismissed the payment — honest failure state.
          setOutcome({
            kind: "failed",
            reason: "The payment window was closed before the payment could complete.",
          });
        },
      },
    };

    const rzp = new window.Razorpay(options);
    rzp.on("payment.failed", () => {
      // Real TEST-mode failure (e.g. the declined test card) — safe state.
      setOutcome({
        kind: "failed",
        reason: "The payment attempt was declined. No money was captured.",
      });
    });
    rzp.open();
  };

  /* ── derived catalog chrome (dynamic categories, search, sort) ──────── */
  const categories = useMemo(() => {
    const m = new Map<string, number>();
    (products ?? []).forEach((p) => {
      const c = (p.category ?? "product").trim() || "product";
      m.set(c, (m.get(c) ?? 0) + 1);
    });
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [products]);

  const totalCount = products?.length ?? 0;

  const visible = useMemo(() => {
    let list = products ?? [];
    if (cat !== "all") list = list.filter((p) => (p.category ?? "product") === cat);
    const q = query.trim().toLowerCase();
    if (q) {
      list = list.filter((p) =>
        `${p.name} ${p.description ?? ""} ${p.category ?? ""}`.toLowerCase().includes(q),
      );
    }
    const arr = [...list];
    if (sort === "price-asc") arr.sort((a, b) => Number(a.price) - Number(b.price));
    else if (sort === "price-desc") arr.sort((a, b) => Number(b.price) - Number(a.price));
    else if (sort === "name") arr.sort((a, b) => a.name.localeCompare(b.name));
    return arr;
  }, [products, cat, query, sort]);

  /* stepper reflects REAL state — success only after backend verification */
  const stepIndex: number = outcome ? 5 : session ? 4 : selected ? 3 : products && products.length > 0 ? 2 : 1;

  const pick = (id: string) => {
    setSelectedId(id);
    setSession(null);
    setOutcome(null);
  };

  return (
    <div className="rgco-page">
      {isPreview && (
        <PreviewModeBanner
          pageName="Checkout Experience"
          description="Viewing merchant product showcase in preview mode. Sign in to connect your live store catalog and process test transactions."
        />
      )}
      {/* ══ HERO ══ */}
      <section className="rgco-hero" aria-labelledby="checkout-heading">
        <div className="rgco-hero__inner">
          <div className="rgco-hero__copy">
            <p className="rgco-eyebrow">
              <span className="rgco-eyebrow__dot" aria-hidden="true" />
              AI BUYER · RAZORPAY TEST MODE
            </p>
            <h1 id="checkout-heading" className="rgco-hero__title">AI Buyer Checkout</h1>
            <p className="rgco-hero__lead">
              An AI buyer reads this merchant&apos;s real product catalog, selects a product,
              and completes a genuine Razorpay TEST purchase — no real money moves.
            </p>
            <div className="rgco-trust" aria-label="Trust indicators">
              <span className="rgco-trust__badge">
                <span className="rgco-trust__icon"><IconShieldCheck /></span>
                <span><p className="rgco-trust__name">Safe Test Mode</p><p className="rgco-trust__sub">No real payment</p></span>
              </span>
              <span className="rgco-trust__badge">
                <span className="rgco-trust__icon"><IconWallet /></span>
                <span><p className="rgco-trust__name">Real Catalog Data</p><p className="rgco-trust__sub">Live products</p></span>
              </span>
              <span className="rgco-trust__badge">
                <span className="rgco-trust__icon"><IconSpark /></span>
                <span><p className="rgco-trust__name">AI Powered Flow</p><p className="rgco-trust__sub">Complete purchase</p></span>
              </span>
              <span className="rgco-trust__badge">
                <span className="rgco-trust__icon"><IconPay /></span>
                <span><p className="rgco-trust__name">Razorpay Test</p><p className="rgco-trust__sub">Simulate success</p></span>
              </span>
            </div>
          </div>
          <div className="rgco-hero__art" aria-hidden="false" role="img" aria-label="Illustrated RazorGrowth AI storefront — same artwork as the Marketing and Product Agent dashboards">
            {/* Reuses the EXACT shared illustration component from the
                Marketing Agent / Product Agent dashboards
                (components/AgentOfficeArt). Only the sign text is adapted
                for Checkout — same composition, colors, line-art, tree,
                sun and wall tags. */}
            <AgentOfficeArt
              sign="RAZORGROWTH AI"
              className="rgco-hero__office"
              label="Illustrated RazorGrowth AI storefront for AI buyer checkout"
            />
          </div>
        </div>
      </section>

      {/* ══ STEPPER ══ */}
      <div className="rgco-steps" aria-label="Checkout progress">
        <div className="rgco-steps__inner">
          {STEPS.map((s, i) => (
            <div key={s.n} className="rgco-step" style={{ flex: i === STEPS.length - 1 ? "0 0 auto" : undefined }}>
              <div
                className={`rgco-step${s.n === stepIndex ? " is-active" : ""}${s.n < stepIndex ? " is-done" : ""}`}
                style={{ display: "flex", alignItems: "center", gap: 9 }}
                aria-current={s.n === stepIndex ? "step" : undefined}
              >
                <span className="rgco-step__num">{s.n < stepIndex ? "✓" : s.n}</span>
                <span>
                  <span className="rgco-step__idx">Step {s.n}</span>
                  <p className="rgco-step__name">{s.title}</p>
                  <p className="rgco-step__sub">{s.sub}</p>
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <span className="rgco-step__chev" aria-hidden="true"><IconChev /></span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ══ MAIN ══ */}
      <div className="rgco-main">
        {/* ── CATALOG ── */}
        <section className="rgco-catalog" aria-label="Product catalog">
          <div className="rgco-catalog__head-bar">
            <div>
              <div className="rgco-catalog__live-pill">
                <span className="rgco-catalog__pulse" aria-hidden="true" />
                <span>{isPreview ? "PREVIEW SHOWCASE CATALOG" : "STORE DATABASE CONNECTED"}</span>
              </div>
              <h2 className="rgco-catalog__title">Product Catalog</h2>
              <p className="rgco-catalog__sub">Products available for AI buyer test purchase. Select a product to continue.</p>
            </div>
            {products && products.length > 0 && (
              <div className="rgco-catalog__stats-badge">
                <span className="rgco-catalog__stats-count">{totalCount}</span>
                <span className="rgco-catalog__stats-lbl">Products In Catalog</span>
              </div>
            )}
          </div>

          {catalogError && catalogError !== "login_required" && (
            <div className="rgco-state" role="alert">
              <strong>Catalog unavailable</strong>
              The catalog could not be loaded. Please try again.
            </div>
          )}

          {!products && !catalogError && (
            <div className="rgco-state" aria-live="polite">
              <strong>Reading the merchant catalog…</strong>
              Loading real products from your store.
            </div>
          )}

          {products && products.length === 0 && (
            <div className="rgco-state" role="status">
              <strong>No products yet</strong>
              This merchant has no products in the catalog yet. Products from the real business data
              will appear here, and the AI buyer will be able to select one and complete a TEST purchase.
            </div>
          )}

          {products && products.length > 0 && (
            <>
              <div className="rgco-toolbar">
                <div className="rgco-search">
                  <IconSearch />
                  <input
                    type="search"
                    placeholder="Search products..."
                    aria-label="Search products"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
                <div className="rgco-sort">
                  <label htmlFor="rgco-sort">Sort by</label>
                  <select id="rgco-sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
                    <option value="recommended">Recommended</option>
                    <option value="price-asc">Price: Low to High</option>
                    <option value="price-desc">Price: High to Low</option>
                    <option value="name">Name A–Z</option>
                  </select>
                </div>
              </div>

              <div className="rgco-cats" role="group" aria-label="Filter by category">
                <button
                  type="button"
                  className={`rgco-cat${cat === "all" ? " is-on" : ""}`}
                  onClick={() => setCat("all")}
                  aria-pressed={cat === "all"}
                >
                  <IconGrid /> All Products <span className="rgco-cat__n">{totalCount}</span>
                </button>
                {categories.map(([c, n]) => (
                  <button
                    key={c}
                    type="button"
                    className={`rgco-cat${cat === c ? " is-on" : ""}`}
                    onClick={() => setCat(c)}
                    aria-pressed={cat === c}
                  >
                    {catIcon(c)} {c.charAt(0).toUpperCase() + c.slice(1)} <span className="rgco-cat__n">{n}</span>
                  </button>
                ))}
              </div>

              {visible.length === 0 ? (
                <div className="rgco-state" role="status">
                  <strong>No matches</strong>
                  No products match the current search and filter. Clear the search or choose another category.
                </div>
              ) : (
                <div className="rgco-grid">
                  {visible.map((p) => {
                    const img = imageForProduct(p);
                    const sel = selectedId === p.id;
                    const ok = isPurchasable(p);
                    return (
                      <article key={p.id} className={`rgco-card${sel ? " is-sel" : ""}`} aria-label={p.name}>
                        <div className="rgco-card__top">
                          <span className={`rgco-card__cat ${catTone(p.category)}`} title={p.category ?? "product"}>
                            {(p.category ?? "product").toUpperCase()}
                          </span>
                          {p.stock_quantity > 0 && (
                            <span className="rgco-card__stock"><i />{p.stock_quantity} IN STOCK</span>
                          )}
                        </div>
                        <ProductMedia images={img} name={p.name} />
                        <h3 className="rgco-card__name" title={p.name}>{p.name}</h3>
                        <p className="rgco-card__desc">{p.description ?? "No description was provided for this product."}</p>
                        <p className="rgco-card__price">{inr(p.price)}</p>
                        <button
                          type="button"
                          className={`rgco-card__btn${sel ? " is-sel" : ""}`}
                          disabled={!ok}
                          onClick={() => pick(p.id)}
                          title={ok ? `Select ${p.name}` : "Not purchasable"}
                        >
                          {sel ? "Selected ✓" : "Select Product →"}
                        </button>
                      </article>
                    );
                  })}
                </div>
              )}
              <p className="rgco-count">
                Showing {visible.length} of {totalCount} products
                {cat !== "all" ? ` · ${cat}` : ""}
              </p>
            </>
          )}
        </section>

        {/* ── RIGHT COLUMN ── */}
        <div className="rgco-side">
          <section className="rgco-buy" aria-label="AI buyer purchase">
            <div className="rgco-buy__head">
              <div className="rgco-buy__head-title">
                <span className="rgco-buy__pulse" aria-hidden="true" />
                <span>AI BUYER · PURCHASE</span>
              </div>
              <span className="rgco-buy__test">TEST MODE</span>
            </div>
            <div className="rgco-preview">
              {!selected ? (
                <div className="rgco-preview__empty">
                  <IconBag />
                  <p className="rgco-preview__t">No product selected</p>
                  <p className="rgco-preview__s">Choose a product from the catalog to continue.</p>
                </div>
              ) : (
                <div className="rgco-preview__sel">
                  <span className="rgco-preview__thumb" aria-hidden="true">
                    {imageForProduct(selected) ? (
                      <img
                        src={imageForProduct(selected)!}
                        alt=""
                        onError={(e) => {
                          const t = e.currentTarget as HTMLImageElement;
                          t.style.display = "none";
                          const fb = t.nextElementSibling as HTMLElement | null;
                          if (fb) fb.style.display = "inline";
                        }}
                      />
                    ) : null}
                    <span style={{ display: imageForProduct(selected) ? "none" : "inline" }}>
                      {initialsOf(selected.name)}
                    </span>
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <p className="rgco-preview__name">{selected.name}</p>
                    <p className="rgco-preview__price">{inr(selected.price)}</p>
                  </span>
                </div>
              )}
            </div>
            <div className="rgco-summary">
              <h3 className="rgco-summary__h">ORDER SUMMARY</h3>
              <div className="rgco-summary__row">
                <span>Product</span>
                <span title={selected?.name ?? ""}>{selected ? selected.name : "—"}</span>
              </div>
              <div className="rgco-summary__row">
                <span>Price</span>
                <span>{selected ? inr(selected.price) : "—"}</span>
              </div>
              <div className="rgco-summary__row">
                <span>Test Mode</span>
                <span><span className="rgco-summary__testdot" />Razorpay TEST</span>
              </div>
              <div className="rgco-total">
                <span>Total</span>
                <span>{selected ? inr(selected.price) : "₹0.00"}</span>
              </div>

              {!selected && (
                <button type="button" className="rgco-orderbtn" disabled>
                  Create Order
                </button>
              )}
              {selected && !session && (
                <button
                  type="button"
                  className="rgco-orderbtn"
                  onClick={startCheckout}
                  disabled={stage === "creating"}
                >
                  {stage === "creating" ? "Creating order…" : "Create Order"}
                </button>
              )}
              {selected && session && (
                <>
                  <p className="rgco-orderref">
                    Order created{session.razorpay_order_id ? ` · ref ${session.razorpay_order_id}` : ""}. Ready for Razorpay TEST checkout.
                  </p>

                  <div
                    className="rgco-quick-card-pill"
                    onClick={() => handleCopyCard("4100 2800 0000 1007")}
                    role="button"
                    tabIndex={0}
                    title="Click to copy payment card number"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        handleCopyCard("4100 2800 0000 1007");
                      }
                    }}
                  >
                    <div className="rgco-quick-card-left">
                      <span className="rgco-quick-card-label">CARD FOR PAYMENT:</span>
                      <code className="rgco-quick-card-code">4100 2800 0000 1007</code>
                    </div>
                    <span className="rgco-quick-card-btn">
                      {copiedCard ? "✓ Copied" : "Copy"}
                    </span>
                  </div>

                  <button
                    type="button"
                    className="rgco-paybtn"
                    onClick={openRazorpay}
                    disabled={!razorpayLoaded}
                  >
                    {razorpayLoaded ? "Open Razorpay TEST checkout" : "Loading checkout…"}
                  </button>
                  <button
                    type="button"
                    className="rgco-startover"
                    onClick={() => { setSession(null); setOutcome(null); }}
                  >
                    Start over
                  </button>
                </>
              )}

              {error && (
                <div className="rgco-err" role="alert">{error}</div>
              )}

              {outcome?.kind === "success" && (
                <div className="rgco-outcome" role="status">
                  <strong>Payment completed</strong>
                  <p>
                    The TEST payment for {selected ? `“${selected.name}”` : "the selected product"} was
                    completed and verified by the system.
                  </p>
                  {outcome.paymentId && <p>Payment reference: {outcome.paymentId}</p>}
                  <p>No real money moved — this was a Razorpay TEST transaction.</p>
                </div>
              )}
              {outcome?.kind === "failed" && (
                <div className="rgco-outcome rgco-outcome--fail" role="alert">
                  <strong>Payment could not be completed</strong>
                  <p><b>What happened:</b> {outcome.reason}</p>
                  <p><b>Money status:</b> No successful capture occurred — no money moved.</p>
                  <p><b>Recommended next step:</b> Try again — in TEST mode you can use the test payment card (4100 2800 0000 1007) to test payments.</p>
                </div>
              )}
            </div>

            {/* ══ TEST PAYMENT CARD CREDENTIALS ══ */}
            <div className="rgco-testcard-box" aria-label="Test payment card credentials">
              <div className="rgco-testcard-head">
                <div className="rgco-testcard-tag">
                  <span className="rgco-testcard-dot" aria-hidden="true" />
                  <span>TEST CARD FOR PAYMENT</span>
                </div>
                <span className="rgco-testcard-badge">Razorpay TEST</span>
              </div>

              <div className="rgco-testcard-main">
                <div className="rgco-testcard-num-group">
                  <span className="rgco-testcard-label">CARD NUMBER</span>
                  <div className="rgco-testcard-num-wrap">
                    <code className="rgco-testcard-number">4100 2800 0000 1007</code>
                    <button
                      type="button"
                      className="rgco-testcard-copy-btn"
                      onClick={() => handleCopyCard("4100 2800 0000 1007")}
                      aria-label="Copy test card number"
                      title="Copy card number to clipboard"
                    >
                      {copiedCard ? (
                        <>
                          <span className="rgco-testcard-check" aria-hidden="true">✓</span>
                          <span>Copied!</span>
                        </>
                      ) : (
                        <>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                          </svg>
                          <span>Copy</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>

                <div className="rgco-testcard-meta-grid">
                  <div className="rgco-testcard-meta-item">
                    <span className="rgco-testcard-meta-label">EXPIRY</span>
                    <span className="rgco-testcard-meta-val">12 / 28</span>
                  </div>
                  <div className="rgco-testcard-meta-item">
                    <span className="rgco-testcard-meta-label">CVV</span>
                    <span className="rgco-testcard-meta-val">123</span>
                  </div>
                  <div className="rgco-testcard-meta-item">
                    <span className="rgco-testcard-meta-label">OTP</span>
                    <span className="rgco-testcard-meta-val">Any OTP</span>
                  </div>
                </div>
              </div>

              <p className="rgco-testcard-note">
                Use card number <strong>4100 2800 0000 1007</strong> in the Razorpay checkout window for payment testing. No real money is charged.
              </p>
            </div>
          </section>

          <section className="rgco-guide" aria-label="What happens next">
            <h3 className="rgco-guide__h">WHAT HAPPENS NEXT?</h3>
            {GUIDE.map((g, i) => (
              <div className="rgco-guide__row" key={g.t}>
                <span className="rgco-guide__n">{i + 1}</span>
                <span className="rgco-guide__icon">{g.icon}</span>
                <span>
                  <p className="rgco-guide__t">{g.t}</p>
                  <p className="rgco-guide__s">{g.s}</p>
                </span>
              </div>
            ))}
          </section>

          <section className="rgco-brand" aria-label="Built with Razorpay">
            <h3 className="rgco-brand__h">BUILT WITH</h3>
            <div className="rgco-brand__row">
              <img src={razorpayLogo} alt="Razorpay" />
              <span className="rgco-brand__test">TEST MODE</span>
            </div>
            <p>Secure test payments powered by Razorpay.</p>
            <a href="https://razorpay.com/docs/" target="_blank" rel="noreferrer">Learn more →</a>
          </section>
        </div>
      </div>

      {/* ══ ILLUSTRATED FOOTER BAND ══ */}
      <section className="rgco-foot" aria-label="AI buyer readiness">
        <div className="rgco-foot__inner">
          <div className="rgco-foot__copy">
            <p className="rgco-foot__quote">
              AI buyers test real purchase flows<br />so your store is always ready.
            </p>
            <div className="rgco-foot__feats">
              <span className="rgco-foot__feat"><IconCube /><p>Real Products<span>from your catalog</span></p></span>
              <span className="rgco-foot__feat"><IconPay /><p>Test Payments<span>via Razorpay</span></p></span>
              <span className="rgco-foot__feat"><IconShieldCheck /><p>Complete Flow<span>order to confirmation</span></p></span>
              <span className="rgco-foot__feat"><IconShieldCheck /><p>No Real Charges<span>safe test environment</span></p></span>
            </div>
          </div>
          <div className="rgco-foot__art" aria-hidden="true">
            <svg viewBox="0 0 460 172" preserveAspectRatio="xMidYMid slice">
              <circle cx="380" cy="34" r="20" fill="#F5A25D" stroke="#24150F" strokeWidth="2.5" />
              <g fill="#FFFDF4" stroke="#24150F" strokeWidth="2">
                <ellipse cx="90" cy="30" rx="40" ry="11" />
                <ellipse cx="230" cy="22" rx="30" ry="9" />
              </g>
              <g stroke="#24150F" strokeWidth="2.5">
                <rect x="230" y="70" width="150" height="70" fill="#FFF6E3" />
                <rect x="242" y="78" width="126" height="18" fill="#FFFDF4" stroke="#25835D" />
                <text x="305" y="92" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="10" fontWeight="700" letterSpacing="1" fill="#24150F" stroke="none">RAZORGROWTH AI</text>
                <rect x="230" y="100" width="150" height="18" fill="#DC6545" />
                {Array.from({ length: 6 }).map((_, i) => (
                  <rect key={i} x={230 + i * 25} y={100} width={12} height={18} fill="#FFF3DF" stroke="none" />
                ))}
                <rect x="230" y="100" width="150" height="18" fill="none" />
                <rect x="286" y="124" width="32" height="16" fill="none" strokeWidth="2" />
                <circle cx="294" cy="132" r="5" fill="none" strokeWidth="1.6" />
                <line x1="299" y1="132" x2="308" y2="132" strokeWidth="1.6" />
                <line x1="305" y1="129" x2="305" y2="135" strokeWidth="1.6" />
                <rect x="246" y="124" width="34" height="16" fill="#D8E8F2" />
              </g>
              <g stroke="#24150F" strokeWidth="2">
                <rect x="120" y="104" width="74" height="30" fill="#E9B44C" />
                <rect x="120" y="96" width="74" height="10" fill="#DC6545" />
                <circle cx="140" cy="138" r="8" fill="#29170F" />
                <circle cx="174" cy="138" r="8" fill="#29170F" />
                <rect x="200" y="112" width="26" height="22" fill="#FFF6E3" />
              </g>
              <g stroke="#24150F" strokeWidth="2">
                <circle cx="60" cy="118" r="18" fill="#7FA88D" />
                <rect x="57" y="130" width="7" height="14" fill="#8A6A54" />
                <circle cx="410" cy="122" r="15" fill="#9DBE9B" />
                <rect x="407" y="132" width="7" height="12" fill="#8A6A54" />
              </g>
              <g stroke="#24150F" strokeWidth="2">
                <ellipse cx="110" cy="152" rx="120" ry="20" fill="#9DBE9B" />
                <ellipse cx="360" cy="154" rx="130" ry="22" fill="#7FA88D" />
                <ellipse cx="230" cy="160" rx="150" ry="16" fill="#F9EBD7" />
              </g>
              <g stroke="#5E8F6E" strokeWidth="1.6">
                <line x1="80" y1="150" x2="80" y2="142" />
                <line x1="150" y1="154" x2="150" y2="146" />
                <line x1="330" y1="152" x2="330" y2="144" />
              </g>
            </svg>
          </div>
        </div>
      </section>
    </div>
  );
}
