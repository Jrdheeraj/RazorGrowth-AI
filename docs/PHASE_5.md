# Phase 5 — Agentic Growth Intelligence

Phase 5 upgrades RazorGrowth AI from *"AI analyzes merchant data"* to
*"specialised AI agents continuously understand the merchant, discover
opportunities, simulate actions, recommend the safest high-impact move,
and learn from measured results"* — while remaining **human-controlled**
end to end.

## Architecture

```
                        ┌────────────────────────────────────────────┐
                        │           GrowthAgentOrchestrator          │
                        │   fast plan · deep plan · savepoint        │
                        │   isolation · partial results · audit      │
                        └────────────────────────────────────────────┘
                                          │ runs (AgentRun rows)
     ┌───────────────────────────────────────────────────────────────────┐
     │ Specialised agents (permission-gated via agents/permissions.py)    │
     │                                                                   │
     │ GrowthMemoryAgent ──▶ loads context / persists run summary         │
     │ GrowthDiscoveryAgent ──▶ radar signals → scored opportunities      │
     │ CustomerIntelligenceAgent ──▶ segments + churn risk                │
     │ PaymentRecoveryAgent ──▶ failed payments → recovery proposals      │
     │ CampaignStrategistAgent ──► segment campaigns → send_campaign prop │
     │ RevenueOptimizationAgent ──▶ top opp → bounded discount proposal   │
     │ ExperimentAgent ──▶ A/B experiment designs                         │
     │ OpportunityPrioritizationAgent ──▶ deterministic ranking           │
     └───────────────────────────────────────────────────────────────────┘
                │ deterministic services                    │ LLM (optional)
                ▼                                           ▼
     scoring.py · radar.py · customer_intelligence.py   reasoning/copy only
     simulation.py · experiment_service.py · memory.py  (Groq/OpenAI provider)
     explainability.py · brief.py · opportunity_upsert.py
                │
                ▼
   Phase 4 safety pipeline (UNCHANGED):
   create_action → requested → [Guardrail #1] → HUMAN APPROVE/REJECT
                → approved → [Guardrail #2] → execute → executors
                → completed/failed → measurement_service → memory
```

**Hard invariants (enforced by tests):**

- No agent holds `approve_action` / `execute_action` / `reject_action`.
- The ONLY bridge to execution is `action_service.create_action()`,
  which lands in `requested` state.
- Guardrail #1 runs before approval; guardrail #2 immediately before
  execution — both preserved verbatim from Phase 4.
- Real Razorpay execution stays disabled (`RAZORPAY_ENABLED=false`);
  the executor refuses honestly rather than faking success.

## Agents & permissions

| Agent | Permissions | Tools |
|---|---|---|
| GrowthDiscoveryAgent | read merchant/customers/orders/payments/products/opportunities | growth_radar, opportunity_upsert, opportunity_scoring |
| CustomerIntelligenceAgent | read merchant/customers/orders/payments | customer_metrics, segment_classification, churn_engine |
| PaymentRecoveryAgent | read payments/customers, simulate, propose_action | failed_payment_scan, recovery_simulation, phase4_propose |
| CampaignStrategistAgent | read customers/opportunities/campaigns, simulate, propose_action | segment_lookup, campaign_simulation, phase4_propose |
| RevenueOptimizationAgent | read opportunities/orders, simulate, propose_action | opportunity_ranking, what_if_simulation, phase4_propose |
| OpportunityPrioritizationAgent | read opportunities | opportunity_scoring |
| ExperimentAgent | read opportunities/customers | experiment_design |
| GrowthMemoryAgent | read/write memory | memory_retrieve, memory_record |

## Deterministic engines (LLM never computes business numbers)

- **OpportunityScoringEngine** (`services/scoring.py`) — transparent formula:
  `score = 100 × revenue_potential × confidence × urgency × evidence_strength ÷ cost_adjustment`
  normalised 0–100; every factor persisted for explainability. Risk is
  reported but deliberately not hidden inside the headline score.
- **Growth Radar** (`services/radar.py`) — SQL aggregates over real
  orders/payments/customers for two equal windows; signals emitted only
  when documented thresholds cross AND sample size ≥ minimum; confidence
  scales with sample size; empty data emits nothing.
- **Customer intelligence + churn** (`services/customer_intelligence.py`)
  — LTV/recency/frequency/AOV/payment-success per customer; weighted
  churn heuristic (recency 0.40, frequency decline 0.25, spend decline
  0.20, payment failures 0.15). Heuristics, **not ML** — no accuracy is
  claimed anywhere.
- **Simulation engine** (`services/simulation.py`) — discount / campaign /
  payment-recovery scenarios with explicit assumptions, ±20% confidence
  bands, `is_estimate=True` always.
- **Experiment engine** (`services/experiment_service.py`) — uplift only
  when both arms have ≥30 samples and a recorded baseline; otherwise
  honest `measurement_pending`. The word "significant" is never used.
- **Growth memory** (`services/memory.py`) — merchant-scoped retrieval
  ranked by semantic similarity (embeddings when configured) + recency +
  importance; keyword fallback otherwise. Learning loop stores expected
  vs actual variance as factual memory — evidence-based memory, not RL.
- **Explainability** (`services/explainability.py`) — WHY / EVIDENCE /
  IMPACT / RISK / ASSUMPTIONS plus DO-NOTHING baseline (projection of the
  measured trend, labelled `is_projection`) vs TAKE-ACTION outlook.
- **Growth Brief** (`services/brief.py`) — revenue vs prior window, top
  opportunity, top risk, recommended action; empty data yields explicit
  nulls, never fabricated numbers.

## Orchestrator modes

- `fast`: memory(load) → discovery → payment_recovery → prioritization.
  Signal-level pass; no LLM required.
- `deep`: full eight-agent pipeline incl. customer intelligence, campaign
  strategy, revenue optimization, experiments; LLM interpretation is used
  only when an API key is configured, and its failure never fails a run.
- Failure isolation: each agent executes inside a SAVEPOINT; a crash rolls
  back that agent only, records the failure on its `AgentRun`, and the
  orchestrator returns `partial_success`.

## Database

New tables (migration `c714f19a0609`, child of `61b79451226c`):
`agent_runs`, `agent_memories`, `customer_insights`, `growth_signals`,
`experiments`, `experiment_results`, `simulations`. Existing tables and
migration history untouched. Memory embeddings are stored as JSON arrays
with in-process cosine similarity at retrieval time (pgvector remains in
use for knowledge_chunks).

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/agents` | registry + permissions + observability |
| GET | `/api/agents/runs` | run history w/ latency breakdown |
| GET | `/api/agents/runs/{run_id}` | single run (merchant-scoped) |
| POST | `/api/agents/run` | `{mode: fast\|deep}` orchestration |
| GET | `/api/radar?refresh=true` | growth radar signals |
| GET | `/api/opportunities/ranked` | scored ranking + factor breakdown |
| GET | `/api/customer-insights?refresh=true` | segments + churn |
| GET | `/api/customers/{id}/insights` | one customer's insight |
| GET/POST | `/api/simulations` | list / run what-if scenarios |
| GET/POST | `/api/experiments` | list / propose A/B experiments |
| GET | `/api/growth-memory` | recall memories (optional ?query=) |
| GET | `/api/growth-brief` | daily decision brief |

All endpoints accept optional `merchant_id`; omitted means first merchant
(single-tenant dev mode, consistent with earlier phases). Cross-merchant
ids return 404 — never another tenant's data.

## Environment variables

No new required variables. Optional:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` / `GROQ_API_KEY` / `GROQ_MODEL` | existing | deep-mode interpretation/copy |
| `EXECUTION_ENABLED` | `false` | global execution switch |
| `RAZORPAY_ENABLED` | `false` | real Razorpay execution switch |

Secrets remain env-only and are never logged or returned by any endpoint.

## Running

```bash
docker compose up -d && alembic upgrade head && python -m backend.app.data.seed
python -m pytest -q                       # full suite (Phase 1–5)
uvicorn backend.app.main:app --reload --port 8001
# dashboard:
cd frontend && npm install && npm run dev
```

Trigger agents: `curl -X POST localhost:8001/api/agents/run -H 'Content-Type: application/json' -d '{"mode":"fast"}'`

## Known limitations

- Churn/scoring are transparent heuristics, not learned models.
- Experiment evaluation reports directional uplift only; no p-values by design.
- Memory embeddings require an embedding key; without it retrieval uses keyword+recency.
- Live Razorpay payment execution remains intentionally unimplemented.
