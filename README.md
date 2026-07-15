# OpenLex — NY Landlord-Tenant Legal Research Assistant (POC)

[![api](https://github.com/rozdolsky33/OpenLex/actions/workflows/api.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/api.yml)
[![pipelines](https://github.com/rozdolsky33/OpenLex/actions/workflows/pipelines.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/pipelines.yml)
[![security](https://github.com/rozdolsky33/OpenLex/actions/workflows/security.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/security.yml)
[![web](https://github.com/rozdolsky33/OpenLex/actions/workflows/web.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/web.yml)
[![evaluation](https://github.com/rozdolsky33/OpenLex/actions/workflows/evaluation.yml/badge.svg)](https://github.com/rozdolsky33/OpenLex/actions/workflows/evaluation.yml)
[![evaluation report](https://img.shields.io/badge/evaluation%20report-live%20on%20pages-blue)](https://rozdolsky33.github.io/OpenLex/)

A retrieval-augmented generation (RAG) legal **research** assistant scoped to New York
landlord-tenant law. It answers questions by retrieving relevant statute and case-law
passages and asking Claude to answer **only** from that retrieved context, with citations.

> **This is legal information, not legal advice**, and is not a substitute for a licensed
> attorney. Every response carries the disclaimer defined in `legal_models.schemas`
> (`DISCLAIMER`) and shown in the UI.

**What this project is really about.** OpenLex is a portfolio POC that demonstrates
SRE / Platform-Engineering practice applied to an AI product: the legal corpus is deliberately
*credible, not exhaustive*, while the operational depth — containerized local dev, a real
GitOps + Kubernetes path, full observability, CI/CD gates, and infrastructure-as-code — is the
actual thing being showcased.

---

## Table of contents

- [High-level architecture](#high-level-architecture)
- [How a question gets answered (the RAG flow)](#how-a-question-gets-answered-the-rag-flow)
- [Components](#components)
- [Data sources &amp; integrations](#data-sources--integrations)
- [Configuration](#configuration)
- [Prerequisites](#prerequisites)
- [Running it — three ways](#running-it--three-ways)
  - [1. Docker Compose (default dev loop)](#1-docker-compose--default-dev-loop)
  - [2. kind (local Kubernetes + GitOps + observability)](#2-kind--local-kubernetes--gitops--observability)
  - [3. AWS EKS (production demo)](#3-aws-eks--production-demo)
- [Repository layout](#repository-layout)
- [Testing](#testing)
- [CI/CD and legal-accuracy evaluation](#cicd-and-legal-accuracy-evaluation)
- [Further documentation](#further-documentation)

---

## High-level architecture

OpenLex is a **monorepo, modular monolith** (not microservices — see
[ADR-0001](docs/decisions/0001-monorepo-restructure.md)): one `uv` workspace of apps and
shared packages. Three runtime components sit in front of a single Postgres database with the
`pgvector` extension, and Claude is called for the generation step.

```
                 ┌─────────────┐         ┌──────────────────────────┐
   user ───────▶ │  apps/web   │ ──HTTP─▶│        apps/api          │
                 │ React chat  │         │  FastAPI: auth · quota   │
                 │   UI (Vite) │◀────────│  retrieve → generate     │
                 └─────────────┘         └────────┬─────────┬───────┘
                                                  │         │
                                     hybrid search│         │grounded generation
                                                  ▼         ▼
                                       ┌────────────────┐  ┌──────────────┐
                                       │  Postgres +    │  │   Claude     │
                                       │   pgvector     │  │ (Anthropic)  │
                                       │ documents /    │  └──────────────┘
                                       │ chunks (+FTS)  │
                                       └───────▲────────┘
                                               │ writes embedded chunks
                                       ┌───────┴────────┐
                                       │   apps/worker  │  ← NY Open Legislation API (statutes)
                                       │ ingestion CLI  │  ← curated case-law seed (cases)
                                       └────────────────┘
```

- **`apps/web`** — the only surface users touch. Talks to the API over HTTP.
- **`apps/api`** — the online request path: authentication, per-tier quota, hybrid retrieval,
  and grounded generation. The **only** component users/the web app call directly.
- **`apps/worker`** — the offline batch path: ingests source data (statutes + cases),
  embeds it, and writes it into Postgres. Never on the request path.
- **Postgres + pgvector** — one store holding `documents` (immutable raw sources) and
  `chunks` (passages with a 384-dim embedding vector *and* a full-text-search `tsv` column).
- **Claude** — called by the API for the final grounded answer; called nowhere else.

For rendered diagrams see [`docs/infrastructure/architecture-diagrams.md`](docs/infrastructure/architecture-diagrams.md).

---

## How a question gets answered (the RAG flow)

RAG is **hybrid retrieval + grounded generation**. Two phases, split across the worker
(offline) and the API (online):

**Ingestion (worker, offline):** fetch/seed → normalize → chunk → **embed** → upsert.
Each chunk's text is turned into a 384-dim vector by the embedding model and stored in
`chunks.embedding`; Postgres separately maintains a generated `tsv` column for keyword search.

**Query (API, online), per `POST /query`:**
1. **Authenticate** the bearer token, then **check &amp; consume quota** for the user's tier
   (429 if exhausted).
2. **Embed the question** with the same embedding model (using BGE's asymmetric *query*
   prefix — see below).
3. **Hybrid search** (`packages/legal_retrieval/search.py`): pgvector cosine similarity
   (HNSW index) **and** Postgres full-text search (GIN index) run in parallel, then are fused
   by **Reciprocal Rank Fusion** — neither signal alone, both combined. Results are collapsed
   to one best chunk per document so a long case can't crowd out a relevant statute.
4. **Grounded generation** (`packages/legal_generation`): the retrieved passages are handed to
   Claude with a tool-forced, answer-only-from-context prompt. If retrieval returns nothing,
   the system **hard-abstains** rather than inventing an answer. Every response returns
   `citations`, an `abstained` flag, and the fixed legal `disclaimer` (the response contract —
   see the `grounded-answer-contract` skill and
   [ADR-0002](docs/decisions/0002-retrieval-and-generation-design.md)).

### The embedding model

```
EMBEDDING_MODEL_NAME=BAAI/bge-small-en-v1.5
```

`BAAI/bge-small-en-v1.5` is a small, open-source sentence-embedding model (384-dimensional
output) run **locally** via `sentence-transformers` + `torch` — **no API key, no external
call, no cost**. It's downloaded from Hugging Face on first use and cached. It lives in
`packages/legal_retrieval/embeddings.py` and is used in exactly two places:

| Where | Function | What it embeds |
|-------|----------|----------------|
| **Worker**, during ingestion (`pipelines/indexing/_shared.py`) | `embed_passages()` | each chunk of statute/case text → written to `chunks.embedding` |
| **API**, at query time (`legal_retrieval/search.py`) | `embed_query()` | the incoming user question → used for the pgvector similarity search |

Two important properties:

- **BGE is asymmetric.** Queries are embedded *with* an instruction prefix
  (`"Represent this sentence for searching relevant passages: "`), passages *without* one.
  Getting this backwards measurably degrades retrieval (see
  [`ml/model_cards/bge-small-en-v1.5.md`](ml/model_cards/bge-small-en-v1.5.md)).
- **The dimension is load-bearing.** The `chunks.embedding` column is `vector(384)`; changing
  to a model with a different output dimension requires a migration **and** re-embedding the
  whole corpus. The API preloads the model at startup (FastAPI `lifespan`) so the first real
  request doesn't pay the multi-second load.

---

## Components

| Component | Path | Runtime | Role |
|-----------|------|---------|------|
| **API** | `apps/api/` | long-running FastAPI server | Online request path. `POST /auth/register` + `POST /auth/login` (JWT), `POST /query` (auth + quota + retrieve + generate), `GET /healthz`, `GET /metrics` (Prometheus). Ingestion endpoint is a deliberate `501` — ingestion is worker-only. |
| **Worker** | `apps/worker/` | one-shot CLI (idle heartbeat otherwise) | Offline ingestion: `python -m openlex_worker ingest --source {statutes\|cases\|all}`. The only component that imports `pipelines/` and the only one that embeds passages. Kept separate so heavy `torch`/model work never touches the online API. |
| **Web UI** | `apps/web/` | Vite + React + TypeScript + Tailwind | Auth-gated chat UI; renders answers with citations and the per-answer disclaimer. Multi-turn, single active conversation. See [ADR-0003](docs/decisions/0003-conversational-chat-and-web-ui.md). |
| **Database** | `migrations/postgres/` | Postgres 16 + `pgvector` | `documents` + `chunks`; HNSW index for vectors, GIN index for full-text search. |
| **Shared packages** | `packages/` | libraries | `legal_models` (schemas/ORM), `legal_retrieval` (embeddings + hybrid search), `legal_generation` (grounded answers), `legal_parsing` (chunking/normalization), `shared` (config, DB session). |

---

## Data sources &amp; integrations

OpenLex talks to three external things. Two shape the **data**; one is the **LLM**.

| Integration | Env var | Used at runtime? | Role |
|-------------|---------|:---:|------|
| **Anthropic (Claude)** | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | ✅ yes — API | The generation step. Claude turns retrieved passages into a grounded, cited answer. Required for the app to answer anything. |
| **NY Open Legislation API** | `NY_OPEN_LEG_API_KEY`, `NY_OPEN_LEG_BASE_URL` | ✅ yes — worker | **Statute source.** The worker fetches live statute text (RPAPL, RPL, GOL sections) from `legislation.nysenate.gov` during `ingest --source statutes`. Free self-serve key. Without it, statute ingestion fails; the app can still serve whatever is already in the DB. |
| **Embedding model** | `EMBEDDING_MODEL_NAME` | ✅ yes — API + worker | Local model, **no key**. See [the embedding-model section](#the-embedding-model) above. |
| **CourtListener** | `COURTLISTENER_API_TOKEN` | ❌ **no** | **Case-law source — curation only.** Case-law full text has no viable live-fetch path (CourtListener's detail API is token-gated; its public pages, court PDFs, and Justia are all bot-blocked — see [ADR-0006](docs/decisions/0006-case-law-ingestion.md)). Opinion text was fetched **once, out-of-band** with this token and baked into `pipelines/ingestion/ny_case_law/seed_cases.json`. The running app never reads this token. |

**Why statutes are fetched live but cases are seeded:** statute text is cleanly available from
a free public API, so the worker pulls it on demand and can re-check freshness
(`scripts/eval/check_statute_freshness.py`). Case-law full text is not automatable, so it's a
hand-curated seed of **five** real NY landlord-tenant decisions — e.g. Park West Management
v. Mitchell (warranty of habitability), Regina Metropolitan v. NYS DHCR (rent-overcharge), and
Mallory Associates v. Barving Realty (security deposits as trust funds), plus Chinatown
Apartments v. Chu Cho Lam and ATM One v. Landaverde.

> **Other tokens you may see in `.env.example`** — `COURTLISTENER_API_TOKEN`, `GHCR_USERNAME`,
> and `GHCR_PAT` are **bootstrap/curation-only** and are *not* wired into application config
> (`openlex_shared.config.Settings`). GHCR credentials are used once by
> `scripts/kind/ghcr-pull-secret-bootstrap.sh` to let a kind cluster pull private images.

---

## Configuration

All runtime config is a single pydantic-settings object
(`packages/shared/src/openlex_shared/config.py`) loaded from `.env`. Copy the template and
fill it in:

```bash
cp .env.example .env
```

| Variable | Required | Default | Consumed by | Purpose |
|----------|:---:|---------|-------------|---------|
| `ANTHROPIC_API_KEY` | ✅ | — | api | Claude auth for grounded generation |
| `ANTHROPIC_MODEL` |  | `claude-sonnet-4-5` | api | Which Claude model answers |
| `DATABASE_URL` | ✅ | — | api, worker | Postgres+pgvector DSN (asyncpg driver) |
| `NY_OPEN_LEG_API_KEY` | for statute ingest | — | worker | Fetch statute text |
| `NY_OPEN_LEG_BASE_URL` |  | `…/api/3` | worker | NY Open Legislation base URL |
| `EMBEDDING_MODEL_NAME` |  | `BAAI/bge-small-en-v1.5` | api, worker | Local embedding model (384-dim) |
| `JWT_SECRET_KEY` | ✅ | — | api | Signs/verifies access tokens (`openssl rand -hex 32`) |
| `JWT_ALGORITHM` / `JWT_EXPIRE_MINUTES` |  | `HS256` / `60` | api | Token algorithm / lifetime |
| `VITE_API_BASE_URL` | ✅ (web) | `http://localhost:8000` | web build | Where the UI sends requests |
| `DEMO_{SILVER,GOLD,PLATINUM}_{EMAIL,PASSWORD}` | for demo logins | — | api seed script | The three tier-gated demo accounts (registration is disabled in this demo) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` |  | in-cluster Collector DNS | api, worker | Where traces/metrics/logs are exported |
| `COURTLISTENER_API_TOKEN` | ❌ | — | *(curation only)* | Not read at runtime |
| `GHCR_USERNAME` / `GHCR_PAT` | ❌ | — | *(kind bootstrap only)* | Not read at runtime |

> ⚠️ The demo passwords committed in `.env.example` are public placeholders. Replace them
> before running against anything but a fully local, throwaway stack.

---

## Prerequisites

- **Docker + Docker Compose** — the default local stack.
- **[uv](https://docs.astral.sh/uv/)** — Python package/workspace manager.
- **An Anthropic API key** — https://console.anthropic.com/
- **A free NY Open Legislation API key** — https://legislation.nysenate.gov/static/docs/html/laws.html
- **Node.js 20+** — only for local, non-Docker `apps/web` development (see `apps/web/.nvmrc`).
- **For the kind path:** `kind`, `kubectl`, `helm`, `kustomize`.
- **For the EKS path:** an AWS account, `terraform`, and the AWS CLI.

---

## Running it — three ways

Three environments of increasing realism. **Docker Compose is the recommended day-to-day loop**;
kind and EKS exist to demonstrate the Kubernetes/GitOps/production story.

### 1. Docker Compose — default dev loop

The fast, native inner loop. Brings up Postgres, the API, the worker, the web UI, and a full
**local observability stack** (OpenTelemetry Collector, Jaeger, Prometheus, Grafana).

**One command** — bootstrap the stack, wait for the API, ingest the corpus, seed demo users:

```bash
cp .env.example .env          # then set ANTHROPIC_API_KEY, NY_OPEN_LEG_API_KEY, JWT_SECRET_KEY
scripts/compose/bringup.sh    # master: bootstrap -> health-wait -> ingest -> seed users
```

<details><summary>…or run the steps individually</summary>

```bash
scripts/compose/bootstrap.sh   # creates .env, uv sync, docker compose up --build
scripts/compose/ingest.sh all  # ingest statutes + cases
scripts/seed/seed-demo-users.sh # create the three tier-gated demo accounts
```
</details>

| Service | URL |
|---------|-----|
| Web UI | http://localhost:5173 |
| API (docs at `/docs`) | http://localhost:8000 |
| Postgres (pgvector) | localhost:5432 (`openlex`/`openlex`/`openlex`) |
| Jaeger (traces) | http://localhost:16686 |
| Prometheus (metrics) | http://localhost:9090 |
| Grafana (dashboards) | http://localhost:3000 |

### 2. kind — local Kubernetes + GitOps + observability

A local **Kubernetes-in-Docker** cluster that mirrors the production topology: a real **ArgoCD
GitOps** pipeline, an in-cluster Postgres StatefulSet, the api/worker/web workloads, and the
full observability stack (kube-prometheus-stack, Grafana, Tempo, Jaeger, Loki, Promtail). It's
for staging-realistic testing, not everyday coding — it needs more tooling and machine
resources than Compose.

**One command** — create the cluster, bootstrap secrets, install ArgoCD, wait for the app to
roll out, then ingest + seed:

```bash
scripts/kind/bringup.sh   # master: up -> ghcr secret -> secrets -> argocd -> wait -> ingest -> seed
```

Then open access in separate terminals (these block on `kubectl port-forward`):

```bash
scripts/kind/app-port-forward.sh            # Web UI :5173, API :8000
scripts/kind/observability-port-forward.sh  # Grafana :3000, ArgoCD :8080, Jaeger :16686
```

<details><summary>…or run the bring-up steps individually</summary>

```bash
# cluster + platform
scripts/kind/up.sh                          # create the `openlex` kind cluster
scripts/kind/ghcr-pull-secret-bootstrap.sh  # let the cluster pull private GHCR images
scripts/kind/secrets-bootstrap.sh           # app secrets from .env -> openlex-secrets
scripts/kind/argocd-bootstrap.sh kind       # install ArgoCD + point it at the kind overlay
# wait for the app pods (ArgoCD syncs them), then load data
kubectl -n openlex rollout status deploy/openlex-api deploy/openlex-worker
scripts/seed/kind-ingest.sh                 # ingest statutes + cases into the cluster DB
scripts/seed/kind-seed-demo-users.sh        # create the tier-gated demo logins
```
</details>

> **Fresh-cluster data steps are required, not optional.** kind starts with an empty database:
> until `kind-ingest.sh` runs, `/query` hard-abstains ("NO CONFIDENT ANSWER FOUND") because
> retrieval has nothing to return; until `kind-seed-demo-users.sh` runs, `/auth/login` returns
> 401 (registration is disabled, so the seeded demo users are the only accounts). Both are
> idempotent — safe to re-run. (docker-compose has the same two steps via
> `scripts/compose/ingest.sh` + `scripts/seed/seed-demo-users.sh`; on kind they run inside the
> worker/api pods instead of `docker compose exec`.)

kind has no ingress, so everything is reached over `kubectl port-forward` (the two scripts
above open all of these):

| Service | URL | Opened by |
|---------|-----|-----------|
| Web UI | http://localhost:5173 | `app-port-forward.sh` |
| API (docs at `/docs`) | http://localhost:8000 | `app-port-forward.sh` |
| **ArgoCD** (GitOps UI) | **https://localhost:8080** | `observability-port-forward.sh` |
| Grafana (dashboards) | http://localhost:3000 | `observability-port-forward.sh` |
| Prometheus (metrics) | http://localhost:9090 | `observability-port-forward.sh` |
| Alertmanager | http://localhost:9093 | `observability-port-forward.sh` |
| Jaeger (traces) | http://localhost:16686 | `observability-port-forward.sh` |

> ArgoCD's initial admin password:
> `kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d`

From here it's **GitOps**: a merge to `develop` triggers `.github/workflows/deploy.yml`, which
builds multi-arch images to GHCR, bumps the image tags in `infra/kubernetes/overlays/kind/`,
and commits — ArgoCD then reconciles that onto the cluster. See
[`docs/infrastructure/kubernetes-topology.md`](docs/infrastructure/kubernetes-topology.md).
Tear down with `scripts/kind/down.sh`.

### 3. AWS EKS — production demo

The production-shaped target. **Terraform** (`infra/terraform/`) provisions the AWS
substrate — VPC, EKS cluster + OIDC, one Spot node group, an **RDS** Postgres instance, ECR
repositories, a Route53 hosted zone, and IRSA roles — and deliberately **stops at the cluster
boundary**. Everything *inside* the cluster (ArgoCD itself, ingress-nginx, cert-manager,
external-dns, external-secrets, and the app) is owned by ArgoCD via
`infra/kubernetes/overlays/eks-demo/`.

Key differences from kind, by design:

- **Postgres → Amazon RDS** (not an in-cluster StatefulSet).
- **Secrets → AWS Secrets Manager**, pulled in by **External Secrets** (`externalsecret-openlex.yaml`).
- **Web UI → S3 + CloudFront** static hosting (`static-site.tf` + `.github/workflows/deploy-static.yml`),
  *not* an in-cluster Deployment. Only api + worker run in the cluster.
- **Ingress** via ingress-nginx + cert-manager + external-dns behind the Route53 domain.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set your domain, region, etc.
terraform init -backend-config=backend.hcl
terraform apply
# then: wire outputs into the eks-demo manifests, populate Secrets Manager, and:
aws eks update-kubeconfig --name <cluster_name> --region <region>
scripts/kind/argocd-bootstrap.sh eks-demo
```

The full first-time runbook (remote state bootstrap, secret population, DNS delegation, the
static-site GitHub variables) is in [`infra/terraform/README.md`](infra/terraform/README.md);
cost/architecture reasoning (no NAT Gateway, one Spot node, no GPUs) is in
[`docs/infrastructure/aws-eks-cost-estimate.md`](docs/infrastructure/aws-eks-cost-estimate.md).

---

**This is the fast, native local dev loop — recommended default for day-to-day iteration.**
There's also a local **kind** (Kubernetes-in-Docker) cluster with a real ArgoCD GitOps
pipeline and full observability stack (Prometheus, Grafana, Tempo, Jaeger, Loki), used for
staging-realistic testing rather than everyday coding — it needs more tools and more machine
resources than docker-compose does. See
[`docs/infrastructure/kubernetes-topology.md`](docs/infrastructure/kubernetes-topology.md) for
what it needs and why, and
[`docs/infrastructure/dev-workflow-and-branching.md`](docs/infrastructure/dev-workflow-and-branching.md)
for how the two fit together with CI/CD.

## Repository layout

- `apps/api/` — FastAPI service (routers, auth, quota, request handling). Imports from `packages/`.
- `apps/worker/` — ingestion runner (`python -m openlex_worker ingest`). Imports `pipelines/` + `packages/`.
- `apps/web/` — Vite + React + TypeScript chat UI.
- `packages/` — reusable domain libraries (`legal_models`, `legal_retrieval`, `legal_generation`,
  `legal_parsing`, `shared`).
- `pipelines/ingestion/` — per-source adapters (`ny_legislation/`, `ny_case_law/`) producing a
  common normalized document shape; `pipelines/normalization/` + `pipelines/indexing/` do the
  normalize→chunk→embed→upsert work.
- `ml/` — prompt templates, model cards, evaluation assets. Not request-handling code.
- `schemas/` — versioned JSON Schema for the core data shapes.
- `migrations/postgres/` — Postgres schema (pgvector + full-text-search indexes).
- `infra/` — `terraform/` (AWS/EKS substrate), `kubernetes/` (base + kind/eks-demo overlays),
  `argocd/` (GitOps apps), `monitoring/` + `local-observability/` (the observability stacks).
- `scripts/` — bootstrap, ingest, evaluate, kind lifecycle, port-forwards, secret bootstraps.
- `tests/` — `integration/`, `end_to_end/`, and the `evaluation/` golden-question harness.
  Unit tests live next to their code (`apps/*/tests/`, `packages/*/tests/`).
- `docker-compose.yml` — Postgres (pgvector), api, worker, web, and the local observability stack.

See [`docs/`](docs/) for architecture documentation and decision records (ADRs).

---

## Testing

```bash
uv run pytest                                  # unit tests (root pyproject sets testpaths)
uv run ruff check . && uv run ruff format .    # lint + format
uv run mypy apps packages                      # typecheck
scripts/test/test-db.sh up                          # start db-test (pgvector on :5544) for integration tests
uv run pytest tests/integration                # real-DB integration tests
scripts/eval/evaluate.sh                            # golden-question legal-accuracy eval (guarded; real API)
```

The `verify` skill runs the project's full gate (lint, types, unit, and real-DB integration
tests) before any change is claimed done.

---

## CI/CD and legal-accuracy evaluation

📊 **[Published pipeline flow diagram](https://claude.ai/code/artifact/e57e1b47-0323-4a09-81c0-fa62b1a910bc)** —
all ten GitHub Actions workflows mapped across their four triggers (PR quality gates, the
`main`-merge guard, image build + GitOps deploy on `develop`, and static web deploy on `main`).

> **Git workflow:** open PRs against `develop`, not `main`. `main` is the production branch;
> a CI guard (`restrict-main-merges.yml`) blocks any PR to `main` that isn't from `develop`.
> See [`docs/infrastructure/dev-workflow-and-branching.md`](docs/infrastructure/dev-workflow-and-branching.md).

The badges above track two different things, and it's worth being explicit about what each
one is checking and why:

- **`api` / `pipelines` / `security` / `web`** are standard PR gates — lint, typecheck, unit
  and integration tests, dependency-vulnerability scanning — scoped by path filter so each
  only runs when the code it covers actually changed. These tell you the code is *correct and
  safe*, not that its answers are *any good*.
- **`evaluation`** is different: it's a legal-accuracy regression suite, not a code-quality
  check. `tests/evaluation/golden_questions.yaml` holds a curated set of real NY
  landlord-tenant questions with known-correct expected citations; the suite fires each one at
  a live stack (Postgres + the API + real Claude calls) and checks that retrieval + generation
  actually finds and cites the right statute. In a system whose entire value proposition is
  "only answer from retrieved context, with correct citations," this is the check that matters
  most — a green `api` badge says nothing about whether the retrieval pipeline just started
  citing the wrong statute for a given question.

**How it's set up, and why it's two-tiered:**

1. **On every PR** touching retrieval/generation/prompts: an automatic, single-pass run
   against `claude-haiku-4-5` (not the production model) — fast, cheap, real feedback on
   whether a change broke retrieval or generation, without the cost of the full comparison
   below.
2. **On demand only** (`gh workflow run evaluation.yml --ref main`, or Actions tab ->
   `evaluation` -> *Run workflow*) — a heavier run: the same 21 questions against **both**
   Haiku and the actual production model (`claude-sonnet-4-5`), a check of whether any of the
   underlying NY statute text has changed since it was last ingested, and a published report.
   This is manual rather than automatic-on-merge specifically to control real Anthropic API
   spend during active development — see
   [ADR-0004](docs/decisions/0004-golden-question-report-and-pages.md) for the full reasoning
   and cost breakdown.

The manual run publishes a **live report to GitHub Pages**:
**[rozdolsky33.github.io/OpenLex](https://rozdolsky33.github.io/OpenLex/)** — showing, per
question, what was expected vs. what each model actually answered and cited; a historical
trend across past runs; where Haiku and Sonnet's answers *diverge* (a direct signal on the
cost/accuracy tradeoff of using Haiku in CI while production runs Sonnet); and whether any
seeded statute's live text has drifted from the snapshot the golden answers were graded
against. See `tests/evaluation/README.md` for how to run the suite locally, and
[ADR-0004](docs/decisions/0004-golden-question-report-and-pages.md) for the full design
(why a git-native `gh-pages` history store, why divergence is flagged the way it is, why the
freshness check runs before any Claude spend).

### Secret scanning &amp; secrets management

Secrets are caught at three layers: **gitleaks** runs in `.pre-commit-config.yaml` (local, before
a commit leaves the machine), again in the `security.yml` CI job (on every PR), and **GitGuardian**
scans PRs from the dashboard side. No real credential is ever committed — all runtime secrets come
from `.env` (local), cluster Secrets (kind), or AWS Secrets Manager via External Secrets (EKS).

CI test jobs (`api` / `pipelines` / `integration`) need a few config values to exist at import
time (`openlex_shared.config.Settings` has required fields), but their tests never make a real
Claude call, open a DB connection, or verify a token. Those placeholders are **generated at
runtime** inside each workflow (`openssl rand` into `$GITHUB_ENV`) rather than hardcoded, so no
secret-shaped literal is ever written into a workflow file for a scanner to flag.

---

## Further documentation

- **Decision records:** [`docs/decisions/`](docs/decisions/) — monorepo structure, retrieval/
  generation design, chat UI, evaluation reporting, local-dev hardening, case-law ingestion.
- **Infrastructure:** [`docs/infrastructure/`](docs/infrastructure/) — architecture diagrams,
  Kubernetes topology, dev workflow &amp; branching, EKS cost estimate, MLOps guide.
- **Project guidance for AI agents:** [`CLAUDE.md`](CLAUDE.md).
