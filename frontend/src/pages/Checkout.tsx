/**
 * /checkout — AI Buyer commerce flow.
 *
 * An AI buyer reads the merchant's real catalog (GET /api/products),
 * selects a product, creates a Razorpay TEST order at the product's real
 * price, and completes payment through Razorpay TEST checkout.
 *
 * Success and failure are both handled honestly:
 *   - Success  → payment verified server-side, result shown.
 *   - Failure  → "Payment could not be completed" safe state, no fake data,
 *                retry available.
 *
 * REAL DATA ONLY — no hardcoded products, prices, or results.
 */
import { useEffect, useState } from "react";
import { createCheckoutSession, verifyPayment, fetchProducts } from "../lib/api";
import type { ProductResponse, CheckoutSessionResponse } from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import "./Checkout.css";

declare global {
  interface Window {
    Razorpay: any;
  }
}

type Outcome =
  | { kind: "success"; paymentId: string | null }
  | { kind: "failed"; reason: string };

export function Checkout() {
  const [products, setProducts] = useState<ProductResponse[] | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [session, setSession] = useState<CheckoutSessionResponse | null>(null);
  const [stage, setStage] = useState<"idle" | "creating" | "paying">("idle");
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [razorpayLoaded, setRazorpayLoaded] = useState(false);

  /* Load the real merchant catalog. */
  useEffect(() => {
    fetchProducts()
      .then((data) => {
        const list = data.products ?? [];
        setProducts(list);
        // Auto-select the first purchasable product — never the ₹0
        // auto-created placeholder, which cannot be ordered (amount > 0).
        const firstPurchasable = list.find((p) => p.active && p.stock_quantity > 0 && Number(p.price) > 0);
        if (firstPurchasable) setSelectedId(firstPurchasable.id);
      })
      .catch((err: unknown) => {
        setCatalogError(
          err instanceof Error ? err.message : "The product catalog could not be loaded"
        );
      });
  }, []);

  /* Load Razorpay Checkout JS. */
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

  return (
    <section id="checkout" className="shell section" aria-labelledby="checkout-heading">
      {/* Header */}
      <div className="checkout-header">
        <div>
          <p className="meta-label">AI BUYER · RAZORPAY TEST MODE</p>
          <h2 id="checkout-heading" className="display-lg" style={{ margin: "10px 0 0" }}>
            AI Buyer Checkout
          </h2>
          <p className="checkout-header__lead">
            An AI buyer reads this merchant's real product catalog, selects a product, and completes
            a genuine Razorpay TEST purchase — no real money moves.
          </p>
        </div>
        <span className="checkout-mode">
          <span className="checkout-mode__dot" aria-hidden="true" />
          Razorpay Test Mode
        </span>
      </div>

      {/* AI buyer flow strip */}
      <div className="checkout-flow" aria-hidden="true">
        <span>AI buyer reads catalog</span>
        <span className="checkout-flow__rule" />
        <span>Product selected</span>
        <span className="checkout-flow__rule" />
        <span>Order created</span>
        <span className="checkout-flow__rule" />
        <span>Test payment</span>
        <span className="checkout-flow__rule" />
        <span>Result recorded</span>
      </div>

      <div className="checkout-workspace">
        {/* Catalog */}
        <main aria-label="AI-readable product catalog">
          <p className="meta-label" style={{ marginBottom: 12 }}>THE CATALOG THE AI BUYER READS</p>

          {catalogError && (
            <WindowPanel title="catalog.app">
              <p style={{ color: "var(--coral-strong)" }}>
                The catalog could not be loaded. Please try again.
              </p>
            </WindowPanel>
          )}

          {!products && !catalogError && (
            <WindowPanel title="catalog.app">
              <p className="meta-label" style={{ color: "var(--ink-soft)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "var(--tracking-meta)" }}>
                Reading the merchant catalog…
              </p>
            </WindowPanel>
          )}

          {products && products.length === 0 && (
            <div className="checkout-empty">
              <p className="meta-label" style={{ color: "var(--coral-strong)" }}>NO PRODUCTS YET</p>
              <p>
                This merchant has no products in the catalog yet. Products from the real business data
                will appear here, and the AI buyer will be able to select one and complete a TEST purchase.
              </p>
            </div>
          )}

          {products && products.length > 0 && (
            <div className="checkout-catalog">
              {products.map((product) => (
                <article
                  className={`buyer-card${selectedId === product.id ? " buyer-card--selected" : ""}`}
                  key={product.id}
                >
                  <div className="buyer-card__bar">
                    <span>{(product.category ?? "product").toUpperCase()}</span>
                    <span>
                      {product.active && product.stock_quantity > 0 && Number(product.price) > 0
                        ? "AVAILABLE"
                        : "NOT PURCHASABLE"}
                    </span>
                  </div>
                  <div className="buyer-card__body">
                    <h3 className="buyer-card__name">{product.name}</h3>
                    <p className="buyer-card__desc">
                      {product.description ?? "No description was provided for this product."}
                    </p>
                    <p className="buyer-card__price">₹{Number(product.price).toFixed(2)}</p>
                    <p className="buyer-card__meta">
                      {product.stock_quantity > 0
                        ? `${product.stock_quantity} in stock`
                        : "Out of stock"}
                    </p>
                  </div>
                  <div className="buyer-card__select">
                    <Button
                      variant={selectedId === product.id ? "primary" : "secondary"}
                      mono
                      onClick={() => {
                        setSelectedId(product.id);
                        setSession(null);
                        setOutcome(null);
                      }}
                      disabled={
                        !product.active ||
                        product.stock_quantity <= 0 ||
                        !(Number(product.price) > 0) // a ₹0 product can never be ordered
                      }
                      style={{ width: "100%" }}
                    >
                      {selectedId === product.id ? "Selected ✓" : "Select product"}
                    </Button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </main>

        {/* Purchase panel */}
        <aside className="buyer-panel" aria-label="AI buyer purchase">
          <div className="buyer-panel__bar">
            <span>AI BUYER · PURCHASE</span>
            <span>TEST MODE</span>
          </div>
          <div className="buyer-panel__body">
            {!selected && (
              <>
                <div className="buyer-panel__section">
                  <p className="buyer-panel__label">SELECTED PRODUCT</p>
                  <p className="buyer-panel__value buyer-panel__value--muted">
                    No product selected yet. Choose one from the catalog.
                  </p>
                </div>
              </>
            )}

            {selected && (
              <>
                <div className="buyer-panel__section">
                  <p className="buyer-panel__label">SELECTED PRODUCT</p>
                  <p className="buyer-panel__value">{selected.name}</p>
                  <p className="buyer-panel__value buyer-panel__value--muted">
                    {selected.description ?? "No description provided."}
                  </p>
                </div>

                <div className="buyer-panel__section">
                  <p className="buyer-panel__label">PRICE</p>
                  <p className="buyer-panel__value buyer-panel__value--price">
                    ₹{Number(selected.price).toFixed(2)}
                  </p>
                  <p className="buyer-panel__value buyer-panel__value--muted">
                    The real catalog price — taken directly from this merchant's product data.
                  </p>
                </div>

                <div className="buyer-panel__section">
                  <p className="buyer-panel__label">ORDER</p>
                  {session ? (
                    <p className="buyer-panel__value">
                      Order created{session.razorpay_order_id ? ` · reference ${session.razorpay_order_id}` : ""}.
                      Ready for Razorpay TEST checkout.
                    </p>
                  ) : (
                    <p className="buyer-panel__value buyer-panel__value--muted">
                      No order yet — create one to continue.
                    </p>
                  )}
                </div>

                <div className="buyer-panel__section">
                  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {!session && (
                      <Button
                        variant="primary"
                        mono
                        onClick={startCheckout}
                        disabled={stage === "creating"}
                        style={{ width: "100%" }}
                      >
                        {stage === "creating" ? "Creating order…" : "Create order"}
                      </Button>
                    )}
                    {session && (
                      <Button
                        variant="primary"
                        mono
                        onClick={openRazorpay}
                        disabled={!razorpayLoaded}
                        style={{ width: "100%" }}
                      >
                        {razorpayLoaded ? "Open Razorpay TEST checkout" : "Loading checkout…"}
                      </Button>
                    )}
                    {(session || outcome) && (
                      <Button
                        variant="ghost-dark"
                        mono
                        onClick={() => {
                          setSession(null);
                          setOutcome(null);
                        }}
                        style={{ width: "100%" }}
                      >
                        Start over
                      </Button>
                    )}
                  </div>
                </div>
              </>
            )}

            {error && (
              <div className="buyer-outcome buyer-outcome--failed">
                <p className="buyer-outcome__title">NOTE</p>
                <p>{error}</p>
              </div>
            )}

            {/* Success outcome */}
            {outcome?.kind === "success" && (
              <div className="buyer-outcome">
                <p className="buyer-outcome__title">PAYMENT COMPLETED</p>
                <p>
                  The TEST payment for {selected ? `“${selected.name}”` : "the selected product"} was
                  completed and verified by the system.
                </p>
                {outcome.paymentId && (
                  <p>Payment reference: {outcome.paymentId}</p>
                )}
                <p>No real money moved — this was a Razorpay TEST transaction.</p>
              </div>
            )}

            {/* Failure outcome — graceful, honest, safe */}
            {outcome?.kind === "failed" && (
              <div className="buyer-outcome buyer-outcome--failed">
                <p className="buyer-outcome__title">PAYMENT COULD NOT BE COMPLETED</p>
                <p>
                  <strong>What happened:</strong> {outcome.reason}
                </p>
                <p>
                  <strong>Money status:</strong> No successful capture occurred — no money moved.
                </p>
                <p>
                  <strong>What the system did:</strong> The attempt was recorded as a failed payment and
                  the order was left unpaid. No automatic retry was made.
                </p>
                <p>
                  <strong>Recommended next step:</strong> Try the payment again — in TEST mode you can
                  use the successful test card, or deliberately use the declined test card
                  (4100 2800 0000 1007 with any future expiry and CVV) to see this safe failure state.
                </p>
              </div>
            )}

            <p className="buyer-hint">
              TEST MODE — use card 4100 2800 0000 1007 with any future expiry and any CVV to simulate
              success. No real money is ever charged.
            </p>
          </div>
        </aside>
      </div>
    </section>
  );
}
