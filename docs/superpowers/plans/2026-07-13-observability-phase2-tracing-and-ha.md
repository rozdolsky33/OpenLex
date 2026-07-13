# Observability Phase 2: Tracing (Tempo + Jaeger), Infra Node Placement, Dashboards, HA Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining gaps identified after the multi-node follow-up landed: ArgoCD
itself was scheduling onto the "apps" nodes (mixed in with the workloads it's supposed to be
separate from, since it predates the node-taint scheme), and the tracing backends (Tempo +
Jaeger), Grafana dashboards, and a real HA validation from the original 5-phase observability
design were still missing. This plan: extends the dedicated node's tolerations to cover ArgoCD
too, deploys Tempo (primary) and Jaeger (comparison) as dual trace backends with the OTel
Collector exporting to both, wires them into Grafana as datasources, adds two initial
dashboards using data that already exists, and proves the HA setup (2-replica anti-affinity +
PodDisruptionBudget) survives an actual node drain.

**Architecture:** Same pattern established in the prior two observability passes — Helm charts
deployed via ArgoCD Applications with a shared `values-base.yaml` (environment-agnostic) plus
a per-environment `valuesObject` (node placement, resource sizing). Tempo runs single-binary
mode with local storage; Jaeger (the modern v2-architecture chart, which unifies
collector+query+storage into one process) runs with an in-memory storage backend — both
match the design doc's "comparison-and-learning setup on kind, not production-shaped"
philosophy. The OTel Collector's traces pipeline gains two real exporters (`otlp/tempo`,
`otlp/jaeger`) alongside its existing metrics/logs `debug` exporters (Loki/real metrics
backends are still a later phase).

**Tech Stack:** `grafana/tempo` Helm chart (pin `1.24.*`), `jaegertracing/jaeger` Helm chart
(pin `4.11.*`, Jaeger v2 architecture), Grafana `additionalDataSources`, `kubectl drain`/
`cordon`/`uncordon` for the chaos test.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-12-production-observability-design.md`
  (Phase 2 of its phased rollout — dual Tempo/Jaeger backends — and part of Phase 5 —
  dashboards).
- Node-placement config (`nodeSelector`/`tolerations`) is kind-specific — goes in each
  component's own Application `valuesObject` (or ArgoCD's own Helm values file for ArgoCD
  itself), never in shared `values-base.yaml` files.
- Verify every Helm values key against the actual chart (`helm show values <chart> --version
  <pin>`) before using it — do not assume a key exists from memory or from another chart's
  convention. This bit twice already in this project's history (kube-prometheus-stack's
  `serviceMonitorSelectorNilUsesHelmValues` gotcha, and the OTel Collector chart's
  `image.repository` requirement).
- All Helm values pin `resources.requests`/`limits` explicitly — no chart defaults. A prior
  pass caught and fixed several chart-managed sidecars left unbounded; don't reintroduce that.
- Nothing is "done" without a real command's output confirming it — especially node placement
  and the chaos test, which must show actual `kubectl get pods -o wide` output, not assumed
  behavior.
- The live kind cluster (`kind-openlex` context) already has the prior two observability
  passes applied directly (not yet merged to `main` — ArgoCD's `syncPolicy.automated` is
  currently paused on `root-kind`/`openlex`/`kube-prometheus-stack`/`otel-collector` for that
  reason). Continue using direct `helm upgrade --install` / `kubectl apply` against local
  files for live verification in this plan too, and pause automation on any *new* Application
  this plan creates (Tempo, Jaeger) for the same reason — do not let selfHeal fight local
  verification.

---

### Task 1: Extend ArgoCD's own components onto the dedicated observability node

**Files:**
- Modify: `infra/argocd/install/argocd-values-kind.yaml`

**Interfaces:**
- Consumes: the `openlex.dev/workload: observability` node label + taint already established
  (kind-config.yaml, from the prior multi-node follow-up plan).
- Produces: every ArgoCD component (`server`, `repoServer`, `controller`, `redis`, `dex`)
  scheduled onto the same dedicated node as the observability stack — no live cluster
  recreation needed, since this only changes where already-running ArgoCD pods land, not the
  node topology itself.

**Why this doesn't need a cluster recreation:** the node label/taint (`openlex.dev/workload:
observability`) already exists from the prior plan. This task only adds matching
`nodeSelector`/`tolerations` to ArgoCD's own Helm values and re-applies via `helm upgrade`
against the *existing* nodes — a live, in-place change, not a topology change.

- [ ] **Step 1: Verify the exact values keys before using them**

Run:
```bash
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null
helm repo update argo
helm show values argo/argo-cd --version "8.*" | grep -B2 -A3 "nodeSelector\|tolerations" | head -150
```
Confirm `server.nodeSelector`/`.tolerations`, `repoServer.nodeSelector`/`.tolerations`,
`controller.nodeSelector`/`.tolerations`, `redis.nodeSelector`/`.tolerations`, and
`dex.nodeSelector`/`.tolerations` (or whatever the actual key path is — dex might be nested
under a different top-level key name in this chart version, e.g. `dex.nodeSelector` vs
`configs.dex...` — check against the real output) all exist. Use the currently-installed
ArgoCD chart version if pinning matters here — check what version is actually running:
`helm list -n argocd --kube-context kind-openlex` — and use that same major version range for
this verification, not a guessed pin.

- [ ] **Step 2: Add nodeSelector/tolerations to each component**

Add (using whatever the verified real key paths are from Step 1) to
`infra/argocd/install/argocd-values-kind.yaml`, for `server`, `repoServer`, `controller`,
`redis`, and `dex`:

```yaml
nodeSelector:
  openlex.dev/workload: observability
tolerations:
  - key: openlex.dev/workload
    operator: Equal
    value: observability
    effect: NoSchedule
```

Add this as sibling keys alongside each component's existing `resources:` block (do not
remove or alter the existing resource values from the prior ArgoCD OOM fix).

- [ ] **Step 3: Apply live and verify placement**

Run:
```bash
helm upgrade argocd argo/argo-cd -n argocd -f infra/argocd/install/argocd-values-kind.yaml --kube-context kind-openlex
```
Then wait for the rollout and confirm every ArgoCD pod is now on the `observability`-labeled
node:
```bash
kubectl --context kind-openlex get pods -n argocd -o wide
```
Expected: every pod's `NODE` column shows the same node that's labeled
`openlex.dev/workload=observability` (find that node name via `kubectl --context kind-openlex
get nodes -l openlex.dev/workload=observability`). If any pod doesn't move on its own (some
components, like a StatefulSet-backed one, may need a manual pod delete to pick up the new
scheduling constraints the same way the application-controller needed a manual delete for its
resource bump earlier) — delete it and confirm it reschedules correctly.

- [ ] **Step 4: Confirm ArgoCD itself is still healthy and functional after the move**

Run: `kubectl --context kind-openlex get application -n argocd` — confirm no new errors
introduced by the move (existing `OutOfSync`/pre-merge states from before this task are
expected and unrelated, per the Global Constraints note above).

- [ ] **Step 5: Commit**

```bash
git add infra/argocd/install/argocd-values-kind.yaml
git commit -m "Schedule ArgoCD components onto the dedicated observability node"
```

---

### Task 2: Deploy Tempo (primary trace backend)

**Files:**
- Create: `infra/monitoring/tempo/values-base.yaml`
- Create: `infra/argocd/apps/kind/app-tempo.yaml`

**Interfaces:**
- Produces: a Tempo instance reachable in-cluster (exact Service name/port to be confirmed via
  `kubectl get svc` after deploy — likely something like
  `tempo.observability.svc.cluster.local:4317` for its own OTLP receiver, or a distinct
  ingest/distributor port depending on whether the chart runs single-binary or
  microservices mode — verify, don't assume). Task 4 (OTel Collector dual export) depends on
  knowing this exact endpoint.

- [ ] **Step 1: Verify the chart's deployment mode and values schema**

Run:
```bash
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo update grafana
helm show values grafana/tempo --version "1.24.*" | head -100
```
Confirm this chart defaults to single-binary mode (matching the design doc's "comparison-and-
learning setup, not production-shaped" — do not opt into the distributed/microservices mode).
Identify the values keys for: local storage backend (should default to local filesystem, not
requiring S3/GCS), `resources`, `nodeSelector`, `tolerations`, and the receiver ports it
exposes (should include an OTLP gRPC/HTTP receiver by default, since that's what the Collector
will send to).

- [ ] **Step 2: Write the shared values-base file**

The `grafana/tempo` chart (distinct from `grafana/tempo-distributed`) is single-binary by
design — its own chart description is literally "Grafana Tempo Single Binary Mode", so no
special config is needed to opt into that mode; it's the only mode this chart offers. Start
from this and adjust only if Step 1's verification shows a materially different default
schema for the pinned version:

```yaml
# infra/monitoring/tempo/values-base.yaml
#
# Shared base values for Tempo, consumed by both the kind Application and any future
# eks-demo Application. This chart (grafana/tempo, not grafana/tempo-distributed) is
# single-binary by design — no config needed to select that mode. Local filesystem storage
# (the chart default) — this is a comparison-and-learning setup on kind (see the design doc),
# not a production-shaped deployment with S3/GCS-backed storage.
#
# Verified against `helm show values grafana/tempo --version 1.24.*` (Step 1): the chart's
# `traces:` block enables an `otlp` receiver (both grpc and http protocols) by default — this
# is confirmed present without any override.
traces:
  otlp:
    grpc:
      enabled: true
    http:
      enabled: true

storage:
  trace:
    backend: local
```

(If Step 1's verification of the *actually pinned* chart version shows these default values
already match — i.e. this file ends up being a no-op confirmation rather than a real
override — that's fine and expected; the point is confirming the defaults are what we want,
not necessarily changing them. If the real schema differs from this sketch, use the verified
real keys instead — do not force this exact shape onto a schema that doesn't match.)

- [ ] **Step 3: Write the ArgoCD Application**

```yaml
# infra/argocd/apps/kind/app-tempo.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tempo
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-kind
  sources:
    - repoURL: https://grafana.github.io/helm-charts
      chart: tempo
      targetRevision: "1.24.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/tempo/values-base.yaml
        valuesObject:
          nodeSelector:
            openlex.dev/workload: observability
          tolerations:
            - key: openlex.dev/workload
              operator: Equal
              value: observability
              effect: NoSchedule
          resources:
            requests: { cpu: 50m, memory: 128Mi }
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

(Adjust the `resources` values if Step 1's verification shows Tempo needs more/less headroom
than this starting guess — confirm empirically via `kubectl top` if available, or by watching
for OOMKilled the way prior tasks in this project have.)

- [ ] **Step 4: Deploy live via direct helm (ArgoCD tracks `main`, doesn't have this file yet)**

```bash
helm upgrade --install tempo grafana/tempo \
  --version "1.24.*" \
  --namespace observability --create-namespace \
  --kube-context kind-openlex \
  -f infra/monitoring/tempo/values-base.yaml \
  --set-json 'nodeSelector={"openlex.dev/workload":"observability"}' \
  --set-json 'tolerations=[{"key":"openlex.dev/workload","operator":"Equal","value":"observability","effect":"NoSchedule"}]' \
  --set-json 'resources={"requests":{"cpu":"50m","memory":"128Mi"},"limits":{"cpu":"200m","memory":"256Mi"}}'
```

Also apply the ArgoCD Application object itself (expect the same kind of `ComparisonError` the
prior two Applications show, for the same pre-merge reason — not a defect):
```bash
kubectl --context kind-openlex apply -f infra/argocd/apps/kind/app-tempo.yaml
```

- [ ] **Step 5: Verify it's running and find its real OTLP endpoint**

```bash
kubectl --context kind-openlex get pods -n observability -l app.kubernetes.io/name=tempo -o wide
kubectl --context kind-openlex get svc -n observability -l app.kubernetes.io/name=tempo
```
Expected: pod Running/Ready on the observability node; note the exact Service name and OTLP
port for Task 4.

- [ ] **Step 6: Commit**

```bash
git add infra/monitoring/tempo/values-base.yaml infra/argocd/apps/kind/app-tempo.yaml
git commit -m "Deploy Tempo (primary trace backend) to kind via ArgoCD"
```

---

### Task 3: Deploy Jaeger (comparison trace backend)

**Files:**
- Create: `infra/monitoring/jaeger/values-base.yaml`
- Create: `infra/argocd/apps/kind/app-jaeger.yaml`

**Interfaces:**
- Produces: a Jaeger instance reachable in-cluster with its own OTLP receiver and a Query UI.
  Task 4 depends on the exact OTLP endpoint; Task 5 depends on the exact Query UI Service
  name/port (for the Grafana Jaeger datasource).

**Important context:** the current `jaegertracing/jaeger` Helm chart (pin `4.11.*`) targets
Jaeger v2, which unifies the old v1 collector/query/agent components into a single process
built on OpenTelemetry Collector core. Its default storage backend is Elasticsearch (an
external dependency this project doesn't want) — it must be overridden to an in-memory backend
via the chart's `userconfig` key, which lets you supply Jaeger v2's native config directly
(receivers/exporters/extensions, similar shape to the OTel Collector's own config). Do not
deploy with the default Elasticsearch storage.

- [ ] **Step 1: Verify the chart's config schema for memory-backed storage**

Run:
```bash
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts >/dev/null
helm repo update jaegertracing
helm show values jaegertracing/jaeger --version "4.11.*" | sed -n '1,135p'
```
This shows a commented-out example `userconfig` block with `service.pipelines`,
`extensions.jaeger_query`, `extensions.jaeger_storage.backends`, `receivers.otlp`, and
`exporters.jaeger_storage_exporter`. Confirm Jaeger v2's memory storage backend syntax (look
at Jaeger v2's own documentation for the `jaeger_storage` extension's `memory:` backend type —
typically `memory: {max_traces: <N>}` under a named backend) and adapt the example's
Elasticsearch-backed `primary_store` to a memory-backed one instead. Also confirm the
top-level `jaeger.nodeSelector`/`jaeger.tolerations`/`jaeger.resources` keys (they exist as
direct siblings under the `jaeger:` top-level key, not nested further, per the chart's default
values.yaml layout — confirmed during planning, but re-verify against the pinned version).

- [ ] **Step 2: Write the shared values-base file**

Adapt the chart's own commented-out example (Step 1) by replacing its Elasticsearch-backed
`primary_store` with Jaeger v2's `memory` backend (documented in Jaeger v2's `jaeger_storage`
extension as `memory: {max_traces: <N>}`), and enabling `jaeger_query` for the UI:

```yaml
# infra/monitoring/jaeger/values-base.yaml
#
# Shared base values for Jaeger (v2 architecture — unifies collector+query+storage into one
# process). Comparison trace backend, run alongside Tempo (see the design doc) for capability
# comparison, not as the primary backend. Uses in-memory storage — no Elasticsearch dependency
# — matching the "comparison-and-learning, not production-shaped" scope of this pass. Data
# does not survive a pod restart — acceptable for a comparison/demo backend, not acceptable if
# this were ever the primary store.
# Environment-specific overrides (resources, node placement) live in the Application's own
# valuesObject, not here.
userconfig:
  service:
    extensions: [jaeger_storage, jaeger_query, healthcheckv2]
    pipelines:
      traces:
        receivers: [otlp]
        processors: [batch]
        exporters: [jaeger_storage_exporter]
    telemetry:
      resource:
        service.name: jaeger
  extensions:
    healthcheckv2:
      use_v2: true
      http:
        endpoint: 0.0.0.0:13133
    jaeger_query:
      base_path: /
      storage:
        traces: primary_store
    jaeger_storage:
      backends:
        primary_store:
          memory:
            max_traces: 100000
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318
  exporters:
    jaeger_storage_exporter:
      trace_storage: primary_store
```

(This is adapted from the chart's own documented example schema and Jaeger v2's documented
`memory` storage backend syntax — verify it actually works by deploying and confirming the
Query UI responds (Step 5 of this task), not just that Helm accepts the YAML. If the pinned
chart version's example differs from this in any field name, use the chart's actual verified
syntax instead of this sketch.)

- [ ] **Step 3: Write the ArgoCD Application**

```yaml
# infra/argocd/apps/kind/app-jaeger.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: jaeger
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-kind
  sources:
    - repoURL: https://jaegertracing.github.io/helm-charts
      chart: jaeger
      targetRevision: "4.11.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/jaeger/values-base.yaml
        valuesObject:
          jaeger:
            nodeSelector:
              openlex.dev/workload: observability
            tolerations:
              - key: openlex.dev/workload
                operator: Equal
                value: observability
                effect: NoSchedule
            resources:
              requests: { cpu: 50m, memory: 128Mi }
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

- [ ] **Step 4: Deploy live via direct helm**

```bash
helm upgrade --install jaeger jaegertracing/jaeger \
  --version "4.11.*" \
  --namespace observability --create-namespace \
  --kube-context kind-openlex \
  -f infra/monitoring/jaeger/values-base.yaml \
  --set-json 'jaeger.nodeSelector={"openlex.dev/workload":"observability"}' \
  --set-json 'jaeger.tolerations=[{"key":"openlex.dev/workload","operator":"Equal","value":"observability","effect":"NoSchedule"}]' \
  --set-json 'jaeger.resources={"requests":{"cpu":"50m","memory":"128Mi"},"limits":{"cpu":"200m","memory":"256Mi"}}'
```

Also apply the ArgoCD Application object (expect the same pre-merge `ComparisonError` pattern):
```bash
kubectl --context kind-openlex apply -f infra/argocd/apps/kind/app-jaeger.yaml
```

- [ ] **Step 5: Verify it's running, healthy, and find its real endpoints**

```bash
kubectl --context kind-openlex get pods -n observability -l app.kubernetes.io/name=jaeger -o wide
kubectl --context kind-openlex get svc -n observability -l app.kubernetes.io/name=jaeger
```
Expected: pod Running/Ready on the observability node. Note the OTLP endpoint (for Task 4) and
the Query UI Service/port (for Task 5 — typically port 16686). Confirm the Query UI actually
responds: port-forward it and hit its health/readiness endpoint or root path, confirm a real
HTTP response (not a connection error) — this is your evidence the memory storage backend
config from Step 1/2 actually works, not just that Helm accepted the YAML.

- [ ] **Step 6: Commit**

```bash
git add infra/monitoring/jaeger/values-base.yaml infra/argocd/apps/kind/app-jaeger.yaml
git commit -m "Deploy Jaeger (comparison trace backend) to kind via ArgoCD"
```

---

### Task 4: Wire the OTel Collector's traces pipeline to export to both Tempo and Jaeger

**Files:**
- Modify: `infra/monitoring/otel-collector/values-base.yaml`

**Interfaces:**
- Consumes: Tempo's OTLP endpoint (Task 2) and Jaeger's OTLP endpoint (Task 3).
- Produces: the Collector's `traces` pipeline now has two real exporters instead of just
  `debug` — the actual comparison the design doc asked for (one test span, visible in both
  backends).

- [ ] **Step 1: Read the current file and confirm the exact Tempo/Jaeger OTLP Service DNS
  names** (from Tasks 2/3's verification — don't re-derive, use what was actually confirmed
  live)

- [ ] **Step 2: Add two OTLP exporters and wire them into the traces pipeline**

Edit `infra/monitoring/otel-collector/values-base.yaml`'s `config` block — add to
`exporters:`:

```yaml
    otlp/tempo:
      endpoint: <tempo-service-dns-from-task-2>:4317
      tls:
        insecure: true
    otlp/jaeger:
      endpoint: <jaeger-service-dns-from-task-3>:4317
      tls:
        insecure: true
```

And change the `traces` pipeline's `exporters:` list from `[debug]` to
`[otlp/tempo, otlp/jaeger]` (drop `debug` for traces now that real backends exist — this
project's other two pipelines, `metrics`/`logs`, keep `debug` since Loki/a real metrics
backend for OTel-sourced data are still later phases; this task only changes `traces`).

- [ ] **Step 3: Apply live and re-run the manual OTLP test span from the original Phase 1 verification**

```bash
helm upgrade otel-collector open-telemetry/opentelemetry-collector \
  --version "0.165.*" \
  --namespace observability \
  --kube-context kind-openlex \
  -f infra/monitoring/otel-collector/values-base.yaml \
  -f /tmp/otel-followup-values.yaml
```

(Reuse the same `nodeSelector`/`tolerations`/`resources` override file from the prior pass, or
recreate it if it's gone — check `/tmp/otel-followup-values.yaml` first.)

Then send a real test span (same shape as Phase 1's original verification) and confirm it
lands in **both** backends:

```bash
kubectl --context kind-openlex run otlp-test --rm -i --image=curlimages/curl --restart=Never -n observability -- \
  curl -s -X POST http://otel-collector-opentelemetry-collector.observability.svc.cluster.local:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{"resourceSpans":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"tempo-jaeger-comparison-test"}}]},"scopeSpans":[{"spans":[{"traceId":"6c9bb6b3e3d883f9432e4842419e7ae3","spanId":"162692c04d666d24","name":"comparison-verification-span","startTimeUnixNano":"1700000000000000000","endTimeUnixNano":"1700000001000000000"}]}]}]}'
```

Then query Tempo's own API for this trace ID (Tempo has a `GET /api/traces/{traceID}` or
similar HTTP query endpoint — confirm the exact path against the chart's exposed ports) and
separately query Jaeger's Query API/UI for the same trace ID (`service=tempo-jaeger-
comparison-test` should show `comparison-verification-span`). Both must show the same trace —
that's the actual proof this task works, not just that the Collector didn't error.

- [ ] **Step 4: Commit**

```bash
git add infra/monitoring/otel-collector/values-base.yaml
git commit -m "Export OTel Collector traces to both Tempo and Jaeger"
```

---

### Task 5: Add Tempo and Jaeger as Grafana datasources

**Files:**
- Modify: `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml`

**Interfaces:**
- Consumes: Tempo's query endpoint and Jaeger's Query UI endpoint (Tasks 2/3).
- Produces: both trace backends browsable from within Grafana's Explore view, completing the
  "single pane of glass" goal from the original design doc.

- [ ] **Step 1: Verify the Grafana values key for static datasources**

Run: `helm show values prometheus-community/kube-prometheus-stack --version "87.15.*" | grep -B2 -A15 "additionalDataSources"`
Confirm the exact schema (typically a list of objects with `name`/`type`/`url`/`access`
fields).

- [ ] **Step 2: Add the two datasources to the Application's valuesObject**

Add to `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml`'s existing `grafana:` block
(alongside the existing `resources`/`nodeSelector`/`tolerations` from the prior pass):

```yaml
          grafana:
            # ... existing nodeSelector/tolerations/resources from the prior pass, unchanged
            additionalDataSources:
              - name: Tempo
                type: tempo
                access: proxy
                url: http://<tempo-service-dns-from-task-2>:<tempo-query-port>
                isDefault: false
              - name: Jaeger
                type: jaeger
                access: proxy
                url: http://<jaeger-query-service-dns-from-task-3>:16686
                isDefault: false
```

(Fill in the real Tempo query port from Task 2's verification — Tempo's query API typically
runs on a different port than its OTLP receiver, confirm which.)

- [ ] **Step 3: Apply live and verify both datasources work in Grafana**

Re-run the `helm upgrade` for kube-prometheus-stack with the updated values (same command
family as the prior pass), then confirm via Grafana's own API:

```bash
kubectl --context kind-openlex port-forward -n observability svc/kube-prometheus-stack-grafana 3000:80 &
PF_PID=$!
sleep 3
GRAFANA_PASS=$(kubectl --context kind-openlex get secret kube-prometheus-stack-grafana -n observability -o jsonpath='{.data.admin-password}' | base64 -d)
curl -s -u "admin:${GRAFANA_PASS}" http://localhost:3000/api/datasources | python3 -m json.tool
kill $PF_PID
```

Expected: both `Tempo` and `Jaeger` datasources present, and each shows a working connection
(Grafana's datasource health check — authenticate the same way as the `curl` call above and
hit `/api/datasources/uid/<uid>/health` for each datasource's uid, confirm `"status": "OK"` or
equivalent, not an error).

- [ ] **Step 4: Commit**

```bash
git add infra/argocd/apps/kind/app-kube-prometheus-stack.yaml
git commit -m "Add Tempo and Jaeger as Grafana datasources"
```

---

### Task 6: Add two initial Grafana dashboards using data that already exists

**Files:**
- Create: `infra/monitoring/grafana/dashboards/golden-signals-api.json`
- Create: `infra/monitoring/grafana/dashboards/tier-and-quota.json`
- Create: `infra/monitoring/grafana/dashboards/kustomization.yaml` (if this directory isn't
  already wired into the `app-observability-dashboards` Application from the original design —
  check whether that Application/kustomization path already exists; if not, this task creates
  it)

**Interfaces:**
- Consumes: `openlex_query_requests_total`/`openlex_query_quota_exceeded_total` (already
  scraped since Phase 1), `container_cpu_usage_seconds_total`/`container_memory_working_set_bytes`/
  HTTP request metrics from cAdvisor (already scraped via kube-state-metrics/node-exporter).
- Produces: two dashboards visible in Grafana, checked into the repo as JSON, auto-loaded via
  the existing `grafana_dashboard: "1"`-labeled ConfigMap sidecar mechanism (already enabled
  from Phase 1 — `grafana.sidecar.dashboards` in `values-base.yaml`).

**Scope note:** this is intentionally the first 2 of the 7 dashboards the original design doc
described, not the full set (Postgres and User Journey dashboards need `postgres_exporter` and
richer trace/span attributes respectively — both later phases). These two use data that's
already flowing today.

- [ ] **Step 1: Check whether a dashboards ConfigMap mechanism already exists**

Run: `ls infra/argocd/apps/kind/ | grep -i dashboard` and `find infra/monitoring/grafana -type f`.
If `app-observability-dashboards.yaml` and a `kustomization.yaml` under
`infra/monitoring/grafana/dashboards/` already exist (per the original design doc's Phase 1
plan mention — verify whether that specific piece was ever actually built, since the actual
Phase 1 implementation plan that shipped may not have included it), reuse that mechanism.
Otherwise, create:

```yaml
# infra/monitoring/grafana/dashboards/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

configMapGenerator:
  - name: openlex-grafana-dashboards
    files:
      - golden-signals-api.json
      - tier-and-quota.json
    options:
      labels:
        grafana_dashboard: "1"
```

And a matching `infra/argocd/apps/kind/app-observability-dashboards.yaml` Application pointing
at this kustomize path, destination namespace `observability`, `syncPolicy.automated` enabled.

- [ ] **Step 2: Write the Golden Signals — API dashboard**

Build `golden-signals-api.json` as a real Grafana dashboard JSON (export-format, not a
hand-typed guess) with 4 panels: request rate (traffic), error rate (errors), p50/p95/p99
latency (duration), and CPU/memory saturation for the `openlex-api` pods — using
`container_cpu_usage_seconds_total{namespace="openlex",pod=~"openlex-api-.*"}` and
`container_memory_working_set_bytes{namespace="openlex",pod=~"openlex-api-.*"}` for
saturation (already confirmed live and non-zero during the prior pass's verification). Traffic/
error/latency panels use whatever HTTP-level metrics are actually available today — check
`apps/api/src/openlex_api/main.py`'s `/metrics` endpoint and `quota.py`'s registered counters
first; if no request-duration histogram exists yet (the original design doc noted
`prometheus-fastapi-instrumentator` for that was never added), this dashboard's latency panel
should say so explicitly (a text panel noting "awaiting request-duration histogram — Phase 2
backend instrumentation") rather than silently showing an empty/misleading graph.

- [ ] **Step 3: Write the Tier & Quota dashboard**

Build `tier-and-quota.json` with panels for `openlex_query_requests_total` and
`openlex_query_quota_exceeded_total`, both broken down `by (tier)` — this data has been live
and confirmed non-zero (or at least present) since Phase 1.

- [ ] **Step 4: Apply and verify both dashboards render**

```bash
kubectl kustomize infra/monitoring/grafana/dashboards | kubectl --context kind-openlex apply -f -
```
Then confirm via Grafana's API (same auth pattern as Task 5):
```bash
curl -s -u "admin:${GRAFANA_PASS}" http://localhost:3000/api/search | python3 -m json.tool
```
Expected: both new dashboards listed. Open each (via the API's dashboard-by-uid endpoint, or
note for the user to check visually) and confirm at least the saturation and tier panels show
real non-zero data, not empty graphs.

- [ ] **Step 5: Commit**

```bash
git add infra/monitoring/grafana/dashboards/
git commit -m "Add Golden Signals (API) and Tier & Quota Grafana dashboards"
```

---

### Task 7: Prove the HA setup survives an actual node drain

**Files:** none (verification-only task, per the SRE skill's "test resilience" step)

**Interfaces:** none — this validates Task 3/4's HA work from the prior follow-up plan
(2-replica `openlex-api` + anti-affinity + PodDisruptionBudget).

- [ ] **Step 1: Confirm current state before the test**

```bash
kubectl --context kind-openlex get pods -n openlex -o wide
kubectl --context kind-openlex get pdb -n openlex
```
Record which node each `openlex-api` replica is on and the PDB's current `ALLOWED
DISRUPTIONS` value.

- [ ] **Step 2: Cordon and drain one of the two apps nodes**

```bash
APPS_NODE=$(kubectl --context kind-openlex get pods -n openlex -l app.kubernetes.io/name=openlex-api -o jsonpath='{.items[0].spec.nodeName}')
echo "Draining: ${APPS_NODE}"
kubectl --context kind-openlex cordon "${APPS_NODE}"
kubectl --context kind-openlex drain "${APPS_NODE}" --ignore-daemonsets --delete-emptydir-data --timeout=120s
```

- [ ] **Step 3: Confirm the PDB actually protected the deployment during the drain, and the
  service stayed up**

While the drain is running (or immediately after), confirm:
```bash
kubectl --context kind-openlex get pods -n openlex -o wide
```
Expected: at no point did `openlex-api` drop to 0 ready replicas — the PDB's `minAvailable: 1`
should have made `kubectl drain` wait for the evicted replica's replacement to be Ready
elsewhere before proceeding (drain respects PDBs by default). The evicted replica's Pod should
reschedule onto the *other* apps node (`nodeSelector` still applies) — confirm via the `NODE`
column. If the drained node happened to be running `openlex-worker`/`postgres` too, confirm
those rescheduled onto the remaining apps node as well (no PDB backs them, so some brief
disruption there is expected and fine — this task is specifically validating `openlex-api`'s
HA claim, not blanket zero-disruption for everything).

- [ ] **Step 4: Confirm the surviving/rescheduled replicas actually served traffic during the disruption**

```bash
kubectl --context kind-openlex port-forward -n openlex svc/openlex-api 18000:80 &
PF_PID=$!
sleep 3
curl -s http://localhost:18000/healthz
kill $PF_PID
```
Expected: `200`/healthy response, proving the Service kept routing to a working backend
throughout.

- [ ] **Step 5: Uncordon the node to restore normal scheduling**

```bash
kubectl --context kind-openlex uncordon "${APPS_NODE}"
```
Confirm: `kubectl --context kind-openlex get nodes` shows it `Ready` (not
`Ready,SchedulingDisabled`).

- [ ] **Step 6: Document the result**

No file changes needed for this task, but append a short summary to the eventual final report
(command outputs from Steps 2-5) — this is the concrete evidence the HA claim from the prior
plan is real, not just configured-and-hoped-for.

---

### Task 8: Deploy Loki (log aggregation)

**Files:**
- Create: `infra/monitoring/loki/values-base.yaml`
- Create: `infra/argocd/apps/kind/app-loki.yaml`

**Interfaces:**
- Produces: a Loki instance reachable in-cluster with a native OTLP log-ingestion endpoint
  (Loki 3.x+ supports this directly — confirmed via this chart's app version, 3.6.7). Task 9
  depends on this endpoint to ship logs into it, and on Loki's query endpoint for the Grafana
  datasource.

**Why Loki now, even though no app emits OTel-format logs yet:** `apps/api`/`apps/worker`
don't have OTel SDK logging instrumentation yet (that's backend-instrumentation, a later
phase). This task and Task 9 get log aggregation working today against what already exists —
every pod's stdout/stderr, including `apps/api`'s existing structured JSON quota-event logs
(`openlex_api.quota._log_quota_event`) — via a node-level log shipper (Task 9), not by waiting
for app-level OTel instrumentation.

- [ ] **Step 1: Verify the chart's deployment mode and values schema**

```bash
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo update grafana
helm show values grafana/loki --version "7.0.*" | head -100
```
Confirm the single-binary/monolithic deployment mode (this chart supports several deployment
topologies — `singleBinary`/monolithic is what we want, not the distributed
microservices mode, matching every other backend's "comparison-and-learning setup on kind, not
production-shaped" scope in this project). Identify the values keys for: single-binary mode
selection, local filesystem storage (not S3/GCS), `resources`, `nodeSelector`, `tolerations`.

- [ ] **Step 2: Write the shared values-base file**

```yaml
# infra/monitoring/loki/values-base.yaml
#
# Shared base values for Loki, consumed by both the kind Application and any future eks-demo
# Application. Single-binary/monolithic mode with local filesystem storage — comparison-and-
# learning setup on kind (see the design doc), not a production-shaped deployment with
# object-storage-backed chunks. Environment-specific overrides (resources, node placement)
# live in the Application's own valuesObject, not here.
#
# Fill in the real keys from Step 1's verification for: deployment mode = single-binary,
# storage backend = local filesystem (not S3/GCS/minio), and confirm native OTLP log
# ingestion is enabled by default for this chart/app version (3.6.7) — it should be, since
# Loki added native OTLP ingestion in 3.x without needing extra config, but verify the
# specific endpoint path (typically `/otlp/v1/logs`) against the actual chart's exposed
# ports/routes.
```

- [ ] **Step 3: Write the ArgoCD Application**

```yaml
# infra/argocd/apps/kind/app-loki.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: loki
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-kind
  sources:
    - repoURL: https://grafana.github.io/helm-charts
      chart: loki
      targetRevision: "7.0.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/loki/values-base.yaml
        valuesObject:
          nodeSelector:
            openlex.dev/workload: observability
          tolerations:
            - key: openlex.dev/workload
              operator: Equal
              value: observability
              effect: NoSchedule
          resources:
            requests: { cpu: 50m, memory: 128Mi }
            limits: { cpu: 200m, memory: 384Mi }
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

(Adjust `resources` from this starting guess if Step 1/deployment shows Loki needs more —
verify empirically, same practice as every other component in this project.)

- [ ] **Step 4: Deploy live and verify**

```bash
helm upgrade --install loki grafana/loki \
  --version "7.0.*" \
  --namespace observability --create-namespace \
  --kube-context kind-openlex \
  -f infra/monitoring/loki/values-base.yaml \
  --set-json 'nodeSelector={"openlex.dev/workload":"observability"}' \
  --set-json 'tolerations=[{"key":"openlex.dev/workload","operator":"Equal","value":"observability","effect":"NoSchedule"}]' \
  --set-json 'resources={"requests":{"cpu":"50m","memory":"128Mi"},"limits":{"cpu":"200m","memory":"384Mi"}}'
```

Apply the ArgoCD Application object too (expect the same pre-merge `ComparisonError` pattern
as every other Application this project has added since the original merge):
```bash
kubectl --context kind-openlex apply -f infra/argocd/apps/kind/app-loki.yaml
```

```bash
kubectl --context kind-openlex get pods -n observability -l app.kubernetes.io/name=loki -o wide
kubectl --context kind-openlex get svc -n observability -l app.kubernetes.io/name=loki
```
Expected: pod Running/Ready on the observability node; note the exact Service name and ports
(query API — typically 3100 — and, if separate, the OTLP ingestion port) for Task 9.

- [ ] **Step 5: Commit**

```bash
git add infra/monitoring/loki/values-base.yaml infra/argocd/apps/kind/app-loki.yaml
git commit -m "Deploy Loki (log aggregation) to kind via ArgoCD"
```

---

### Task 9: Ship pod logs to Loki via Promtail, add the Grafana datasource

**Files:**
- Create: `infra/monitoring/promtail/values-base.yaml`
- Create: `infra/argocd/apps/kind/app-promtail.yaml`
- Modify: `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml`

**Interfaces:**
- Consumes: Loki's endpoint from Task 8.
- Produces: every pod's stdout/stderr (including `apps/api`'s structured JSON quota-event
  logs) queryable in Grafana via a Loki datasource.

**Why Promtail, not the OTel Collector's own log-tailing:** the existing OTel Collector
Application runs in `mode: deployment` (a single pod, receiving pushed OTLP data — it was
never set up to tail node-local container log files). Promtail is the standard, well-
documented, single-purpose tool for exactly this job (a DaemonSet that tails
`/var/log/pods/*` on every node and ships to Loki) — adding this responsibility to the
existing Collector would mean reconfiguring it into DaemonSet mode for an unrelated reason.
Keep them separate, matching this project's existing "one focused component per job" pattern
(e.g., Tempo and Jaeger are separate deployments, not merged into one).

- [ ] **Step 1: Verify the chart's values schema and confirm Loki's ingestion endpoint**

```bash
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo update grafana
helm show values grafana/promtail --version "6.17.*" | grep -B2 -A10 "^config:\|clients:\|nodeSelector\|tolerations"
```
Confirm how to point Promtail's `clients` config at the Loki Service/port from Task 8
(typically Loki's push API, `http://<loki-service>.observability.svc.cluster.local:3100/loki/api/v1/push`).
Promtail is a DaemonSet by chart default — it must run on every node (including the
observability node, apps nodes, and the control-plane, to capture pod logs everywhere), so
unlike the other observability components in this project, it should NOT get a restrictive
`nodeSelector` — only a `toleration` for the observability taint (same reasoning as
`prometheus-node-exporter` in the kube-prometheus-stack task), so it isn't repelled from the
one node it would otherwise be blocked from.

- [ ] **Step 2: Write the shared values-base file**

```yaml
# infra/monitoring/promtail/values-base.yaml
#
# Shared base values for Promtail — ships every pod's stdout/stderr to Loki. DaemonSet by
# chart default; must run on every node including the tainted observability node (see the
# Application's tolerations, not a nodeSelector, since this needs to run everywhere).
# Environment-specific overrides (resources, the Loki endpoint it points at) live in the
# Application's own valuesObject, not here — fill in the real `config.clients[].url` schema
# from Step 1's verification, pointed at Loki's Service from Task 8.
```

- [ ] **Step 3: Write the ArgoCD Application**

```yaml
# infra/argocd/apps/kind/app-promtail.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: promtail
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-kind
  sources:
    - repoURL: https://grafana.github.io/helm-charts
      chart: promtail
      targetRevision: "6.17.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/promtail/values-base.yaml
        valuesObject:
          tolerations:
            - key: openlex.dev/workload
              operator: Equal
              value: observability
              effect: NoSchedule
          resources:
            requests: { cpu: 25m, memory: 64Mi }
            limits: { cpu: 100m, memory: 128Mi }
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

- [ ] **Step 4: Deploy live and confirm logs are actually flowing**

```bash
helm upgrade --install promtail grafana/promtail \
  --version "6.17.*" \
  --namespace observability --create-namespace \
  --kube-context kind-openlex \
  -f infra/monitoring/promtail/values-base.yaml \
  --set-json 'tolerations=[{"key":"openlex.dev/workload","operator":"Equal","value":"observability","effect":"NoSchedule"}]' \
  --set-json 'resources={"requests":{"cpu":"25m","memory":"64Mi"},"limits":{"cpu":"100m","memory":"128Mi"}}'
```

Confirm a Promtail pod is running on **every** node (all 4: control-plane + 3 workers):
```bash
kubectl --context kind-openlex get pods -n observability -l app.kubernetes.io/name=promtail -o wide
```

Then confirm logs actually landed in Loki by querying it directly (not just trusting Promtail
is running) — generate a real log line first, then query for it:
```bash
kubectl --context kind-openlex exec -n openlex deployment/openlex-worker -- uv run --frozen python -m openlex_worker ingest --source statutes >/dev/null 2>&1 &
sleep 5
kubectl --context kind-openlex port-forward -n observability svc/loki 3100:3100 &
PF_PID=$!
sleep 3
curl -sG "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={namespace="openlex"}' \
  --data-urlencode 'limit=5' | python3 -m json.tool | head -30
kill $PF_PID
```
Expected: real log lines from `openlex` namespace pods returned, not an empty result.

- [ ] **Step 5: Add Loki as a Grafana datasource**

Add to `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml`'s existing `grafana:` block
(alongside the `additionalDataSources` entries Task 5 already added for Tempo/Jaeger — append
to that same list, don't create a second list):

```yaml
              - name: Loki
                type: loki
                access: proxy
                url: http://loki.observability.svc.cluster.local:3100
                isDefault: false
```

Re-apply via the same `helm upgrade` command family used for kube-prometheus-stack throughout
this plan, then confirm via Grafana's datasource health-check API (same authenticated-`curl`
pattern established in Task 5) that the Loki datasource shows a healthy connection.

- [ ] **Step 6: Commit**

```bash
git add infra/monitoring/promtail/values-base.yaml infra/argocd/apps/kind/app-promtail.yaml infra/argocd/apps/kind/app-kube-prometheus-stack.yaml
git commit -m "Ship pod logs to Loki via Promtail; add Loki as a Grafana datasource"
```

---

### Task 10: Final verification pass and checklist update

**Files:**
- Modify: `docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md`

**Interfaces:** none.

- [ ] **Step 1: Confirm ArgoCD placement (Task 1), Tempo (Task 2), Jaeger (Task 3), the
  dual-export (Task 4), and Loki/Promtail (Tasks 8-9) are all still healthy after every other
  task's changes**

```bash
kubectl --context kind-openlex get pods -n argocd -n observability -n openlex -o wide
```
Expected: all pods `Running`/`Ready`, correct node placement per the design (ArgoCD +
observability stack + Tempo + Jaeger + Loki all on the `observability`-labeled node, Promtail
on all 4 nodes as a DaemonSet; `openlex-api`/`worker`/`postgres` on the two `apps`-labeled
nodes).

- [ ] **Step 2: Update the checklist**

Modify `docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md`'s observability section,
marking this phase's items complete (ArgoCD placement fix, Tempo, Jaeger, dual trace export,
Loki + Promtail log shipping, Grafana datasources, 2 initial dashboards, HA drain test) and
noting the remaining gaps explicitly (full 7-dashboard set, `postgres_exporter`, backend app
OTel instrumentation for traces/metrics/trace-correlated logs, Alertmanager rules) so the next
pass knows exactly what's left.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-07-12-ga-readiness-checklist.md
git commit -m "Mark observability tracing/HA follow-up complete in the GA checklist"
```

## Checkpoint: Phase 2 follow-up complete

- [ ] Every ArgoCD pod on the observability node, ArgoCD itself still healthy
- [ ] Tempo and Jaeger both running, both confirmed to receive and store the same test trace
- [ ] Loki running, Promtail running on all 4 nodes, a real log line confirmed queryable
- [ ] Grafana's Tempo, Jaeger, and Loki datasources all pass their health check
- [ ] Two new dashboards visible in Grafana with real (or explicitly-labeled-as-pending) data
- [ ] A real `kubectl drain` on an apps node did not drop `openlex-api` below 1 ready replica,
  and `/healthz` stayed reachable throughout
- [ ] Checklist doc reflects this pass's actual scope, not aspirational completeness
