# Observability Phase 1 — Infra Plumbing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the `openlex` kind cluster if it doesn't exist, then deploy
`kube-prometheus-stack` (Prometheus/Grafana/Alertmanager/node-exporter/kube-state-metrics)
and an OpenTelemetry Collector onto it via ArgoCD, wire the existing `openlex-api`
`/metrics` endpoint into Prometheus scraping, and prove the OTLP pipeline works end-to-end
with a manual test span — all before any application code changes.

**Architecture:** ArgoCD Helm Applications under `infra/argocd/apps/kind/`, each sourcing its
chart directly from the upstream Helm repo plus a shared
`infra/monitoring/<component>/values-base.yaml` file from this git repo, combined via
ArgoCD's multi-source `$values` reference. The same values-base file is what a future
`eks-demo` Application would reuse — see the "Local kind vs EKS-demo consistency" section of
the design doc.

**Tech Stack:** ArgoCD (bootstrapped via `scripts/argocd-bootstrap.sh`), Helm charts
`prometheus-community/kube-prometheus-stack` (pin `87.15.*`) and
`open-telemetry/opentelemetry-collector` (pin `0.165.*`) — versions confirmed live via
`helm search repo` on 2026-07-12, not guessed — and Prometheus Operator's `ServiceMonitor`
CRD.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-12-production-observability-design.md`
  — every task here implements one part of it.
- New components go in the `observability` namespace. `postgres_exporter` (a later phase)
  goes in the `openlex` namespace instead — not part of this plan.
- All Helm values pin `resources.requests`/`limits` explicitly — no chart defaults.
- Follow `infra/argocd/projects/appproject-eks-demo.yaml`'s existing pattern exactly when
  editing `appproject-kind.yaml` for the new Helm repos/namespace.
- Nothing is "done" without a real command's output confirming it — no step is marked
  complete on assertion alone (per `superpowers:verification-before-completion`).
- Laptop-scale kind cluster: ephemeral storage (no PVC for Prometheus this phase), low
  resource requests throughout.
- There is currently **no `openlex` kind cluster** — only an unrelated `omnicart` cluster is
  running on this machine. Task 1 creates a new, separate `openlex` kind cluster (isolated
  Docker containers; does not touch `omnicart`).

---

### Task 1: Bootstrap the baseline `openlex` kind cluster (if not already up)

**Files:** none (uses existing `scripts/kind-up.sh`, `scripts/kind-load-images.sh`,
`scripts/kind-secrets-bootstrap.sh`, `scripts/argocd-bootstrap.sh`)

**Interfaces:**
- Produces: a running `kind-openlex` context with ArgoCD installed in `argocd` namespace,
  `openlex-secrets` Secret in `openlex` namespace, and the `openlex` ArgoCD Application
  synced (api/worker/postgres healthy). Later tasks depend on this context existing.

- [ ] **Step 1: Check whether the `openlex` kind cluster already exists**

Run: `kind get clusters`
Expected: either `openlex` is in the list (skip to Step 5), or it isn't (continue).

- [ ] **Step 2: Create the cluster**

Run: `scripts/kind-up.sh`
Expected: ends with `kubectl context set to kind-openlex.`

- [ ] **Step 3: Build and load app images, bootstrap secrets**

Run:
```bash
scripts/kind-load-images.sh
scripts/kind-secrets-bootstrap.sh
```
Expected: last line of each script confirms success (`Loaded openlex-api:kind-local...`,
`openlex-secrets created/updated in namespace 'openlex' from .env.`).

- [ ] **Step 4: Bootstrap ArgoCD and the root Application**

Run: `scripts/argocd-bootstrap.sh kind`
Expected: ends with `ArgoCD installed and root-kind applied.` — this installs ArgoCD via Helm
and applies `infra/argocd/projects/appproject-kind.yaml` + `infra/argocd/root-apps/root-kind.yaml`.

- [ ] **Step 5: Confirm the base `openlex` app is healthy before adding anything new**

Run:
```bash
kubectl config use-context kind-openlex
kubectl get application -n argocd
kubectl get pods -n openlex
```
Expected: `openlex` Application shows `Synced`/`Healthy`; `api`, `worker`, `postgres` pods
`Running`/`1/1 Ready`.

---

### Task 2: Grant the kind AppProject access to the new Helm repos and namespace

**Files:**
- Modify: `infra/argocd/projects/appproject-kind.yaml`

**Interfaces:**
- Consumes: nothing new.
- Produces: `sourceRepos` entries for `https://prometheus-community.github.io/helm-charts`
  and `https://open-telemetry.github.io/opentelemetry-helm-charts`; a `destinations` entry
  for `namespace: observability`. Tasks 3–4's Applications require these to exist first, or
  ArgoCD rejects them with a project-permission error.

- [ ] **Step 1: Edit the file**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: openlex-kind
  namespace: argocd
spec:
  description: OpenLex workload on the local kind cluster
  sourceRepos:
    - https://github.com/rozdolsky33/OpenLex.git
    # Helm chart sources for the observability stack (see
    # docs/superpowers/specs/2026-07-12-production-observability-design.md) — each
    # Application below points at the upstream chart repo directly.
    - https://prometheus-community.github.io/helm-charts
    - https://open-telemetry.github.io/opentelemetry-helm-charts
  destinations:
    - namespace: openlex
      server: https://kubernetes.default.svc
    - namespace: argocd
      server: https://kubernetes.default.svc
    - namespace: observability
      server: https://kubernetes.default.svc
  clusterResourceWhitelist:
    - group: "*"
      kind: "*"
```

- [ ] **Step 2: Apply it directly (root-kind Application won't reconcile its own project — this file is applied imperatively by `scripts/argocd-bootstrap.sh`, same as its first run)**

Run: `kubectl apply -f infra/argocd/projects/appproject-kind.yaml`
Expected: `appproject.argoproj.io/openlex-kind configured`

- [ ] **Step 3: Commit**

```bash
git add infra/argocd/projects/appproject-kind.yaml
git commit -m "Grant kind AppProject access to observability Helm repos and namespace"
```

---

### Task 3: Deploy kube-prometheus-stack (Prometheus, Grafana, Alertmanager)

**Files:**
- Create: `infra/monitoring/kube-prometheus-stack/values-base.yaml`
- Create: `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml`

**Interfaces:**
- Consumes: `observability` namespace/repo access from Task 2.
- Produces: a running Prometheus (scraping cluster-wide `ServiceMonitor`s — critical for
  Task 5), Grafana (dashboard sidecar watching `grafana_dashboard: "1"`-labeled ConfigMaps
  in any namespace — used by later phases), and Alertmanager (default `null` route, no
  custom rules yet — those come in a later phase). Later tasks in this plan (5, 6) depend on
  Prometheus actually scraping all namespaces, which requires the
  `serviceMonitorSelectorNilUsesHelmValues: false` + empty `serviceMonitorNamespaceSelector`
  settings below — a well-known kube-prometheus-stack gotcha where, without these, the chart
  only watches `ServiceMonitor`s carrying its own release label.

- [ ] **Step 1: Write the shared values-base file**

```yaml
# infra/monitoring/kube-prometheus-stack/values-base.yaml
#
# Shared base values for kube-prometheus-stack, consumed by both the kind Application
# (infra/argocd/apps/kind/app-kube-prometheus-stack.yaml) and any future eks-demo
# Application, via ArgoCD's multi-source `$values` reference. Environment-specific overrides
# (resource sizing, storage) live in each Application's own inline `valuesObject`, not here —
# see the design doc's "Local kind vs EKS-demo consistency" section.

grafana:
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      labelValue: "1"
      searchNamespace: ALL

alertmanager:
  enabled: true

prometheus:
  prometheusSpec:
    # Without these two, Prometheus only selects ServiceMonitors/PodMonitors carrying this
    # chart's own release label — openlex-api's ServiceMonitor (Task 5, a different
    # namespace, no such label) would silently never be scraped.
    serviceMonitorSelectorNilUsesHelmValues: false
    serviceMonitorNamespaceSelector: {}
    podMonitorSelectorNilUsesHelmValues: false
    podMonitorNamespaceSelector: {}
```

- [ ] **Step 2: Write the ArgoCD Application**

```yaml
# infra/argocd/apps/kind/app-kube-prometheus-stack.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kube-prometheus-stack
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
spec:
  project: openlex-kind
  sources:
    - repoURL: https://prometheus-community.github.io/helm-charts
      chart: kube-prometheus-stack
      targetRevision: "87.15.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/kube-prometheus-stack/values-base.yaml
        valuesObject:
          prometheus:
            prometheusSpec:
              retention: 6h
              resources:
                requests: { cpu: 100m, memory: 400Mi }
                limits: { cpu: 500m, memory: 800Mi }
          alertmanager:
            alertmanagerSpec:
              resources:
                requests: { cpu: 10m, memory: 32Mi }
                limits: { cpu: 100m, memory: 64Mi }
          grafana:
            resources:
              requests: { cpu: 25m, memory: 96Mi }
              limits: { cpu: 100m, memory: 192Mi }
          kube-state-metrics:
            resources:
              requests: { cpu: 10m, memory: 32Mi }
              limits: { cpu: 50m, memory: 64Mi }
          prometheus-node-exporter:
            resources:
              requests: { cpu: 10m, memory: 24Mi }
              limits: { cpu: 50m, memory: 48Mi }
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 3: Apply and wait for it to sync**

Run:
```bash
kubectl apply -f infra/argocd/apps/kind/app-kube-prometheus-stack.yaml
kubectl wait --for=jsonpath='{.status.health.status}'=Healthy application/kube-prometheus-stack -n argocd --timeout=300s
```
Expected: `application.argoproj.io/kube-prometheus-stack condition met`

- [ ] **Step 4: Verify pods are actually running**

Run: `kubectl get pods -n observability`
Expected: `kube-prometheus-stack-grafana-*`, `kube-prometheus-stack-kube-state-metrics-*`,
`kube-prometheus-stack-prometheus-node-exporter-*`, `alertmanager-kube-prometheus-stack-*`,
and `prometheus-kube-prometheus-stack-*` all `Running`/`Ready`.

- [ ] **Step 5: Commit**

```bash
git add infra/monitoring/kube-prometheus-stack/values-base.yaml infra/argocd/apps/kind/app-kube-prometheus-stack.yaml
git commit -m "Deploy kube-prometheus-stack to kind via ArgoCD (observability Phase 1)"
```

---

### Task 4: Deploy the OpenTelemetry Collector

**Files:**
- Create: `infra/monitoring/otel-collector/values-base.yaml`
- Create: `infra/argocd/apps/kind/app-otel-collector.yaml`

**Interfaces:**
- Consumes: `observability` namespace from Task 2; nothing from Task 3 (independent chart,
  same sync-wave ordering only matters relative to CRDs, which this chart doesn't need).
- Produces: an OTLP receiver reachable in-cluster at
  `otel-collector-opentelemetry-collector.observability.svc.cluster.local:4317` (gRPC) and
  `:4318` (HTTP) — this exact DNS name is what `apps/api`/`apps/worker` will point
  `OTEL_EXPORTER_OTLP_ENDPOINT` at in a later phase. For this phase, exports go to a `debug`
  exporter (stdout) only — no Tempo/Loki exist yet — so "working" here means "receives and
  logs a span/metric/log record," not "forwards it somewhere permanent."

- [ ] **Step 1: Write the shared values-base file**

```yaml
# infra/monitoring/otel-collector/values-base.yaml
#
# Shared base values for the OTel Collector, consumed by both kind and any future eks-demo
# Application. The exporters here are intentionally `debug`-only in this phase — Tempo,
# Jaeger, and Loki don't exist yet (later phases add real exporters to these same
# pipelines). This proves the receive-and-process path works before wiring real backends.

mode: deployment

config:
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
    debug:
      verbosity: detailed
  service:
    pipelines:
      traces:
        receivers: [otlp]
        processors: [batch]
        exporters: [debug]
      metrics:
        receivers: [otlp]
        processors: [batch]
        exporters: [debug]
      logs:
        receivers: [otlp]
        processors: [batch]
        exporters: [debug]

ports:
  otlp:
    enabled: true
  otlp-http:
    enabled: true

serviceMonitor:
  enabled: true
```

- [ ] **Step 2: Write the ArgoCD Application**

```yaml
# infra/argocd/apps/kind/app-otel-collector.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: otel-collector
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
spec:
  project: openlex-kind
  sources:
    - repoURL: https://open-telemetry.github.io/opentelemetry-helm-charts
      chart: opentelemetry-collector
      targetRevision: "0.165.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/otel-collector/values-base.yaml
        valuesObject:
          resources:
            requests: { cpu: 25m, memory: 64Mi }
            limits: { cpu: 200m, memory: 256Mi }
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 3: Apply and wait for it to sync**

Run:
```bash
kubectl apply -f infra/argocd/apps/kind/app-otel-collector.yaml
kubectl wait --for=jsonpath='{.status.health.status}'=Healthy application/otel-collector -n argocd --timeout=180s
kubectl get pods -n observability -l app.kubernetes.io/name=opentelemetry-collector
```
Expected: the wait condition is met and the pod is `Running`/`1/1 Ready`.

- [ ] **Step 4: Send a manual test span through the pipeline (proves it before any app code changes)**

Run:
```bash
kubectl run otlp-test --rm -it --image=curlimages/curl --restart=Never -n observability -- \
  curl -s -X POST http://otel-collector-opentelemetry-collector.observability.svc.cluster.local:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"manual-test"}}]},"scopeSpans":[{"spans":[{"traceId":"5b8aa5a2d2c872e8321cf37308d69df2","spanId":"051581bf3cb55c13","name":"manual-verification-span","startTimeUnixNano":"1700000000000000000","endTimeUnixNano":"1700000001000000000"}]}]}]}'
kubectl logs -n observability -l app.kubernetes.io/name=opentelemetry-collector --tail=50 | grep -i "manual-verification-span"
```
Expected: the `debug` exporter's log output includes `manual-verification-span` — proof the
OTLP HTTP receiver → batch processor → debug exporter pipeline actually works end-to-end.

- [ ] **Step 5: Commit**

```bash
git add infra/monitoring/otel-collector/values-base.yaml infra/argocd/apps/kind/app-otel-collector.yaml
git commit -m "Deploy OpenTelemetry Collector to kind via ArgoCD (observability Phase 1)"
```

---

### Task 5: Wire the existing `openlex-api` `/metrics` endpoint into Prometheus

**Files:**
- Create: `infra/kubernetes/overlays/kind/servicemonitor-openlex-api.yaml`
- Modify: `infra/kubernetes/overlays/kind/kustomization.yaml`

**Interfaces:**
- Consumes: `openlex-api` Service (`infra/kubernetes/base/api/service.yaml` — labels
  `app.kubernetes.io/name: openlex-api`, port named `http`), Prometheus's cluster-wide
  `ServiceMonitor` selection from Task 3.
- Produces: the `openlex_query_requests_total`/`openlex_query_quota_exceeded_total` counters
  (already implemented in `apps/api/src/openlex_api/quota.py`, exposed at `/metrics` since
  the Phase 1 tier-quota work) become visible in Prometheus/Grafana for the first time.

**Why this file lives in the kind overlay, not `base/api`:** `base/api` is shared with the
`eks-demo` overlay, which has no `ServiceMonitor` CRD installed (kube-prometheus-stack isn't
deployed there — see the design's consistency section). Adding a `ServiceMonitor` resource
to a shared base file would break `eks-demo`'s sync (`no matches for kind "ServiceMonitor"`)
if that cluster is ever live. It's an overlay-only resource until `eks-demo` opts in.

- [ ] **Step 1: Write the ServiceMonitor**

```yaml
# infra/kubernetes/overlays/kind/servicemonitor-openlex-api.yaml
#
# kind-only: base/api is shared with the eks-demo overlay, which has no ServiceMonitor CRD
# installed. See Task 5 of docs/superpowers/plans/2026-07-12-observability-phase1-infra-plumbing.md.
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: openlex-api
  labels:
    app.kubernetes.io/name: openlex-api
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: openlex-api
  endpoints:
    - port: http
      path: /metrics
      interval: 15s
```

- [ ] **Step 2: Add it to the kind overlay's kustomization**

Modify `infra/kubernetes/overlays/kind/kustomization.yaml` — add to `resources:`:

```yaml
resources:
  - ../../base/postgres
  - ../../base/api
  - ../../base/worker
  - servicemonitor-openlex-api.yaml
```

- [ ] **Step 3: Validate the kustomization builds**

Run: `kubectl kustomize --load-restrictor=LoadRestrictionsNone infra/kubernetes/overlays/kind | grep -A5 "kind: ServiceMonitor"`
Expected: the `ServiceMonitor` manifest appears in the rendered output.

- [ ] **Step 4: Let ArgoCD's existing `openlex` Application pick it up (or sync manually)**

Run:
```bash
kubectl get application openlex -n argocd -o jsonpath='{.status.sync.status}'
# If not "Synced" after a minute, force a refresh:
kubectl patch application openlex -n argocd --type merge -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"hard"}}}'
kubectl get servicemonitor -n openlex
```
Expected: `openlex-api` `ServiceMonitor` exists in the `openlex` namespace.

- [ ] **Step 5: Confirm Prometheus actually scraped it**

Run:
```bash
kubectl port-forward -n observability svc/kube-prometheus-stack-prometheus 9090:9090 &
sleep 3
curl -s 'http://localhost:9090/api/v1/query?query=up{job="openlex-api"}' | python3 -m json.tool
kill %1
```
Expected: `"value": ["<timestamp>", "1"]` — Prometheus has the target `up`.

- [ ] **Step 6: Commit**

```bash
git add infra/kubernetes/overlays/kind/servicemonitor-openlex-api.yaml infra/kubernetes/overlays/kind/kustomization.yaml
git commit -m "Wire openlex-api /metrics into Prometheus scraping on kind"
```

---

### Task 6: Add the multi-service port-forward helper script

**Files:**
- Create: `scripts/observability-port-forward.sh`

**Interfaces:**
- Consumes: the `observability` namespace Services created by Tasks 3–4.
- Produces: a single command replacing five separate `kubectl port-forward` terminals.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Port-forwards every observability UI/endpoint at once — kind has no ingress (see
# infra/kubernetes/README.md), so this replaces juggling five separate `kubectl
# port-forward` terminals. Ctrl-C kills all of them (trap below).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NAMESPACE="observability"

pids=()
cleanup() {
  echo
  echo "Stopping port-forwards..."
  for pid in "${pids[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

kubectl port-forward -n "${NAMESPACE}" svc/kube-prometheus-stack-grafana 3000:80 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/kube-prometheus-stack-prometheus 9090:9090 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/kube-prometheus-stack-alertmanager 9093:9093 &
pids+=($!)
kubectl port-forward -n "${NAMESPACE}" svc/otel-collector-opentelemetry-collector 4318:4318 &
pids+=($!)

echo "Grafana:      http://localhost:3000  (admin password: kubectl -n ${NAMESPACE} get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d)"
echo "Prometheus:   http://localhost:9090"
echo "Alertmanager: http://localhost:9093"
echo "OTLP/HTTP:    http://localhost:4318  (for browser tracing in a later phase)"
echo
echo "Press Ctrl-C to stop all port-forwards."
wait
```

- [ ] **Step 2: Make it executable and smoke-test it**

Run:
```bash
chmod +x scripts/observability-port-forward.sh
scripts/observability-port-forward.sh &
sleep 5
curl -s -o /dev/null -w "Grafana: %{http_code}\n" http://localhost:3000/login
curl -s -o /dev/null -w "Prometheus: %{http_code}\n" http://localhost:9090/graph
kill %1
```
Expected: both return `200`.

- [ ] **Step 3: Commit**

```bash
git add scripts/observability-port-forward.sh
git commit -m "Add scripts/observability-port-forward.sh for the observability stack"
```

---

### Task 7: Manual end-to-end verification pass and roadmap/checklist update

**Files:**
- Modify: `docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md`

**Interfaces:** none — this is a verification + bookkeeping task, no new production code.

- [ ] **Step 1: Log into Grafana and confirm stock dashboards render real data**

Run: `scripts/observability-port-forward.sh` (leave running), then open
`http://localhost:3000`, log in with `admin` / the password from the script's own output,
and open the bundled "Kubernetes / Compute Resources / Namespace (Pods)" dashboard.
Expected: non-zero CPU/memory graphs for the `observability` and `openlex` namespaces — this
is the kube-state-metrics/node-exporter data flowing for real, not a placeholder.

- [ ] **Step 2: Confirm the quota counters exist in Prometheus (values may be 0 — no real
  traffic yet — but the series must exist)**

Run (with the port-forward still up):
```bash
curl -s 'http://localhost:9090/api/v1/query?query=openlex_query_requests_total' | python3 -m json.tool
```
Expected: a `result` array is present (may be empty of samples if no `/query` calls have
happened yet, but the metric name must be recognized — cross-check with
`curl -s 'http://localhost:9090/api/v1/label/__name__/values' | grep openlex_query`).

- [ ] **Step 3: Update the flat checklist to reflect the new plan**

Modify `docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md`, replacing the Phase 3
block:

```markdown
## Phase 3 — Production observability 🔴 blocker (superseded by expanded design)
See `docs/superpowers/specs/2026-07-12-production-observability-design.md` (approved) and
its per-phase implementation plans under `docs/superpowers/plans/2026-07-12-observability-phase*.md`.
- [x] 3.3 `/metrics` endpoint exposed (done in the original Phase 1 tier-quota work)
- [ ] 3.2 Error tracking (Sentry or equivalent) — still explicitly out of scope; separate
      cost/compliance decision, not part of the observability design
- [x] 3.7 Observability Phase 1: kube-prometheus-stack + OTel Collector infra plumbing on kind
- [ ] 3.8 Observability Phase 2: `apps/api` backend tracing (Tempo + Jaeger dual-export)
- [ ] 3.9 Observability Phase 3: `apps/worker` + `postgres_exporter`
- [ ] 3.10 Observability Phase 4: `apps/web` browser tracing
- [ ] 3.11 Observability Phase 5: Loki logs + dashboards + Alertmanager rules
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md
git commit -m "Mark observability Phase 1 (infra plumbing) complete in the GA checklist"
```

---

## Checkpoint: Phase 1 complete

- [ ] `kubectl get application -n argocd` shows `kube-prometheus-stack` and `otel-collector`
  both `Synced`/`Healthy`
- [ ] Grafana reachable via `scripts/observability-port-forward.sh`, stock dashboards render
  non-zero data
- [ ] Prometheus target `up{job="openlex-api"}` returns `1`
- [ ] Manual OTLP test span appears in the Collector's `debug` exporter log output
- [ ] `docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md` reflects the new
  per-phase breakdown

Phase 2 (backend instrumentation — `apps/api` traces/logs, Tempo + Jaeger deployed and
wired) gets its own detailed plan written immediately before it starts, per the roadmap's
incremental-planning convention — not front-loaded here.
