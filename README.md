# RazorGrowth AI

**AI Growth & Agentic Commerce platform for Razorpay merchants.**

RazorGrowth AI analyses merchant commerce data, detects revenue growth opportunities,
explains them with evidence-grounded reasoning, and enforces a human-approval gate before
any money-touching action could ever execute — with a full audit trail on every step.

> **Status:** active development (backend v0.3.0). Phase 5 Agentic Growth Intelligence is
> implemented: specialised agents, growth radar, opportunity scoring, customer/churn
> intelligence, what-if simulation, honest experiments, growth memory, explainability,
> and the Agentic Growth Control Center dashboard. See [docs/PHASE_5.md](docs/PHASE_5.md).

---

## Overview

- **What it does:** turns commerce data (merchants, products, customers, orders, payments)
  into structured growth opportunities — cross-sell, upsell, campaign, checkout
  optimization, failed-payment recovery — each with confidence, expected revenue, and reasoning.
- **The problem it solves:** merchants have data but no systematic way to detect and act
  on revenue opportunities. AI suggestions involving money are unsafe unless they are
  explained, bounded, approved by a human, and auditable.
- **Who it is designed for:** Razorpay merchants (currently operating in single-tenant
  test/synthetic-data mode; auth tokens are planned for a later phase).
- **Core workflow:** deterministic rule-based detection plus an optional Agentic RAG
  analysis layer → evidence-grounded explanation → mandatory human approval →
  (planned) bounded execution → measurement → immutable audit events.

## Key Features

**Implemented**

- Deterministic, reproducible synthetic commerce dataset with idempotent seeding.
- Rule-based growth engine producing a cross-sell opportunity from order patterns.
- REST API for health, opportunities, merchants, products, customers, orders, payments.
- Knowledge store (`knowledge_documents` / `knowledge_chunks`) with pgvector embeddings,
  SHA-256 checksum-based idempotent ingestion of production-table rows.
- **Agentic RAG pipeline**: the LLM selects which read-only tool to call next, evidence is
  accumulated over a bounded loop (max 3 steps), sufficiency is evaluated, and a structured,
  schema-validated analysis is synthesised.
- Money-action guardrail chain: policy → risk → amount bounds → approval gate.
- Immutable audit events for analysis lifecycle and ingestion.
- React + TypeScript + Vite dashboard displaying detected opportunities.

**Planned / scaffolded (not functional yet)**

- Action execution after merchant approval (Phase 4+; guardrails currently never execute anything).
- Approval endpoints — the frontend "Review & Approve" button is display-only today.
- Campaign measurement pipeline (`campaigns.estimated_revenue` / `actual_revenue` columns exist; no measurement logic yet).
- Authentication / multi-tenancy (merchant currently resolved from the first DB record when omitted).
- Live Razorpay integration (`RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` are placeholders only).

## Architecture

```
User / Merchant
        ↓
Frontend (React 19 + TypeScript + Vite)
        ↓  HTTP/JSON  (base URL currently hardcoded to 127.0.0.1:8000)
FastAPI API  (/api/*)
        ↓
Services   (growth engine · opportunity service · AI analysis service ·
            production data connector · knowledge service · entity services)
        ↓
Repositories  (SQLAlchemy 2.0 ORM data access)
        ↓
PostgreSQL 16 + pgvector   ← Docker (pgvector/pgvector:pg16)

AI layer:
AgenticRAGPipeline ──► AgentToolkit (read-only tools)
        │                       │
        │                       ▼
        │            KnowledgeRetriever
        │              ├─ pgvector cosine similarity (PostgreSQL)
        │              └─ keyword LIKE fallback (SQLite/tests)
        ▼
OpenAI LLM provider (JSON-mode, retrying, schema-validated output)
```

## AI Architecture

All AI components live under `backend/app/ai/`.

- **LLM abstraction** (`ai/llm/`) — `BaseLLMProvider` with an OpenAI implementation
  (`OpenAIProvider`). Supports plain generation and `generate_structured()`, which forces
  JSON response mode, validates output against a Pydantic schema (`GrowthAnalysisResult`),
  and retries transient errors. Provider/model/key/timeouts are configuration-driven;
  only the `openai` provider is currently supported.
- **Embedding layer** (`ai/embeddings/`) — `BaseEmbeddingProvider` with an OpenAI
  implementation (`text-embedding-3-small`, 1536 dimensions by default).
- **Agentic RAG pipeline** (`ai/rag/pipeline.py`) — *not* a simple query → vector search →
  LLM chain. The loop is:
  1. Agent receives a natural-language growth goal.
  2. LLM selects the most useful retrieval tool (JSON tool-selection step).
  3. Tool executes; evidence accumulates in `AgentState`.
  4. LLM evaluates whether more retrieval is needed; steps repeat up to `MAX_RETRIEVAL_STEPS = 3`.
  5. Evidence sufficiency check (`ai/rag/citations.py`); insufficient runs fail safe.
  6. Final synthesis reasons over all collected evidence and returns a validated
     `GrowthAnalysisResult`.
- **Retrieval** (`ai/rag/retriever.py`) — cosine-similarity nearest-neighbour search over
  `knowledge_chunks.embedding` using pgvector's `<=>` operator on PostgreSQL; automatic
  keyword-LIKE fallback on SQLite (test environment), clearly labelled as non-vector.
- **Agent tools** (`ai/agents/tools.py`) — strictly read-only:
  `search_knowledge`, `get_merchant_context`, `get_failed_payments`, `get_product`,
  `get_customer_segments`, `get_order_patterns`. No financial mutation tools exist yet.
- **Prompts** (`ai/prompts/growth.py`) — system/user prompt pairs for tool selection and
  final growth analysis.
- **Agent state** (`ai/agents/state.py`) — records run ID, tool calls, retrieved evidence,
  terminal status (`completed` / `insufficient_evidence` / `failed`), never raises.
- **Human approval flow** — every insight produced starts as `pending_approval`; the
  guardrail `ApprovalGate` never auto-approves. Execution itself is Phase 4+.

## Core Workflow

```
Detect    → rule-based growth engine and/or POST /api/ai/analyze (agentic RAG)
Explain   → reasoning list + evidence summary + tool-call trace returned to the caller
Approve   → every action/insight is pending_approval; guardrails enforce human sign-off
Execute   → NOT YET IMPLEMENTED (Phase 4+) — nothing executes autonomously today
Measure   → SCAFFOLDED (campaign estimated/actual revenue columns exist; no pipeline)
Audit     → audit_events rows record WHO / WHAT / WHEN / RESULT for analysis & ingestion
```

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript ~5.7, Vite 6, axios |
| Backend | Python 3.11, FastAPI 0.141, Uvicorn, Pydantic v2 + pydantic-settings |
| Database | PostgreSQL 16 with pgvector (Docker image `pgvector/pgvector:pg16`), SQLAlchemy 2.0, psycopg2-binary |
| Migrations | Alembic |
| AI / ML | OpenAI SDK (`openai`), default model `gpt-4o-mini`, tiktoken |
| RAG | Custom agentic pipeline, OpenAI `text-embedding-3-small` (1536-dim), pgvector IVFFlat cosine index |
| Infrastructure | Docker Compose (database service), python-dotenv |
| Testing | pytest, pytest-asyncio, Starlette TestClient, in-memory SQLite (WAL) |

## Project Structure

```
RazorGrowth AI/
├── backend/
│   ├── .env.example          # minimal template (SQLite URL variant)
│   └── app/
│       ├── main.py           # FastAPI entry point + router registration
│       ├── api/routes/       # health, ai, merchants, products, customers,
│       │                     # orders, payments, opportunities
│       ├── services/         # business logic (growth engine, AI analysis,
│       │                     # ingestion connector, knowledge, entities)
│       ├── repositories/     # SQLAlchemy data-access layer
│       ├── models/           # ORM models + enums
│       ├── schemas/          # Pydantic request/response schemas
│       ├── ai/
│       │   ├── llm/          # provider abstraction + OpenAI provider
│       │   ├── embeddings/   # provider abstraction + OpenAI embedder
│       │   ├── rag/          # pipeline, retriever, context, citations
│       │   ├── agents/       # agent state + read-only tool toolkit
│       │   └── prompts/      # growth analysis prompts
│       ├── guardrails/       # policy/risk/amount/approval validator chain
│       ├── audit/            # audit support package
│       ├── core/             # config (pydantic-settings), errors, logging
│       ├── db/               # base, engine, session
│       └── data/             # deterministic synthetic dataset + seed script
├── frontend/                 # React + TypeScript + Vite dashboard
│   ├── index.html
│   ├── package.json
│   └── src/                  # main.tsx, styles.css
├── migrations/               # Alembic environment + versions
├── tests/                    # pytest suite (5 modules + shared conftest)
├── data/                     # reserved placeholder (empty)
├── docs/                     # reserved placeholder (empty)
├── alembic.ini
├── docker-compose.yml        # pgvector/pgvector:pg16 database service
├── pytest.ini
├── requirements.txt
├── .env.example              # full template (Postgres + AI settings)
└── README.md
```

## Backend Architecture

- **API routes** (`backend/app/api/routes/`) — thin HTTP layer per resource; routers are
  registered under `/api` in `main.py`. A catch-all exception handler
  (`core/errors.py`) guarantees consistent JSON errors without leaking stack traces,
  secrets, or internal details.
- **Services** (`backend/app/services/`) — business logic:
  - `growth_engine.py` — deterministic rule-based opportunity detection (in-memory fallback preserved for Phase 1 API compatibility).
  - `opportunity_service.py` — DB-backed opportunity analysis and persistence.
  - `ai_analysis_service.py` — orchestrates validation → audit → agentic RAG → audit.
  - `ingestion_connector.py` — the only production-data entry point into the knowledge store; delegates embedding/upsert to `knowledge_service.py`; idempotent via SHA-256 checksums.
  - Entity services for merchants, products, customers, orders, payments.
- **Repositories** (`backend/app/repositories/`) — all database access goes through
  repositories built on a shared `base.py`; no raw queries in routes.
- **Models** (`backend/app/models/`) — `Merchant`, `Product`, `Customer`, `Order`,
  `OrderItem`, `Payment`, `GrowthOpportunity`, `Campaign`, `AgentAction`, `AuditEvent`,
  `KnowledgeDocument`, `KnowledgeChunk`, plus typed enums (statuses, segments, providers,
  opportunity types/statuses).
- **Schemas** (`backend/app/schemas/`) — Pydantic request/response contracts, including
  `analysis.py` (public analysis response) and `ingestion.py`.
- **Database** (`backend/app/db/`) — engine builder, session factory, declarative base
  with UUID primary-key and timestamp mixins; pool initialised during app lifespan.
- **Configuration** (`backend/app/core/config.py`) — cached `Settings` singleton loaded
  from environment variables / `.env`.
- **Error handling** — centralised helpers return client-safe messages and always log
  context server-side.

## Frontend

React 19 + TypeScript + Vite 6 single-page dashboard ("Merchant Growth Command Center"):

- Fetches `GET /api/opportunities` and renders each opportunity with type tag, title,
  reasoning, confidence, expected revenue, and an approval-required chip.
- Shows static synthetic baseline metrics and a TEST MODE badge.
- The backend base URL is currently hardcoded (`http://127.0.0.1:8000`) in
  `frontend/src/main.tsx`; no Vite proxy or CORS middleware is configured yet, so run
  both servers locally for the dashboard to load live data.
- The "Review & Approve" button is display-only — no approve endpoint exists yet.
- Note: `frontend/` currently has no `vite.config.*` or `tsconfig.json`; `npm run dev`
  relies on Vite defaults. `npm run build` (`tsc -b && vite build`) may require adding
  TypeScript config before it succeeds.

## Database

- **PostgreSQL 16 + pgvector**, provisioned by Docker Compose (`pgvector/pgvector:pg16`)
  with a named volume (`postgres_data`) and a readiness healthcheck.
- **Alembic** manages schema (`alembic.ini` at repo root; `migrations/env.py` injects
  `DATABASE_URL` from application settings, i.e. your `.env`).
- Current migration (`61b79451226c_phase3_knowledge_tables`) creates all tables:
  merchants, products, customers, orders, order_items, payments, growth_opportunities,
  campaigns, agent_actions, audit_events, knowledge_documents, knowledge_chunks —
  enables the `vector` extension, converts `knowledge_chunks.embedding` from JSONB to
  `vector(1536)`, and creates an IVFFlat cosine index (built post-seed in practice,
  since IVFFlat needs rows first).
- Tests intentionally bypass PostgreSQL using in-memory SQLite (WAL mode) with a
  JSONB→JSON type swap in `tests/conftest.py`.

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+ (required by Vite 6)
- Docker Desktop (for the PostgreSQL/pgvector container)
- An OpenAI API key (only needed for `/api/ai/*` endpoints)

### Environment Variables

Copy the template and fill in your values:

```bash
cp .env.example .env
```

Key variables (see `.env.example` for the full annotated list):

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` \| `testing` \| `production` |
| `DATABASE_URL` | PostgreSQL connection string (default matches `docker-compose.yml`) |
| `LLM_PROVIDER` / `LLM_MODEL` | Currently `openai` / `gpt-4o-mini` |
| `LLM_API_KEY` | **Secret.** Required for `/api/ai/*`; leave empty otherwise |
| `LLM_REQUEST_TIMEOUT` / `LLM_MAX_RETRIES` / `LLM_MAX_TOKENS` | LLM call tuning |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | Currently `openai` / `text-embedding-3-small` / `1536` |
| `GUARDRAIL_MAX_AMOUNT_INR` | Max allowed single-action amount (default 50000) |
| `GUARDRAIL_REQUIRE_APPROVAL` | Always require human approval (default true) |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Placeholders — not used yet |

A minimal variant also exists at `backend/.env.example` (SQLite URL for quick local runs).

### Backend Setup

Run all commands from the **project root** (imports use absolute `backend.app.*` paths):

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

Interactive API docs: <http://127.0.0.1:8000/docs>

Seed the deterministic synthetic dataset (idempotent):

```bash
python -m backend.app.data.seed
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Then open the printed local URL (Vite default: http://localhost:5173).
Other scripts defined in `frontend/package.json`: `npm run build`, `npm run preview`.

### Database Setup

```bash
docker compose up -d      # starts PostgreSQL 16 + pgvector
alembic upgrade head      # applies migrations (uses DATABASE_URL from .env)
python -m backend.app.data.seed
```

### Running Tests

```bash
pytest            # configured via pytest.ini (testpaths = tests, asyncio auto mode)
pytest -v         # verbose
```

Tests use an in-memory SQLite database with WAL mode and a JSONB→JSON swap —
no PostgreSQL container required. AI-dependent tests mock/fake providers; see
`tests/test_ai_phase3.py` and `tests/test_phase3_expansion.py`.

## API

All routes are prefixed with `/api`. Interactive docs at `/docs`.

| Method | Path | Description |
|---|---|---|
| GET | `/` | Service identity (name, status, version) |
| GET | `/api/health` | Health check |
| GET | `/api/opportunities` | Growth opportunities; DB-backed when seeded, falls back to the in-memory engine otherwise |
| GET | `/api/merchants` | List merchants |
| GET | `/api/products` | List products |
| GET | `/api/customers` | List customers |
| GET | `/api/orders` | List orders |
| GET | `/api/payments` | List payments |
| POST | `/api/ai/ingest` | Ingest production-table rows into the knowledge store as embedded documents (idempotent via checksums) |
| POST | `/api/ai/analyze` | Run agentic growth analysis for a merchant; returns insights + tool-call trace + evidence summary |

`POST /api/ai/analyze` and `POST /api/ai/ingest` accept an optional `merchant_id`;
when omitted, the first merchant in the DB is used (single-tenant mode).
Both return `503` if `LLM_API_KEY` is not configured, `404` if no merchant exists.

## Configuration

All settings are loaded by `backend/app/core/config.py` from environment variables or
`.env` (never commit `.env`). Highlights:

- **Environment tiers:** `APP_ENV` switches log verbosity (DEBUG in development) and
  exposes `is_testing` / `is_production` helpers.
- **Database:** `DATABASE_URL` drives both the app and Alembic (`migrations/env.py`).
- **LLM behaviour:** timeouts, retries, and max output tokens are configurable so the
  agent degrades predictably instead of hanging.
- **Guardrails:** `GUARDRAIL_MAX_AMOUNT_INR` caps any proposed monetary action;
  `GUARDRAIL_REQUIRE_APPROVAL=true` makes the approval gate non-bypassable.
- **Secrets:** only ever provided via environment (`LLM_API_KEY`, Razorpay keys).
  They are never logged and never appear in error payloads.

## Development Workflow

1. Start the database: `docker compose up -d`
2. Apply migrations: `alembic upgrade head`
3. Seed data (first run): `python -m backend.app.data.seed`
4. Run the backend: `uvicorn backend.app.main:app --reload` (from project root)
5. Run the frontend: `cd frontend && npm run dev`
6. Run tests before committing: `pytest`

To exercise the AI features end-to-end: set `LLM_API_KEY` in `.env`, restart the
backend, `POST /api/ai/ingest`, then `POST /api/ai/analyze`.

## Current Status

**Implemented**

- Full layered backend (routes → services → repositories → models) with centralised error handling and logging.
- Deterministic growth engine + synthetic seed dataset.
- Production commerce tables and REST read APIs.
- Knowledge store with checksum-idempotent embedding ingestion.
- Agentic RAG pipeline with bounded tool-selection loop, sufficiency checks, and schema-validated output.
- Guardrail chain (policy / risk / amount / approval gate) and audit event recording.
- Opportunity dashboard UI.

**Partially implemented**

- Approval UX: button rendered in the frontend, but no approval endpoint/action wiring.
- Campaign measurement: schema fields exist, no measurement logic.
- Retrieval fallback path (keyword search) is functional but intended only for tests/non-PG environments.

**Planned / future**

- Post-approval action execution (Phase 4+), executed only behind guardrails.
- Authentication, authorization, multi-tenancy (auth tokens noted in code as Phase 4).
- Live Razorpay integration (Test Mode adapter; keys are placeholders today).
- CORS configuration / configurable frontend API base URL.

## Roadmap

Phase 5 (implemented — see docs/PHASE_5.md): multi-agent system, scoring engine,
growth radar, customer intelligence, churn risk, payment recovery intelligence,
campaign strategist, simulation, experiments, growth memory, learning loop,
deduplication, agent permissions, agent audit + observability, explainability,
do-nothing baseline, Growth Control Center UI, daily brief.

Remaining candidate next steps:

1. Authentication / authorization / multi-tenancy tokens across all APIs.
2. Razorpay Test-Mode adapter for simulated-then-real payment verification; live execution stays behind explicit flags.
3. CI pipeline running `pytest` and the frontend build; lint/type-check configs.
4. Vector index maintenance strategy and agent-quality evaluation harness.

## Security

- All secrets are supplied via environment variables; `.env` is git-ignored while
  `.env.example` templates remain tracked.
- Agent tools are **read-only** — there is no code path today that creates payments,
  refunds, links, orders, or campaigns.
- Every proposed monetary action passes the guardrail chain and ends as
  `requires_approval` or `rejected`; nothing auto-executes.
- Immutable `audit_events` record analysis and ingestion lifecycles; the audit writer
  deliberately excludes API keys, passwords, customer PII, and raw LLM reasoning.
- Centralised error handling returns generic client-safe messages; full context is
  logged server-side only.
- No authentication/authorization exists yet — the API is currently suitable for local
  development and testing only. Do not expose it publicly.

## Contributing

1. Fork / branch from `main`.
2. Create a feature branch (`feat/my-feature` or `fix/my-fix`).
3. Make changes; add or update tests under `tests/`.
4. Run `pytest` and ensure everything passes.
5. Update `.env.example` (not `.env`) if new configuration is introduced.
6. Open a pull request describing what changed and why.

## License

License: Not yet specified.

## Important Project Notes

- **Run from the project root.** All backend imports are absolute (`backend.app.*`);
  `uvicorn backend.app.main:app`, `python -m backend.app.data.seed`, and `alembic`
  must be invoked from the repository root.
- **Phase compatibility:** `GET /api/opportunities` preserves the exact Phase 1 response
  contract (including its DB-less fallback) so early clients and tests keep working.
- **Graceful degradation:** vector search requires PostgreSQL + pgvector; elsewhere
  retrieval falls back to labelled keyword matching rather than failing.
- **Idempotency everywhere:** seeding is get-or-create keyed on stable natural keys;
  knowledge ingestion skips unchanged content via SHA-256 content checksums.
- **Bounded autonomy:** the agent loop is capped at `MAX_RETRIEVAL_STEPS = 3` and can
  never loop infinitely or execute side effects.
