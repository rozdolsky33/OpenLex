---
name: local-environment
description: Use when bringing up, tearing down, or troubleshooting OpenLex's local environments (docker-compose or kind) — drives the master scripts and knows the fresh-cluster gotchas (empty-corpus abstain, unseeded-user 401, postgres-exporter secret, stale Grafana port-forward).
---

# OpenLex Local Environment

Two local environments, each driven by **one master script** that takes `up` or `down`.
Prefer the master script over running the individual steps by hand.

## Bring up / tear down

| Environment | Up | Down |
|---|---|---|
| **docker-compose** (default dev loop) | `scripts/compose-master.sh up` | `scripts/compose-master.sh down` |
| **kind** (Kubernetes + ArgoCD GitOps) | `scripts/kind-master.sh up` | `scripts/kind-master.sh down` |

Both `up` flows are **idempotent** (safe to re-run). They chain the individual scripts and
print colored, timestamped step banners.

- **compose up:** `.env` guard → `compose/bootstrap.sh` → wait for `/healthz` → `compose/ingest.sh all` → `seed/seed-demo-users.sh`.
- **kind up:** `kind/up.sh` → `kind/ghcr-pull-secret-bootstrap.sh` → `kind/secrets-bootstrap.sh` → `kind/argocd-bootstrap.sh kind` → wait for `openlex-api`/`openlex-worker` rollout → `seed/kind-ingest.sh` → `seed/kind-seed-demo-users.sh`.

## Prerequisites

- `.env` with **`ANTHROPIC_API_KEY`** + **`NY_OPEN_LEG_API_KEY`** set (compose-master guards this; kind ingestion also needs the NY key).
- kind also needs **`GHCR_USERNAME`/`GHCR_PAT`** (a PAT with `read:packages`) to pull the private GHCR images.
- Ensure `.env` **ends with a trailing newline** (see the postgres-exporter gotcha below).

## Access (kind) — start each in its own terminal; they block on `kubectl port-forward`

The masters do **not** start port-forwards. After `up`, run:

```bash
scripts/kind/app-port-forward.sh            # Web UI :5173, API :8000
scripts/kind/observability-port-forward.sh  # Grafana :3000 (anon Viewer), ArgoCD :8080, Jaeger :16686
```

Always (re)start port-forwards **after** `up` — the app/Grafana pods roll during setup, so any
forward started earlier is stale (see the Grafana gotcha).

## Troubleshooting matrix (symptom → cause → fix)

These are the real failure modes a fresh cluster hits. Everything is verifiable with a
`kubectl exec` into a running pod (the API pod has `curl`).

| Symptom | Cause | Fix |
|---|---|---|
| Chat: **"NO CONFIDENT ANSWER FOUND"** on every question | Empty corpus — nothing was ingested. The grounded-answer contract abstains (working as intended). | `scripts/seed/kind-ingest.sh` (or `scripts/compose/ingest.sh all`). Verify: `documents`/`chunks` count > 0. |
| `POST /auth/login` → **401** for demo creds | `users` table empty — demo users never seeded (registration is disabled). | `scripts/seed/kind-seed-demo-users.sh` (or `scripts/seed/seed-demo-users.sh` for compose). |
| **postgres-exporter** pod `CreateContainerConfigError` | `openlex-secrets` is missing the derived `POSTGRES_EXPORTER_DSN` key — usually because `.env` had no trailing newline, so the appended key merged into the previous line. | Ensure `.env` ends with a newline, re-run `scripts/kind/secrets-bootstrap.sh`, `kubectl -n openlex delete pod -l app.kubernetes.io/name=prometheus-postgres-exporter`. Verify the key exists in the Secret. |
| **Grafana "No data"** on every panel and/or **can't log in** | Stale port-forward: the Grafana pod rolled during `up`, killing your earlier `kubectl port-forward`. | Restart `scripts/kind/observability-port-forward.sh`; open `localhost:3000` in an **incognito** window. Anonymous **Viewer** is enabled — no login needed to view. |
| **Jaeger** "parent span … is not in the trace; skipping clock skew adjustment" | Benign — a parent (e.g. the browser root span) isn't in the trace, so Jaeger can't clock-skew-adjust. | No action. Not data loss; the trace still renders. |

## Verifying from outside the cluster (read-only)

The metrics/data pipeline is almost always healthy even when the browser shows nothing — check
server-side before chasing config:

```bash
NS=openlex
PROM=http://kube-prometheus-stack-prometheus.observability:9090
GF=http://kube-prometheus-stack-grafana.observability

# corpus present? (empty -> chat abstains)
kubectl -n $NS exec deploy/openlex-api -- uv run --frozen python -c \
  "import asyncio;from openlex_shared.db import SessionLocal;from sqlalchemy import text
async def c():
    async with SessionLocal() as s:
        print('chunks:', (await s.execute(text('select count(*) from chunks'))).scalar())
asyncio.run(c())"

# prometheus has app metrics?
kubectl -n $NS exec deploy/openlex-api -- sh -c "curl -s '$PROM/api/v1/query?query=count(openlex_http_requests_total)'"

# grafana anonymous query works? (200 = anon Viewer OK; 401 = login still required)
kubectl -n $NS exec deploy/openlex-api -- sh -c \
  "curl -s -o /dev/null -w '%{http_code}\n' '$GF/api/datasources/proxy/uid/prometheus/api/v1/query?query=up'"
```

## Guardrails

- Don't hand-patch ArgoCD-managed resources on kind — `selfHeal` reverts them. Change them in
  git and let ArgoCD sync (or `argocd app sync`).
- `kind-master.sh down` deletes the whole cluster; `compose-master.sh down` removes volumes
  (`-v`). Confirm with the user before running `down` on an environment they're using.
