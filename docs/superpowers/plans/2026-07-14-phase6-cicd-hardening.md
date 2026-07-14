# Phase 6 — CI/CD Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give OpenLex a real CI/CD pipeline (tests gated in CI, a real e2e smoke test, a
GHCR-backed GitOps deploy pipeline) and a real three-environment model (docker-compose for
local dev, kind+ArgoCD on `develop` as staging, `main` reserved for future EKS/production).

**Architecture:** `develop` becomes the branch ArgoCD's 9 kind Applications watch; `deploy.yml`
builds/pushes images to GHCR on every push to `develop` and commits an image-tag bump back to
`develop` itself, closing the GitOps loop without GitHub ever needing network access to the
local kind cluster. `docker-compose.yml` gains a lightweight observability subset (OTel
Collector, Prometheus, Grafana, Jaeger) so local dev has trace/metric visibility without
needing kind at all. Two new CI workflows (`integration.yml`, `smoke.yml`) gate real
Postgres-backed and full-stack tests that only ran manually before.

**Tech Stack:** GitHub Actions, Docker/docker-compose, GHCR (`ghcr.io`), Kustomize, ArgoCD,
OpenTelemetry Collector, Prometheus, Grafana, Jaeger — all already in use elsewhere in this
repo; no new tooling categories introduced.

## Global Constraints

- No AWS/EKS/ECR work of any kind — that's Phase 7 (`docs/superpowers/specs/
  2026-07-14-phase6-cicd-hardening-design.md`'s "Explicitly out of scope").
- No Terraform changes (GA checklist 6.4/6.5 deferred to Phase 7).
- `tests/integration/conftest.py` and every existing test file's assertions are unchanged —
  only new CI wiring and one new test file.
- Existing `Dockerfile`s (`apps/api/Dockerfile`, `apps/worker/Dockerfile`,
  `apps/web/Dockerfile`) are unchanged.
- `docker-compose.yml`'s existing `db`/`db-test`/`api`/`worker`/`web` service definitions
  (bind mounts, `env_file: .env`, healthchecks) are unchanged — this phase is additive only.
- Third-party Helm-chart `targetRevision` values in the 9 `infra/argocd/apps/kind/*.yaml`
  files (e.g. `kube-prometheus-stack`'s `"87.15.*"`) must **not** be touched — only each file's
  own-repo (`https://github.com/rozdolsky33/OpenLex.git`) source `targetRevision` changes.
  `scripts/kind-load-images.sh` is not modified.
- GHCR images are **private**, pulled via an `imagePullSecrets` entry — not public images.
- Verify every claim live (this project's established convention) — every task's testing step
  must be a real command run against a real service, not an assumption.

---

### Task 1: Create `develop` branch and confirm repo state

**Files:** none (git operation only)

**Interfaces:**
- Produces: a `develop` branch on the remote, branched from current `main` HEAD, ready for
  Task 2's ArgoCD retarget and every later task's PR target.

- [ ] **Step 1: Confirm a clean working tree and current branch**

Run: `git status --short && git branch --show-current`
Expected: no uncommitted changes; on `main`.

- [ ] **Step 2: Create and push `develop`**

```bash
git checkout -b develop
git push -u origin develop
```

- [ ] **Step 3: Verify the branch exists on the remote**

Run: `git ls-remote --heads origin develop`
Expected: one line showing the `develop` ref at the same commit as `main`.

- [ ] **Step 4: Switch back to a feature branch for the rest of this plan**

```bash
git checkout -b phase6-cicd-hardening
```

(All subsequent tasks in this plan commit to `phase6-cicd-hardening`; the whole plan's PR
targets `develop`, per the design's branch model — not `main`.)

---

### Task 2: Retarget ArgoCD kind Applications to `develop`

**Files:**
- Modify: `infra/argocd/apps/kind/app-openlex.yaml`
- Modify: `infra/argocd/apps/kind/app-loki.yaml`
- Modify: `infra/argocd/apps/kind/app-jaeger.yaml`
- Modify: `infra/argocd/apps/kind/app-tempo.yaml`
- Modify: `infra/argocd/apps/kind/app-otel-collector.yaml`
- Modify: `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml`
- Modify: `infra/argocd/apps/kind/app-postgres-exporter.yaml`
- Modify: `infra/argocd/apps/kind/app-promtail.yaml`
- Modify: `infra/argocd/apps/kind/app-observability-dashboards.yaml`

**Interfaces:**
- Consumes: the `develop` branch created in Task 1.
- Produces: every kind ArgoCD Application now watches `develop` for its own-repo source; no
  later task depends on this directly (it takes effect once these manifests are applied to the
  live cluster, done in this task's verification step).

- [ ] **Step 1: Confirm the exact lines to change in each file**

Run: `grep -n "targetRevision: main" infra/argocd/apps/kind/*.yaml`

Expected output (one line per file — `app-openlex.yaml` has exactly one `targetRevision: main`
line since it has one `source:` block; the other 8 files have exactly one *own-repo*
`targetRevision: main` line each, alongside a separate Helm-chart `targetRevision` with a
semver value like `"87.15.*"` that must not match this grep since it's never literally the
string `main`):

```
infra/argocd/apps/kind/app-jaeger.yaml:36:      targetRevision: main
infra/argocd/apps/kind/app-kube-prometheus-stack.yaml:126:      targetRevision: main
infra/argocd/apps/kind/app-loki.yaml:40:      targetRevision: main
infra/argocd/apps/kind/app-observability-dashboards.yaml:14:    targetRevision: main
infra/argocd/apps/kind/app-openlex.yaml:13:    targetRevision: main
infra/argocd/apps/kind/app-otel-collector.yaml:30:      targetRevision: main
infra/argocd/apps/kind/app-postgres-exporter.yaml:34:      targetRevision: main
infra/argocd/apps/kind/app-promtail.yaml:47:      targetRevision: main
infra/argocd/apps/kind/app-tempo.yaml:37:      targetRevision: main
```

If any file shows more than one match, stop and inspect it by hand before proceeding — that
would mean a Helm-chart source also happens to have `targetRevision: main` literally, which
must NOT be changed (only the `repoURL: https://github.com/rozdolsky33/OpenLex.git` source's
`targetRevision` changes).

- [ ] **Step 2: Change each file's own-repo `targetRevision` to `develop`**

For each of the 9 files, since every match from Step 1 is confirmed to be exactly the
own-repo source's `targetRevision: main` line (single match per file, matching the pattern
"this repo's `repoURL`, not a Helm chart's"), run:

```bash
for f in infra/argocd/apps/kind/app-openlex.yaml \
         infra/argocd/apps/kind/app-loki.yaml \
         infra/argocd/apps/kind/app-jaeger.yaml \
         infra/argocd/apps/kind/app-tempo.yaml \
         infra/argocd/apps/kind/app-otel-collector.yaml \
         infra/argocd/apps/kind/app-kube-prometheus-stack.yaml \
         infra/argocd/apps/kind/app-postgres-exporter.yaml \
         infra/argocd/apps/kind/app-promtail.yaml \
         infra/argocd/apps/kind/app-observability-dashboards.yaml; do
  sed -i.bak 's/targetRevision: main/targetRevision: develop/' "$f"
  rm "${f}.bak"
done
```

- [ ] **Step 3: Verify no `targetRevision: main` remains, and Helm-chart revisions are untouched**

Run: `grep -n "targetRevision:" infra/argocd/apps/kind/*.yaml`
Expected: every own-repo line now reads `targetRevision: develop`; every Helm-chart line
(e.g. `"87.15.*"`, `"4.11.*"`, `"1.24.*"`, `"6.17.*"`, `"0.165.*"`, `"7.0.*"`, `"8.1.1"`) is
unchanged from Step 1's baseline.

- [ ] **Step 4: Apply to the live cluster and confirm ArgoCD picks up `develop`**

```bash
kubectl apply -f infra/argocd/apps/kind/
```

Run: `kubectl -n argocd get application openlex -o jsonpath='{.spec.source.targetRevision}{"\n"}'`
Expected: `develop`

Run: `kubectl -n argocd get application openlex -o jsonpath='{.status.sync.status} {.status.health.status}{"\n"}'`
Expected: `Synced Healthy` (against `develop`, which is currently identical to `main`, so this
should sync cleanly with zero diff).

- [ ] **Step 5: Commit**

```bash
git add infra/argocd/apps/kind/
git commit -m "Retarget kind ArgoCD Applications from main to develop"
```

---

### Task 3: Docker-compose observability parity

**Files:**
- Modify: `docker-compose.yml`
- Create: `infra/local-observability/otel-collector-config.yaml`
- Create: `infra/local-observability/prometheus.yml`
- Create: `infra/local-observability/grafana-datasources.yaml`
- Create: `infra/local-observability/grafana-dashboards-provider.yaml`

**Interfaces:**
- Consumes: `infra/monitoring/grafana/dashboards/**` (existing, read-only bind-mount source —
  not modified).
- Produces: `docker-compose.yml`'s `api`/`worker` services now export real traces/metrics,
  visible in a local Jaeger UI (`localhost:16686`) and Grafana (`localhost:3000`) without kind.

- [ ] **Step 1: Write the OTel Collector config**

```yaml
# infra/local-observability/otel-collector-config.yaml
#
# Docker-compose's lightweight observability subset -- mirrors
# infra/monitoring/otel-collector/values-base.yaml's receive-and-export shape, minus the
# metrics/logs debug-only pipelines (compose has no Prometheus remote-write or Loki target to
# send those to; traces are the one signal worth exporting locally).
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch: {}

exporters:
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/jaeger]
```

- [ ] **Step 2: Write the Prometheus scrape config**

```yaml
# infra/local-observability/prometheus.yml
#
# Static scrape config -- docker-compose's built-in service-name DNS makes this trivial (no
# ServiceMonitor/service-discovery machinery needed, unlike kind's kube-prometheus-stack).
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: api
    static_configs:
      - targets: ["api:8000"]
```

- [ ] **Step 3: Write the Grafana datasource provisioning config**

```yaml
# infra/local-observability/grafana-datasources.yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
  - name: Jaeger
    type: jaeger
    access: proxy
    url: http://jaeger:16686
```

- [ ] **Step 4: Write the Grafana dashboard-provisioning config**

```yaml
# infra/local-observability/grafana-dashboards-provider.yaml
apiVersion: 1

providers:
  - name: default
    folder: ""
    type: file
    options:
      path: /etc/grafana/provisioning/dashboards/json
      foldersFromFilesStructure: true
```

- [ ] **Step 5: Add the four services and api/worker OTLP env override to `docker-compose.yml`**

Add these four new service blocks after the existing `web` service (before the top-level
`volumes:` block), and add the two-line `environment:` override to the existing `api` and
`worker` service blocks (do not remove or reorder anything else in those two blocks):

```yaml
  otel-collector:
    image: otel/opentelemetry-collector:0.156.0
    command: ["--config=/etc/otelcol/config.yaml"]
    volumes:
      - ./infra/local-observability/otel-collector-config.yaml:/etc/otelcol/config.yaml:ro
    ports:
      - "4317:4317"
      - "4318:4318"
    depends_on:
      - jaeger

  jaeger:
    image: jaegertracing/jaeger:2.19.0
    ports:
      - "16686:16686"

  prometheus:
    image: prom/prometheus:v3.13.1
    volumes:
      - ./infra/local-observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"
    depends_on:
      - api

  grafana:
    image: grafana/grafana:13.1.0
    environment:
      - GF_AUTH_ANONYMOUS_ENABLED=true
      - GF_AUTH_ANONYMOUS_ORG_ROLE=Admin
    volumes:
      - ./infra/local-observability/grafana-datasources.yaml:/etc/grafana/provisioning/datasources/datasources.yaml:ro
      - ./infra/local-observability/grafana-dashboards-provider.yaml:/etc/grafana/provisioning/dashboards/dashboards.yaml:ro
      - ./infra/monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards/json:ro
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
      - jaeger
```

`GF_AUTH_ANONYMOUS_ENABLED=true` — this is a local, laptop-only Grafana with no sensitive
data; skipping the login screen matches the project's existing "local dev should be
frictionless" precedent (e.g. `kind-secrets-bootstrap.sh` reading straight from `.env`).

For the existing `api` and `worker` service blocks, add this `environment:` key (both
currently have no `environment:` block, only `env_file: .env` — add it as a new sibling key):

```yaml
    environment:
      - OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
```

(`openlex_shared.config.Settings.otel_exporter_otlp_endpoint` defaults to the kind-cluster
Collector's in-cluster DNS name, which doesn't resolve in docker-compose — this override
points it at the compose Collector service instead. `environment:` takes precedence over
`env_file:` in compose's merge order, so this works even if a developer's own `.env` has no
`OTEL_EXPORTER_OTLP_ENDPOINT` line.)

- [ ] **Step 6: Verify docker-compose config parses**

Run: `docker compose config --quiet`
Expected: no output, exit code 0 (validates YAML + service references resolve).

- [ ] **Step 7: Bring up the full stack and verify traces/metrics/dashboards are real**

```bash
docker compose up -d --build
```

Wait for `api` healthy (`curl -sf http://localhost:8000/healthz` returns `{"status":"ok",...}`,
retry every 5s up to 60s), then:

```bash
scripts/ingest.sh statutes
scripts/seed-demo-users.sh
```

Log in and make one real query (replace `<platinum-email>`/`<platinum-password>` with your
`.env`'s `DEMO_PLATINUM_EMAIL`/`DEMO_PLATINUM_PASSWORD`):

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -d "username=<platinum-email>&password=<platinum-password>" | jq -r .access_token)
curl -s -X POST http://localhost:8000/query \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  -d '{"question": "How much notice must a landlord give before a nonpayment proceeding?"}' | jq .
```

Then verify each observability component actually has real data (not just that the containers
are up):

- Jaeger: `curl -s "http://localhost:16686/api/traces?service=openlex-api&limit=1" | jq '.data | length'` → expect `1` (a real trace exists).
- Prometheus: `curl -s "http://localhost:9090/api/v1/query?query=up{job=\"api\"}" | jq -r '.data.result[0].value[1]'` → expect `"1"`.
- Grafana: `curl -s http://localhost:3000/api/search?query=Golden | jq '. | length'` → expect a value `>= 1` (the Golden Signals dashboard is provisioned and discoverable; no auth header needed since `GF_AUTH_ANONYMOUS_ENABLED=true` grants anonymous Admin access on this local-only instance).

- [ ] **Step 8: Tear down**

```bash
docker compose down
```

- [ ] **Step 9: Commit**

```bash
git add docker-compose.yml infra/local-observability/
git commit -m "Bring docker-compose to observability parity: OTel Collector, Prometheus, Grafana, Jaeger"
```

---

### Task 4: Gate `tests/integration/` in CI

**Files:**
- Create: `.github/workflows/integration.yml`

**Interfaces:**
- Consumes: `tests/integration/conftest.py`'s existing `TEST_DATABASE_URL` default
  (`postgresql+asyncpg://openlex_test@127.0.0.1:5544/openlex_test`) — this task's service
  container is configured to make that default correct with zero env var override needed.
- Produces: nothing later tasks depend on — this is a standalone CI gate.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/integration.yml
name: integration

on:
  pull_request:
    paths:
      - "packages/legal_retrieval/**"
      - "packages/legal_parsing/**"
      - "packages/legal_models/**"
      - "packages/shared/**"
      - "pipelines/**"
      - "migrations/**"
      - "tests/integration/**"

jobs:
  integration-tests:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: openlex_test
          POSTGRES_DB: openlex_test
          POSTGRES_HOST_AUTH_METHOD: trust
        ports:
          - 5544:5432
        options: >-
          --health-cmd "pg_isready -U openlex_test -d openlex_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    # Same three dummy values as api.yml/pipelines.yml -- openlex_shared.config.Settings
    # requires these at import time; tests/integration never makes a real Anthropic call or
    # reads JWT_SECRET_KEY, so placeholders are correct here.
    env:
      ANTHROPIC_API_KEY: ci-placeholder
      DATABASE_URL: postgresql+asyncpg://ci:ci@localhost:5432/ci
      JWT_SECRET_KEY: ci-placeholder-not-a-real-secret-32chars
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - run: uv sync --all-packages

      - name: Apply migrations
        run: |
          for f in migrations/postgres/*.sql; do
            echo "Applying $f"
            PGPASSWORD="" psql -h localhost -p 5544 -U openlex_test -d openlex_test -v ON_ERROR_STOP=1 -f "$f"
          done

      - run: uv run pytest tests/integration -v
```

No `TEST_DATABASE_URL` env var needed — the `services.postgres` block above (same user/db name
and port `5544` as `scripts/test-db.sh`'s local `db-test` service) makes `conftest.py`'s
built-in default already correct.

- [ ] **Step 2: Verify the workflow is syntactically valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/integration.yml'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Verify locally that the same migration-apply + pytest sequence works**

(Simulates the CI job against the existing local `db-test` service, which uses the identical
port/user/db-name convention.)

```bash
scripts/test-db.sh reset
uv run pytest tests/integration -v
```

Expected: all tests pass (same suite that already passes locally today — this step proves the
workflow's `psql` migration-apply loop is equivalent to `scripts/test-db.sh`'s existing setup,
not a new behavior).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/integration.yml
git commit -m "Gate tests/integration in CI with a real Postgres+pgvector service container"
```

---

### Task 5: Real end-to-end smoke test

**Files:**
- Create: `tests/end_to_end/test_smoke.py`
- Modify: `tests/end_to_end/README.md`
- Modify: `pyproject.toml`
- Create: `.github/workflows/smoke.yml`

**Interfaces:**
- Consumes: `POST /auth/login` (`apps/api/src/openlex_api/routers/auth.py`, OAuth2 password
  form, returns `{"access_token": str, "token_type": "bearer"}`), `POST /query`
  (`apps/api/src/openlex_api/routers/query.py`, `{"question": str}` body, `Authorization:
  Bearer <token>` header, returns `QueryResponse`: `{answer: str, citations: list[Citation],
  abstained: bool, disclaimer: str, conversation_id: str|None, usage: ...}`).
- Produces: nothing later tasks depend on — standalone CI gate, same category as Task 4.

- [ ] **Step 1: Add a new `e2e` pytest marker, excluded from the default run**

In `pyproject.toml`'s `[tool.pytest.ini_options]` section, change:

```toml
markers = [
    "evaluation: golden-question legal-accuracy eval -- hits a live API + real Claude, costs money and needs a running server. Excluded from the default run; use scripts/evaluate.sh.",
]
addopts = "-m 'not evaluation' --cov --cov-report=term-missing"
```

to:

```toml
markers = [
    "evaluation: golden-question legal-accuracy eval -- hits a live API + real Claude, costs money and needs a running server. Excluded from the default run; use scripts/evaluate.sh.",
    "e2e: full-stack smoke test -- hits a live, already-running API over HTTP. Excluded from the default run; needs docker compose up -d --build db api worker first.",
]
addopts = "-m 'not evaluation and not e2e' --cov --cov-report=term-missing"
```

- [ ] **Step 2: Write the smoke test**

```python
# tests/end_to_end/test_smoke.py
"""Full-stack smoke test: proves the golden path (login -> query -> cited answer) is alive
against a live, already-running stack. Deliberately does NOT re-test citation accuracy -- that
is tests/evaluation's job. Marked `e2e` and excluded from the default `uv run pytest` run (see
the root pyproject.toml's addopts): it needs a running server. Run via:

    docker compose up -d --build db api worker
    scripts/ingest.sh statutes
    scripts/seed-demo-users.sh
    uv run pytest tests/end_to_end -v -m e2e
"""

import os

import httpx
import pytest
from openlex_shared.config import settings

pytestmark = pytest.mark.e2e

API_BASE_URL = os.environ.get("EVAL_API_BASE_URL", "http://localhost:8000")
REQUEST_TIMEOUT_SECONDS = 60.0


def test_smoke_login_query_cited_answer() -> None:
    email = settings.demo_platinum_email
    password = settings.demo_platinum_password
    assert email and password, (
        "DEMO_PLATINUM_EMAIL/DEMO_PLATINUM_PASSWORD aren't set -- seed the demo users "
        "(scripts/seed-demo-users.sh) and ensure .env has them before running this test."
    )

    login_response = httpx.post(
        f"{API_BASE_URL}/auth/login",
        data={"username": email, "password": password},
        timeout=10.0,
    )
    login_response.raise_for_status()
    token = login_response.json()["access_token"]

    query_response = httpx.post(
        f"{API_BASE_URL}/query",
        json={"question": "How much notice must a landlord give before a nonpayment eviction proceeding in New York?"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    query_response.raise_for_status()
    body = query_response.json()

    assert body["abstained"] is False, f"unexpectedly abstained: {body['answer']!r}"
    assert body["answer"].strip(), "answer was empty"
    assert len(body["citations"]) >= 1, "expected at least one citation"
    assert body["disclaimer"], "disclaimer missing"
```

- [ ] **Step 3: Replace the stub README**

```markdown
# End-to-end tests

Full-stack smoke test driving the running `docker-compose` stack over real HTTP (see
`test_smoke.py`'s module docstring for exact setup/run commands). Proves the golden path --
login, ask a question, get a cited, disclaimered answer -- actually works end-to-end. This is
deliberately narrow: it does not re-check citation *accuracy* (see `tests/evaluation/` for
that), only that the full request path (auth -> retrieval -> generation -> response shape) is
alive.
```

- [ ] **Step 4: Run the test locally against a real stack to verify it passes**

```bash
docker compose up -d --build db api worker
```

Wait for `curl -sf http://localhost:8000/healthz` to report `{"status":"ok",...}` (retry every
5s up to 60s), then:

```bash
scripts/ingest.sh statutes
scripts/seed-demo-users.sh
uv run pytest tests/end_to_end -v -m e2e
```

Expected: `test_smoke_login_query_cited_answer PASSED`.

```bash
docker compose down
```

- [ ] **Step 5: Verify the default `uv run pytest` run still excludes it**

Run: `uv run pytest --collect-only -q 2>&1 | grep -c "test_smoke"`
Expected: `0` (excluded by the `not e2e` addopts, confirming Step 1's marker change works).

- [ ] **Step 6: Write the CI workflow**

```yaml
# .github/workflows/smoke.yml
name: smoke

on:
  pull_request: {}

jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true

      - name: Check required secrets are configured
        id: secrets
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          NY_OPEN_LEG_API_KEY: ${{ secrets.NY_OPEN_LEG_API_KEY }}
        run: |
          if [ -n "$ANTHROPIC_API_KEY" ] && [ -n "$NY_OPEN_LEG_API_KEY" ]; then
            echo "configured=true" >> "$GITHUB_OUTPUT"
          else
            echo "configured=false" >> "$GITHUB_OUTPUT"
            echo "::notice::smoke test skipped: ANTHROPIC_API_KEY and/or NY_OPEN_LEG_API_KEY repo secrets aren't configured."
          fi

      - run: uv sync --all-packages
        if: steps.secrets.outputs.configured == 'true'

      - name: Write .env for the live stack
        if: steps.secrets.outputs.configured == 'true'
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          NY_OPEN_LEG_API_KEY: ${{ secrets.NY_OPEN_LEG_API_KEY }}
        run: |
          cat > .env <<EOF
          ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
          ANTHROPIC_MODEL=claude-haiku-4-5
          DATABASE_URL=postgresql+asyncpg://openlex:openlex@db:5432/openlex
          NY_OPEN_LEG_API_KEY=${NY_OPEN_LEG_API_KEY}
          NY_OPEN_LEG_BASE_URL=https://legislation.nysenate.gov/api/3
          EMBEDDING_MODEL_NAME=BAAI/bge-small-en-v1.5
          JWT_SECRET_KEY=ci-smoke-not-a-real-secret-32characters
          JWT_ALGORITHM=HS256
          JWT_EXPIRE_MINUTES=60
          DEMO_SILVER_EMAIL=ci-smoke-silver@example.com
          DEMO_SILVER_PASSWORD=ci-smoke-silver-not-a-real-password
          DEMO_GOLD_EMAIL=ci-smoke-gold@example.com
          DEMO_GOLD_PASSWORD=ci-smoke-gold-not-a-real-password
          DEMO_PLATINUM_EMAIL=ci-smoke-platinum@example.com
          DEMO_PLATINUM_PASSWORD=ci-smoke-platinum-not-a-real-password
          EOF

      - name: Start db, api, and worker
        if: steps.secrets.outputs.configured == 'true'
        run: docker compose up -d --build db api worker

      - name: Wait for API to report status=ok
        if: steps.secrets.outputs.configured == 'true'
        run: |
          for i in $(seq 1 60); do
            health_status=$(curl -sf http://localhost:8000/healthz | jq -r '.status' 2>/dev/null || echo "unreachable")
            if [ "$health_status" = "ok" ]; then
              echo "API ready"
              exit 0
            fi
            echo "waiting for API readiness ($i/60): $health_status"
            sleep 5
          done
          echo "::error::API did not report status=ok within 5 minutes"
          docker compose logs api
          exit 1

      - name: Ingest seed statutes
        if: steps.secrets.outputs.configured == 'true'
        run: scripts/ingest.sh statutes

      - name: Seed demo users
        if: steps.secrets.outputs.configured == 'true'
        run: scripts/seed-demo-users.sh

      - name: Run smoke test
        if: steps.secrets.outputs.configured == 'true'
        env:
          EVAL_API_BASE_URL: http://localhost:8000
        run: uv run pytest tests/end_to_end -v -m e2e

      - name: Show container logs on failure
        if: failure() && steps.secrets.outputs.configured == 'true'
        run: docker compose logs --no-color db api worker

      - name: Tear down
        if: always() && steps.secrets.outputs.configured == 'true'
        run: docker compose down -v --remove-orphans
```

Triggered on every PR (`pull_request: {}`, no path filter, no branch filter) — deliberately
broader than `api.yml`/`pipelines.yml`'s path-scoped triggers, per the design.

- [ ] **Step 7: Verify the workflow is syntactically valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/smoke.yml'))" && echo OK`
Expected: `OK`

- [ ] **Step 8: Commit**

```bash
git add tests/end_to_end/test_smoke.py tests/end_to_end/README.md pyproject.toml .github/workflows/smoke.yml
git commit -m "Add real end-to-end smoke test, replacing the stub"
```

---

### Task 6: GHCR pull secret bootstrap and `imagePullSecrets`

**Files:**
- Create: `scripts/kind-ghcr-pull-secret-bootstrap.sh`
- Modify: `.env.example`
- Modify: `infra/kubernetes/base/api/deployment.yaml`
- Modify: `infra/kubernetes/base/worker/deployment.yaml`
- Modify: `infra/kubernetes/base/web/deployment.yaml`

**Interfaces:**
- Produces: a `ghcr-pull-secret` Secret in the `openlex` namespace, referenced by all three
  Deployments — Task 7's `deploy.yml` assumes this secret already exists on the cluster before
  its first real deploy (documented as a one-time manual bootstrap step, same as
  `kind-secrets-bootstrap.sh`).

- [ ] **Step 1: Add `GHCR_USERNAME`/`GHCR_PAT` to `.env.example`**

Append to `.env.example`:

```
# GHCR pull-secret bootstrap only (personal access token, "read:packages" scope) -- used once,
# out-of-band, by scripts/kind-ghcr-pull-secret-bootstrap.sh to let the kind cluster pull
# private images from ghcr.io. Not read by the running app at runtime -- never wired into
# openlex_shared.config.Settings or any application code path (same framing as
# COURTLISTENER_API_TOKEN above).
GHCR_USERNAME=
GHCR_PAT=
```

- [ ] **Step 2: Write the bootstrap script**

```bash
#!/usr/bin/env bash
# Manual, idempotent GHCR pull-secret bootstrap for the kind cluster -- same category of
# exception as scripts/kind-secrets-bootstrap.sh (kind has no IRSA/External Secrets Operator to
# automate this). Creates a docker-registry Secret so kubelet can pull the private
# ghcr.io/<owner>/openlex-{api,worker,web} images deploy.yml publishes. Not committed anywhere;
# not managed by ArgoCD. Safe to re-run after rotating GHCR_PAT in .env.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAMESPACE="openlex"

if [ ! -f .env ]; then
  echo "No .env found — run scripts/bootstrap.sh first (or copy .env.example to .env and fill it in)." >&2
  exit 1
fi

GHCR_USERNAME="$(grep '^GHCR_USERNAME=' .env | cut -d= -f2-)"
GHCR_PAT="$(grep '^GHCR_PAT=' .env | cut -d= -f2-)"

if [ -z "$GHCR_USERNAME" ] || [ -z "$GHCR_PAT" ]; then
  echo "GHCR_USERNAME and/or GHCR_PAT are empty in .env — set both (a GitHub personal access token with 'read:packages' scope) before running this." >&2
  exit 1
fi

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret docker-registry ghcr-pull-secret \
  --namespace "${NAMESPACE}" \
  --docker-server=ghcr.io \
  --docker-username="${GHCR_USERNAME}" \
  --docker-password="${GHCR_PAT}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "ghcr-pull-secret created/updated in namespace '${NAMESPACE}' from .env."
```

- [ ] **Step 3: Make it executable**

```bash
chmod +x scripts/kind-ghcr-pull-secret-bootstrap.sh
```

- [ ] **Step 4: Add `imagePullSecrets` to each Deployment**

In `infra/kubernetes/base/api/deployment.yaml`, add `imagePullSecrets` as a sibling of
`serviceAccountName` (inside `spec.template.spec`):

```yaml
    spec:
      serviceAccountName: openlex-api
      imagePullSecrets:
        - name: ghcr-pull-secret
      containers:
```

Same pattern for `infra/kubernetes/base/worker/deployment.yaml` (`serviceAccountName:
openlex-worker`):

```yaml
    spec:
      serviceAccountName: openlex-worker
      imagePullSecrets:
        - name: ghcr-pull-secret
      containers:
```

`infra/kubernetes/base/web/deployment.yaml` has no `serviceAccountName` line — add
`imagePullSecrets` as the first key under `spec.template.spec`:

```yaml
    spec:
      imagePullSecrets:
        - name: ghcr-pull-secret
      containers:
```

- [ ] **Step 5: Verify the manifests still render**

Run: `kubectl kustomize infra/kubernetes/overlays/kind | grep -A2 imagePullSecrets`
Expected: three `imagePullSecrets:` blocks (api, worker, web), each followed by `- name:
ghcr-pull-secret`.

- [ ] **Step 6: Bootstrap the secret on the live cluster and verify**

(Requires a real GitHub personal access token with `read:packages` scope in `.env`'s
`GHCR_USERNAME`/`GHCR_PAT` — create one at github.com/settings/tokens if you don't have one.)

```bash
scripts/kind-ghcr-pull-secret-bootstrap.sh
```

Run: `kubectl -n openlex get secret ghcr-pull-secret -o jsonpath='{.type}{"\n"}'`
Expected: `kubernetes.io/dockerconfigjson`

- [ ] **Step 7: Commit**

```bash
git add scripts/kind-ghcr-pull-secret-bootstrap.sh .env.example infra/kubernetes/base/api/deployment.yaml infra/kubernetes/base/worker/deployment.yaml infra/kubernetes/base/web/deployment.yaml
git commit -m "Add GHCR pull-secret bootstrap and imagePullSecrets to api/worker/web"
```

---

### Task 7: `deploy.yml` — build, push to GHCR, GitOps commit to `develop`

**Files:**
- Create: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: the `ghcr-pull-secret` bootstrapped in Task 6 (must exist on the cluster before
  this workflow's first real run produces a pullable deployment); the `develop` branch and
  ArgoCD retarget from Tasks 1-2.
- Produces: `ghcr.io/<owner>/openlex-{api,worker,web}:<git-sha>` images and a commit on
  `develop` bumping `infra/kubernetes/overlays/kind/kustomization.yaml`'s `images:` tags —
  Task 8's `use-local-images.sh` is the local-only counterpart that temporarily overrides what
  this task commits.

- [ ] **Step 1: Write the workflow**

```yaml
# .github/workflows/deploy.yml
name: deploy

on:
  push:
    branches:
      - develop

permissions:
  contents: write
  packages: write

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    env:
      REGISTRY: ghcr.io
      IMAGE_OWNER: ${{ github.repository_owner }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push openlex-api
        uses: docker/build-push-action@v6
        with:
          context: .
          file: apps/api/Dockerfile
          push: true
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/openlex-api:${{ github.sha }}

      - name: Build and push openlex-worker
        uses: docker/build-push-action@v6
        with:
          context: .
          file: apps/worker/Dockerfile
          push: true
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/openlex-worker:${{ github.sha }}

      - name: Build and push openlex-web
        uses: docker/build-push-action@v6
        with:
          context: apps/web
          file: apps/web/Dockerfile
          push: true
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/openlex-web:${{ github.sha }}

      - name: Bump image tags in the kind overlay
        run: |
          curl -sL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.4.3/kustomize_v5.4.3_linux_amd64.tar.gz" | tar xz
          cd infra/kubernetes/overlays/kind
          ../../../../kustomize edit set image \
            openlex-api=${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/openlex-api:${{ github.sha }} \
            openlex-worker=${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/openlex-worker:${{ github.sha }} \
            openlex-web=${{ env.REGISTRY }}/${{ env.IMAGE_OWNER }}/openlex-web:${{ github.sha }}

      - name: Commit and push the tag bump
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add infra/kubernetes/overlays/kind/kustomization.yaml
          if git diff --cached --quiet; then
            echo "No image-tag changes to commit (rebuilt identical digests)."
          else
            git commit -m "chore: deploy ${{ github.sha }}"
            git push origin HEAD:develop
          fi
```

`fetch-depth: 0` — the commit-back step needs real branch history to push cleanly, not a
shallow clone. The `kustomize` binary is fetched directly (pinned version `v5.4.3`) rather than
relying on whatever `kubectl kustomize` ships with, since `kustomize edit set image` is a
`kustomize`-CLI-only subcommand, not part of `kubectl`'s bundled kustomize support.

- [ ] **Step 2: Verify the workflow is syntactically valid**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy.yml'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Verify `kustomize edit set image` produces the expected diff locally**

(Dry run against a throwaway copy, without pushing anywhere.)

```bash
cp -r infra/kubernetes/overlays/kind /tmp/kind-overlay-test
cd /tmp/kind-overlay-test
kustomize edit set image \
  openlex-api=ghcr.io/testowner/openlex-api:testsha \
  openlex-worker=ghcr.io/testowner/openlex-worker:testsha \
  openlex-web=ghcr.io/testowner/openlex-web:testsha
grep -A2 "name: openlex-api" kustomization.yaml
cd -
rm -rf /tmp/kind-overlay-test
```

Expected: `kustomization.yaml`'s `images:` block now shows `newName: ghcr.io/testowner/
openlex-api` / `newTag: testsha` for each of the three images (requires the `kustomize` CLI
installed locally — `brew install kustomize` or equivalent — to run this verification step).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "Add deploy.yml: build, push to GHCR, GitOps-commit to develop"
```

---

### Task 8: Local-dev fast-path companion script

**Files:**
- Create: `scripts/use-local-images.sh`

**Interfaces:**
- Consumes: `scripts/kind-load-images.sh`'s `:kind-local` image tags (unchanged, Task 8 doesn't
  modify that script).
- Produces: nothing later tasks depend on — this is the final piece of the design.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Local-only counterpart to deploy.yml's GHCR tag bump: after scripts/kind-load-images.sh
# loads fresh :kind-local images into the kind cluster's containerd store, this points the
# overlay's committed images: block at those tags instead of whatever ghcr.io/...:<sha> the
# last real deploy set -- otherwise ArgoCD/kubectl would keep pulling the old GHCR image, not
# the freshly-loaded local one.
#
# Deliberately NOT committed or pushed -- this is an uncommitted, working-tree-only edit. Once
# you're done iterating, `git checkout -- infra/kubernetes/overlays/kind/kustomization.yaml`
# (or a fresh `git pull`) restores the real GHCR-tag state. Never run this as part of any CI
# workflow.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v kustomize >/dev/null 2>&1; then
  echo "kustomize CLI not found — install it first (e.g. \`brew install kustomize\`)." >&2
  exit 1
fi

cd infra/kubernetes/overlays/kind
kustomize edit set image \
  openlex-api=openlex-api:kind-local \
  openlex-worker=openlex-worker:kind-local \
  openlex-web=openlex-web:kind-local

echo "overlays/kind/kustomization.yaml now points at :kind-local images (uncommitted)."
echo "Apply with: kubectl apply -k infra/kubernetes/overlays/kind"
echo "Revert with: git checkout -- infra/kubernetes/overlays/kind/kustomization.yaml"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/use-local-images.sh
```

- [ ] **Step 3: Verify it works and is cleanly revertible**

```bash
git status --short infra/kubernetes/overlays/kind/kustomization.yaml
```
Expected: no output (clean before the test).

```bash
scripts/use-local-images.sh
git diff infra/kubernetes/overlays/kind/kustomization.yaml
```
Expected: a diff showing all three `newName`/`newTag` pairs changed to `openlex-{api,worker,
web}` / `kind-local`.

```bash
git checkout -- infra/kubernetes/overlays/kind/kustomization.yaml
git status --short infra/kubernetes/overlays/kind/kustomization.yaml
```
Expected: no output (cleanly reverted).

- [ ] **Step 4: Commit**

```bash
git add scripts/use-local-images.sh
git commit -m "Add use-local-images.sh: local-only kind-local image tag override"
```

---

## Final verification (whole-plan, after all 8 tasks)

- [ ] `uv run pytest` (default run) still passes and still excludes both `evaluation` and `e2e`
  tests: `uv run pytest --collect-only -q 2>&1 | grep -cE "evaluation|test_smoke"` should be
  `0` for `test_smoke` specifically (the golden-question tests are collected but deselected,
  which is existing, unchanged behavior).
- [ ] Open the PR from `phase6-cicd-hardening` against **`develop`**, not `main` — this is the
  one place in this whole plan where getting the target branch wrong would silently break the
  entire design (deploy.yml only triggers on push to `develop`).
- [ ] After merging: watch one real `deploy.yml` run end-to-end (Actions tab), confirm images
  land in GHCR (repo's Packages tab), confirm the bot commit lands on `develop`
  (`git log develop --oneline -5`), confirm ArgoCD picks it up (`kubectl -n argocd get
  application openlex -o jsonpath='{.status.sync.status} {.status.health.status}{"\n"}'` →
  `Synced Healthy`), and confirm the running pods' `imageID`s match the newly-pushed digests
  (`kubectl -n openlex get pods -l app.kubernetes.io/name=openlex-api -o custom-columns=NAME:
  .metadata.name,IMAGEID:.status.containerStatuses[0].imageID`).
