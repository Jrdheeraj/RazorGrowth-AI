<div align="center">

# 🚀 RazorGrowth AI

### **Your AI Growth Team for Razorpay — it finds the revenue, explains the why, and waits for your approval.**

![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688?style=flat-square&logo=fastapi)
![React](https://img.shields.io/badge/frontend-React%2019%20%2B%20TypeScript-61dafb?style=flat-square&logo=react)
![PostgreSQL](https://img.shields.io/badge/db-PostgreSQL%2016%20%2B%20pgvector-336791?style=flat-square&logo=postgresql)
![Razorpay](https://img.shields.io/badge/payments-Razorpay%20TEST%20mode-0c2451?style=flat-square)
![LLM](https://img.shields.io/badge/LLM-OpenRouter%20free%20%2B%20Groq%20%2B%20OpenAI-8b5cf6?style=flat-square)
![Tests](https://img.shields.io/badge/tests-673%20passing-brightgreen?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

**RazorGrowth AI ingests a merchant's real Razorpay TEST-mode business data, runs a team of 13 specialised AI agents over it, debates the findings, and turns the strongest opportunity into a bounded, explainable, human-approved action — with an immutable audit trail on every step. It also includes an AI Buyer that reads the merchant's catalog and completes a genuine Razorpay TEST purchase end-to-end.**

*Every number is real. Every money action is explained, bounded, gated by human approval, and auditable.*

<br>

<img src="frontend/src/assets/homepage.png" alt="RazorGrowth AI — home" width="880">

</div>

---

## 📖 What is RazorGrowth AI?

Merchants on Razorpay have real data — successful payments, failed payments, repeat customers, product catalogs — but no systematic way to turn it into decisions. RazorGrowth AI is the decision layer between raw commerce data and action:

> **Data in → AI team analyses → agents debate the evidence → you approve → the system executes → every step is audited.**

The system is built like a company staffed with AI employees: a Growth **Manager** who coordinates, four **specialists** (Marketing, Product, Design/UX, Technology) who investigate and cross-examine each other's findings, and a bench of eight **domain experts** (payment recovery, customer intelligence, revenue optimisation, campaign strategy, experimentation, growth memory, discovery, prioritisation). No single agent decides alone — important conclusions are reached through structured multi-agent debate, then gated behind human approval.

**Who it's for:** Razorpay merchants (TEST mode today) who want to know *what is happening in my business, why it matters, and what to do next* — without trusting a black box with their money.

---

## ✨ Core Features

### 📡 Growth Radar
A live business-health dashboard computed from real Razorpay TEST data — revenue captured, transactions, customers, orders, average order value, failed payments — followed by a **plain-English business summary generated from that data**, detected growth signals ranked by confidence, and the priority opportunity. Signals cover revenue change, repeat-purchase decline, payment failures, dormant customers, and unusual order behaviour. Missing data produces an honest empty state — never invented numbers.

### 🧠 AI Growth Team
Thirteen specialised agents (see the [AI Team](#-the-ai-team) table) execute a collaborative pipeline over the merchant's data: retrieve evidence → analyse → produce findings → create ranked opportunities with confidence and expected revenue → prepare recommendations. Agents hold a **capability model** that structurally forbids them from approving actions, bypassing guardrails, or touching money — they can only *propose*.

### ⚖️ Agent Debates
Specialist agents don't just report — they **cross-examine each other** across structured rounds (investigate → cross-examine → rebut → synthesise), with findings classified as *supporting / opposing / uncertainty* and the Growth Manager synthesising a final recommendation. A **Groq/LLM-powered chat assistant** on the debate page answers merchant questions ("why was this recommended?", "which agent contributed?") using only that debate's context.

### 🛡️ Actions & Human Approval
Every money-touching action is **explainable** (why it was recommended, evidence, scope, amount, who/what is affected), **bounded** (an explicit will-do / will-not-do list, guardrail amount ceilings, campaign audience limits, discount percentage caps), and **gated** — agents propose, but only a merchant **owner/admin** can approve or reject. Approved actions execute behind double guardrails with idempotency, and an **immutable audit trail** records every step with AI / YOU / SYS actor markers.

### 🤖 AI Buyer Checkout
An AI buyer reads the merchant's real catalog, selects a product at its real price, creates a Razorpay TEST order, and completes payment. **Success and failure are both honest** — the declined test card produces a real "payment could not be completed" safe state: no money captured, no automatic retry, a clear recovery path. Never a fabricated result.

### 🔐 Multi-Tenant Security
JWT authentication with scrypt password hashing, merchant-scoped roles (`owner / admin / operator / analyst`), and strict tenant isolation: every query is scoped to the authenticated user's workspace. Cross-tenant access returns `403`; logged-out requests return `401` — there is no anonymous fallback and no shared data. Razorpay records belong to exactly one workspace and are never copied across merchants.

### 🧮 Business Data Intelligence
Razorpay TEST ingestion (orders, payments, customers), a RAG knowledge store with pgvector embeddings, deterministic opportunity scoring (revenue potential × confidence × urgency × evidence strength), revenue-impact simulations with confidence bands, A/B experiment design, growth memory that learns from prior outcomes, and per-merchant customer intelligence (LTV, churn risk, payment success).

### 🔌 Multi-Provider LLM Layer
One provider abstraction — **OpenRouter (free models only) · Groq · OpenAI** — selected by a single `LLM_PROVIDER` setting. Free-model enforcement is in code: the OpenRouter provider refuses to construct unless the model id ends with `:free`; there is no paid fallback and no silent provider switch.

---

## 🧠 The AI Team

Populated from `backend/app/agents/registry.py` — 13 agents in two groups:

### Main Growth Team (runs the debate pipeline)

| Agent | Responsibility | Input | Output |
|---|---|---|---|
| **ManagerAgent** | Top-level coordinator — decomposes objectives, delegates, manages the debate, synthesises | Merchant RAG context, objective | Action plan, debate coordination, final synthesis |
| **MarketingAgent** | Customer segments, retention / win-back campaigns, messaging strategy | Customer intelligence, verified facts | Campaign recommendations with evidence |
| **ProductAgent** | Upsell / cross-sell discovery, product affinity, product strategy | Orders, order items, product catalog | Product growth opportunities with evidence |
| **DesignerAgent** | Campaign creatives, messaging, experiment variants, UX recommendations | Debate context, prior findings | Creative briefs for human approval |
| **SoftwareAgent** | Technical implementation planning, feasibility, integration requirements | Findings, action plan | Engineering specifications |

### Domain Specialists (support the analysis pipeline)

| Agent | Responsibility | Input | Output |
|---|---|---|---|
| **GrowthDiscoveryAgent** | Detects revenue, churn, and payment signals | Radar signals, commerce data | Deduplicated, scored opportunities |
| **CustomerIntelligenceAgent** | LTV, recency, frequency, payment success, churn risk | Customers, orders, payments | Segment metrics + churn-risk insights |
| **RevenueOptimizationAgent** | Ranks opportunities, proposes highest-impact bounded action | Open opportunities, scoring engine | Discount / campaign proposals |
| **CampaignStrategistAgent** | Designs campaigns (segment, objective, channel, offer) | Customer segments | Human-approved campaign actions |
| **PaymentRecoveryAgent** | Finds failed payments worth recovering, quantifies value | Failed payments | Retry actions (still require approval) |
| **OpportunityPrioritizationAgent** | Scores and ranks open opportunities | Deterministic scoring engine | Best-first opportunity queue |
| **ExperimentAgent** | Designs honest A/B experiments (control vs treatment) | Top opportunity | Experiments (pending until real data) |
| **GrowthMemoryAgent** | Remembers prior recommendations and outcomes | Past runs, memories | History that grounds new recommendations |

**Orchestration & persistence.** `GrowthAgentOrchestrator` executes a mode-specific plan (`fast` / `deep` / `team` / `growth_team`). Specialists share findings through a common context; debate turns are grounded by the configured LLM; every run is recorded in `agent_runs` (status, latency, provider, model, tools used, outputs). **Failure handling:** each agent runs inside a savepoint — a failed agent rolls back only its own work, its error is recorded, and the run reports `partial_success` when some agents succeed; a run only fails when every agent fails.

---

## ⚖️ How an Agent Debate Works

```mermaid
flowchart TB
    RZP[Razorpay TEST Account] -->|ingestion: orders, payments, customers| DB[(PostgreSQL)]
    DB --> RADAR[Growth Radar<br/>signal detection]
    RADAR --> MGR[ManagerAgent<br/>decomposes objective]

    subgraph DEBATE [Structured multi-agent debate]
        MGR -->|delegates tasks| SPEC[Specialists:<br/>Marketing · Product · Designer · Software]
        SPEC -->|investigate| F1[Findings: supporting / opposing / uncertainty]
        F1 -->|cross-examine| SPEC
        F1 -->|rebut| SPEC
        SPEC --> SYN[Manager synthesises]
    end

    SYN --> REC[Final Recommendation]
    REC --> OPP[Ranked Opportunities<br/>confidence · expected revenue · evidence]
    OPP --> ACT[Action prepared:<br/>explainable + bounded]
    ACT -->|APPROVE / REJECT — human only| HUMAN[Merchant owner / admin]
    HUMAN -->|approved| EXE[Execution behind double guardrails]
    EXE --> AUDIT[Immutable audit trail<br/>AI / YOU / SYS on every step]
    EXE -->|failure| SAFE[Safe state — no unauthorised money action]

    classDef human fill:#f7ebd7,stroke:#2a1810,stroke-width:2px,color:#2a1810
    class HUMAN human
```

Every arrow is enforced in code: agents **cannot** approve (the capability model forbids it), approval endpoints are restricted to owner/admin roles, guardrails re-evaluate immediately before execution, and failed executions persist a safe-state audit event. Debate turns are real LLM reasoning grounded in the merchant's verified data — never canned responses.

---

## 👤 The User Journey

```mermaid
flowchart LR
    A[Sign up] --> B[Own workspace<br/>+ own default catalog]
    B --> C[Razorpay TEST data<br/>synced to YOUR workspace]
    C --> D[Growth Radar<br/>signals & business summary]
    D --> E[AI Team analysis<br/>13 agents]
    E --> F[Agent Debate<br/>cross-examination]
    F --> G[Ranked opportunities<br/>with evidence]
    G --> H[Action review<br/>why · scope · boundaries]
    H --> I{Human approval}
    I -->|approved| J[Execution + audit trail]
    I -->|rejected| K[Stopped — nothing runs]
    B --> L[Checkout<br/>AI Buyer completes a TEST order]
```

1. **Sign up** → a new user, a new workspace, one owner membership, and a 10-product default catalog — instantly
2. **Growth Radar** → real Razorpay TEST signals with a plain-English summary
3. **AI Team** → start an analysis; watch the agents run and persist findings
4. **Debates** → specialists cross-examine each other; the manager synthesises a recommendation
5. **Opportunities** → ranked with confidence, expected revenue, and evidence
6. **Actions** → inspect the prepared action: why, evidence, scope, and explicit boundaries
7. **Approve → Run** → execute and watch the audit trail record every step
8. **Checkout** → the AI Buyer reads your catalog and completes a Razorpay TEST order

---

## 🏛️ Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  FRONTEND — React 19 · TypeScript · Vite                          │
│  Home · Login/Signup · Growth Radar · AI Team · Debates          │
│  Growth Actions · AI Buyer Checkout · Profile                      │
└──────────────────────────────┬─────────────────────────────────────┘
                        REST /api + Bearer JWT
┌──────────────────────────────▼─────────────────────────────────────┐
│  BACKEND — FastAPI · SQLAlchemy 2.0 · Alembic                       │
│                                                                      │
│  ┌────────────┐ ┌───────────────┐ ┌──────────────────────────────┐  │
│  │ Radar      │ │ 13 AI Agents  │ │ Opportunity Engine           │  │
│  │ signals    │ │ + Debate      │ │ (scoring · ranking · sims)   │  │
│  └────────────┘ └──────┬────────┘ └──────────────────────────────┘  │
│  ┌─────────────────────▼─────────────────────────────────────────┐  │
│  │ Action layer: guardrails → human approval → executors           │  │
│  │              + immutable audit events                           │  │
│  └─────────────────────┬─────────────────────────────────────────┘  │
│  ┌─────────────────────▼─────────────────────────────────────────┐  │
│  │ LLM provider layer: OpenRouter (free-only) · Groq · OpenAI     │  │
│  └───────────────────────────────────────────────────────────────┘  │
└────────┬───────────────────────────────────────────────┬────────────┘
         │                                               │
   ┌─────▼──────────────┐                      ┌─────────▼───────────┐
   │ PostgreSQL 16      │                      │ Razorpay TEST APIs   │
   │ + pgvector (Docker)│                      │ orders · payments ·  │
   │ tenant-isolated    │                      │ customers            │
   └────────────────────┘                      └─────────────────────┘
```

**Tenant isolation is enforced at the data layer**: every merchant-owned query filters by the authenticated user's workspace, and the Razorpay ingestion carries a cross-tenant ownership guard so one workspace's checkout records can never be copied into another merchant's workspace.

---

## 🛠️ Tech Stack

| Layer | Technologies |
|---|---|
| Backend | FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, Pydantic-Settings |
| Database | PostgreSQL 16 + pgvector (Docker Compose) |
| Auth | JWT (PyJWT), scrypt password hashing, role-based multi-tenancy |
| Payments | Razorpay Python SDK (TEST mode, HMAC-SHA256 signed webhooks) |
| LLM | OpenRouter (free-only) / Groq / OpenAI via one provider abstraction |
| Frontend | React 19, TypeScript 5.7, Vite 6, custom editorial design system |

---

## ⚡ Quick Start

### Prerequisites
Python 3.11+ · Node.js 18+ · Docker

### 1 — Clone and start PostgreSQL
```bash
git clone <repository-url> && cd "RazorGrowth AI"
docker compose up -d        # PostgreSQL 16 + pgvector on :5432
```

### 2 — Backend
```bash
pip install -r requirements.txt
cp .env.example .env         # then fill in the values from the table below
alembic upgrade head          # create the schema
uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

### 3 — Frontend
```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173 (Vite proxies /api → :8001)
```

### 4 — Create your account
Open `http://localhost:5173/login` and sign up — signup creates **your own workspace with its own 10-product default catalog**, so Checkout works immediately without any Razorpay connection.

<details>
<summary><b>Optional — bootstrap an admin on an existing workspace</b></summary>

```bash
python -m backend.app.data.bootstrap_admin --email <email> --password '<12+ chars, letter+digit>'
```
</details>

---

## 🔧 Environment Variables

Copy `.env.example` to `.env` and configure. **Variable names only** — never commit real secrets.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `AUTH_MODE` | `required` — protected endpoints demand a Bearer token |
| `AUTH_SECRET_KEY` | JWT signing key (≥ 32 chars) |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Razorpay **TEST** credentials |
| `RAZORPAY_ENABLED` / `RAZORPAY_TEST_MODE` / `REAL_TEST_INTEGRATION_ENABLED` | TEST-mode switches |
| `RAZORPAY_WEBHOOK_SECRET` | Webhook signature validation |
| `LLM_PROVIDER` | `openrouter` \| `groq` \| `openai` |
| `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` | OpenRouter — model id **must** end in `:free` (enforced in code) |
| `GROQ_API_KEY` / `GROQ_MODEL` | Groq configuration |
| `LLM_API_KEY` / `LLM_MODEL` | OpenAI configuration |
| `EXECUTION_ENABLED` | Global action-execution kill switch |
| `GUARDRAIL_MAX_AMOUNT_INR` / `GUARDRAIL_REQUIRE_APPROVAL` | Money-action guardrails |
| `CORS_ORIGINS` / `TRUSTED_HOSTS` | Security middleware |

---

## 🧪 Development

```bash
pytest                        # backend suite (673 tests)
cd frontend && npm run build  # TypeScript check + production build
```

Tests run against an isolated SQLite schema with JSONB-compatible DDL — they never touch your PostgreSQL data. A small number of end-to-end tests exercise live LLM calls and may be skipped when the provider's rate limit window is active; they are not required for the core suite.

### Common setup issues

| Symptom | Cause / fix |
|---|---|
| `Database not initialised` on first request | Run `alembic upgrade head` before starting uvicorn |
| `422` on signup | Password policy: ≥ 12 characters, at least one letter and one digit |
| Empty Radar on a new account | Expected until that workspace connects its own Razorpay data — the default catalog still powers Checkout |
| `RAZORPAY_CREATE_PAYMENT_LINK_FAILED` in logs | Razorpay TEST caps payment links at 30/day; checkout continues via the order id |
| LLM `429` responses | Provider rate limit — retry after the window; free models only, no paid fallback |

---

## 📁 Project Structure

```
RazorGrowth AI/
├── backend/app/
│   ├── agents/              # 13 specialised agents + orchestrator + registry
│   ├── ai/llm/              # provider layer: OpenRouter (free-only) · Groq · OpenAI
│   ├── api/routes/          # auth, radar, agents, debates, actions, payments, webhooks…
│   ├── core/                # config, security, middleware, secret-redacting logs
│   ├── data/                # deterministic seed, workspace bootstrap, admin tools
│   ├── integrations/        # Razorpay client (TEST-mode boundary, honest refusals)
│   ├── models/              # SQLAlchemy models (tenant-scoped)
│   ├── repositories/        # data-access layer
│   ├── schemas/             # Pydantic API contracts
│   └── services/           # radar, ingestion, actions, executors, scoring, debate…
├── frontend/src/
│   ├── components/          # WindowPanel, buttons, header (editorial design system)
│   ├── features/public/     # marketing sections + Agent Debate UI
│   ├── pages/               # Home, GrowthRadar, AgentsPage, DebatePage,
│   │                        # ActionsPage, Checkout, Login, Profile
│   ├── lib/                 # typed API client, auth context
│   └── styles/              # design tokens (cream / ink / terracotta)
├── migrations/versions/     # Alembic migrations (Phases 3–6 + alignment)
├── tests/                   # 673-test pytest suite
├── docker-compose.yml       # PostgreSQL 16 + pgvector
├── requirements.txt
└── .env.example             # annotated configuration template (blank secrets)
```

---

## 🎯 Hackathon Track: AI Growth & Agentic Commerce

Every claim below maps to shipped functionality:

| Track requirement | Where it exists |
|---|---|
| Real Razorpay TEST data | Genuine TEST-mode integration — orders created & verified on Razorpay endpoints, ingested per-merchant |
| AI agents | 13 specialised agents with a capability/permission model |
| Upsell & cross-sell | ProductAgent affinity analysis from real order items |
| Payment recovery | PaymentRecoveryAgent → bounded retry action for the highest-value failure |
| Campaign opportunities | CampaignStrategistAgent → human-approved campaign action |
| Agentic workflow | detect → analyse → debate → propose → approve → execute → audit |
| Human approval | Owner/admin-only approve & reject; agents structurally cannot approve |
| Explainable, bounded actions | Every action shows why, evidence, scope, amount, and will-do / will-not-do |
| Audit trail | Per-action timeline of every step, merchant-friendly rendering |
| Graceful failure | Checkout failure = honest safe state (no capture, retry path); execution failures persist a safe-state audit event |
| AI buyer commerce | AI Buyer reads the real catalog → real-price Razorpay TEST order → payment result |

### 10-minute demo flow
1. **Sign up** → your own workspace + default catalog appears instantly
2. **Growth Radar** → real Razorpay TEST signals with a plain-English summary
3. **Start AI analysis** → watch 13 agents run and persist findings
4. **Open the Debate** → read the cross-examination; ask the debate assistant a question
5. **Growth Actions** → inspect the prepared action: why, evidence, scope, boundaries
6. **Approve → Run** → execute and watch the audit trail record every step
7. **Checkout** → select a real product, create a Razorpay TEST order, pay with test card `4111 1111 1111 1111`
8. **Failure demo** → use a declined test card: the honest "payment could not be completed" safe state appears

---

## 🗺️ Roadmap

Items below are **not yet implemented** — recorded as direction only:

- Live Razorpay execution path (currently refused honestly behind feature flags)
- Multi-merchant agency view
- Automated A/B measurement on executed campaigns
- Streaming agent activity during debate rounds

---

## 🔒 Security & Safety

- **Fail-closed Razorpay boundary** — execution requires explicit enablement; live mode refuses honestly until deliberately implemented
- **Signed webhooks** — HMAC-SHA256 validation; unsigned deliveries are rejected
- **Secret-safe logging** — a log filter redacts every configured secret value
- **Rate limiting** — sliding-window limits on auth and webhook endpoints
- **Production fail-fast** — startup refuses weak JWT secrets / unsafe hosts
- **Guardrails everywhere** — amount ceilings, approval gates, idempotent execution, immutable audit events

---

## 📄 License

Released under the [MIT License](LICENSE) — Copyright © 2026 DHEERAJ
