<div align="center">

# 🚀 RazorGrowth AI
### **The Autonomous Merchant Growth & Agentic Commerce Engine for Razorpay**

<p align="center">
  <b>Ingesting real commerce data · Coordinating 14 specialized AI agents · Debating growth hypotheses · Enforcing double guardrails · Gated by human approval</b>
</p>

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI_0.141-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/Frontend-React_19_TypeScript-61dafb?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![Vite](https://img.shields.io/badge/Bundler-Vite_6.0-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL_16_pgvector-336791?style=flat-square&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph_1.2_%2B_LangChain-FF6F00?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![Razorpay](https://img.shields.io/badge/Payments-Razorpay_TEST_Mode-0c2451?style=flat-square&logo=razorpay&logoColor=white)](https://razorpay.com)
[![Cloudflare Workers AI](https://img.shields.io/badge/LLM-Cloudflare_Workers_AI-F38020?style=flat-square&logo=cloudflare&logoColor=white)](https://developers.cloudflare.com/workers-ai/)
[![Test Suite](https://img.shields.io/badge/Tests-2%2C155_Collected_%7C_1%2C650%2B_Passing-brightgreen?style=flat-square&logo=pytest&logoColor=white)](#testing-and-verification)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

<br/>

<a href="#quick-start">
  <img src="https://img.shields.io/badge/Quick_Start-Docker_Compose_in_1_Command-2ea44f?style=for-the-badge" alt="Quick Start" />
</a>
&nbsp;
<a href="#the-14-agent-growth-team">
  <img src="https://img.shields.io/badge/Explore-14_Agent_Catalog-d97757?style=for-the-badge" alt="Explore AI Team" />
</a>
&nbsp;
<a href="#system-architecture">
  <img src="https://img.shields.io/badge/Architecture-LangGraph_%26_Guardrails-10182b?style=for-the-badge" alt="System Architecture" />
</a>
&nbsp;
<a href="#human-in-the-loop-safeguards--double-guardrails">
  <img src="https://img.shields.io/badge/Security-Human_Gate_%26_Guardrails-c85f43?style=for-the-badge" alt="Human-in-the-Loop Safeguards" />
</a>
<br/><br/>

<p align="center">
  <img src="frontend/src/assets/homepage.png" alt="RazorGrowth AI Merchant Operating System" width="100%" style="border-radius: 6px; border: 1px solid #2a1810; box-shadow: 0 12px 36px rgba(16, 24, 43, 0.25);" />
</p>

<br/>

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          RAZORGROWTH AI PLATFORM OVERVIEW                              │
│                                                                                        │
│   • 14 Specialized AI Agents (5 Collaborative Team + 9 Domain Analysts)                │
│   • 4-Round Adversarial Debate: Investigation → Cross-Exam → Rebuttal → Synthesis      │
│   • Double Guardrails: Pre-Approval Financial Cap + Pre-Execution Live Re-validation   │
│   • Zero Autonomous Money Movement: 100% Gated Behind Merchant Owner / Admin Approval  │
│   • Verified Razorpay TEST-Mode Telemetry · Deterministic Scoring · Pgvector RAG       │
│   • Complete Enterprise Audit Log Stamped with AI / YOU / SYS Actor Provenance         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

</div>

---

### <a id="executive-summary"></a>⚡ Executive Summary

> **RazorGrowth AI** is an AI-powered merchant growth and agentic commerce platform designed to help digital businesses understand growth opportunities, coordinate specialized AI agents, and execute controlled growth workflows.
>
> Modern e-commerce businesses generate immense volumes of transactional data — successful payments, failed checkouts, customer churn signals, product affinities, and catalog shifts — yet turning this stream into revenue-generating execution remains slow, manual, and error-prone. Traditional "AI assistants" act as opaque, ungrounded black boxes that hallucinate numbers and cannot be trusted with monetary execution.
>
> **RazorGrowth AI solves this fundamental gap.** It acts as an autonomous, multi-agent growth department that ingests verified Razorpay TEST-mode commerce data, detects underlying growth signals across revenue and customer cohorts, convenes a team of 14 specialized AI agents to investigate and cross-examine findings through structured multi-round debate, synthesizes explainable action proposals bounded by strict financial ceilings, and requires explicit merchant human approval before triggering idempotent, double-guardrailed execution. Every step, tool invocation, and human decision is immutably recorded in an audit trail.

---

## 📑 Table of Contents

- [Executive Summary](#executive-summary)
- [The Problem RazorGrowth AI Solves](#the-problem-razorgrowth-ai-solves)
- [Core Platform Capabilities](#core-platform-capabilities)
- [Quick Start & Complete Setup Guide](#quick-start)
  - [Prerequisites & Supported Environments](#prerequisites-and-supported-environments)
  - [Option 1 — Recommended Docker Deployment (One-Command)](#docker-deployment)
  - [Option 2 — Host-Based Manual Local Development](#local-setup)
  - [Option 3 — Common First-Run Issues & Verified Fixes](#troubleshooting-setup)
- [How It Works — End-to-End Visual Workflow](#how-it-works--end-to-end-visual-workflow)
- [The 14-Agent Growth Team](#the-14-agent-growth-team)
  - [14-Agent System Collaboration Visual](#agent-collaboration-visual)
  - [Main Growth Team (Collaborative Debate & Planning)](#main-growth-team)
  - [Domain Specialists (Analysis & Decisioning Engine)](#domain-specialists)
  - [Canonical Tool Catalog & Strict Permission Model](#canonical-tool-catalog)
- [Agent Execution Lifecycle & Durability](#agent-execution-lifecycle)
- [Multi-Agent Orchestration & LangGraph](#multi-agent-orchestration--langgraph)
  - [Execution Modes & Plans](#execution-modes-and-plans)
  - [LangGraph StateGraph Integration](#langgraph-stategraph-integration)
  - [Durable Lifecycle, Lease Fencing & Recovery](#durable-lifecycle-and-recovery)
- [The 4-Round Agent Debate Protocol](#the-4-round-agent-debate-protocol)
- [Human-in-the-Loop Safeguards & Double Guardrails](#human-in-the-loop-safeguards--double-guardrails)
  - [Action Lifecycle State Transitions](#action-lifecycle-state-transitions)
- [External Integrations & Execution Layer](#external-integrations--execution-layer)
- [System Architecture & Request Pathways](#system-architecture)
  - [Shipped Frontend Experience Routes](#shipped-frontend-experience-routes)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Environment Configuration](#environment-configuration)
- [Database Setup & Alembic Migrations](#database-setup--alembic-migrations)
- [API Usage & Endpoints](#api-usage--endpoints)
- [Testing and Verification](#testing-and-verification)
- [Configuration & Troubleshooting](#configuration--troubleshooting)
- [Implementation Status & Honest Engineering Boundaries](#implementation-status--honest-engineering-boundaries)
- [Product Roadmap](#product-roadmap)
- [Contributing Guidelines](#contributing-guidelines)
- [License & Acknowledgments](#license--acknowledgments)

---

## <a id="the-problem-razorgrowth-ai-solves"></a>🎯 The Problem RazorGrowth AI Solves

Merchants operating on payment gateways like Razorpay capture continuous transactional reality: completed checkouts, recurring subscriptions, high-value cart abandonments, technical card declines, and shifting SKU affinities. However, extracting actionable commercial lift from this data presents critical bottlenecks:

| Traditional Commerce Operations | Unbounded Generative AI "Copilots" | **RazorGrowth AI Platform** |
|:---|:---|:---|
| **Siloed Analysis**: Merchant data lives across SQL databases, gateway dashboards, and analytics tools. Growth analysis is manual, sporadic, and delayed by weeks. | **Hallucinated Recommendations**: General-purpose LLMs generate unsubstantiated recommendations disconnected from real unit economics and verified ledger data. | **Deterministic Signal Grounding**: 100% of insights originate from real transaction logs via PostgreSQL queries, deterministic scoring engines, and RAG knowledge retrievals. |
| **Monolithic Decision Making**: A single marketer or developer attempts to plan retention campaigns, write ad copy, analyze failed payments, and design A/B experiments. | **Single-Agent Blindspots**: A lone LLM prompt produces uncritical, agreeable responses without internal challenge, counter-argument, or feasibility auditing. | **14-Agent Collaborative Division of Labor**: Specialized agents cross-examine hypotheses in a 4-round adversarial debate (Marketing, Product, Design, Tech, Finance). |
| **High Financial Risk**: Manual campaigns and automated scripts can inadvertently over-discount products, blast wrong customer segments, or exhaust budgets. | **Uncontrolled Execution**: Granting agents direct API keys or money-transfer access creates massive liability and catastrophic failure risk. | **Structurally Enforced Human-in-the-Loop**: Agents hold zero execution or approval permissions. All write actions land in `requested` state, awaiting human owner/admin approval behind double guardrails. |
| **No Accountability**: When campaigns fail, teams cannot determine why an action was recommended, what data informed it, or what alternatives were rejected. | **Black-Box Outputs**: No durable logs of agent reasoning, tool payloads, intermediate findings, or external network calls. | **Immutable Audit Trail**: Every tool call, agent finding, debate turn, human approval, and execution step is stamped with `AI`, `YOU`, or `SYS` actor markers. |

---

## <a id="core-platform-capabilities"></a>✨ Core Platform Capabilities

### 📡 1. Real-Data Growth Radar
A live diagnostic command center computed directly from ingested Razorpay TEST data. Calculates net captured revenue, transactions, active customer count, order volumes, average order value (AOV), and payment failure ratios. Detects ranked growth signals across revenue momentum, repeat-purchase decay, dormant customer cohorts, and anomalous order behavior — accompanied by an honest, plain-English executive summary. Missing data produces clear empty states, never synthesized mock statistics.

### 🧠 2. 14-Agent Coordinated Intelligence
A multidisciplinary virtual growth department composed of **5 Main Growth Team agents** (Manager, Marketing, Product, Designer, Software) and **9 Domain Specialists** (Growth Discovery, Customer Intelligence, Revenue Optimization, Campaign Strategy, Payment Recovery, Opportunity Prioritization, Experimentation, Growth Memory, and Personalization). Every agent operates under a strict capability model that structurally forbids money manipulation or autonomous action approval.

### ⚖️ 3. 4-Round Structured Multi-Agent Debate
Specialists do not operate in silos. In `growth_team` mode, agents engage in a formal 4-round debate: **Investigation → Cross-Examination → Rebuttal → Executive Synthesis**. Findings are classified into *supporting*, *opposing*, and *uncertainty* categories. A context-aware chat assistant on the debate interface enables merchants to inspect specific debate dynamics ("Why did Software challenge Product's recommendation?", "What evidence supported this discount?").

### 🛡️ 4. Explainable, Bounded Actions & Human Approval Gate
Every proposed growth initiative is:
- **Explainable**: Contains the exact commercial rationale, supporting data points, target customer segment, and expected revenue impact.
- **Bounded**: Includes an explicit list of *what the action will do* and *what it will never do*, capped by hard financial ceilings (`GUARDRAIL_MAX_AMOUNT_INR`) and audience volume limits.
- **Human-Gated**: Agents can only *propose* (`requested` state). Execution requires explicit authentication and cryptographic signature by a verified workspace `owner` or `admin`.

### 🤖 5. Autonomous AI Buyer Checkout
A fully realized autonomous buyer module designed to test and validate agentic commerce. The AI Buyer inspects the merchant's live catalog, selects products at their real prices, creates genuine Razorpay TEST orders, and verifies payment signatures. Failures (such as declined test cards) trigger honest, graceful degradation: no funds captured, no infinite retries, and clear recovery telemetry.

### 🔌 6. Enterprise Integration Layer (Marketing AGI)
External marketing execution connects to verified third-party providers: **Resend** (Email campaigns), **Google Ads** (OAuth2 + Developer token), **Meta Ads**, and **Instagram** (OAuth2). Per-workspace credentials are encrypted at rest using Fernet keys (`integration_connections` table). Read actions are autonomous when connected; write actions (`send_email`, `create_campaign_paused`, `publish_photo`) are strictly approval-gated through the Actions pipeline.

### 🔐 7. Multi-Tenant Architectural Isolation
JWT-authenticated session security with scrypt password hashing, session revocation, and fine-grained role-based access control (`owner`, `admin`, `operator`, `analyst`). Every database query enforces tenant scoping (`merchant_id`). Cross-tenant access attempts immediately yield `403 Forbidden` responses. Razorpay records are tied immutably to a single merchant workspace and cannot be accessed across boundaries.

### 🧮 8. Resilient Multi-Provider LLM & RAG Layer
Unified model provider abstraction routing between **Cloudflare Workers AI** (the platform default) and **OpenAI**, governed by the `LLM_PROVIDER` environment variable. Zero unannounced fallbacks: if no provider is configured, agents degrade gracefully to deterministic analytical modes rather than fabricating claims or leaking data to unauthorized external endpoints.

---

## <a id="quick-start"></a>⚡ Quick Start & Complete Setup Guide

Follow this guide to get RazorGrowth AI running on a fresh clone.

> [!TIP]
> **Recommended for Beginners & Rapid Evaluation**: Use **Option 1 (Docker Compose)**. It provisions PostgreSQL 16 with pre-installed `pgvector`, runs database health checks, applies all Alembic migrations automatically on container startup, and configures safe local defaults with zero manual database administration.

### <a id="prerequisites-and-supported-environments"></a>Prerequisites & Supported Environments

| Platform / Tool | Supported Versions | Notes |
|:---|:---|:---|
| **Operating System** | Windows 10/11 (with WSL2 or Docker Desktop), macOS (Apple Silicon & Intel), Ubuntu 20.04+, Debian 12+, Fedora | Native PowerShell scripts provided for Windows; standard Bash for Unix. |
| **Docker & Compose** | Docker Desktop 24.0+ / Docker Compose v2.20+ | Required for Option 1; used to host `pgvector/pgvector:pg16` for Option 2. |
| **Python** | Python `3.11.x` or `3.12.x` | Required for Option 2 (manual host setup). Verify with `python --version`. |
| **Node.js & npm** | Node.js `18.x` or `20.x` LTS, npm `9.x`+ | Required for Option 2 (frontend Vite compilation). |

---

### <a id="docker-deployment"></a>Option 1 — Recommended Docker Deployment (One-Command)

Docker Compose configures three interconnected containers: `db` (PostgreSQL 16 with pgvector), `backend` (FastAPI with automatic migrations), and `frontend` (React 19 served by Nginx with `/api` reverse proxy).

#### Step 1: Start Docker Desktop
Ensure Docker Desktop is running on Windows/macOS, or verify the daemon on Linux:
```bash
docker info
```

#### Step 2: Clone the Repository
```bash
git clone https://github.com/Jrdheeraj/RazorGrowth-AI.git
cd RazorGrowth-AI
```

#### Step 3: Local Configuration File (Optional for Docker)
The repository `docker-compose.yml` provides secure, working local development defaults out-of-the-box (`AUTH_SECRET_KEY`, database credentials, and standard ports). Creating a local `.env` file is **optional** unless you want to customize port allocations or provide live Cloudflare Workers AI or OpenAI API tokens:
```bash
# Optional: copy template to customize ports or add LLM API keys
cp .env.example .env
```

#### Step 4: Build and Start the Full Application Stack
```bash
docker compose up --build
```

#### Step 5: How Docker Boots & Auto-Migrates
1. **Database Initialization (`db`)**: The `pgvector/pgvector:pg16` image launches and mounts the `postgres_data` volume. A healthcheck verifies readiness (`pg_isready`).
2. **Backend Startup (`backend`)**: The backend container waits for `db` to become completely healthy via `depends_on: { db: { condition: service_healthy } }`. The entrypoint script (`scripts/start.sh`) automatically executes:
   ```bash
   alembic upgrade head
   ```
   This migrates all 15 schema revisions up to `p5e2r0na1z04` before launching Uvicorn on port 8001. No manual database setup is required.
3. **Frontend Compilation & Proxy (`frontend`)**: Vite builds the production React application and Nginx serves it on port 5173, routing `/api/*` requests directly to `backend:8001`.

#### Step 6: Verified Service Access Points
Once startup completes, open your browser to the following verified URLs:
- **Frontend Workspace**: [http://localhost:5173](http://localhost:5173)
- **Interactive Swagger API Documentation**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **Backend Health Check**: [http://localhost:8001/api/health](http://localhost:8001/api/health)
- **PostgreSQL Database**: `localhost:5432` (Username: `razorgrowth`, Password: `razorgrowth`, Database: `razorgrowth`)

#### Step 7: First-Time User Onboarding & Tenant Signup
RazorGrowth AI does not ship with hardcoded credentials. To initialize your workspace:
1. Open [http://localhost:5173](http://localhost:5173) and click **Sign Up** (or use `POST /api/auth/register`).
2. Register with your email and a password of at least 12 characters (must include letters and numbers).
3. The registration handler calls `initialize_user_workspace`, creating your private tenant-isolated workspace (`merchant_id`) and pre-seeding an initial 10-product demo catalog.

#### Step 8: Managing Docker Services
- **View Live Backend Logs**: `docker compose logs -f backend`
- **View Database Logs**: `docker compose logs -f db`
- **Stop Containers (Preserving Data)**: `docker compose down`
- **Complete Reset (Wipes Database Volume)**: `docker compose down -v`

---

### <a id="local-setup"></a>Option 2 — Host-Based Manual Local Development

For developers actively modifying backend Python code or frontend components on their local host machine.

#### Step 1: Start PostgreSQL with pgvector via Docker
The simplest and most reliable way to obtain PostgreSQL 16 with pre-compiled pgvector without manual C compilation is using Docker:
```bash
docker compose up -d db
```
*If you run PostgreSQL natively on your host, ensure `pgvector` is installed and run `CREATE EXTENSION IF NOT EXISTS vector;` in your database.*

#### Step 2: Configure & Run the Backend

##### A. Windows (PowerShell)
```powershell
# Verify Python version (must be 3.11+)
python --version

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install pinned Python dependencies
pip install -r requirements.txt

# Create your local environment configuration
Copy-Item .env.example .env
```

##### B. Linux / macOS (Bash)
```bash
# Verify Python version (must be 3.11+)
python3 --version

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install pinned Python dependencies
pip install -r requirements.txt

# Create your local environment configuration
cp .env.example .env
```

##### C. Configure Required Settings in `.env`
Open `.env` in your editor and configure the single mandatory setting before first startup:
- Set `AUTH_SECRET_KEY` to any random string of 32 or more characters. Generate one with:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- Ensure `DATABASE_URL` matches your local PostgreSQL instance:
  ```env
  DATABASE_URL=postgresql://razorgrowth:razorgrowth@localhost:5432/razorgrowth
  ```

##### D. Apply Database Migrations
Run Alembic from the **repository root directory** (where `alembic.ini` is located):
```bash
alembic upgrade head
```
*Verify the active migration revision with `alembic current`. You should see `p5e2r0na1z04 (head)`.*

##### E. Start the FastAPI Backend Server
```bash
uvicorn backend.app.main:app --host 127.0.0.1 --port 8001 --reload
```
*The backend is now live at [http://127.0.0.1:8001](http://127.0.0.1:8001) and interactive Swagger docs at [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).*

#### Step 3: Configure & Run the Frontend (Second Terminal)
Open a new terminal window:
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:5173](http://localhost:5173). Vite's development proxy automatically forwards `/api/*` network requests to `http://127.0.0.1:8001`.

---

### <a id="troubleshooting-setup"></a>Option 3 — Common First-Run Issues & Verified Fixes

| Problem / Error Message | Root Cause | Verified Resolution |
|:---|:---|:---|
| `docker: error during connect` / `daemon not running` | Docker Desktop is not started or WSL2 integration is disabled. | Start Docker Desktop, wait until the tray icon turns green, and ensure WSL2 integration is active in Settings → Resources → WSL Integration. |
| `Bind for 0.0.0.0:5432 failed: port is already allocated` | A local PostgreSQL service is already running on port 5432. | Either stop local PostgreSQL (`net stop postgresql-x64-16` on Windows or `sudo systemctl stop postgresql` on Linux), or change `POSTGRES_PORT=5433` in `.env`. |
| `Bind for 0.0.0.0:8001 failed` / `port 8001 in use` | Another Uvicorn or backend instance is occupying port 8001. | Terminate the existing process or set `BACKEND_PORT=8002` in `.env`. |
| `sqlalchemy.exc.OperationalError: connection to server at localhost:5432 refused` | The database container has not completed booting or `DATABASE_URL` host is incorrect. | Ensure `docker compose up -d db` is healthy (`docker compose ps db`). If running inside Docker, backend must connect to host `db:5432`, not `localhost:5432`. |
| `type "vector" does not exist` | Standard PostgreSQL was started instead of the pgvector image. | Ensure your image is `pgvector/pgvector:pg16` as declared in `docker-compose.yml`. Standard `postgres:16` lacks vector extensions. |
| `alembic: command not found` or migration fails from subdirectory | Virtual environment not active or Alembic run from wrong working directory. | Activate `.venv` and ensure you run `alembic upgrade head` from the **repository root**, not from inside `migrations/` or `backend/`. |
| `422 Unprocessable Entity` on user registration | Password does not satisfy the security policy. | Passwords must be at least 12 characters long and contain both letters and numbers. |
| `npm ERR! code ERESOLVE` during `npm install` | Node.js version mismatch or conflicting cached dependencies. | Use Node 20 LTS. Run `npm install --legacy-peer-deps` if peer dependency warnings block installation. |
| `503 Service Unavailable: AI provider not configured` | No Cloudflare or OpenAI credentials provided in `.env`. | Expected behavior when optional LLM keys are omitted. Analytical tools and deterministic scoring continue to function; configure `CLOUDFLARE_API_TOKEN` or `LLM_API_KEY` for generative features. |
| Frontend displays network error / CORS failure | Frontend attempted direct external API request or backend is down. | Ensure backend is running on `127.0.0.1:8001`. Vite proxies `/api/*` automatically; do not alter `VITE_API_BASE_URL` in local development. |

---

## <a id="how-it-works--end-to-end-visual-workflow"></a>🔄 How It Works — End-to-End Visual Workflow

The platform enforces a deterministic, multi-stage progression from raw payment events to human-approved execution:

```mermaid
flowchart TD
    subgraph INGEST["1. Ingestion & Signal Detection"]
        RZP["Razorpay TEST Mode<br/>Orders · Payments · Webhooks"] -->|HMAC-SHA256 Ingest| DB[("PostgreSQL 16 + pgvector<br/>Tenant-Isolated Data Store")]
        DB --> RADAR["Growth Radar Engine<br/>Failure Rates · Cohort Churn · AOV Shifts"]
        RADAR --> DISC["GrowthDiscoveryAgent<br/>Signal Deduplication & Scoring"]
    end

    subgraph ORCH["2. Orchestration & Adversarial Debate"]
        DISC --> MGR["ManagerAgent<br/>Goal Decomposition & Plan Materialization"]
        MGR -->|LangGraph StateGraph / Orchestrator| R1
        
        subgraph DEBATE["4-Round Structured Debate Pipeline"]
            R1["Round 1: Individual Investigation<br/>Marketing · Product · Designer · Software"] --> R2["Round 2: Cross-Examination<br/>Adversarial Challenge & Verification"]
            R2 --> R3["Round 3: Formal Rebuttal<br/>Evidence Validation & Defense"]
            R3 --> R4["Round 4: Executive Synthesis<br/>Manager Formulates Consensus"]
        end
    end

    subgraph GOVERN["3. Proposal, Guardrails & Human Gate"]
        R4 --> PROP["Action Proposal Prepared<br/>Why · Scope · Financial Bounds · Will/Will-Not-Do"]
        PROP --> G1{"Pre-Approval Guardrail<br/>Amount &le; ₹50,000 INR?"}
        G1 -->|Within Limit| GATE["HUMAN APPROVAL GATE<br/>Owner / Admin Authentication Required"]
        G1 -->|Exceeded| REJECT["Action Rejected / Scope Clamped"]
        GATE -->|Human Rejects| ABORT["Workflow Terminated<br/>Recorded to Audit Log"]
        GATE -->|Human Approves| G2{"Pre-Execution Guardrail<br/>Live Balance · Rate Limits · Kill Switch"}
    end

    subgraph EXEC_PERSIST["4. Execution, Audit & Learning"]
        G2 -->|Verified| EXEC["Execution Engine<br/>Resend Email · Paused Ad Campaign · Retry Schedule"]
        EXEC --> AUDIT["Immutable Audit Trail<br/>Stamped with AI / YOU / SYS Actors"]
        AUDIT --> MEM["GrowthMemoryAgent<br/>Vector & Outcome Persistence - pgvector"]
        MEM -->|Grounds Future Cycles| MGR
    end

    classDef human fill:#f7ebd7,stroke:#d97757,stroke-width:2px,color:#2a1810;
    classDef secure fill:#10182b,stroke:#70b88a,stroke-width:2px,color:#f7ebd7;
    classDef alert fill:#301b12,stroke:#c85f43,stroke-width:2px,color:#fff3df;
    
    class GATE human;
    class DB,AUDIT,MEM secure;
    class G1,G2 alert;
```

*Figure 1: Complete end-to-end data progression from Razorpay TEST transactions through deterministic signal detection, multi-agent debate, two-tier guardrails, human approval, and persistent vector memory.*

---

## <a id="the-14-agent-growth-team"></a>🧠 The 14-Agent Growth Team

The RazorGrowth AI agent roster is defined authoritatively in `backend/app/agents/registry.py`. Every agent inherits from `BaseGrowthAgent` (`backend/app/agents/base.py`) and declares an explicit capability boundary.

> [!NOTE]
> **Subsystem Clarification**: The names **`MarketingAGI`** and **`ProductAGI`** refer to broader platform subsystems (such as the external marketing integration hub and the catalog intelligence module). They are not separate or additional registered agent instances beyond the canonical 14-agent registry.

### <a id="agent-collaboration-visual"></a>14-Agent System Collaboration Visual

The diagram below illustrates how the 5 Main Growth Team agents and 9 Domain Specialist agents collaborate under `ManagerAgent` orchestration:

```mermaid
flowchart TB
    subgraph MGR_BOX["Central Coordination & Synthesis"]
        MGR["ManagerAgent<br/>★ Strategic Planning & Decomposition<br/>★ Task Delegation & Handoffs<br/>★ Debate Direction & Consensus<br/>★ Action Proposal Synthesis"]
    end

    subgraph MAIN_TEAM["Main Growth Team (Collaborative Debate & Planning)"]
        direction LR
        MKT["MarketingAgent<br/>• Retention & Churn Analysis<br/>• Customer LTV Cohorts<br/>• Win-back Messaging"]
        PROD["ProductAgent<br/>• Catalog Intelligence<br/>• SKU Affinity & Bundling<br/>• Basket Pricing Dynamics"]
        DES["DesignerAgent<br/>• Creative Campaign Briefs<br/>• Copywriting Variants<br/>• FLUX Visual Asset Specs"]
        SOFT["SoftwareAgent<br/>• API & Integration Specs<br/>• Technical Feasibility<br/>• Infrastructure Bounds"]
    end

    subgraph SPECIALISTS["Domain Specialists (Deep Analytics & Scoring Engine)"]
        direction TB
        subgraph S_ROW1["Signal Ingestion & Customer Intel"]
            DISC["GrowthDiscoveryAgent<br/>Radar Signals & Scoring"]
            CUST["CustomerIntelligenceAgent<br/>RFM & Churn Probability"]
            PERS["PersonalizationAgent<br/>Next-Best-Action Engine"]
        end
        subgraph S_ROW2["Revenue Optimization & Campaigns"]
            REV["RevenueOptimizationAgent<br/>Elasticity & Margin Models"]
            CAMP["CampaignStrategistAgent<br/>Multi-Channel Blueprints"]
            PAY["PaymentRecoveryAgent<br/>Decline Heuristics & Retries"]
        end
        subgraph S_ROW3["Prioritization, Experimentation & Memory"]
            PRIOR["OpportunityPrioritizationAgent<br/>Deterministic Scoring Matrix"]
            EXP["ExperimentAgent<br/>A/B Hypothesis & Power Specs"]
            MEM["GrowthMemoryAgent<br/>Vector & Audit Memory Recall"]
        end
    end

    subgraph OUTPUT_BOX["Action Governance & Execution Pipeline"]
        ACTION["Proposed Growth Action<br/>Status: requested · Bounded Scope · Financial Ceiling"]
    end

    %% Inter-Agent Information Flows
    DISC -->|Anomaly Signals| PRIOR
    CUST -->|Cohort Segments| MKT
    CUST -->|RFM Data| PERS
    REV -->|Price Elasticity| PROD
    PAY -->|Failed Transactions| PRIOR
    CAMP -->|Channel Plans| MGR
    EXP -->|Test Variants| SOFT
    MEM -->|Historical Context| MGR

    PRIOR -->|Ranked Opportunity Queue| MGR
    MGR <-->|Debate Rounds 1-4| MAIN_TEAM
    MGR -->|Synthesize Consensus| ACTION
    ACTION -->|Post-Execution Outcome| MEM

    classDef mgr fill:#2a1810,stroke:#d97757,stroke-width:2px,color:#fff3df;
    classDef main fill:#10182b,stroke:#d97757,stroke-width:1px,color:#f7ebd7;
    classDef spec fill:#182238,stroke:#336791,stroke-width:1px,color:#e2ecf8;
    classDef action fill:#0f2d1d,stroke:#70b88a,stroke-width:2px,color:#f0fdf4;

    class MGR mgr;
    class MKT,PROD,DES,SOFT main;
    class DISC,CUST,PERS,REV,CAMP,PAY,PRIOR,EXP,MEM spec;
    class ACTION action;
```

*Figure 2: Collaboration and data interchange topology across all 14 registered agents, illustrating how specialist analytical findings flow into ManagerAgent planning, multi-agent debate, and human-gated action synthesis.*

---

### <a id="main-growth-team"></a>1. Main Growth Team (Collaborative Debate & Planning)

The 5 main growth agents collaborate in high-level strategic planning, cross-functional debate rounds, and executive synthesis.

| Agent | Core Responsibility | Key Inputs | Primary Outputs | Execution Role |
|:---|:---|:---|:---|:---|
| **`ManagerAgent`** | Top-level coordinator. Decomposes objectives into validated execution plans, delegates tasks, directs debate rounds, synthesizes final consensus. | Merchant RAG context, strategic objectives, cross-agent debate findings | Materialized action plans, debate direction, executive synthesis | Orchestrator & Debater |
| **`MarketingAgent`** | Analyzes customer cohorts, retention rates, win-back opportunities, messaging strategy, and channel ROI. | Customer intelligence data, transaction recency/frequency metrics | Retention campaign blueprints, target audience specifications | Debate Specialist |
| **`ProductAgent`** | Discovers product affinities, cross-sell/upsell pairs, inventory velocity, and catalog pricing optimizations. | Order items, product catalog metadata, historical basket combinations | Product bundling opportunities, SKU affinity matrices | Debate Specialist |
| **`DesignerAgent`** | Formulates creative messaging concepts, ad variants, visual UX briefs, and generates campaign visuals. | Strategic recommendations, customer persona data, brand parameters | Creative design briefs, copy variants, FLUX visual assets | Creative Specialist |
| **`SoftwareAgent`** | Evaluates technical feasibility, API prerequisites, integration constraints, and architectural requirements. | Proposed marketing/product actions, system integration contracts | Technical implementation specs, API dependency reports | Feasibility Specialist |

### <a id="domain-specialists"></a>2. Domain Specialists (Analysis & Decisioning Engine)

Nine specialized domain agents handle high-depth, deterministic analysis and opportunity generation.

| Agent | Core Responsibility | Key Inputs | Primary Outputs | Status & Catalogued Tools |
|:---|:---|:---|:---|:---|
| **`GrowthDiscoveryAgent`** | Ingests Growth Radar signals and converts raw business anomalies into scored growth opportunities. | Raw payment and order telemetry, radar anomaly signals | Deduplicated, ranked growth opportunities with confidence metrics | `analytics.growth_radar`<br/>`opportunities.rank` |
| **`CustomerIntelligenceAgent`** | Computes RFM scores, Customer Lifetime Value (LTV), churn probability, and customer health segments. | Customer profiles, historical payment logs, order frequency | Customer segment classifications, churn-risk alerts | `customer.insights` |
| **`RevenueOptimizationAgent`** | Evaluates price elasticity, models promotion economics, and prepares bounded financial propositions. | Open growth opportunities, margin data, historical orders | Bounded discount and revenue recovery proposals | Deterministic Scoring Engine |
| **`CampaignStrategistAgent`** | Architectures targeted marketing initiatives, matching customer segments with appropriate communication channels. | Customer cohorts, validated opportunities, channel history | Structured campaign blueprints awaiting human approval | Bounded Campaign Engine |
| **`PaymentRecoveryAgent`** | Analyzes failed Razorpay transactions using classification heuristics and schedules bounded recovery actions. | Failed payment records, gateway error codes, order links | Bounded retry actions, customer recovery email proposals | `payments.failure_analytics`<br/>`actions.propose` |
| **`OpportunityPrioritizationAgent`** | Applies deterministic multi-criteria scoring to prioritize the merchant's global opportunity queue. | Raw opportunity candidate list, merchant risk profile | Ranked, best-first opportunity queue | `opportunities.rank` |
| **`ExperimentAgent`** | Formulates statistically valid A/B experiment frameworks with explicit sample size criteria. | Top-ranked opportunities, baseline conversion metrics | Controlled experiment designs with test/control parameters | `experiments.design`<br/>`experiments.record_result` |
| **`GrowthMemoryAgent`** | Manages persistent merchant memory across execution cycles using vector similarity and historical audit records. | Post-execution outcome evaluations, historical audit logs | Contextual memory retrievals grounding new planning cycles | `memory.recall` |
| **`PersonalizationAgent`** | Determines deterministic next-best-action recommendations for individual customer profiles. | Customer RFM metrics, product affinity baskets, churn scores | Individualized personalization decisions with evidence records | `customer.insights`<br/>`commerce.catalog_intelligence` |

### <a id="canonical-tool-catalog"></a>3. Canonical Tool Catalog & Strict Permission Model

Every capability invoked by an agent is registered in `backend/app/agents/catalog.py` and strictly checked against `backend/app/agents/permissions.py`.

```
CANONICAL TOOL INVENTORY (12 Verified Tools):
├── analytics.business_overview       [read_merchant]       → AnalyticsService.get_overview
├── analytics.growth_radar            [read_orders]         → GrowthRadarService.detect
├── customer.insights                 [read_customers]      → CustomerIntelligenceService.compute_metrics
├── commerce.catalog_intelligence     [read_products]       → ProductIntelligenceService (stock, pricing)
├── payments.failure_analytics        [read_payments]       → PaymentRecoveryService.get_failed_analytics
├── opportunities.rank                [read_opportunities]  → OpportunityScoringEngine.rank
├── experiments.design                [read_opportunities]  → ExperimentService.create_experiment
├── experiments.record_result         [read_opportunities]  → ExperimentService.record_result
├── research.web_search               [read_merchant]       → ResearchService.search (unconfigured default)
├── collaboration.request_handoff     [read_merchant]       → HandoffService.request (durable handoff)
├── memory.recall                     [read_merchant]       → GrowthMemoryService.retrieve
└── actions.propose                   [read_merchant]       → ActionService.create_action (requested only)
```

#### Structurally Forbidden Capabilities
The platform defines an immutable invariant in `FORBIDDEN_CAPABILITIES`:
```python
FORBIDDEN_CAPABILITIES: frozenset[str] = frozenset({
    "approve_action",
    "execute_action",
    "reject_action",
    "bypass_guardrails",
    "direct_database_mutation",
    "send_money",
})
```
No agent holds or can be granted these permissions. Proposing an action creates an `AgentAction` record locked in `requested` status; approval remains exclusive to human administrators.

---

## <a id="agent-execution-lifecycle"></a>🔄 Agent Execution Lifecycle & Durability

Every agent run adheres to an 8-stage bounded lifecycle defined in `BaseGrowthAgent.execute()` (`backend/app/agents/base.py`). The lifecycle is completely decoupled from crash-recovery leasing and human approval:

```mermaid
flowchart LR
    G["1. Goal Setting<br/>Intake Objective & Bounds"] --> C["2. Context Gathering<br/>RAG Facts & DB Telemetry"]
    C --> P["3. Planning<br/>Decompose into Steps"]
    P --> TS["4. Tool Selection<br/>Catalog Registry Check"]
    TS --> TE["5. Tool Execution<br/>Isolated in SAVEPOINT"]
    TE --> O["6. Observation<br/>Metrics & Trace Capture"]
    O --> EV{"7. Evaluation<br/>Constraints Met?"}
    
    EV -->|Yes| PF["8. Persist Findings<br/>Step Records & Vectors"]
    EV -->|No - Replan| P
    EV -->|Fatal / Denied| PF

    subgraph CONCERNS["Independent Operational Concerns"]
        direction TB
        CHECKPOINT["Crash Recovery & Leasing<br/>• Atomic Compare-and-Set Leases<br/>• Generation Fencing Tokens<br/>• Safe Replay of Persisted Steps"]
        APPROVAL["Human-in-the-Loop Governance<br/>• Actions Output in 'requested' Status<br/>• Agents Structurally Cannot Approve<br/>• Exclusive to Merchant Owner / Admin"]
    end

    PF -.-> CHECKPOINT
    PF -.-> APPROVAL

    classDef stage fill:#10182b,stroke:#d97757,stroke-width:1px,color:#f7ebd7;
    classDef decision fill:#2a1810,stroke:#d97757,stroke-width:2px,color:#fff3df;
    classDef concern fill:#182238,stroke:#70b88a,stroke-width:1px,color:#e2ecf8;

    class G,C,P,TS,TE,O,PF stage;
    class EV decision;
    class CHECKPOINT,APPROVAL concern;
```

*Figure 3: The 8-phase bounded agent execution lifecycle, highlighting how failure isolation, database savepoints, and durable checkpointing operate independently from merchant approval gating.*

### The 8 Bounded Lifecycle Stages
1. **Goal Setting (`goal_set`)**: Parses merchant objective, window parameters, and resource boundaries.
2. **Context Gathering (`context_gathering`)**: Ingests RAG factual context, verified order telemetry, and customer segments.
3. **Planning (`planning`)**: The agent's core engine breaks the objective into concrete sub-tasks.
4. **Tool Selection (`tools`)**: Identifies registered tools from `TOOL_REGISTRY` and validates caller permissions.
5. **Tool Execution (`tool_exec`)**: Executes the tool within an isolated database `SAVEPOINT`. Errors are captured without crashing sibling agents.
6. **Observation (`observation`)**: Records execution latency, token counts, error payloads, and intermediate results.
7. **Evaluation (`evaluation_result`)**: Validates findings against commercial rules. If confidence thresholds are not met, a bounded replan is triggered (up to `max_retries`).
8. **Persistence (`persist_findings`)**: Persists structured output to `agent_workflow_steps` and writes outcome embeddings to pgvector.

---

## <a id="multi-agent-orchestration--langgraph"></a>⚙️ Multi-Agent Orchestration & LangGraph

The orchestration architecture operates through two complementary, production-grade layers:
1. **`GrowthAgentOrchestrator`** (`backend/app/agents/orchestrator.py`): Step-level savepoints, lease management, fencing tokens, and database transaction boundaries.
2. **`LangGraphWorkflowExecutor`** (`backend/app/ai/langgraph_orchestrator/`): Compiled `StateGraph` managing state transitions, conditional edges, checkpointers, and cancellation hooks across all 14 agents.

### <a id="execution-modes-and-plans"></a>Execution Modes & Plans

| Mode | Target Use Case | Pipeline Plan Execution | LLM Dependency |
|:---|:---|:---|:---:|
| **`fast`** | Instant diagnostic scan | `GrowthMemoryAgent` (load) → `GrowthDiscoveryAgent` → `PaymentRecoveryAgent` → `OpportunityPrioritizationAgent` | None (Deterministic) |
| **`deep`** | Comprehensive business audit | Memory (load) → Discovery → Customer Intelligence → Payment Recovery → Campaign Strategist → Revenue Optimization → Experiment Agent → Prioritization | Optional |
| **`growth_team`** | 4-round adversarial debate | Memory (load) → Manager (plan) → Round 1 (Investigate) → Round 2 (Cross-Examine) → Round 3 (Rebut) → Round 4 (Synthesize) → Memory (persist) | Active LLM |
| **`team`** | Full collaborative pipeline | 14-Agent sequential workspace execution including Personalization and Handoffs | Active LLM |

### <a id="langgraph-stategraph-integration"></a>LangGraph StateGraph Integration

LangGraph compiles an authoritative `StateGraph(GrowthWorkflowState)` wiring all agents into conditional execution paths:

```mermaid
flowchart TD
    START([START]) --> VR["validate_request<br/>Validate Payload & Permissions"]
    VR --> LC["load_context<br/>Resolve Merchant & RAG Context"]
    LC --> ROUTE{"Route by Mode"}
    
    subgraph M_FAST["Mode: fast (Instant Deterministic Scan)"]
        FM["fast_memory_load"] --> FD["fast_discovery"]
        FD --> FP["fast_payment_recovery"]
        FP --> FO["fast_prioritization"]
    end

    subgraph M_DEEP["Mode: deep (Comprehensive Business Audit)"]
        DM["deep_memory_load"] --> DD["deep_discovery"]
        DD --> DC["deep_customer_intel"]
        DC --> DP["deep_payment_recovery"]
        DP --> DCS["deep_campaign_strategist"]
        DCS --> DR["deep_revenue_opt"]
        DR --> DE["deep_experiment"]
        DE --> DO["deep_prioritization"]
        DO --> DMP["deep_memory_persist"]
    end

    subgraph M_GT["Mode: growth_team (4-Round Multi-Agent Collaboration)"]
        GM["growth_team_memory_load"] --> GP["growth_team_manager_plan"]
        GP --> G_MKT["growth_team_marketing"]
        G_MKT --> G_PROD["growth_team_product"]
        G_PROD --> G_DES["growth_team_designer"]
        G_DES --> G_SOFT["growth_team_software"]
        G_SOFT --> G_PRIOR["growth_team_prioritization"]
        G_PRIOR --> GS["growth_team_manager_synth"]
        GS --> GMP["growth_team_memory_persist"]
    end

    ROUTE -->|fast| FM
    ROUTE -->|deep| DM
    ROUTE -->|growth_team| GM
    
    FO --> FW["finalize_workflow<br/>Snapshot Metrics & Status"]
    DMP --> FW
    GMP --> FW
    
    FW --> END([END])

    classDef nodeStyle fill:#10182b,stroke:#d97757,stroke-width:1px,color:#f7ebd7;
    classDef decision fill:#2a1810,stroke:#d97757,stroke-width:2px,color:#fff3df;
    classDef terminal fill:#0f2d1d,stroke:#70b88a,stroke-width:2px,color:#f0fdf4;

    class VR,LC,FM,FD,FP,FO,DM,DD,DC,DP,DCS,DR,DE,DO,DMP,GM,GP,G_MKT,G_PROD,G_DES,G_SOFT,G_PRIOR,GS,GMP,FW nodeStyle;
    class ROUTE decision;
    class START,END terminal;
```

*Figure 4: The compiled LangGraph StateGraph topology, highlighting conditional mode dispatch (`fast`, `deep`, `growth_team`), shared foundation nodes, and workflow finalization.*

### <a id="durable-lifecycle-and-recovery"></a>Durable Lifecycle, Lease Fencing & Recovery

Long-running agent workflows are defended against server restarts, timeouts, and multi-process contention by `WorkflowRunService` (`backend/app/services/workflow_run_service.py`):
- **Compare-and-Set Leases (`claim`)**: Workers acquire an atomic database lease (`DEFAULT_LEASE_SECONDS = 900`). A crashed cycle older than `STALE_TAKEOVER_SECONDS = 120` can be taken over safely by a replacement worker.
- **Generation Fencing Tokens (`StaleLeaseError`)**: Every lease acquisition increments the workflow's generation token. If a slow worker awakens after losing its lease, its write operations are strictly rejected to prevent stale state corruption.
- **Deterministic Step Identity**: Step keys are generated from stable hashes of `(mode, index, agent_name, phase)`. Replays of completed steps reuse persisted outputs, while illegitimate duplicate executions are rejected by unique database constraints.
- **Plan Compatibility Fingerprints**: Workflows persist a cryptographic fingerprint of their planned steps. A resume request against a modified codebase plan refuses to graft mismatched results, ensuring strict state integrity.
- **Savepoint Isolation**: Each agent step executes inside a database `SAVEPOINT`. If an agent encounters an unhandled exception, only its step is rolled back and marked `failed`. The parent cycle records `partial_success` and continues cleanly.

---

## <a id="the-4-round-agent-debate-protocol"></a>⚖️ The 4-Round Agent Debate Protocol

In `growth_team` mode, RazorGrowth AI executes a structured, adversarial multi-agent debate that tests hypotheses from multiple business angles:

```mermaid
sequenceDiagram
    autonumber
    actor Merchant as Merchant (User / Admin)
    participant Mgr as ManagerAgent
    participant Mkt as MarketingAgent
    participant Prod as ProductAgent
    participant Des as DesignerAgent
    participant Soft as SoftwareAgent
    participant Act as Actions & Guardrails

    Merchant->>Mgr: Submit Objective / Trigger Analysis
    Note over Mgr: Phase: Delegate & Decompose
    Mgr->>Mkt: Investigate Customer Retention Signals
    Mgr->>Prod: Investigate Product Affinity & AOV
    Mgr->>Des: Investigate Messaging & Creative Fit
    Mgr->>Soft: Investigate Technical & API Prerequisites

    rect rgb(16, 24, 43)
        Note over Mkt,Soft: Round 1: Individual Investigation
        Mkt-->>Mgr: Finding: 24% churn in 60-day cohort (Supporting)
        Prod-->>Mgr: Finding: SKU A + SKU B bundle uplift potential (Supporting)
        Des-->>Mgr: Finding: Discount messaging fatigue detected (Opposing)
        Soft-->>Mgr: Finding: Razorpay webhook latency within bounds (Supporting)
    end

    rect rgb(33, 19, 14)
        Note over Mkt,Soft: Round 2: Adversarial Cross-Examination
        Mkt->>Des: Challenges creative fatigue with segmented email proof
        Prod->>Mkt: Questions whether discounting cannibalizes full-price repeat buyers
        Soft->>Prod: Flags catalog inventory constraint on SKU B
    end

    rect rgb(16, 24, 43)
        Note over Mkt,Soft: Round 3: Formal Rebuttal & Defense
        Mkt-->>Mgr: Concedes to exclude active 30-day VIP cohort
        Des-->>Mgr: Proposes non-monetary VIP loyalty copy variant
        Prod-->>Mgr: Adjusts bundle ratio to clear inventory safely
    end

    rect rgb(42, 24, 16)
        Note over Mgr: Round 4: Executive Synthesis
        Mgr->>Act: Synthesize Consensus into Bounded Action Proposal
    end

    Act-->>Merchant: Action Proposal Ready for Review (Status: Requested)
    Merchant->>Act: POST /api/actions/{id}/approve (Human Decision)
    Act->>Act: Verify Double Guardrails & Idempotency
    Act-->>Merchant: Action Executed & Stamped to Immutable Audit Log
```

*Figure 5: Sequence diagram of the 4-round adversarial debate protocol, from initial manager delegation through multi-agent cross-examination, synthesis, and human approval.*

---

## <a id="human-in-the-loop-safeguards--double-guardrails"></a>🛡️ Human-in-the-Loop Safeguards & Double Guardrails

RazorGrowth AI guarantees that autonomous agents can never trigger direct financial transactions, drain ad budgets, or modify external customer data without verification:

```mermaid
flowchart TD
    AGENT["AI Agent Proposes Growth Action"] --> PREP["Action Created in 'requested' Status<br/>Stored in agent_actions"]
    
    subgraph G1["First Guardrail Pass: Pre-Approval Evaluation"]
        PREP --> CHK1{"Amount &le; GUARDRAIL_MAX_AMOUNT_INR?<br/>Default: ₹50,000 INR"}
        CHK1 -->|Exceeded| AUTO_REJ["Status: REJECTED<br/>Reason: GUARDRAIL_LIMIT_EXCEEDED"]
        CHK1 -->|Within Limit| AUD1["Audit Event Logged: action_proposed<br/>Actor: AI"]
    end
    
    AUD1 --> QUEUE["Action Placed in Merchant Approval Queue"]
    
    subgraph HUMAN_GATE["Human Gate: Owner / Admin Only"]
        QUEUE --> REVIEW["Merchant Inspects Proposal<br/>Rationale · Evidence · Scope · Will/Will-Not-Do"]
        REVIEW --> DECISION{"Merchant Decision"}
        DECISION -->|Reject| REJ_ACT["Status: REJECTED<br/>Actor: YOU<br/>Audit Event: action_rejected"]
        DECISION -->|Approve| APP_ACT["Status: APPROVED<br/>Actor: YOU<br/>Audit Event: action_approved"]
    end
    
    subgraph G2["Second Guardrail Pass: Pre-Execution Re-check"]
        APP_ACT --> RE_EVAL{"Re-validate Guardrails Live<br/>Balance · Volume · Rate Limits"}
        RE_EVAL -->|Fails| SAFE_STATE["Execution Aborted<br/>Safe State Persisted in Audit"]
        RE_EVAL -->|Passes| KILL_SW{"EXECUTION_ENABLED == true?"}
        KILL_SW -->|false - Default Dry Run| TEST_EXEC["Dry-Run / Test-Mode Response<br/>mode: 'test', executed: false<br/>Audit: action_executed_test_mode"]
        KILL_SW -->|true - Authorized Live| LIVE_EXEC["Execute External Provider Call<br/>Resend / Google Ads / Meta Ads"]
        LIVE_EXEC --> AUD2["Audit Event: action_executed<br/>Actor: SYS · Idempotency Key Locked"]
    end

    classDef pass fill:#10182b,stroke:#70b88a,stroke-width:1px,color:#f7ebd7;
    classDef gate fill:#f7ebd7,stroke:#d97757,stroke-width:2px,color:#2a1810;
    classDef fail fill:#301b12,stroke:#c85f43,stroke-width:1px,color:#fff3df;

    class CHK1,RE_EVAL,KILL_SW pass;
    class REVIEW,DECISION,APP_ACT gate;
    class AUTO_REJ,REJ_ACT,SAFE_STATE fail;
```

*Figure 6: The two-pass guardrail security workflow. All agent proposals are bounded by pre-approval limits, gated by human authentication, re-evaluated before execution, and governed by the global execution switch.*

### <a id="action-lifecycle-state-transitions"></a>Action Lifecycle State Transitions

The state diagram below maps all supported transitions for an `AgentAction` record (`backend/app/models/enums.py`):

```mermaid
stateDiagram-v2
    [*] --> Requested: Agent proposes action (propose_action)
    Requested --> Rejected: Pre-approval guardrail fails (Amount > Limit)
    Requested --> Rejected: Merchant rejects proposal (action_rejected)
    Requested --> Approved: Merchant approves proposal (action_approved)
    Approved --> Aborted: Pre-execution guardrail fails (Live limits)
    Approved --> Executing: Guardrails pass & Idempotency locked
    Executing --> Completed: Test-mode dry run (EXECUTION_ENABLED = false)
    Executing --> Completed: External API delivered (EXECUTION_ENABLED = true)
    Executing --> Failed: Provider network error / Timeout
    Completed --> [*]
    Rejected --> [*]
    Failed --> [*]
    Aborted --> [*]
```

*Figure 7: Finite state machine governing growth action proposals from creation in requested state to human review, double-guardrailed execution, and audit finalization.*

---

## <a id="external-integrations--execution-layer"></a>🔌 External Integrations & Execution Layer

The **Marketing AGI** execution engine connects to external advertising, messaging, and CRM providers.

| Provider | Service Type | Authentication Method | Live Read Capabilities | Write Capabilities (Approval-Gated) |
|:---|:---|:---|:---|:---|
| **Resend** | Email Infrastructure | API Key + Verified Domain Sender | Sender verification, sending quota | `send_email` (segmented campaigns) |
| **Google Ads** | PPC / Search Ads | OAuth2 (Refresh Token) + Developer Token | Customer accounts, campaign lists, spend | `create_campaign_paused` (Paused by default) |
| **Meta Ads** | Social Ad Campaigns | OAuth2 Long-Lived Token + Ad Account ID | Ad accounts, campaigns, reach metrics | `create_campaign_paused` (Paused by default) |
| **Instagram** | Organic / Visual Feed | Shared Meta Graph OAuth2 Token | Account metrics, media publishing status | `publish_photo` (two-step upload & publish) |
| **Internal CRM** | Customer Profiles | Multi-tenant PostgreSQL session | RFM scores, LTV, churn history | Internal customer tagging & segmentation |

### Security Invariants for External Providers
1. **Live Handshake Verification**: An integration card displays `CONNECTED` only after a live, authenticated round-trip verification request succeeds. Missing credentials or expired tokens display honest `NOT CONNECTED` states.
2. **At-Rest Fernet Encryption**: Workspace API secrets are encrypted using Fernet keys (`INTEGRATION_CREDENTIAL_KEY` or derived from `AUTH_SECRET_KEY`) before persisting to `integration_connections`. Secrets are never exposed in API responses, logs, or audit records.
3. **Signed OAuth State Tokens**: OAuth handshakes enforce a 15-minute TTL with HMAC-SHA256 signatures over `(merchant_id, provider, exp, nonce)` to eliminate cross-tenant CSRF risks.
4. **Global Execution Kill-Switch**: The platform ships with `EXECUTION_ENABLED=false` by default. When disabled, write operations return clean, simulated test outcomes without contacting external APIs.

---

## <a id="system-architecture"></a>🏛️ System Architecture & Request Pathways

RazorGrowth AI is architected as an authenticated, tenant-isolated multi-tier application:

```mermaid
flowchart LR
    subgraph CLIENT["Client Tier"]
        UI["React 19 + Vite 6<br/>Workspace & Canvas UI"]
    end

    subgraph API_GATE["FastAPI Gateway"]
        AUTH["Auth & Tenant Context<br/>Bearer JWT · merchant_ctx"]
        ROUTES["API Controllers<br/>/agents · /actions · /debate"]
    end

    subgraph ORCH["Dual Orchestration Engine"]
        LG["LangGraphWorkflowExecutor<br/>StateGraph · Mode Routing · Checkpoints"]
        GO["GrowthAgentOrchestrator<br/>Lease Fencing · Savepoint Isolation"]
    end

    subgraph AGENT_TIER["14 Agents & Tool Catalog"]
        AGENTS["14 Specialized Agents<br/>5 Main Team · 9 Specialists"]
        TOOLS["Canonical Tool Catalog<br/>12 Verified Implementations"]
    end

    subgraph PERSIST["PostgreSQL 16 + pgvector"]
        DATA[("Tenant Tables<br/>orders · payments · customers")]
        CHECK[("LangGraph Checkpoints<br/>Workflow State & Steps")]
        AUDIT_DB[("Immutable Audit Log<br/>AI / YOU / SYS Events")]
        VEC[("Vector Embeddings<br/>1536-dim Merchant Memory")]
    end

    subgraph PROVIDERS["Model & External Providers"]
        LLM["Cloudflare Workers AI / OpenAI<br/>resolve_llm_provider"]
        EXT["External APIs (Approval-Gated)<br/>Resend · Google Ads · Meta Ads"]
    end

    UI -->|HTTPS / Bearer JWT| AUTH
    AUTH --> ROUTES
    ROUTES --> LG
    LG <--> GO
    LG --> AGENTS
    AGENTS --> TOOLS
    AGENTS <--> LLM
    GO --> DATA
    LG --> CHECK
    TOOLS --> DATA
    ROUTES --> AUDIT_DB
    ROUTES -->|After Human Approval| EXT
    AGENTS --> VEC

    classDef c1 fill:#10182b,stroke:#d97757,stroke-width:1px,color:#f7ebd7;
    classDef c2 fill:#182238,stroke:#336791,stroke-width:1px,color:#e2ecf8;
    classDef c3 fill:#0f2d1d,stroke:#70b88a,stroke-width:1px,color:#f0fdf4;

    class UI,AUTH,ROUTES,LG,GO c1;
    class AGENTS,TOOLS,LLM,EXT c2;
    class DATA,CHECK,AUDIT_DB,VEC c3;
```

*Figure 8: High-level architectural data flow from the React client through FastAPI security middleware, dual orchestration, agent execution, and durable PostgreSQL/pgvector persistence.*

### <a id="shipped-frontend-experience-routes"></a>Shipped Frontend Experience Routes
- **`/`**: Public product landing page, manifesto, interactive merchant world canvas, and feature architecture.
- **`/growth-radar`**: Real-time business diagnostic radar computed directly from PostgreSQL transaction tables.
- **`/agents`**: Coordinated 14-Agent Growth Team dashboard displaying active statuses, tool capabilities, and run logs.
- **`/manager-agent`**: Manager Agent autonomous coordinator panel (goal intake, validated execution planning, workflow status).
- **`/marketing-agent`**: Marketing AGI workstation (integrations stack with Resend, Google Ads, Meta Ads, Instagram).
- **`/designer-agent`**: Creative studio for asset review, brief generation, and Cloudflare FLUX image synthesis.
- **`/product-agent`**: Product catalog intelligence, SKU affinity mapping, and basket bundle discovery.
- **`/software-agent`**: Technical feasibility and integration architecture analysis console.
- **`/debate`**: Multi-agent adversarial debate viewer with round-by-round cross-examination cards and debate chat assistant.
- **`/actions`**: Growth Actions approval console featuring double-guardrail status and immutable audit timeline.
- **`/checkout`**: Live AI Buyer simulator running genuine Razorpay TEST transactions against merchant products.

---

## <a id="technology-stack"></a>🛠️ Technology Stack

Every component and library in RazorGrowth AI has been verified against the active codebase manifests:

| Layer | Component | Verified Version | Purpose & Architecture |
|:---|:---|:---|:---|
| **Backend Framework** | **FastAPI** | `0.141.1` | High-performance asynchronous API, dependency injection, and Pydantic validation |
| **ASGI Server** | **Uvicorn** | `0.52.4` | Production ASGI web server running FastAPI |
| **ORM & Relational DB** | **SQLAlchemy** | `2.0.52` | Declarative 2.0 ORM, connection pooling, and multi-tenant scoping |
| **Database Migrations** | **Alembic** | `1.16.4` | Schema versioning; 15 revisions single-head chain up to `p5e2r0na1z04` |
| **Primary Database** | **PostgreSQL** | `16.x` | Enterprise relational database with row-level transactional consistency |
| **Vector Storage** | **pgvector** | `0.3.6` | 1536-dimensional vector embedding storage for merchant knowledge RAG |
| **Agent Orchestration** | **LangGraph** | `1.2.16` | Multi-agent state machines, cyclical graphs, state reducers, and checkpointers |
| **Agent Abstractions** | **LangChain** | `1.4.6` / `1.6.12` | Structured prompt templates, message abstractions, and tool schemas |
| **Payment Gateway** | **Razorpay Python** | `2.0.1` | Order creation, payment verification, and HMAC-SHA256 webhook validation |
| **Authentication & Crypto**| **PyJWT & Cryptography** | `2.13.0` / `44.0.2` | HS256 JWT token lifecycle and Fernet encryption for workspace secrets |
| **HTTP Client** | **HTTPX** | `0.28.1` | Asynchronous HTTP client for provider verification and webhooks |
| **Testing Engine** | **Pytest** | `8.4.2` | 2,155-test suite covering unit, recovery, security, and contract fixtures |
| **Frontend Framework** | **React** | `19.0.0` | Latest concurrent React framework powering merchant workspace UIs |
| **Frontend Tooling** | **Vite** | `6.0.5` | Next-generation ESM bundler and development proxy server |
| **Type Safety** | **TypeScript** | `5.7.2` | End-to-end typed interfaces across API clients and component states |
| **Client Routing** | **React Router** | `7.18.2` | Declarative client-side routing with role-based auth wrappers |
| **Interactive Canvas** | **Pixi.js** | `8.5.1` | Hardware-accelerated 2D canvas rendering for the Merchant World interface |
| **Typography** | **Archivo & IBM Plex** | `@fontsource` | Variable display typography paired with monospace code aesthetics |

---

## <a id="repository-structure"></a>📁 Repository Structure

```
RazorGrowth AI/
├── backend/
│   ├── Dockerfile                   # FastAPI container image (auto-migrating)
│   └── app/
│       ├── agents/                  # 14 Specialized AI agents & orchestration
│       │   ├── catalog.py           # Canonical 12-tool registry & tool schemas
│       │   ├── orchestrator.py      # GrowthAgentOrchestrator (fast/deep/team/growth_team)
│       │   ├── permissions.py       # Capability model & FORBIDDEN_CAPABILITIES
│       │   ├── registry.py          # Authoritative 14-agent registry & catalog
│       │   └── manager_agent.py     # ManagerAgent coordination & debate synthesis
│       ├── ai/
│       │   ├── langchain_adapter/   # Model adapters, tools, and structured outputs
│       │   ├── langgraph_orchestrator/ # StateGraph, 14 agent nodes, checkpointer
│       │   └── llm/                 # Cloudflare Workers AI & OpenAI provider layer
│       ├── api/
│       │   ├── deps.py              # Auth & tenant dependency injection (merchant_ctx)
│       │   └── routes/              # Modular API endpoints (actions, debate, radar, etc.)
│       ├── core/                    # Security, logging, log-redaction filter, config
│       ├── data/                    # Deterministic demo dataset & bootstrap tools
│       ├── db/                      # Database engine, session maker, base models
│       ├── models/                  # Tenant-scoped SQLAlchemy 2.0 ORM models
│       ├── schemas/                 # Pydantic v2 validation contracts
│       └── services/                # Business services (actions, debate, radar, recovery)
├── frontend/
│   ├── Dockerfile                   # Multi-stage Vite build served via Nginx
│   ├── package.json                 # React 19, TypeScript 5.7, Vite 6 dependencies
│   └── src/
│       ├── components/              # WindowPanel, Button, StatusBadge, AuthGuards
│       ├── features/public/         # Landing page, Merchant World canvas, Hero
│       ├── lib/                     # Typed API client, authentication context
│       ├── pages/                   # ActionsPage, AgentsPage, DebatePage, Radar, etc.
│       └── styles/                  # Editorial design tokens (tokens.css, components.css)
├── migrations/
│   ├── env.py                       # Alembic environment configuration (pgvector)
│   └── versions/                    # 15 single-head migrations (up to p5e2r0na1z04)
├── scripts/
│   └── start.sh                     # Backend container entrypoint (db wait + migration + uvicorn)
├── tests/                           # 62 test files (2,155 collected test cases)
├── docker-compose.yml               # Complete stack: PostgreSQL 16 + pgvector, Backend, Frontend
├── requirements.txt                 # Exact pinned Python dependencies
└── .env.example                     # Comprehensive configuration template with blank secrets
```

---

## <a id="environment-configuration"></a>🔧 Environment Configuration

All settings are managed via environment variables and parsed through Pydantic Settings (`backend/app/core/config.py`). Copy `.env.example` to `.env` to customize settings.

> [!IMPORTANT]
> Never commit `.env` files containing real production secrets or API credentials. The table below lists variable names and safe placeholder defaults.

| Environment Variable | Default Value | Description & Security Boundary |
|:---|:---|:---|
| `APP_ENV` | `development` | Runtime environment (`development`, `staging`, `production`) |
| `DATABASE_URL` | `postgresql://...` | Connection URI for PostgreSQL 16 + pgvector |
| `AUTH_SECRET_KEY` | *(Required in local)* | Secret key for signing JWT tokens (min 32 characters) |
| `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` (24h) | JWT access token lifespan |
| `EXECUTION_ENABLED` | `false` | **Global safety switch**. Keep `false` to enforce test-mode execution |
| `GUARDRAIL_MAX_AMOUNT_INR` | `50000` | Maximum monetary amount (INR) an agent action may propose |
| `GUARDRAIL_REQUIRE_APPROVAL` | `true` | When true, every money-touching action requires human owner/admin approval |
| `LLM_PROVIDER` | `cloudflare` | Active LLM provider (`cloudflare` or `openai`) |
| `CLOUDFLARE_ACCOUNT_ID` | *(Optional)* | Cloudflare Workers AI Account ID |
| `CLOUDFLARE_API_TOKEN` | *(Optional)* | Cloudflare Workers AI API Token (used for text & FLUX image models) |
| `CLOUDFLARE_TEXT_MODEL` | `@cf/zai-org/glm-4.7-flash` | Text generation model identifier on Workers AI |
| `LLM_API_KEY` | *(Optional)* | OpenAI API key (used if `LLM_PROVIDER=openai`) |
| `LLM_MODEL` | `gpt-4o-mini` | OpenAI model identifier |
| `RAZORPAY_KEY_ID` | *(Optional)* | Razorpay **TEST** Key ID (must begin with `rzp_test_`) |
| `RAZORPAY_KEY_SECRET` | *(Optional)* | Razorpay **TEST** Key Secret |
| `RAZORPAY_WEBHOOK_SECRET`| *(Optional)* | HMAC-SHA256 signature secret for inbound Razorpay webhooks |
| `RESEND_API_KEY` | *(Optional)* | Default platform Resend key (per-workspace keys set via UI take precedence) |
| `GOOGLE_OAUTH_CLIENT_ID`| *(Optional)* | Google OAuth2 Client ID for Google Ads integration |
| `META_APP_ID` | *(Optional)* | Meta Application ID for Meta Ads and Instagram integration |
| `INTEGRATION_CREDENTIAL_KEY`| *(Optional)* | 32-byte URL-safe base64 Fernet key for encrypting workspace integration secrets |

---

## <a id="database-setup--alembic-migrations"></a>🗄️ Database Setup & Alembic Migrations

RazorGrowth AI uses a fully versioned relational schema backed by Alembic. The migration graph forms a verified, single-head chain of 15 revisions ending at `p5e2r0na1z04`.

```
alembic_version chain:
Initial Schema ──> Phase 3 ──> Phase 4 (Actions) ──> Phase 5 (Radar/Agents) ──> Phase 6 (Auth) ──> h4n0d0ff2a11 (Handoffs) ──> p5e2r0na1z04 (Personalization) [HEAD]
```

### Applying Migrations
When running via Docker Compose, migrations execute automatically on container startup. To apply migrations manually from the repository root:
```bash
alembic upgrade head
```

### Checking Current Revision
```bash
alembic current
```

### Multi-Tenant Schema Invariants
- Every primary business table (`orders`, `payments`, `customers`, `products`, `growth_opportunities`, `agent_actions`, `agent_debates`, `integration_connections`) contains a non-nullable `merchant_id` foreign key.
- Compound indexes enforce tenant scoping: `(merchant_id, status)`, `(merchant_id, created_at)`.
- The pgvector extension (`CREATE EXTENSION IF NOT EXISTS vector`) is provisioned in the first migration and supports 1536-dimensional cosine distance searches.

---

## <a id="api-usage--endpoints"></a>📡 API Usage & Endpoints

All protected endpoints require an `Authorization: Bearer <token>` header obtained from `/api/auth/login`.

<details>
<summary><b>1. Authentication: Register, Login & Identity</b></summary>

```bash
# Register a new merchant workspace
curl -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "founder@merchant.com",
    "password": "SecurePassword123!",
    "merchant_name": "Acme Retailers"
  }'

# Login to obtain JWT Bearer Token
curl -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "founder@merchant.com",
    "password": "SecurePassword123!"
  }'

# Inspect authenticated identity
curl -X GET http://localhost:8001/api/auth/me \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
```
</details>

<details>
<summary><b>2. Growth Radar: Live Business Telemetry</b></summary>

```bash
# Retrieve real-data Growth Radar signals and summary
curl -X GET "http://localhost:8001/api/growth/radar?window_days=30" \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
```
*Sample Response:*
```json
{
  "summary": "Revenue increased by 14.2% over the last 30 days. However, checkout payment failures spiked by 6.8% primarily driven by card network timeouts.",
  "metrics": {
    "captured_revenue_inr": 248500.0,
    "transactions_count": 312,
    "customers_count": 184,
    "failed_payments_count": 21,
    "average_order_value_inr": 796.47
  },
  "signals": [
    {
      "signal_type": "payment_failure_spike",
      "severity": "high",
      "confidence": 0.94,
      "estimated_lost_revenue_inr": 16720.0
    }
  ]
}
```
</details>

<details>
<summary><b>3. AI Team: Launching Multi-Agent Workflows</b></summary>

```bash
# Launch a 4-round Multi-Agent Growth Team Debate
curl -X POST http://localhost:8001/api/agents/run \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "growth_team",
    "params": {
      "objective": "Recover high-value abandoned checkouts and reduce repeat churn",
      "window_days": 30
    }
  }'

# Check Workflow Execution Status
curl -X GET http://localhost:8001/api/agents/status/<WORKFLOW_RUN_ID> \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
```
</details>

<details>
<summary><b>4. Growth Actions: Review, Approve & Execute</b></summary>

```bash
# List all pending action proposals
curl -X GET "http://localhost:8001/api/actions?status=requested" \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>"

# Approve an action (Owner / Admin ONLY)
curl -X POST http://localhost:8001/api/actions/<ACTION_ID>/approve \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "notes": "Approved based on debate findings; scope clamped to 10% discount"
  }'

# Trigger execution behind guardrails
curl -X POST http://localhost:8001/api/actions/<ACTION_ID>/execute \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>"

# Inspect the immutable audit trail for an action
curl -X GET http://localhost:8001/api/actions/<ACTION_ID>/audit \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>"
```
</details>

---

## <a id="testing-and-verification"></a>🧪 Testing and Verification

RazorGrowth AI is backed by an automated testing suite comprising **2,155 collected tests** across 62 test files.

### Running Python Tests
Default test execution runs against an isolated in-memory SQLite schema with custom JSONB-compatible DDL, ensuring test runs never mutate or depend on production PostgreSQL data:
```bash
# Run the complete test suite
pytest

# Run tests with short execution summary
pytest -q
```

### Focused Backend Test Groups
```bash
# Run multi-agent LangGraph integration tests (all 14 agents)
pytest tests/test_langchain_langgraph_14_agents.py

# Run workflow recovery, leasing, and fence token unit tests
pytest tests/test_workflow_recovery_unit.py

# Run security, guardrails, and role-based access tests
pytest tests/test_agent_security.py tests/test_roles.py tests/test_tenant_isolation.py
```

### PostgreSQL Integration Tests & Limitations
Three specific test modules validate physical PostgreSQL features (pgvector indexes, concurrency locks, and migration chains):
- `tests/test_workflow_recovery_postgres.py`
- `tests/test_recovery_safety_postgres.py`
- `tests/test_postgres_migration.py`

> [!NOTE]
> **Deliberate Skipping**: These three integration suites require a live PostgreSQL connection string via the `POSTGRES_DSN` environment variable. When `POSTGRES_DSN` is not set, they are **deliberately skipped** to prevent accidental mutation of local databases. They should never be described as passing until run against an explicit test PostgreSQL instance:
> ```bash
> # Linux/macOS
> POSTGRES_DSN="postgresql://razorgrowth:razorgrowth@localhost:5432/razorgrowth" pytest tests/test_workflow_recovery_postgres.py
>
> # Windows PowerShell
> $env:POSTGRES_DSN="postgresql://razorgrowth:razorgrowth@localhost:5432/razorgrowth"; pytest tests/test_workflow_recovery_postgres.py
> ```

### Frontend Testing & Verification
```bash
cd frontend

# Run specialist roster definition contract tests
npm run test:roster

# Run office canvas layout tests
npm run test:office

# Run responsive CSS contract tests
npm run test:responsive

# Validate full production build
npm run build
```

---

## <a id="configuration--troubleshooting"></a>❓ Configuration & Troubleshooting

| Symptom / Error | Root Cause | Verified Resolution |
|:---|:---|:---|
| `Docker daemon not running` | Docker Desktop is stopped or starting up | Start Docker Desktop, wait for the engine status indicator to turn green, then rerun `docker compose up`. |
| `Port 5432 / 8001 / 5173 is already allocated` | Existing local services (PostgreSQL or Node) occupy required ports | Change `POSTGRES_PORT`, `BACKEND_PORT`, or `FRONTEND_PORT` in your `.env` file (e.g., `FRONTEND_PORT=5174`). |
| `422 Unprocessable Entity` on signup | Password fails platform complexity policy | Passwords must be at least 12 characters long and contain at least one letter and one number. |
| `Database not initialized` on first local request | Alembic migrations have not been applied to PostgreSQL | Run `alembic upgrade head` from repository root before starting the Uvicorn server (Docker Compose handles this automatically). |
| `403 Forbidden: MERCHANT_ACCESS_DENIED` | Caller attempted to access data belonging to a different tenant workspace | Verify the `Authorization: Bearer <token>` corresponds to an active user belonging to that specific workspace. |
| `LLM 429: Provider Rate Limited` | Free-tier Cloudflare Workers AI or OpenAI request rate limits reached | Wait for the provider rate window to refresh. The system handles rate limits cleanly without corrupting run state. |
| `pgvector extension missing` | Using standard `postgres:16` instead of `pgvector/pgvector:pg16` | Ensure your Docker image is set to `pgvector/pgvector:pg16` as defined in `docker-compose.yml`. |

---

## <a id="implementation-status--honest-engineering-boundaries"></a>🔍 Implementation Status & Honest Engineering Boundaries

In keeping with venture-grade engineering standards, RazorGrowth AI distinguishes verified operational capabilities from unconfigured external dependencies and future aspirations:

### Shipped & Verified Functionality
- ✅ **14 Registered Specialized Agents**: 5 Main Team agents + 9 Domain Specialists fully instantiated in `backend/app/agents/registry.py`.
- ✅ **LangGraph Multi-Agent Architecture**: Shared `StateGraph` compiled across all 14 agents with durable checkpointers.
- ✅ **Workflow Checkpointing & Recovery**: Atomic lease claims, generation fencing, savepoint isolation, and safe step replays.
- ✅ **Strict Capability & Permission Model**: Invariants forbidding agent execution or approval enforced in code and validated in unit tests.
- ✅ **Human Approval Gating**: Approval/rejection endpoints restricted to owner/admin roles; actions proposed in `requested` state.
- ✅ **Double Guardrails**: Maximum financial amount ceilings (`GUARDRAIL_MAX_AMOUNT_INR`) re-evaluated before execution.
- ✅ **Immutable Audit Trail**: Chronological event timeline recording every tool call, decision, and error with `AI`, `YOU`, `SYS` markers.
- ✅ **Razorpay TEST Ingestion & AI Buyer**: Genuine TEST orders, payments, webhooks, and decline handling.
- ✅ **External Integration Infrastructure**: Resend, Google Ads, Meta Ads, and Instagram adapters with Fernet-encrypted credentials.

### Honest Engineering Boundaries & Blockers
- ⚠️ **Live Monetary Execution Switch**: `EXECUTION_ENABLED` defaults to `false`. Live payment modification requires deliberate configuration; simulated test-mode preview is returned otherwise.
- ⚠️ **Web Research Service**: `services/research.py` is fully implemented with HTML stripping and prompt injection filters, but returns `status="unavailable"` until a live search API credential is provided.
- ⚠️ **Orchestration Verb Tool Labels**: 28 agent tool labels represent internal reasoning and orchestration verbs rather than external data-fetching tools. They are reported transparently under `unimplemented_tools` in the tool catalog.
- ⚠️ **RAG Knowledge Embeddings**: Pgvector RAG retrieval gates on `LLM_API_KEY`. If unset, agents degrade to structured database querying rather than vector search.

---

## <a id="product-roadmap"></a>🗺️ Product Roadmap

The following capabilities represent future development phases and are not currently active in production:

- [ ] **Multi-Merchant Agency Command View**: A consolidated multi-tenant dashboard allowing growth agencies to oversee multiple merchant portfolios from a single operator session.
- [ ] **Automated Closed-Loop A/B Measurement**: Automatic attribution linking executed email and ad actions back to post-campaign Razorpay order volume to evaluate statistical lift.
- [ ] **Real-Time WebSocket Agent Streaming**: Live streaming of intermediate agent thought traces, tool invocations, and debate arguments directly to the frontend workspace.
- [ ] **Live-Mode Razorpay Automated Refunds & Payment Links**: Enabling verified, human-approved refunds and payment links on production Razorpay accounts under biometric re-authentication.

---

## <a id="contributing-guidelines"></a>🤝 Contributing Guidelines

We welcome contributions to RazorGrowth AI. To maintain high code quality and architectural integrity:

1. **Fork and Branch**: Create a feature branch off `main` (`git checkout -b feature/growth-enhancement`).
2. **Follow Invariants**:
   - Never grant agents direct database mutation or action approval capabilities.
   - Always route write actions through `ActionService.create_action` in `requested` status.
   - Ensure all queries are scoped by `merchant_id`.
3. **Write Tests**: Add corresponding test cases in `tests/` ensuring no regression in the test suite.
4. **Run Verification**: Ensure `pytest` passes and `npm run build` succeeds in the frontend directory.
5. **Submit a Pull Request**: Provide a clear description of changes, architectural rationale, and verification steps.

---

## <a id="license--acknowledgments"></a>📄 License & Acknowledgments

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for complete details.

**Copyright © 2026 DHEERAJ**. All rights reserved.

Built with rigor for the modern e-commerce ecosystem, powered by FastAPI, React 19, LangGraph, and Razorpay TEST-mode agentic commerce.

---

<div align="center">
  <sub>RazorGrowth AI · Autonomous Merchant Growth & Agentic Commerce Engine · Engineered for Resilience & Transparency</sub>
</div>
