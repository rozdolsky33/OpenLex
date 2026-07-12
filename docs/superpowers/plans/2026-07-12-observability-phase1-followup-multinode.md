# Observability Phase 1 Follow-up: Migrations Fix + 3-Node Kind Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two gaps flagged in the Phase 1 (infra plumbing) PR: (1) the kind cluster's
Postgres is missing every migration past `0001_init.sql`, so `/auth/login` 500s; (2) properly
build the 3-node kind topology a prior concurrent commit (`80b7977`, decoupled from the Phase 1
merge per its own final review) attempted — a dedicated, tainted node for the observability
stack and two nodes for app workloads — this time with the missing tolerations that made that
attempt's separation-of-concerns goal never actually take effect, plus a `PodDisruptionBudget`
for `openlex-api`'s HA story.

**Architecture:** `infra/kubernetes/kind/kind-config.yaml` grows to 1 control-plane + 3 workers
(one labeled+tainted `openlex.dev/workload=observability`, two labeled
`openlex.dev/workload=apps`). App workloads (`openlex-api`/`worker`/`postgres`) get a
`nodeSelector` onto the apps nodes, matching the previously-reviewed-sound design; `openlex-api`
also gets `replicas: 2` + preferred `podAntiAffinity` + a `PodDisruptionBudget`. The
observability stack (`kube-prometheus-stack`, OTel Collector) gets matching `nodeSelector` +
`tolerations` added to each ArgoCD Application's per-environment `valuesObject` (not the shared
`values-base.yaml` — node placement is kind-specific, per the design doc's kind/eks-demo
consistency section) so it actually lands on the dedicated node instead of being repelled by
the taint with nowhere else defined to go. Applying any of this requires deleting and
recreating the kind cluster (kind cannot add nodes to a running cluster) — approved as
acceptable since the destroyed data is dev/demo seed data only, and the plan's last task
re-seeds it.

**Tech Stack:** kind multi-node cluster config, Kubernetes `nodeSelector`/`tolerations`/
`podAntiAffinity`/`PodDisruptionBudget`, ArgoCD Application `valuesObject` overrides.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-12-production-observability-design.md`
  (kind/eks-demo consistency section governs where node-placement config lives).
- Node-placement config (`nodeSelector`/`tolerations`) is kind-specific — it goes in each
  ArgoCD Application's own `valuesObject`, never in the shared `infra/monitoring/*/values-base.yaml`
  files, which stay environment-agnostic.
- Postgres HA is explicitly out of scope (would need an operator — CloudNativePG/Patroni).
  This plan only keeps Postgres off the dedicated observability node, same as other app
  workloads — it remains single-instance.
- kind's multi-node topology is still one Docker daemon underneath — this proves out the
  scheduling/affinity/taint tooling and separation-of-concerns design, not genuine
  infrastructure-failure isolation. Say so in any user-facing description of this work.
- Nothing is "done" without a real command's output confirming it — especially node placement,
  which must be verified via `kubectl get pods -o wide` showing the right pods on the right
  nodes, not assumed from the YAML alone.
- Every new/changed Python file (none expected in this plan) would need
  `uv run ruff check .`/`uv run mypy` clean; this plan is YAML/shell only.

---

### Task 1: Fix the Postgres migrations gap

**Files:**
- Modify: `infra/kubernetes/base/postgres/kustomization.yaml`

**Interfaces:**
- Consumes: `migrations/postgres/{0001_init,0002_users,0003_conversations,0004_user_tiers,0005_conversation_ownership}.sql` (existing files).
- Produces: a `postgres-init-sql` ConfigMap containing all 5 migration files, mounted at
  `/docker-entrypoint-initdb.d` (the StatefulSet already mounts the whole ConfigMap as a
  directory — `infra/kubernetes/base/postgres/statefulset.yaml`'s `init-sql` volume — so this
  is a config-only fix, no StatefulSet changes needed). Postgres's own
  `docker-entrypoint-initdb.d` mechanism runs every `.sql` file in the directory in
  alphabetical order on first init against an *empty* data directory — the `000N_` filename
  prefixes already guarantee correct ordering.

**Why this was missed:** the ConfigMap generator only ever listed `0001_init.sql` — every
migration added since (users table, conversations, tier columns, conversation ownership) never
made it into the kind cluster's bootstrap, even though `docker-compose.yml` mounts the whole
`migrations/postgres/` directory and picks all of them up. This is why `/auth/login` 500s with
`UndefinedTableError: relation "users" does not exist` on kind specifically.

- [ ] **Step 1: Edit the file**

```yaml
# infra/kubernetes/base/postgres/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - statefulset.yaml
  - service.yaml

# Reuses the same schema files docker-compose.yml already mounts at
# /docker-entrypoint-initdb.d — no duplicated SQL. Kustomize's default load restrictor refuses
# to read generator files from outside the kustomization directory tree, so building this
# (directly, or transitively via an overlay) requires `--load-restrictor LoadRestrictionsNone`
# (`kubectl kustomize --load-restrictor=LoadRestrictionsNone ...` /
# `kustomize build --load-restrictor LoadRestrictionsNone ...`). ArgoCD is configured for this
# repo-wide via `kustomize.buildOptions` in infra/argocd/install/argocd-values-*.yaml, so this
# only matters for manual/local `kustomize build` validation. Hash-suffixed by default, so
# editing any of these files produces a new ConfigMap name and rolls the StatefulSet. Note:
# this only re-runs against an *empty* PGDATA (Postgres image behavior) — it does not re-seed
# an already-initialized volume. List every migration file, not just the first — a prior
# version of this list only had 0001_init.sql, silently skipping every later migration
# (users/conversations/tiers/conversation-ownership) on kind specifically.
configMapGenerator:
  - name: postgres-init-sql
    files:
      - 0001_init.sql=../../../../migrations/postgres/0001_init.sql
      - 0002_users.sql=../../../../migrations/postgres/0002_users.sql
      - 0003_conversations.sql=../../../../migrations/postgres/0003_conversations.sql
      - 0004_user_tiers.sql=../../../../migrations/postgres/0004_user_tiers.sql
      - 0005_conversation_ownership.sql=../../../../migrations/postgres/0005_conversation_ownership.sql
```

- [ ] **Step 2: Validate the kustomization builds and includes all 5 files**

Run: `kubectl kustomize --load-restrictor=LoadRestrictionsNone infra/kubernetes/base/postgres | grep -c "CREATE TABLE"`
Expected: at least 5 (one per migration file defining at least one table — cross-check the
actual count against `grep -c "CREATE TABLE" migrations/postgres/*.sql | awk -F: '{sum+=$2} END {print sum}'`
matches).

- [ ] **Step 3: Commit**

```bash
git add infra/kubernetes/base/postgres/kustomization.yaml
git commit -m "Include all Postgres migrations in kind's init ConfigMap, not just 0001"
```

**Note:** this fix only takes effect against a fresh (empty) PGDATA — it will not retroactively
fix the currently-running kind cluster's existing Postgres volume. Task 7 (cluster recreation)
is what actually applies it.

---

### Task 2: Add the 3-node kind cluster config

**Files:**
- Modify: `infra/kubernetes/kind/kind-config.yaml`

**Interfaces:**
- Produces: a kind cluster spec with 1 control-plane + 3 workers — one labeled+tainted
  `openlex.dev/workload=observability`, two labeled `openlex.dev/workload=apps`. Tasks 3-6
  depend on these exact label values existing on the recreated cluster's nodes.

This content was already written and reviewed once (in a prior commit, `80b7977`, on a branch
that was decoupled from the Phase 1 merge specifically because the *other* half of that
commit's work — matching tolerations for the observability stack — was never added, not
because this file itself had a problem). Reintroducing it here, unchanged, with the
tolerations gap closed by Tasks 5-6.

- [ ] **Step 1: Edit the file**

```yaml
# infra/kubernetes/kind/kind-config.yaml
# No ingress/TLS in kind (see infra/kubernetes/README.md) — access is via
# `kubectl port-forward`, so no extraPortMappings are needed for that.
#
# 1 control-plane + 3 workers, to mimic real separation-of-concerns topology instead of
# everything landing on one node: one worker is dedicated (labeled + tainted) to the
# observability stack (kube-prometheus-stack, later Tempo/Jaeger/Loki/OTel Collector), the
# other two are for application workloads (openlex-api/worker/postgres), which lets
# openlex-api run 2 replicas spread across real separate nodes via podAntiAffinity instead of
# a same-node anti-affinity that proves nothing. See infra/kubernetes/overlays/kind/
# patch-resources.yaml for the nodeSelector/affinity wiring on the apps side, and
# infra/argocd/apps/kind/{app-kube-prometheus-stack,app-otel-collector}.yaml's valuesObject
# for the matching nodeSelector/tolerations on the observability side.
#
# IMPORTANT: kind can't add nodes to a running cluster — changing this file requires
# `kind delete cluster --name openlex && scripts/kind-up.sh` (destructive: wipes all
# workloads, including Postgres data). Applying this is a deliberate, separate step (Task 7),
# not automatic on commit.
#
# Also worth being explicit about what this does NOT simulate: kind's "nodes" are containers
# on one Docker daemon/laptop, not separate hosts — there's no real network partition, zone,
# or hardware failure isolation between them. This demonstrates the scheduling/affinity/
# separation-of-concerns *design* and gets the real tooling (nodeSelector, taints,
# podAntiAffinity) exercised, not genuine infrastructure-failure HA.
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
    kubeadmConfigPatches:
      - |
        kind: JoinConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "openlex.dev/workload=observability"
          taints:
            - key: openlex.dev/workload
              value: observability
              effect: NoSchedule
  - role: worker
    kubeadmConfigPatches:
      - |
        kind: JoinConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "openlex.dev/workload=apps"
  - role: worker
    kubeadmConfigPatches:
      - |
        kind: JoinConfiguration
        nodeRegistration:
          kubeletExtraArgs:
            node-labels: "openlex.dev/workload=apps"
```

- [ ] **Step 2: Validate YAML syntax (read-only, no cluster impact yet)**

Run: `python3 -c "import yaml; yaml.safe_load(open('infra/kubernetes/kind/kind-config.yaml'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add infra/kubernetes/kind/kind-config.yaml
git commit -m "Add 3-node kind topology: dedicated observability node, 2 apps nodes"
```

---

### Task 3: Schedule app workloads onto the apps nodes, add HA for openlex-api

**Files:**
- Modify: `infra/kubernetes/overlays/kind/patch-resources.yaml`

**Interfaces:**
- Consumes: node labels from Task 2 (`openlex.dev/workload: apps`).
- Produces: `openlex-api` at `replicas: 2` with `nodeSelector`/`podAntiAffinity`;
  `openlex-worker`/`postgres` with the same `nodeSelector`. Task 4's `PodDisruptionBudget`
  targets the same `app.kubernetes.io/name: openlex-api` label selector this task's
  anti-affinity uses.

Same content as the prior reviewed-sound commit — this part of that earlier attempt had no
review findings against it.

- [ ] **Step 1: Edit the file** (adds to the existing `openlex-api`/`openlex-worker`/`postgres`
  patches already in this file from Phase 1 — insert the new fields shown below into each
  existing block, don't replace the whole file)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openlex-api
spec:
  # 2 replicas spread across the two `openlex.dev/workload=apps` nodes (see
  # infra/kubernetes/kind/kind-config.yaml) via the preferred podAntiAffinity below — real
  # separation from the dedicated observability node, and real (if kind-scale) HA instead of
  # both replicas landing on whatever node is free. See patch_resources.yaml Task 4's
  # PodDisruptionBudget for what backs this during voluntary disruptions.
  replicas: 2
  template:
    spec:
      nodeSelector:
        openlex.dev/workload: apps
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app.kubernetes.io/name: openlex-api
                topologyKey: kubernetes.io/hostname
      containers:
        - name: api
          # ... existing imagePullPolicy/resources/readinessProbe/livenessProbe from Phase 1
          # stay exactly as they are — only the fields above are new.
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openlex-worker
spec:
  template:
    spec:
      nodeSelector:
        openlex.dev/workload: apps
      containers:
        - name: worker
          # ... existing fields unchanged
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  # Single instance — real Postgres HA (streaming replicas, failover) would need an operator
  # (e.g. CloudNativePG/Patroni), out of scope here. This only keeps Postgres off the
  # dedicated observability node, same as the other app workloads.
  template:
    spec:
      nodeSelector:
        openlex.dev/workload: apps
  volumeClaimTemplates:
    # ... existing volumeClaimTemplates unchanged
```

- [ ] **Step 2: Validate the kustomization builds and the new fields render**

Run: `kubectl kustomize --load-restrictor=LoadRestrictionsNone infra/kubernetes/overlays/kind | grep -A3 "nodeSelector:"`
Expected: three `nodeSelector: openlex.dev/workload: apps` blocks (api, worker, postgres).

- [ ] **Step 3: Commit**

```bash
git add infra/kubernetes/overlays/kind/patch-resources.yaml
git commit -m "Schedule app workloads onto apps nodes; run openlex-api at 2 replicas with anti-affinity"
```

---

### Task 4: Add a PodDisruptionBudget for openlex-api

**Files:**
- Create: `infra/kubernetes/overlays/kind/pdb-openlex-api.yaml`
- Modify: `infra/kubernetes/overlays/kind/kustomization.yaml`

**Interfaces:**
- Consumes: `app.kubernetes.io/name: openlex-api` label (same selector Task 3's anti-affinity
  and the existing Service/Deployment already use).
- Produces: a `PodDisruptionBudget` ensuring at least 1 of the 2 `openlex-api` replicas stays
  available during voluntary disruptions (node drains, `kubectl evict`) — the actual
  HA-under-maintenance guarantee the 2-replica/anti-affinity setup exists to provide.

**Why this is kind-only** (like `servicemonitor-openlex-api.yaml` before it): `eks-demo` may
run `openlex-api` at a different replica count, and this PDB's `minAvailable: 1` assumption is
specific to this kind topology's 2-replica setup — not shared base behavior.

- [ ] **Step 1: Write the PodDisruptionBudget**

```yaml
# infra/kubernetes/overlays/kind/pdb-openlex-api.yaml
#
# kind-only: assumes the 2-replica setup from patch-resources.yaml. Ensures at least 1
# replica survives a voluntary disruption (node drain, kubectl evict) — this is what actually
# backs the "HA" claim of running 2 replicas with anti-affinity; without it, a node drain could
# legally evict both replicas at once.
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: openlex-api
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: openlex-api
```

- [ ] **Step 2: Add it to the kind overlay's kustomization**

Modify `infra/kubernetes/overlays/kind/kustomization.yaml` — add to `resources:`:

```yaml
resources:
  - ../../base/postgres
  - ../../base/api
  - ../../base/worker
  - servicemonitor-openlex-api.yaml
  - pdb-openlex-api.yaml
```

- [ ] **Step 3: Validate the kustomization builds**

Run: `kubectl kustomize --load-restrictor=LoadRestrictionsNone infra/kubernetes/overlays/kind | grep -A5 "kind: PodDisruptionBudget"`
Expected: the PDB manifest appears with `minAvailable: 1`.

- [ ] **Step 4: Commit**

```bash
git add infra/kubernetes/overlays/kind/pdb-openlex-api.yaml infra/kubernetes/overlays/kind/kustomization.yaml
git commit -m "Add PodDisruptionBudget for openlex-api's 2-replica HA setup"
```

---

### Task 5: Add tolerations + node placement for kube-prometheus-stack

**Files:**
- Modify: `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml`

**Interfaces:**
- Consumes: node labels/taint from Task 2.
- Produces: `prometheusOperator`, `prometheus.prometheusSpec`, `alertmanager.alertmanagerSpec`,
  `grafana`, and `kube-state-metrics` all scheduled onto the `openlex.dev/workload=observability`
  node; `prometheus-node-exporter` (a DaemonSet — must run on every node, including the
  observability one, to report that node's own metrics) gets only the toleration, no
  nodeSelector, so it's not restricted to a single node.

**This is the actual fix for the gap the final Phase 1 review found**: the taint alone repels
these pods with nowhere else defined to go if a nodeSelector were added without a matching
toleration (or, as happened before, if neither was added at all) — they'd just land on the apps
nodes instead, and the separation-of-concerns goal wouldn't materialize. Node placement is
kind-specific, so it goes in this Application's `valuesObject`, not the shared
`infra/monitoring/kube-prometheus-stack/values-base.yaml`.

**Important — do not duplicate `resources` here.** `prometheusOperator.resources` (25m/64Mi
request, 100m/128Mi limit) and `prometheusOperator.prometheusConfigReloader.resources` are
already set in the shared `values-base.yaml`. ArgoCD's Helm multi-source deep-merges
`valuesObject` over `valueFiles`, with `valuesObject` winning on any overlapping key — so
adding `prometheusOperator.resources` again here, with different numbers, would silently
override the shared file's already-correct values with new ones, not merge harmlessly. Add
only `nodeSelector`/`tolerations` under `prometheusOperator` below; leave `resources` alone.
The `resources` blocks shown below for `prometheus`/`alertmanager`/`grafana`/
`kube-state-metrics`/`prometheus-node-exporter` are unaffected by this — those already live
in this Application's `valuesObject` from Phase 1 (not the shared file), so adding
`nodeSelector`/`tolerations` alongside them is a normal same-object edit, not a duplication.

- [ ] **Step 1: Verify the exact values keys before using them** (don't assume — the pattern
  established by observability Phase 1 was to check every non-obvious Helm key against the
  actual chart, not guess)

Run:
```bash
helm repo update prometheus-community
helm show values prometheus-community/kube-prometheus-stack --version "87.15.*" | grep -B2 -A2 "nodeSelector\|tolerations" | head -100
```
Confirm `prometheusOperator.nodeSelector`/`.tolerations`,
`prometheus.prometheusSpec.nodeSelector`/`.tolerations`,
`alertmanager.alertmanagerSpec.nodeSelector`/`.tolerations`, `grafana.nodeSelector`/
`.tolerations`, `kube-state-metrics.nodeSelector`/`.tolerations`, and
`prometheus-node-exporter.tolerations` all exist as documented in this chart version. If any
key differs, use the real one instead.

- [ ] **Step 2: Add the fields to the Application's `valuesObject`**

```yaml
# infra/argocd/apps/kind/app-kube-prometheus-stack.yaml — add these keys into the existing
# valuesObject block (alongside the existing resources blocks from Phase 1), don't replace it
spec:
  sources:
    - repoURL: https://prometheus-community.github.io/helm-charts
      chart: kube-prometheus-stack
      targetRevision: "87.15.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/kube-prometheus-stack/values-base.yaml
        valuesObject:
          prometheusOperator:
            # nodeSelector/tolerations only — resources already live in the shared
            # values-base.yaml (25m/64Mi request, 100m/128Mi limit); do not repeat them here,
            # see the note above this YAML block.
            nodeSelector:
              openlex.dev/workload: observability
            tolerations:
              - key: openlex.dev/workload
                operator: Equal
                value: observability
                effect: NoSchedule
          prometheus:
            prometheusSpec:
              retention: 6h
              nodeSelector:
                openlex.dev/workload: observability
              tolerations:
                - key: openlex.dev/workload
                  operator: Equal
                  value: observability
                  effect: NoSchedule
              resources:
                requests: { cpu: 100m, memory: 400Mi }
                limits: { cpu: 500m, memory: 800Mi }
          alertmanager:
            alertmanagerSpec:
              nodeSelector:
                openlex.dev/workload: observability
              tolerations:
                - key: openlex.dev/workload
                  operator: Equal
                  value: observability
                  effect: NoSchedule
              resources:
                requests: { cpu: 10m, memory: 32Mi }
                limits: { cpu: 100m, memory: 64Mi }
          grafana:
            nodeSelector:
              openlex.dev/workload: observability
            tolerations:
              - key: openlex.dev/workload
                operator: Equal
                value: observability
                effect: NoSchedule
            resources:
              requests: { cpu: 25m, memory: 96Mi }
              limits: { cpu: 100m, memory: 192Mi }
          kube-state-metrics:
            nodeSelector:
              openlex.dev/workload: observability
            tolerations:
              - key: openlex.dev/workload
                operator: Equal
                value: observability
                effect: NoSchedule
            resources:
              requests: { cpu: 10m, memory: 32Mi }
              limits: { cpu: 50m, memory: 64Mi }
          prometheus-node-exporter:
            # DaemonSet — must run on every node (including the observability one, to report
            # its own metrics), so only the toleration, no nodeSelector restricting it.
            tolerations:
              - key: openlex.dev/workload
                operator: Equal
                value: observability
                effect: NoSchedule
            resources:
              requests: { cpu: 10m, memory: 24Mi }
              limits: { cpu: 50m, memory: 48Mi }
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
```

- [ ] **Step 3: Commit**

```bash
git add infra/argocd/apps/kind/app-kube-prometheus-stack.yaml
git commit -m "Schedule kube-prometheus-stack components onto the dedicated observability node"
```

---

### Task 6: Add tolerations + node placement for the OTel Collector

**Files:**
- Modify: `infra/argocd/apps/kind/app-otel-collector.yaml`

**Interfaces:**
- Consumes: node labels/taint from Task 2.
- Produces: the OTel Collector deployment scheduled onto the observability node, matching
  Task 5's placement for the rest of the observability stack.

- [ ] **Step 1: Verify the exact values keys**

Run: `helm show values open-telemetry/opentelemetry-collector --version "0.165.*" | grep -B2 -A2 "nodeSelector\|tolerations"`
Confirm top-level `nodeSelector`/`tolerations` keys exist for this chart in `mode: deployment`.

- [ ] **Step 2: Add the fields to the Application's `valuesObject`**

```yaml
# infra/argocd/apps/kind/app-otel-collector.yaml — add these keys into the existing
# valuesObject block, don't replace it
spec:
  sources:
    - repoURL: https://open-telemetry.github.io/opentelemetry-helm-charts
      chart: opentelemetry-collector
      targetRevision: "0.165.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/otel-collector/values-base.yaml
        valuesObject:
          nodeSelector:
            openlex.dev/workload: observability
          tolerations:
            - key: openlex.dev/workload
              operator: Equal
              value: observability
              effect: NoSchedule
          resources:
            requests: { cpu: 25m, memory: 64Mi }
            limits: { cpu: 200m, memory: 256Mi }
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
```

- [ ] **Step 3: Commit**

```bash
git add infra/argocd/apps/kind/app-otel-collector.yaml
git commit -m "Schedule OTel Collector onto the dedicated observability node"
```

---

### Task 7: Recreate the kind cluster, verify the topology, and re-seed data

**Files:** none (execution/verification task)

**Interfaces:**
- Consumes: every prior task's committed manifests.
- Produces: a live, verified 3-node kind cluster with correct workload placement, the
  migrations fix confirmed via a real login, and demo data restored.

- [ ] **Step 1: Tear down the current single-node cluster**

Run: `scripts/kind-down.sh`
Expected: `Deleted nodes: ["openlex-control-plane"]` or similar — this destroys all current
workloads and the Postgres PVC, which is expected and approved (dev/demo data only).

- [ ] **Step 2: Recreate with the 3-node config**

Run: `scripts/kind-up.sh`
Expected: ends with `kubectl context set to kind-openlex.`

- [ ] **Step 3: Confirm node labels/taints landed correctly**

Run:
```bash
kubectl --context kind-openlex get nodes --show-labels | grep 'openlex.dev/workload'
kubectl --context kind-openlex get nodes -o json | python3 -c "
import json,sys
for n in json.load(sys.stdin)['items']:
    name = n['metadata']['name']
    taints = n['spec'].get('taints', [])
    print(name, taints)
"
```
Expected: exactly one node labeled `openlex.dev/workload=observability` with a matching
`NoSchedule` taint, and two nodes labeled `openlex.dev/workload=apps` with no taints.

- [ ] **Step 4: Rebuild/load images, bootstrap secrets, bootstrap ArgoCD**

Run:
```bash
scripts/kind-load-images.sh
scripts/kind-secrets-bootstrap.sh
scripts/argocd-bootstrap.sh kind
```
Expected: each ends with its own success message, same as the original Phase 1 bootstrap.

- [ ] **Step 5: Wait for ArgoCD to sync everything, then confirm workload placement**

Run (poll until all Applications are `Synced`/`Healthy` — expect this to take several minutes
given kube-prometheus-stack's size):
```bash
kubectl --context kind-openlex get application -n argocd -w
```
Then confirm placement:
```bash
kubectl --context kind-openlex get pods -n openlex -o wide
kubectl --context kind-openlex get pods -n observability -o wide
```
Expected: `openlex-api` (2 pods), `openlex-worker`, `postgres-0` all on the two `apps`-labeled
nodes (never the `observability`-labeled one); every `observability` namespace pod (Prometheus,
Grafana, Alertmanager, kube-state-metrics, OTel Collector) on the `observability`-labeled node;
`prometheus-node-exporter` DaemonSet pods present on **all three** worker nodes (confirming its
toleration works without an exclusive nodeSelector).

- [ ] **Step 6: Confirm the migrations fix — real login now works**

Run:
```bash
kubectl --context kind-openlex port-forward -n openlex svc/openlex-api 18000:80 &
PF_PID=$!
sleep 3
curl -s -X POST http://localhost:18000/auth/login -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=<DEMO_SILVER_EMAIL from .env>&password=<DEMO_SILVER_PASSWORD from .env>"
kill $PF_PID
```
Expected: a `200` with an access token, not a `500`/`UndefinedTableError`.

- [ ] **Step 7: Re-seed demo data**

Run:
```bash
scripts/seed-demo-users.sh
scripts/ingest.sh all
```
Expected: both complete successfully — demo users exist, statute/case-law data re-ingested.

- [ ] **Step 8: Confirm the PodDisruptionBudget is live**

Run: `kubectl --context kind-openlex get pdb -n openlex`
Expected: `openlex-api` PDB present, `ALLOWED DISRUPTIONS: 1`.

## Checkpoint: Follow-up complete

- [ ] All 3 nodes present with correct labels/taints
- [ ] `openlex-api`/`worker`/`postgres` scheduled only on `apps`-labeled nodes; `openlex-api`
  running 2 replicas on 2 different nodes
- [ ] Every `observability` namespace workload scheduled on the `observability`-labeled node;
  `node-exporter` present on all 3 nodes
- [ ] `/auth/login` succeeds against the recreated cluster (migrations fix confirmed)
- [ ] `openlex-api` PodDisruptionBudget present with `minAvailable: 1`
- [ ] Demo users and statute/case-law data re-seeded
- [ ] All ArgoCD Applications `Synced`/`Healthy` with `selfHeal` genuinely active (a fresh
  install — no live-only patches from the Phase 1 troubleshooting session carry over)
