import React from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

async function loadOpportunities() {
  const res = await fetch("http://127.0.0.1:8000/api/opportunities");
  return res.json();
}

function App() {
  const [data, setData] = React.useState<any>(null);

  React.useEffect(() => {
    loadOpportunities().then(setData).catch(() => setData({items: []}));
  }, []);

  return (
    <main className="shell">
      <header>
        <div>
          <p className="eyebrow">RAZORGROWTH AI</p>
          <h1>Merchant Growth Command Center</h1>
          <p className="muted">AI-generated revenue opportunities from synthetic commerce data.</p>
        </div>
        <div className="status">● TEST MODE</div>
      </header>

      <section className="metrics">
        <div><span>Revenue</span><strong>₹4.2L</strong><small>synthetic baseline</small></div>
        <div><span>Orders</span><strong>200</strong><small>last 30 days</small></div>
        <div><span>Opportunities</span><strong>{data?.items?.length ?? "—"}</strong><small>AI detected</small></div>
        <div><span>AI confidence</span><strong>87%</strong><small>highest opportunity</small></div>
      </section>

      <section className="panel">
        <div className="panelHead">
          <div><p className="eyebrow">AI GROWTH ENGINE</p><h2>Recommended actions</h2></div>
          <button onClick={() => loadOpportunities().then(setData)}>Refresh analysis</button>
        </div>

        {!data ? <p className="muted">Analyzing merchant data…</p> :
          data.items.map((o: any) => (
            <article className="opportunity" key={o.id}>
              <div>
                <div className="tag">{o.type.replace("_", " ").toUpperCase()}</div>
                <h3>{o.title}</h3>
                <p className="muted">{o.reasoning.join(" ")}</p>
                <div className="chips">
                  <span>{Math.round(o.confidence * 100)}% confidence</span>
                  <span>Expected ₹{o.expected_revenue}</span>
                  <span>Approval required</span>
                </div>
              </div>
              <button className="primary">Review & Approve</button>
            </article>
          ))
        }
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>
);
