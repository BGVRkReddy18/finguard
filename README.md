# FinGuard — Real-Time Fraud Detection & AI Risk Analyst Platform

[![CI](https://github.com/BGVRkReddy18/finguard/actions/workflows/ci.yml/badge.svg)](https://github.com/BGVRkReddy18/finguard/actions/workflows/ci.yml)

**Live demo: [gvrkrishnareddybommareddy-finguard.hf.space](https://gvrkrishnareddybommareddy-finguard.hf.space)** — sign in as `analyst` / `finguard123`
or `manager` / `finguard123`. (Hosted free on Hugging Face Spaces; data is simulated.)

FinGuard scores card transactions for fraud in real time as they stream through Kafka, explains every
decision, and routes suspicious ones to a case-management workflow for fraud analysts — with a full
audit trail, the way banks require.

## Architecture

```
┌────────────┐  transactions.raw  ┌──────────────────────┐  transactions.scored  ┌────────────────┐
│ Simulator  │ ─────────────────▶ │  ML Service (FastAPI)│ ────────────────────▶ │ Ingest worker  │
│ (Kafka     │   keyed by         │  • Redis feature     │                       │ (Django cmd)   │
│  producer) │   customer_id      │    store (online)    │                       │ idempotent     │
└────────────┘                    │  • explainable scorer│                       │ upsert         │
                                  │  • /score, /metrics  │                       └───────┬────────┘
                                  └──────────┬───────────┘                               │
                                             │                                           ▼
                                        ┌────▼────┐                          ┌──────────────────────┐
                                        │  Redis  │                          │ PostgreSQL           │
                                        └─────────┘                          │ transactions, cases, │
                                                                             │ audit log            │
                                                                             └──────────┬───────────┘
                                                                                        │
                                                         Django REST API (JWT + RBAC) ◀─┘
                                                         /api/transactions, /api/cases, /api/audit-logs
```

| Component | Tech | Responsibility |
|---|---|---|
| `simulator/` | Python, confluent-kafka | Realistic Indian card traffic + 3 labelled fraud patterns |
| `ml_service/` | FastAPI, aiokafka, Redis, XGBoost | Streaming feature engineering + fraud scoring with SHAP explanations |
| `ml_service/training/` | pandas, scikit-learn, MLflow | Offline replay, training, threshold tuning, benchmarking, backfill |
| `backend/` | Django, DRF, PostgreSQL | Auth, roles, case workflow, audit log, analytics API |
| `ai_service/` | FastAPI, OpenAI-compatible SDK (Groq / Ollama), sqlglot | LLM risk-analyst agent + natural-language analytics |
| `frontend/` | Next.js 15, React 19, TypeScript, Tailwind 4, Recharts | Analyst console: live dashboard, case workflow, AI investigations, Ask AI, model card |
| Infra | Docker Compose, Kafka (KRaft) | One command to run everything locally |

### Engineering decisions worth noting
- **Effectively-once processing:** consumers commit Kafka offsets only after a successful write
  (at-least-once), and ingestion is idempotent on `txn_id`, so redelivered events never duplicate.
- **Per-customer ordering:** events are keyed by `customer_id`, so one customer's transactions stay
  on one partition and features (velocity, travel speed) are computed in order.
- **No data leakage:** features are computed from the customer's profile *before* the current
  transaction updates it; the simulator's ground-truth label is ignored by the scorer.
- **No train/serve skew:** feature logic is two pure functions shared by a Redis store (serving) and an
  in-memory store (training replay); a test asserts both produce identical features.
- **Time-based split:** train on the first 70% of time, tune the threshold on the next 15%, report once
  on the final 15% — random splits leak future behaviour and overstate results.
- **Explainability for free:** XGBoost's native TreeSHAP (`pred_contribs`) returns the score *and* the
  per-feature contributions in one call; the top contributions become analyst-readable reasons.
- **Cold-start fix:** customer profiles are backfilled into Redis from history before going live.
- **Online statistics:** per-customer mean/variance are updated in O(1) with Welford's algorithm.
- **Compliance:** the audit log is append-only at the model layer *and* in the admin.
- **RBAC:** analysts claim and resolve only their own cases; managers assign cases and read the audit log.

## AI service (Phase 3)

**Risk-analyst agent.** When a case opens, the ingest worker publishes `cases.opened` (after the DB
commit). The agent receives the case with its SHAP reasons, calls tools (customer profile, recent
transactions, past cases) for up to 4 rounds, then writes a JSON report — `BLOCK` / `VERIFY` /
`APPROVE`, confidence, summary, evidence, next steps — validated with Pydantic and posted back to
Django with a service token, where it is audit-logged. The recommendation is advisory; analysts decide.

**Natural-language analytics.** `POST :8002/ask {"question": "Which cities had the most flagged
transactions today?"}` → LLM writes SQL → guard → read-only execution → rows + chart hint + 1-2
sentence answer.

Safety, in layers:

| Risk | Control |
|---|---|
| LLM writes destructive / exfiltrating SQL | sqlglot AST allow-list: one SELECT, 3 tables, no `pg_*`/`set_config`, forced `LIMIT 200` |
| Guard bypass | Postgres role `finguard_ro`: SELECT-only on 3 tables, read-only sessions, 3 s timeout |
| Password hashes / audit log exposure | Those tables are not granted to the role at all |
| Agent "cheating" with simulator labels | Column-level grant hides `label_is_fraud`, `fraud_pattern` |
| Prompt injection via tool data / browsing other customers | Data marked untrusted in the prompt; tools are bound to the case's customer |
| Malformed LLM output | Pydantic validation, one corrective retry, then deterministic template report |
| Free-tier limits | `gpt-oss-20b` + daily cap for auto-investigation; `gpt-oss-120b` on demand; RPM limiter + SDK backoff |
| No API key / provider outage | Offline template mode — the pipeline never stops |

Auth: the AI service verifies Django-issued JWTs (shared HS256 secret), so users log in once.

Models: Groq free tier — `openai/gpt-oss-120b` (on-demand investigations, analytics) and
`openai/gpt-oss-20b` (automatic investigations). Any OpenAI-compatible provider works via `LLM_BASE_URL`.

Live example (case 397, ground truth hidden from the agent: account takeover) — 3 tool calls, 7 s:

> **BLOCK (0.93)** — The ₹18,621.94 POS purchase in Visakhapatnam is 8.1× the customer's average spend,
> 775 km from the home city and 799 km from the last transaction one minute earlier (~48,000 km/h)…
> Next steps: contact the cardholder; if unrecognised, block and replace the card; if recognised,
> obtain travel proof before releasing the hold.

Prompt-injection attempts against `/ask` (fake tables, "system override" to read labels, "run this
DELETE") were all refused; the SQL guard and DB role are tested independently of the model.

## Analyst console (Phase 4)

http://localhost:3000 — sign in with a demo account.

| Page | What it shows |
|---|---|
| Overview | KPIs, throughput and alert charts, risk mix, top cities, **live transaction feed over WebSocket** |
| Cases | Queue with status tabs / priority / "mine" filters; refreshes itself when cases open or AI reports land |
| Case detail | Amount, SHAP reasons and features, **"Investigate with AI"** with live agent progress, claim / assign / resolve, audit trail |
| Ask AI | Plain-English questions → chart or table, with the generated SQL one click away |
| Model | Rules vs. XGBoost on the held-out test set, recall by fraud pattern, SHAP importance |
| Audit log | Every human and AI action (managers only) |

Engineering notes:
- **Live stream:** Kafka → AI service → WebSocket fan-out with a bounded queue per browser (slow
  clients drop their own oldest events instead of stalling others); JWT in the query string because
  browsers can't set WebSocket headers; client reconnects with exponential backoff and a fresh token.
- **Auth:** access + refresh JWTs, silent refresh shared across parallel requests; deep links survive
  login (`/login?next=…`, same-site paths only to prevent open redirects). Tokens live in localStorage —
  the stricter alternative is an httpOnly-cookie BFF, at the cost of proxying every call and the socket.
- **Charts:** one y-axis per chart, validated colour-blind-safe palette in light *and* dark mode,
  status always shown as dot + text, every chart has a table view, no animation on polling charts.
- **LLM cost control:** token usage is metered per model per day from provider responses;
  auto-investigation stops at `AUTO_INVESTIGATE_DAILY_TOKENS` (default 100k of the 200k free tier),
  `/ask` returns a clean 503 on quota exhaustion and still returns data if only the summary fails.
  Known limitation: the meter is in-memory and resets on restart (Redis would persist it).

## Production engineering (Phase 5)

**CI (GitHub Actions)** — on every push/PR: `ruff` lint · unit tests for all three Python services ·
frontend type-check, lint and production build · Docker build of every image · and an
**integration job on real Postgres** that applies migrations, checks for missing migrations, runs the
backend suite and *proves* the AI's read-only role is least-privilege (`backend/scripts/verify_readonly_role.py`).

**CD** — after CI passes on `main`, GitHub Actions deploys over SSH (pinned host key) and smoke-tests
the public URLs. Off until `DEPLOY_ENABLED=true`.

**Monitoring** — `make monitoring` → Grafana on http://localhost:3001 (dashboard *FinGuard — Operations*):
scoring throughput and p50/p95/p99 latency, transactions by risk level, **Kafka consumer lag**, LLM
calls by outcome (incl. rate-limited), LLM tokens per model against the free-tier quota, LLM latency,
AI investigations by recommendation, live WebSocket clients.

**Load test** (`loadtest/locustfile.py`, Locust) — `POST /score` (Redis feature store + XGBoost + SHAP),
run on a MacBook Air (8 cores) alongside ~13 other containers, so treat as a lower bound:

| Scenario | Throughput | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|
| Steady load, 4 workers | 295 req/s | **6 ms** | 36 ms | 130 ms | 0 / 13,015 |
| Saturation, 1 worker (64 concurrent) | 701 req/s | 82 ms | 150 ms | 210 ms | 0 / 30,913 |
| Saturation, 4 workers (64 concurrent) | **1,217 req/s** | 45 ms | 92 ms | 150 ms | 0 / 53,714 |

Saturation latency is mostly queueing (Little's law: 64 / 1,217 req/s ≈ 52 ms ≈ measured p50); the
steady-load row is the operating latency. Workers scale throughput because all state lives in Redis.

**Two deployment targets** (guide in [DEPLOY.md](DEPLOY.md)):
- **Hugging Face Spaces (live demo, free, no card):** the whole platform in one container
  (`deploy/hf/`) — supervisord runs Postgres, Redis, Kafka (KRaft), Django, both FastAPI services,
  Next.js and Caddy as uid 1000 on port 7860. Cold boot to fully live in **~25 s** (incl. replaying
  460k historical transactions into the feature store); a self-refreshing "starting up" page covers
  that window; hourly retention keeps an always-on demo's disk bounded. GitHub Actions syncs the
  Space after CI passes; an external uptime monitor keeps it from idling.
- **Multi-service VM** (`docker-compose.prod.yml`, e.g. Oracle Cloud Always Free): — Caddy with automatic
HTTPS and security headers is the only public entry point; path allow-lists keep `/metrics`,
`/docs` and `/ml/score` internal; gunicorn + WhiteNoise for Django (`check --deploy` clean, refuses
weak secrets); Redis AOF persistence; bounded Kafka heap and 24 h retention; capped container logs;
random secrets in a mode-600 `.env.prod`; per-user hourly limits on LLM endpoints; admin password
separate from the public demo accounts. Verified locally end to end, including a browser session
over `wss://` through Caddy and a scan showing Postgres/Redis/Kafka/internal ports closed.

## Quick start

Requires Docker.

```bash
cp .env.example .env      # optional — every value has a default
make up                   # build and start all services
make logs                 # watch transactions being scored
make test                 # run both test suites
make down                 # stop
```

| URL | What |
|---|---|
| http://localhost:3000 | **Analyst console** |
| http://localhost:8000/admin | Django admin (`admin` / `finguard123`) |
| http://localhost:8000/api/ | REST API |
| http://localhost:8001/docs | FastAPI interactive docs |
| http://localhost:8001/metrics | Prometheus metrics |
| http://localhost:8002/docs | AI service docs (`/investigate/{case_id}`, `/ask`) |
| http://localhost:3001 | Grafana (after `make monitoring`) |

### Train the model

```bash
make ml-bootstrap   # pause stream -> 24h history -> train -> backfill Redis -> resume with the model
make mlflow         # experiment tracking UI on http://localhost:5050
make evaluate       # live precision / recall per model version
```

The ML service auto-loads `ml_service/artifacts/model.json` when present (`SCORER=auto`) and
falls back to the rules otherwise.

Demo users: `analyst`, `manager`, `admin` (password `finguard123`, or `DEMO_USER_PASSWORD`).

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/token/ -H 'Content-Type: application/json' \
  -d '{"username":"analyst","password":"finguard123"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access"])')
curl -s localhost:8000/api/transactions/stats/ -H "Authorization: Bearer $TOKEN"
curl -s "localhost:8000/api/cases/?status=OPEN" -H "Authorization: Bearer $TOKEN"
curl -s -X POST localhost:8000/api/cases/1/assign/ -H "Authorization: Bearer $TOKEN"
```

## API

| Method | Endpoint | Who |
|---|---|---|
| POST | `/api/auth/token/`, `/api/auth/token/refresh/` | anyone |
| GET | `/api/auth/me/` | authenticated |
| GET | `/api/auth/users/` | manager+ |
| GET | `/api/transactions/` (filters: `is_flagged`, `risk_level`, `channel`, `city`, …) | authenticated |
| GET | `/api/transactions/stats/?hours=24` | authenticated |
| GET | `/api/cases/` (filters: `status`, `priority`, `assigned_to`) | authenticated |
| POST | `/api/cases/{id}/assign/` `{user_id?}` | analyst (self) / manager (anyone) |
| POST | `/api/cases/{id}/resolve/` `{status, note}` | assignee / manager |
| GET | `/api/audit-logs/` | manager+ |
| POST | `:8001/score` | service-to-service |

## Results

Held-out test set: the last 15% (by time) of 461k simulated transactions, 2.4% fraud. Simulated
fraud deliberately overlaps with genuine behaviour (genuine travel, big purchases, gift cards), and one
pattern (`card_not_present`) mimics normal spend — so these numbers are realistic, not a toy 1.0 AUC.

| Metric | Rules (`rules-v1`) | XGBoost |
|---|---|---|
| PR-AUC | 0.102 | **0.716** |
| ROC-AUC | 0.761 | **0.979** |
| Precision | 0.322 | **0.743** |
| Recall | 0.167 | **0.621** |
| Fraud amount caught | 46.0% | **53.5%** |
| False alerts / 1,000 genuine txns | 6.7 | **4.1** |

Recall by pattern (XGBoost): card testing 0.78, account takeover 0.59, impossible travel 0.30,
card-not-present 0.00. Training takes ~3 s. Scoring compute: p50 0.15 ms (fast path), 0.9 ms with SHAP
(only computed for risky transactions), 0.46 ms for the Redis feature lookup; top global features by mean |SHAP|: online channel,
amount, distance from home, amount vs. customer average.

**Train/serve skew, measured:** serving at a different traffic rate than training changes the
velocity and history features. Replaying 26 h through the live feature code at 5 tx/s (training rate)
gives precision 0.79 / recall 0.62; at 3 tx/s it drops to 0.72 / 0.59 — so every deployment runs the
simulator at the training rate.

**Known limitations / next steps:** impossible-travel recall is weak (genuine travel looks similar
without device or IP signals); card-not-present fraud needs signals this simulator doesn't produce
(device fingerprint, merchant risk, account age).

## Roadmap

- [x] **Phase 1** — Streaming pipeline, feature store, rule baseline, Django API, RBAC, audit log, tests
- [x] **Phase 2** — XGBoost on 461k replayed transactions, SHAP reasons, MLflow tracking, threshold tuning, Redis backfill
- [x] **Phase 3** — LLM risk-analyst agent with tool calls, event-driven auto-investigation, guarded text-to-SQL
- [x] **Phase 4** — Next.js analyst console: live WebSocket feed, case workflow, AI investigations, Ask AI, model card
- [x] **Phase 5** — CI/CD (GitHub Actions), Prometheus + Grafana, Locust load tests, hardened production stack for Oracle Cloud Always Free
