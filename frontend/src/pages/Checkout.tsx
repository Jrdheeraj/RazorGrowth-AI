import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useReveal } from "../lib/useReveal";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import { createCheckoutSession, verifyPayment as verifyPaymentRequest } from "../lib/api";

declare global {
  interface Window {
    Razorpay: any;
  }
}

export function Checkout() {
  const navigate = useNavigate();
  const reveal = useReveal<HTMLDivElement>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkoutData, setCheckoutData] = useState<{
    razorpay_order_id: string;
    amount: number;
    currency: string;
    key_id: string;
  } | null>(null);
  const [razorpayLoaded, setRazorpayLoaded] = useState(false);

  // Load Razorpay Checkout JS script
  useEffect(() => {
    if (window.Razorpay) {
      setRazorpayLoaded(true);
      return;
    }

    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = () => setRazorpayLoaded(true);
    script.onerror = () => setError("Failed to load Razorpay Checkout script");
    document.body.appendChild(script);

    return () => {
      document.body.removeChild(script);
    };
  }, []);

  const initiateCheckout = async () => {
    setLoading(true);
    setError(null);

    try {
      // Step 1: Create checkout session on backend
      const requestBody = {
        amount: 100, // ₹100 test amount
        currency: "INR",
        description: "Razorpay TEST Checkout",
        customer_email: "test@example.com",
        receipt: `receipt_${Date.now()}`,
      };

      const data = await createCheckoutSession(requestBody);
      setCheckoutData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to initiate checkout");
    } finally {
      setLoading(false);
    }
  };

  const openRazorpayCheckout = () => {
    if (!checkoutData || !razorpayLoaded || !window.Razorpay) {
      setError("Razorpay Checkout not loaded");
      return;
    }

    const options = {
      key: checkoutData.key_id,
      amount: checkoutData.amount * 100, // Razorpay expects amount in paise
      currency: checkoutData.currency,
      name: "RazorGrowth AI",
      description: "Razorpay TEST Checkout",
      order_id: checkoutData.razorpay_order_id,
      theme: { color: "#0d9488" },
      handler: async (response: any) => {
        // Payment successful - verify on backend
        await verifyPayment(response);
      },
      modal: {
        ondismiss: () => {
          setError("Payment cancelled");
        },
      },
    };

    const rzp = new window.Razorpay(options);
    rzp.open();
  };

  const verifyPayment = async (response: any) => {
    setLoading(true);
    setError(null);

    try {
      const data = await verifyPaymentRequest({
        razorpay_order_id: response.razorpay_order_id,
        razorpay_payment_id: response.razorpay_payment_id,
        razorpay_signature: response.razorpay_signature,
      });

      if (data.verified) {
        setError(null);
        alert("Payment successful! Payment ID: " + data.payment_id);
        // Navigate to success page or refresh
        window.location.reload();
      } else {
        setError("Payment verification failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment verification failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section id="checkout" className="shell section" aria-labelledby="checkout-heading">
      <div className="page-hero" style={{ paddingBottom: 0 }}>
        <p className="meta-label">CHECKOUT · RAZORPAY TEST MODE</p>
        <h2 id="checkout-heading" className="display-lg" style={{ marginTop: 10 }}>
          Razorpay TEST Checkout
        </h2>
      </div>

      <div ref={reveal} className="reveal">
        <WindowPanel title="Razorpay TEST Checkout" tone="choc" dark>
          <p style={{ color: "var(--cream-muted)", maxWidth: "60ch" }}>
            Complete a genuine Razorpay TEST payment. This uses real Razorpay TEST MODE APIs.
            No real money is charged. Use test card: <strong>4111 1111 1111 1111</strong>
          </p>

          <div style={{ marginTop: 24, display: "flex", flexDirection: "column", gap: 16, alignItems: "flex-start" }}>
            <div style={{ padding: 16, background: "var(--navy)", borderRadius: 8, border: "1px solid var(--teal)", maxWidth: 400 }}>
              <p className="meta-label">TEST MODE</p>
              <p style={{ fontSize: "1.2rem", fontWeight: 600, color: "var(--teal)" }}>
                ₹100.00 INR
              </p>
              <p className="meta-label" style={{ marginTop: 8 }}>
                Test order will be created on Razorpay TEST mode
              </p>
            </div>

            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <Button
                onClick={initiateCheckout}
                disabled={loading}
                style={{ minWidth: 200 }}
              >
                {loading ? "Creating order..." : "Create TEST Order"}
              </Button>

              {checkoutData && !loading && (
                <Button
                  onClick={openRazorpayCheckout}
                  disabled={loading || !razorpayLoaded}
                  variant="primary"
                  style={{ minWidth: 200 }}
                >
                  {loading ? "Verifying..." : "Open Razorpay Checkout"}
                </Button>
              )}

              {!razorpayLoaded && (
                <span className="meta-label" style={{ alignSelf: "center" }}>
                  Loading Razorpay Checkout...
                </span>
              )}
            </div>

            {error && (
              <div style={{ marginTop: 16, padding: 12, background: "rgba(239, 68, 68, 0.1)", border: "1px solid #ef4444", borderRadius: 8, color: "#ef4444" }}>
                <strong>Error:</strong> {error}
              </div>
            )}

            {checkoutData && !error && !loading && (
              <div style={{ marginTop: 16, padding: 12, background: "rgba(13, 148, 136, 0.1)", border: "1px solid var(--teal)", borderRadius: 8 }}>
                <p className="meta-label">Order Created</p>
                <p style={{ fontFamily: "monospace", fontSize: "0.9rem" }}>
                  Order ID: {checkoutData.razorpay_order_id}
                </p>
                <p className="meta-label" style={{ marginTop: 8 }}>
                  Click "Open Razorpay Checkout" to complete the TEST payment
                </p>
              </div>
            )}
          </div>
        </WindowPanel>
      </div>
    </section>
  );
}