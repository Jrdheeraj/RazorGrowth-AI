# Phase 6 — Authentication, Multi-Tenancy & Production Security

Status: **implemented**. This document describes the architecture, the security
model, and the operational runbook for everything added in Phase 6.

The central constraint of this phase: add authentication, tenant isolation,
roles, agent hardening, a Razorpay boundary, and production hardening —
**without changing any Phase 3/4/5 behaviour**. The full pipeline is preserved:

```
Agent → Observation → Reasoning → Opportunity → Simulation → Proposal
→ Guardrail #1 → Human Approval → Guardrail #2 → Execution
→ Measurement → Memory → Learning
```

---

## 1. Authentication

### Model
- `users` table (`backend/app/models/user.py`): UUID pk, unique lowercase email,
  `password_hash`, optional `full_name`, `status` (`active` / `disabled`),
  timestamps.
- Passwords are hashed with **scrypt (RFC 7914)** via `hashlib.scrypt`
  (`backend/app/core/security.py`): 16-byte random salt per password, N=2^14,
  r=8, dklen=32, stored as `scrypt$N$r$p$salt$digest`. Verification is
  constant-time (`hmac.compare_digest`). Plaintext passwords are never stored,
  logged, or returned. Policy: ≥ `PASSWORD_MIN_LENGTH` (12) chars with at least
  one letter and one digit.
- Tokens are **HS256 JWTs** minted by `POST /api/auth/login`
  (PyJWT). Claims: `sub` (user id), `email`, `type=access`, `iat`, mandatory
  `exp` (`AUTH_ACCESS_TOKEN_EXPIRE_MINUTES`, default 60), `iss`, `jti`.
- Validation (`decode_access_token`) enforces signature, expiry, type, issuer
  and a well-formed subject; failures map to stable codes:
  - missing header → `401 NOT_AUTHENTICATED`
  - expired → `401 TOKEN_EXPIRED`
  - anything else invalid → `401 TOKEN_INVALID`
  - disabled account → `403 USER_DISABLED` (login and every protected request)
- Login errors are identical for unknown email and wrong password
  (`401 INVALID_CREDENTIALS`) — no account enumeration.

### Endpoints
| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/register` | Toggleable via `AUTH_ENABLE_REGISTRATION`; policy-checked; rate limited |
| POST | `/api/auth/login` | Rate limited per client IP |
| GET | `/api/auth/me` | User + memberships |
| GET | `/api/auth/merchants` | Accessible merchants + roles |
| GET/POST/PATCH/DELETE | `/api/auth/merchants/{merchant_id}/members…` | Admin/owner membership administration |

Bootstrap CLI for the first owner:
```bash
python -m backend.app.data.bootstrap_admin \
    --email owner@example.com --password 'A-Long-Password-123'
```

---

## 2. Multi-Tenancy

```
User ──< MerchantMembership >── Merchant
              (role, status)
```

- `memberships` table: unique `(user_id, merchant_id)`, role, active/disabled status.
- **Isolation rule:** every request's merchant identity comes from the
  authenticated user's *active memberships* (`backend/app/api/deps.py`). A
  client-supplied `merchant_id` — query param or body field — must equal one of
  those memberships or the request is rejected `403 MERCHANT_ACCESS_DENIED`
  without disclosing whether that merchant exists.
- One membership → implicit context. Multiple memberships without an explicit
  choice → `400 AMBIGUOUS_MERCHANT`. No memberships → `403 NO_MERCHANT_MEMBERSHIP`.
- All queries are filtered by the resolved tenant id; single-resource reads of
  another tenant's objects return the same answer as "not found" where that was
  already the contract (agent runs, customer insights), preserving no-leak semantics.
- Development convenience only: `AUTH_MODE=optional` lets unauthenticated local
  requests fall back to the pre-auth single-tenant behaviour so existing tooling
  and tests keep working. Any request that *does* present a token is fully
  validated in both modes. Production refuses to boot in optional mode.

---

## 3. Roles & Permission Matrix

Roles live on the membership (`owner`, `admin`, `operator`, `analyst`;
`backend/app/core/roles.py`):

| Capability | owner | admin | operator | analyst |
|---|---|---|---|---|
| Read merchant-scoped data | ✔ | ✔ | ✔ | ✔ |
| Run agents / analyses / simulations / ingest / refresh | ✔ | ✔ | ✔ | ✘ |
| Execute approved actions (behind Guardrail #2) | ✔ | ✔ | ✔ | ✘ |
| Approve / reject actions | ✔ | ✔ | ✘ | ✘ |
| Manage members (operator/analyst tier) | ✔ | ✔ | ✘ | ✘ |
| Grant/revoke/change owner role | ✔ | ✘ | ✘ | ✘ |

Invariants enforced by tests:
- No role bypasses guardrails — approval-time Guardrail #1 and execution-time
  Guardrail #2 apply regardless of role.
- Owner-tier operations require owner; the last active owner cannot be demoted,
  disabled, or removed (`LAST_OWNER_PROTECTED`).

---

## 4. Agent Security

- Agents are **not users**: there is no signup/login path, no role, and no
  membership. A forged JWT claiming an agent identity fails closed because the
  subject resolves to no user row (`401 TOKEN_INVALID`).
- Capability registry (`backend/app/agents/permissions.py`) unchanged from
  Phase 5, now also covered by the Phase 6 suite: for **every** agent × **every**
  forbidden capability (`approve_action`, `reject_action`, `execute_action`,
  `bypass_guardrails`, `direct_database_mutation`, `send_money`),
  `assert_permission` raises `AgentPermissionError`.
- Approval/rejection/execution exist only as human-only HTTP endpoints guarded
  by roles; the AI toolkit exposes read-only tools only.
- Production kill switch: when `APP_ENV=production` and `EXECUTION_ENABLED=false`
  (default), `action_service.execute_action` refuses every execution with
  `EXECUTION_DISABLED_BY_ENVIRONMENT`.

---

## 5. Razorpay Test Mode Boundary

`backend/app/integrations/razorpay.py` is the single integration boundary:

| Adapter | Selected when | Behaviour |
|---|---|---|
| `DisabledRazorpayClient` | `RAZORPAY_ENABLED=false` (**default**) | Honest non-success `RAZORPAY_DISABLED`; nothing charged |
| `TestModeRazorpayClient` | `RAZORPAY_ENABLED=true` + `RAZORPAY_TEST_MODE=true` | Deterministic simulation, `simulated=True executed=False`, no network |
| `LiveRazorpayClient` | `RAZORPAY_ENABLED=true` + test mode off | Refuses honestly (`RAZORPAY_LIVE_RETRY_NOT_IMPLEMENTED`); real execution remains unimplemented |

- Credentials come exclusively from env (`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`);
  never hardcoded, logged, or included in API responses
  (`safe_public_dict()` projections expose booleans only).
- Webhooks: `POST /api/webhooks/razorpay` validates
  `X-Razorpay-Signature = hex(HMAC_SHA256(secret, raw_body))` in constant time;
  missing secret → `503 WEBHOOK_NOT_CONFIGURED` (**fails closed**); bad signature
  → `400 INVALID_SIGNATURE`. Valid deliveries are recorded as audit events only —
  webhooks never trigger money movement.

---

## 6. Security Hardening

- **Production fail-fast** (`core/middleware.validate_production_safety`):
  refuses to start unless `AUTH_SECRET_KEY` ≥ 32 chars, `AUTH_MODE=required`,
  explicit `TRUSTED_HOSTS`.
- **CORS** from `CORS_ORIGINS` (empty default = same-origin only);
  **TrustedHostMiddleware** when explicit hosts are configured.
- **Security headers** on every response: `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `X-Permitted-Cross-Domain-Policies`, `Cache-Control: no-store`; HSTS in
  production.
- **Rate limiting** (`core/ratelimit.py`): sliding window per IP per bucket;
  strict on auth endpoints, separate bucket for webhooks; configurable /
  disableable.
- **Secret-safe logging** (`core/logfilter.py`): redacting filter scrubs known
  secret values from messages and args as defence-in-depth.
- **Errors:** catch-all handler returns generic JSON; no stack traces, secrets,
  or internals in any response body.

---

## 7. Environment Variables

See `.env.example` for the annotated list. Highlights:

```
AUTH_MODE=required            # secure default; 'optional' is dev-only
AUTH_SECRET_KEY=<generated>   # python -c "import secrets; print(secrets.token_urlsafe(48))"
AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=60
PASSWORD_MIN_LENGTH=12
CORS_ORIGINS=                 # e.g. http://localhost:5173
TRUSTED_HOSTS=*               # production: explicit hostnames
RATE_LIMIT_AUTH_REQUESTS=10   # per 300 s window
RAZORPAY_ENABLED=false
RAZORPAY_TEST_MODE=false
RAZORPAY_WEBHOOK_SECRET=
EXECUTION_ENABLED=false
```

---

## 8. Local Development

```bash
docker compose up -d
alembic upgrade head
python -m backend.app.data.seed                       # synthetic commerce data
python -m backend.app.data.bootstrap_admin \
    --email you@example.com --password 'A-Long-Password-123'
uvicorn backend.app.main:app --reload                  # http://127.0.0.1:8000/docs
```

For zero-friction anonymous browsing you may set `AUTH_MODE=optional` in your
local `.env` (never in production). Otherwise obtain tokens:

```bash
curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"A-Long-Password-123"}'
# use Authorization: Bearer <access_token> on subsequent calls
```

---

## 9. CI

`.github/workflows/ci.yml` runs four jobs on push/PR to main:

1. **backend-tests** — pip install, compile-all, secret scan
   (`scripts/check_no_secrets.sh`), full pytest matrix (Python 3.11/3.12).
2. **migration-consistency** — fresh PostgreSQL 16 + pgvector service;
   `alembic upgrade head` from scratch, verify heads/current, drift check via
   `alembic check` (documented baseline noise filtered).
3. **backend-startup** — import app, assert all Phase 3/4/5/6 routes registered
   and no `/api/api/*` duplication, boot uvicorn against SQLite, hit
   `/api/health`, `/openapi.json`, `/docs`.
4. **frontend-build** — `npm ci && npm run build` (type-check + Vite build).

CI requires no production secrets.

---

## 10. Production Deployment Considerations

- Set `APP_ENV=production`; the server then enforces: strong `AUTH_SECRET_KEY`,
  `AUTH_MODE=required`, explicit `TRUSTED_HOSTS`.
- Keep `EXECUTION_ENABLED=false` until execution has been deliberately reviewed;
  `RAZORPAY_*` credentials only via secret manager; configure
  `RAZORPAY_WEBHOOK_SECRET` before exposing the webhook endpoint publicly.
- Terminate TLS at a reverse proxy (HSTS header is emitted in production).
- The in-memory rate limiter is per-process; front horizontal replicas with a
  gateway limiter if needed.
- Run Alembic migrations as a deployment step (`alembic upgrade head`).
