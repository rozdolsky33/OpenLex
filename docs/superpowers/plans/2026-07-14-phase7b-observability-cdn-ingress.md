# Phase 7b — Observability + Ingress/Auth + Static CDN + Remote State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Prerequisite:** `docs/superpowers/plans/2026-07-14-phase7a-aws-rds-node-topology.md` must be
complete first — this plan's Tasks 1-5 (observability) assume its two-node-group topology
(`openlex.dev/workload={observability,apps}` taint/label, the `gp3` default `StorageClass`)
and RDS-backed `openlex/app` Secrets Manager secret (`DATABASE_URL`/`POSTGRES_EXPORTER_DSN`)
already exist. Every reference to "Phase 7a Task N" below points at that plan.

**Goal:** Build (not deploy) `eks-demo`'s observability, exposure, and static-hosting layers —
the same self-hosted stack kind runs (kube-prometheus-stack + Tempo + Jaeger + Loki +
Promtail) running for real on Phase 7a's compute, Ingress + oauth2-proxy auth for Grafana
(Prometheus/Jaeger stay port-forward-only), S3+CloudFront static hosting for `apps/web`, and
Terraform remote state — all `terraform validate`-clean and ready to deploy, with zero live AWS
deployment in this phase.

**Architecture:** Extends the existing (never-deployed) `infra/terraform/` + `infra/argocd/` +
`infra/kubernetes/overlays/eks-demo/` scaffolding Phase 7a leaves in place. Every observability
Application (Tasks 1-4) is a near-literal copy of its `infra/argocd/apps/kind/` counterpart —
same chart, same shared `infra/monitoring/*/values-base.yaml` file, same
`openlex.dev/workload` taint/label/toleration strings — because `eks-demo` runs the *same*
observability stack as kind, just on Phase 7a's real multi-AZ, EBS-backed compute instead of
kind's single shared Docker daemon.

**Tech Stack:** Terraform ~>1.5 (AWS provider ~>5.0, plus new `tls` provider), ArgoCD
Application CRDs (Helm-chart sources), Kustomize overlays, GitHub Actions with OIDC federation.

**Domain:** `openlex.arwest.dev` (a delegated subdomain of `arwest.dev`) —
`infra/terraform/terraform.tfvars.example`'s `domain_name` default. Resulting endpoints once
actually deployed: `app.openlex.arwest.dev` (CloudFront/S3, Task 6), `api.openlex.arwest.dev`
(ingress-nginx → `openlex-api`, already existing, Task 6 only renames the host from
`app.<DOMAIN>`), `grafana.openlex.arwest.dev` (ingress-nginx → oauth2-proxy → Grafana, Task
5), `argocd.openlex.arwest.dev` (ArgoCD's own existing ingress, unchanged by this plan). The
**only manual DNS action ever required**, and only once this plan is actually deployed for
real (not this phase): after `terraform apply`, take `terraform output route53_name_servers`
(4 AWS-assigned nameservers) and add them as an NS record set for the `openlex` subdomain
wherever `arwest.dev`'s DNS is managed (registrar or separate DNS provider) — a one-time
subdomain delegation. Every subdomain under `openlex.arwest.dev` is then created automatically
(`external-dns` for the ingress-backed ones, Terraform's own `aws_route53_record.app` alias for
CloudFront) — no other manual DNS records, ever. GitHub repo:
`rozdolsky33/OpenLex` (`https://github.com/rozdolsky33/OpenLex`) — already
`infra/terraform/variables.tf`'s planned `github_repository` default in Task 6.

## Global Constraints

- **No live `terraform apply`, no live AWS deployment of any kind this phase** — every
  Terraform task's test is `terraform fmt -check` + `terraform init -backend=false` +
  `terraform validate` (not `terraform plan` — this sandbox has no valid AWS credentials,
  confirmed via `aws sts get-caller-identity` returning `InvalidClientTokenId`; `terraform
  plan` needs real AWS API access even to read `data "aws_availability_zones"`, so it is not
  executable here and is explicitly out of scope — document this in every task's report rather
  than silently skipping it).
- **No static AWS credentials anywhere** — every AWS-authenticating workload uses IRSA
  (in-cluster) or GitHub OIDC federation (CI). Never add an `aws_iam_access_key` or a GitHub
  secret holding a raw AWS key. **Every observability Application in Tasks 1-4 needs zero
  AWS IAM at all** — a deliberate consequence of the self-hosted design (see "Note on the
  7.6/7.9 revision" below), not an oversight.
- **No changes to `docker-compose.yml` or the `develop`/kind GitOps pipeline from Phase 6.**
- **No changes to `scripts/kind-secrets-bootstrap.sh` or any file under
  `infra/kubernetes/overlays/kind/`, `infra/argocd/apps/kind/`, or `infra/kubernetes/kind/`,
  or `scripts/observability-port-forward.sh`** — this is 7.3's isolation guarantee (local kind
  never gains any path to real AWS resources). The final whole-branch review explicitly diffs
  `main...HEAD` against these paths and must show zero changes.
- **`ArgoCD` does not get `oauth2-proxy` in front of it** — it keeps its own existing native
  login (`argocd-admin-externalsecret.yaml`, unchanged). Only Grafana gets the oauth2-proxy
  gate. Prometheus and Jaeger get **no Ingress at all**, only a port-forward script.
- **Every eks-demo observability Application mirrors its kind counterpart** — the only
  intentional differences are `project: openlex-eks-demo` (not `openlex-kind`), the values-repo
  source's `targetRevision: main` (not `develop`), and `postgres-exporter`'s DSN (RDS, not the
  in-cluster Service). No AWS-native exporters (X-Ray/CloudWatch/Fluent Bit) are built this
  phase — see the design spec's 7.6 "Future enhancement" note.
- **CloudFront's ACM certificate must use a `us-east-1` provider alias** regardless of
  `var.region`'s value.
- Every new ArgoCD `Application` that pulls from a Helm chart repo not already in
  `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos` must add that repo URL, or
  ArgoCD will refuse to sync it (`AppProject` enforcement).

---

## Note on the 7.6/7.9 revision (self-hosted, not AWS-native)

This plan implements the design spec's *revised* 7.6/7.9 sections directly — an earlier design
pass proposed AWS-native observability (X-Ray/CloudWatch/a standalone Grafana with oauth2-proxy
in front of Grafana+Prometheus+Jaeger), reversed after direct feedback before any task here was
executed. Two practical consequences worth stating up front:

- **No new IAM/IRSA roles are needed for observability at all.** Every self-hosted component
  (OTel Collector, Tempo, Jaeger, Loki, Promtail, kube-prometheus-stack, postgres-exporter)
  talks only to other in-cluster Services or (for postgres-exporter) RDS over the network via
  the security group Phase 7a's Task 1 already opens — none of them call an AWS API.
- **Grafana dashboards need no CloudWatch-flavored parallel versions.** Because `eks-demo` now
  queries the same Prometheus/Tempo/Jaeger/Loki backends kind does, the existing PromQL/LogQL/
  TraceQL dashboard JSON under `infra/monitoring/grafana/dashboards/` works unchanged.

---

## File Structure

New/modified files, grouped by task:

- **Task 1:** `infra/argocd/apps/eks-demo/{app-otel-collector.yaml,app-tempo.yaml,
  app-jaeger.yaml}` (new), `infra/argocd/projects/appproject-eks-demo.yaml` (modified)
- **Task 2:** `infra/argocd/apps/eks-demo/{app-loki.yaml,app-promtail.yaml}` (new — no new
  `sourceRepos` entry, `grafana.github.io/helm-charts` already added by Task 1)
- **Task 3:** `infra/argocd/apps/eks-demo/{app-kube-prometheus-stack.yaml,
  app-observability-dashboards.yaml}` (new), `infra/argocd/projects/appproject-eks-demo.yaml`
  (modified)
- **Task 4:** `infra/argocd/apps/eks-demo/app-postgres-exporter.yaml` (new)
- **Task 5:** `infra/argocd/apps/eks-demo/{app-oauth2-proxy.yaml,
  externalsecret-oauth2-proxy.yaml,ingress-grafana.yaml}` (new),
  `scripts/eks-demo-observability-port-forward.sh` (new),
  `infra/argocd/projects/appproject-eks-demo.yaml`, `infra/terraform/README.md` (modified)
- **Task 6:** `infra/terraform/static-site.tf` (new),
  `infra/terraform/iam_oidc_github_actions.tf` (new), `infra/terraform/providers.tf`,
  `infra/terraform/versions.tf`, `infra/terraform/variables.tf`, `infra/terraform/outputs.tf`,
  `infra/kubernetes/overlays/eks-demo/ingress-api.yaml` (all modified)
- **Task 7:** `.github/workflows/deploy-static.yml` (new), `infra/terraform/README.md`
  (modified)
- **Task 8:** `infra/terraform/backend.tf`, `infra/terraform/backend.hcl.example` (new),
  `infra/terraform/README.md`, `.gitignore` (modified)

---

### Task 1: Observability — OTel Collector, Tempo, Jaeger (traces, mirrors kind) (7.6 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-otel-collector.yaml`,
  `infra/argocd/apps/eks-demo/app-tempo.yaml`, `infra/argocd/apps/eks-demo/app-jaeger.yaml`
- Modify: `infra/argocd/projects/appproject-eks-demo.yaml`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability` taint/label (Phase 7a Task 4), the `gp3`
  `StorageClass` (Phase 7a Task 5), the shared `infra/monitoring/{otel-collector,tempo,jaeger}/
  values-base.yaml` files (exist today, already written to be consumed by "the kind
  Application and any future eks-demo Application").
- Produces: an `otel-collector-opentelemetry-collector` Service (OTLP receiver, ports
  4317/4318) in the `observability` namespace — no later task in this plan sends traces to it
  directly (apps/api's own OTel wiring is out of this plan's scope, unchanged from what already
  exists), but it's the collector every future app deployment on `eks-demo` will point at.

These three are a near-literal copy of their kind counterparts — same chart/version, same
`$values` file reference, only `project`/`targetRevision` differ. Read each kind file first so
the diff is obvious.

- [ ] **Step 1: Add the OTel Collector, Tempo, and Jaeger chart repos to the AppProject**

Edit `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos:` list, appending:

```yaml
    - https://open-telemetry.github.io/opentelemetry-helm-charts
    - https://grafana.github.io/helm-charts
    - https://jaegertracing.github.io/helm-charts
```

- [ ] **Step 2: Write the OTel Collector Application**

Read `infra/argocd/apps/kind/app-otel-collector.yaml` first (identical shape, `project` and
`targetRevision` differ only):

```yaml
# infra/argocd/apps/eks-demo/app-otel-collector.yaml
#
# Identical to infra/argocd/apps/kind/app-otel-collector.yaml — same chart/version/
# values-base.yaml, same otlp/tempo + otlp/jaeger dual export (no AWS exporters; see the
# plan's "Note on the 7.6/7.9 revision"). Only `project` and the values-repo source's
# `targetRevision` (main, not develop — eks-demo tracks main) differ.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: otel-collector
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
spec:
  project: openlex-eks-demo
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

- [ ] **Step 3: Write the Tempo Application**

Read `infra/argocd/apps/kind/app-tempo.yaml` first:

```yaml
# infra/argocd/apps/eks-demo/app-tempo.yaml
#
# Identical to infra/argocd/apps/kind/app-tempo.yaml. persistence.enabled/size (in the shared
# values-base.yaml) binds against the gp3 StorageClass (Phase 7a Task 5's default-class annotation) --
# no storageClassName override needed here, same as kind relying on its own default `standard`
# StorageClass.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: tempo
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
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
          tempo:
            memBallastSizeMbs: 128
            resources:
              requests: { cpu: 50m, memory: 512Mi }
              limits: { cpu: 500m, memory: 1536Mi }
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

- [ ] **Step 4: Write the Jaeger Application**

Read `infra/argocd/apps/kind/app-jaeger.yaml` first:

```yaml
# infra/argocd/apps/eks-demo/app-jaeger.yaml
#
# Identical to infra/argocd/apps/kind/app-jaeger.yaml — in-memory storage (comparison backend,
# data does not survive a pod restart), no PVC, no StorageClass dependency.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: jaeger
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
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

- [ ] **Step 5: Validate**

```bash
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-otel-collector.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-otel-collector.yaml)
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-tempo.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-tempo.yaml)
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-jaeger.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-jaeger.yaml)
```

Expected: the only differences per file are the header comment, `project: openlex-eks-demo`
(vs. `openlex-kind`), and `targetRevision: main` (vs. `develop`) on the values-repo source.
Anything else differing is a real mistake — fix it before committing.

```bash
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['infra/argocd/apps/eks-demo/app-otel-collector.yaml','infra/argocd/apps/eks-demo/app-tempo.yaml','infra/argocd/apps/eks-demo/app-jaeger.yaml']]" && echo OK
```

Expected: `OK`, no exceptions.

- [ ] **Step 6: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-otel-collector.yaml infra/argocd/apps/eks-demo/app-tempo.yaml infra/argocd/apps/eks-demo/app-jaeger.yaml infra/argocd/projects/appproject-eks-demo.yaml
git commit -m "Mirror kind's OTel Collector/Tempo/Jaeger onto eks-demo (7.6 revised)"
```

---

### Task 2: Observability — Loki, Promtail (logs, mirrors kind) (7.6 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-loki.yaml`, `infra/argocd/apps/eks-demo/app-promtail.yaml`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability`/`apps` taints/labels (Phase 7a Task 4), the `gp3`
  `StorageClass` (Phase 7a Task 5), `grafana.github.io/helm-charts` (already in the AppProject's
  `sourceRepos` from Task 1 — Loki uses the same repo Tempo does).
- Produces: a `loki` Service (push/query API, port 3100) in the `observability` namespace —
  consumed by Task 3's Grafana (as a datasource) and by Promtail (this task).

Both are a near-literal copy of their kind counterparts. Read each kind file first.

- [ ] **Step 1: Write the Loki Application**

Read `infra/argocd/apps/kind/app-loki.yaml` first:

```yaml
# infra/argocd/apps/eks-demo/app-loki.yaml
#
# Identical to infra/argocd/apps/kind/app-loki.yaml — SingleBinary mode, replication_factor 1
# (all in the shared values-base.yaml). singleBinary.persistence (chart default: enabled)
# binds against the gp3 StorageClass (Phase 7a Task 5's default-class annotation) -- no
# storageClassName override needed, same as kind relying on its own default `standard`
# StorageClass.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: loki
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://grafana.github.io/helm-charts
      chart: loki
      targetRevision: "7.0.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/loki/values-base.yaml
        valuesObject:
          singleBinary:
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

- [ ] **Step 2: Write the Promtail Application**

Read `infra/argocd/apps/kind/app-promtail.yaml` first:

```yaml
# infra/argocd/apps/eks-demo/app-promtail.yaml
#
# Identical to infra/argocd/apps/kind/app-promtail.yaml — DaemonSet, deliberately no
# nodeSelector (must run on both node groups to ship openlex-api/worker's own pod logs too,
# not just observability-node components), three-entry toleration list (control-plane taint +
# master taint + the observability taint) so nothing gets silently dropped by Helm's
# array-replace-not-merge values semantics -- same reasoning as kind's own file.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: promtail
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://grafana.github.io/helm-charts
      chart: promtail
      targetRevision: "6.17.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/promtail/values-base.yaml
        valuesObject:
          tolerations:
            - key: node-role.kubernetes.io/master
              operator: Exists
              effect: NoSchedule
            - key: node-role.kubernetes.io/control-plane
              operator: Exists
              effect: NoSchedule
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

- [ ] **Step 3: Validate**

```bash
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-loki.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-loki.yaml)
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-promtail.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-promtail.yaml)
```

Expected: same pattern as Task 1 Step 5 — only header comment/`project`/`targetRevision`
differ.

```bash
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['infra/argocd/apps/eks-demo/app-loki.yaml','infra/argocd/apps/eks-demo/app-promtail.yaml']]" && echo OK
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-loki.yaml infra/argocd/apps/eks-demo/app-promtail.yaml
git commit -m "Mirror kind's Loki/Promtail onto eks-demo (7.6 revised)"
```

---

### Task 3: Observability — kube-prometheus-stack + dashboards (mirrors kind) (7.6 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml`,
  `infra/argocd/apps/eks-demo/app-observability-dashboards.yaml`
- Modify: `infra/argocd/projects/appproject-eks-demo.yaml`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability` taint/label (Phase 7a Task 4), Tempo's
  `metricsGenerator.remoteWriteUrl` (Task 1, already hardcoded in the shared
  `tempo/values-base.yaml` to `kube-prometheus-stack-prometheus.observability.svc.cluster.local`
  — this Service name is what this task's Application name (`kube-prometheus-stack`) produces
  via the chart's default fullname).
- Produces: a `kube-prometheus-stack-grafana` Service (port 80) — consumed by Task 5's
  Ingress. A `kube-prometheus-stack-prometheus` Service (port 9090) and
  `kube-prometheus-stack-alertmanager` Service (port 9093) — consumed by Task 5's
  port-forward script.

- [ ] **Step 1: Add the prometheus-community chart repo to the AppProject**

Edit `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos:` list, appending:

```yaml
    - https://prometheus-community.github.io/helm-charts
```

- [ ] **Step 2: Write the kube-prometheus-stack Application**

Read `infra/argocd/apps/kind/app-kube-prometheus-stack.yaml` first (the largest of the mirrored
files — same reasoning applies: only `project`, `targetRevision`, and the Grafana
`additionalDataSources` block differ, since eks-demo's Tempo/Jaeger/Loki Services live at the
same in-cluster DNS names as kind's, just resolved against this cluster instead):

```yaml
# infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml
#
# Identical to infra/argocd/apps/kind/app-kube-prometheus-stack.yaml, including the shared
# values-base.yaml's additionalPrometheusRulesMap (the five symptom-based alerts) and
# Grafana's dashboard sidecar config -- both apply to eks-demo automatically once this
# Application syncs, no separate wiring needed. additionalDataSources' URLs are unchanged from
# kind's: Tempo/Jaeger/Loki resolve at the same in-cluster Service DNS names here as they do
# on kind (Tasks 6/7 gave eks-demo its own tempo/jaeger/loki Services in the same
# `observability` namespace).
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kube-prometheus-stack
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://prometheus-community.github.io/helm-charts
      chart: kube-prometheus-stack
      targetRevision: "87.15.*"
      helm:
        valueFiles:
          - $values/infra/monitoring/kube-prometheus-stack/values-base.yaml
        valuesObject:
          prometheusOperator:
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
              requests: { cpu: 50m, memory: 256Mi }
              limits: { cpu: 300m, memory: 768Mi }
            additionalDataSources:
              - name: Tempo
                uid: tempo
                type: tempo
                access: proxy
                url: http://tempo.observability.svc.cluster.local:3200
                isDefault: false
                jsonData:
                  serviceMap:
                    datasourceUid: prometheus
              - name: Jaeger
                uid: jaeger
                type: jaeger
                access: proxy
                url: http://jaeger.observability.svc.cluster.local:16686
                isDefault: false
              - name: Loki
                uid: loki
                type: loki
                access: proxy
                url: http://loki.observability.svc.cluster.local:3100
                isDefault: false
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
            # Blanket toleration (not scoped to the observability taint alone) so this
            # DaemonSet also schedules on the control-plane and apps node groups -- same
            # reasoning as kind's own file (a scoped-only toleration here previously caused a
            # live bug on kind where node-exporter silently missed the control-plane node,
            # since Helm values arrays replace rather than merge with the chart default).
            tolerations:
              - effect: NoSchedule
                operator: Exists
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
      - ServerSideApply=true
```

- [ ] **Step 3: Write the observability-dashboards Application**

Read `infra/argocd/apps/kind/app-observability-dashboards.yaml` first — this one needs zero
content changes at all beyond `project`/`targetRevision`, since
`infra/monitoring/grafana/dashboards/` is already environment-agnostic PromQL/LogQL/TraceQL
JSON, consumed via Kustomize (not Helm), so there's no `$values` multi-source pattern to adapt:

```yaml
# infra/argocd/apps/eks-demo/app-observability-dashboards.yaml
#
# Identical to infra/argocd/apps/kind/app-observability-dashboards.yaml. The dashboard JSON
# itself (infra/monitoring/grafana/dashboards/) needs zero eks-demo-specific changes -- it's
# PromQL/LogQL/TraceQL querying Prometheus/Loki/Tempo by Service DNS name, and eks-demo's
# Tempo/Jaeger/Loki/Prometheus resolve at those same names (Tasks 6/7/8's Applications all
# live in the same `observability` namespace kind uses). This is what resolves the original
# 7.6 draft's open question about needing parallel CloudWatch-flavored dashboards -- moot,
# since eks-demo never queries CloudWatch at all under this revised design.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: observability-dashboards
  namespace: argocd
spec:
  project: openlex-eks-demo
  source:
    repoURL: https://github.com/rozdolsky33/OpenLex.git
    targetRevision: main
    path: infra/monitoring/grafana/dashboards
  destination:
    server: https://kubernetes.default.svc
    namespace: observability
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
```

- [ ] **Step 4: Validate**

```bash
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-kube-prometheus-stack.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml)
diff infra/argocd/apps/kind/app-observability-dashboards.yaml infra/argocd/apps/eks-demo/app-observability-dashboards.yaml
```

Expected: only header comment/`project`/`targetRevision` differ in both files — confirm no
other line drifted (this is the largest mirrored file; a missed line here is easy to miss by
eye alone, which is why this diff check matters more here than anywhere else in Task 1-3).

```bash
python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml','infra/argocd/apps/eks-demo/app-observability-dashboards.yaml']]" && echo OK
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-kube-prometheus-stack.yaml infra/argocd/apps/eks-demo/app-observability-dashboards.yaml infra/argocd/projects/appproject-eks-demo.yaml
git commit -m "Mirror kind's kube-prometheus-stack + dashboards onto eks-demo (7.6 revised)"
```

---

### Task 4: Observability — postgres-exporter retargeted at RDS (7.6 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/app-postgres-exporter.yaml`

**Interfaces:**
- Consumes: `POSTGRES_EXPORTER_DSN` key in the `openlex-secrets` k8s Secret (Phase 7a Task 1's
  `aws_secretsmanager_secret_version.app`, flowing through `externalsecret-openlex.yaml`'s
  `dataFrom.extract`, confirmed automatic by Phase 7a Task 3), `openlex.dev/workload: apps` taint/label
  (Phase 7a Task 4), `prometheus-community.github.io/helm-charts` (already in the AppProject from Task
  3).
- Produces: nothing consumed by a later task — Prometheus (Task 3) discovers it automatically
  via its chart-native `serviceMonitor.enabled: true`, no manual wiring needed.

- [ ] **Step 1: Write the Application**

Read `infra/argocd/apps/kind/app-postgres-exporter.yaml` first. The chart/values are identical
(the shared `infra/monitoring/postgres-exporter/values-base.yaml` already points
`config.datasourceSecret` at `openlex-secrets`/`POSTGRES_EXPORTER_DSN` — the same Secret name
and key on both environments, just sourced differently upstream: kind's `.env`-derived vs.
Phase 7a Task 1's RDS-derived). Only `project`/`targetRevision` and the `nodeSelector` differ from
kind's file — this one lives in the `openlex` namespace, on the `apps` node group, not
`observability`, matching kind's own placement rationale (it reads the same
`openlex`-namespace Secret the app itself uses):

```yaml
# infra/argocd/apps/eks-demo/app-postgres-exporter.yaml
#
# Identical to infra/argocd/apps/kind/app-postgres-exporter.yaml. config.datasourceSecret
# (in the shared values-base.yaml) points at the same openlex-secrets/POSTGRES_EXPORTER_DSN
# key kind uses -- here it resolves to RDS (Phase 7a Task 1's rds.tf writes that key), not the
# in-cluster StatefulSet kind's key resolves to. Deliberately not in the `observability`
# namespace (same as kind): Prometheus already watches ServiceMonitors across every namespace
# (serviceMonitorSelectorNilUsesHelmValues: false, in the shared kube-prometheus-stack
# values-base.yaml), so this doesn't need to live in `observability` to be scraped, and
# staying in `openlex` avoids duplicating DB credentials into a second namespace.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: postgres-exporter
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  sources:
    - repoURL: https://prometheus-community.github.io/helm-charts
      chart: prometheus-postgres-exporter
      targetRevision: "8.1.1"
      helm:
        valueFiles:
          - $values/infra/monitoring/postgres-exporter/values-base.yaml
        valuesObject:
          nodeSelector:
            openlex.dev/workload: apps
    - repoURL: https://github.com/rozdolsky33/OpenLex.git
      targetRevision: main
      ref: values
  destination:
    server: https://kubernetes.default.svc
    namespace: openlex
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

- [ ] **Step 2: Validate**

```bash
diff <(grep -v "^apiVersion: argoproj" infra/argocd/apps/kind/app-postgres-exporter.yaml) <(grep -v "^apiVersion: argoproj" infra/argocd/apps/eks-demo/app-postgres-exporter.yaml)
python3 -c "import yaml; yaml.safe_load(open('infra/argocd/apps/eks-demo/app-postgres-exporter.yaml'))" && echo OK
```

Expected: only header comment/`project`/`targetRevision` differ; `OK` printed.

- [ ] **Step 3: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-postgres-exporter.yaml
git commit -m "Mirror kind's postgres-exporter onto eks-demo, retargeted at RDS (7.6 revised)"
```

---

### Task 5: Ingress + oauth2-proxy for Grafana; port-forward script for Prometheus/Jaeger (7.9 revised)

**Files:**
- Create: `infra/argocd/apps/eks-demo/{app-oauth2-proxy.yaml,
  externalsecret-oauth2-proxy.yaml,ingress-grafana.yaml}`,
  `scripts/eks-demo-observability-port-forward.sh`
- Modify: `infra/argocd/projects/appproject-eks-demo.yaml`, `infra/terraform/README.md`

**Interfaces:**
- Consumes: `openlex.dev/workload: observability` taint/label (Phase 7a Task 4), the
  `kube-prometheus-stack-grafana` Service on port `80`, the
  `kube-prometheus-stack-prometheus` Service on port `9090`, the
  `kube-prometheus-stack-alertmanager` Service on port `9093` (all Task 3), the `jaeger`
  Service on port `16686` (Task 1), the `aws-secrets-manager` `ClusterSecretStore` (exists
  today, `infra/argocd/apps/eks-demo/secretstore-aws.yaml`).
- Produces: nothing consumed by a later task.

Per the design spec's revised 7.9: Grafana (plus ArgoCD's own existing login) gets real
internet-facing exposure. Prometheus and Jaeger get **no Ingress at all** — the port-forward
script is their only access path, mirroring `scripts/observability-port-forward.sh`'s existing
pattern for kind (not touching that file — a brand-new file, per 7.3's isolation discipline).

- [ ] **Step 1: Add the oauth2-proxy chart repo to the AppProject**

Edit `infra/argocd/projects/appproject-eks-demo.yaml`'s `sourceRepos:` list, appending:

```yaml
    - https://oauth2-proxy.github.io/manifests
```

- [ ] **Step 2: Write the ExternalSecret for oauth2-proxy's OAuth credentials**

```yaml
# infra/argocd/apps/eks-demo/externalsecret-oauth2-proxy.yaml
#
# Requires the openlex/oauth2-proxy AWS Secrets Manager secret to exist by hand (JSON keys
# client_id, client_secret, cookie_secret — see infra/terraform/README.md's updated step 5) —
# a GitHub OAuth App's client ID/secret are external credentials, same category as
# ANTHROPIC_API_KEY; cookie_secret is a random 32-byte value the operator generates once
# (`python3 -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`).
# Lives here (not infra/kubernetes/overlays/eks-demo/) and sets its own namespace explicitly
# because that overlay's kustomization.yaml sets a global `namespace: openlex` transformer that
# would silently override any namespace set on a resource routed through it — same reasoning as
# argocd-admin-externalsecret.yaml's explicit `namespace: argocd`.
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: oauth2-proxy-secrets-es
  namespace: observability
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: oauth2-proxy-secrets
    creationPolicy: Owner
  data:
    - secretKey: client-id
      remoteRef:
        key: openlex/oauth2-proxy
        property: client_id
    - secretKey: client-secret
      remoteRef:
        key: openlex/oauth2-proxy
        property: client_secret
    - secretKey: cookie-secret
      remoteRef:
        key: openlex/oauth2-proxy
        property: cookie_secret
```

- [ ] **Step 3: Write the oauth2-proxy Application**

```yaml
# infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml
#
# Gates Grafana behind a single login (7.9 revised). GitHub OAuth chosen over a static
# htpasswd-style provider (spec's own open question, resolved here): oauth2-proxy's htpasswd
# support is a secondary/basic-auth fallback, not designed as a standalone primary provider,
# and GitHub OAuth is both the more realistic cloud-native pattern and a natural fit for a
# project that already lives on GitHub. Requires a GitHub OAuth App registered by hand
# (Settings -> Developer settings -> OAuth Apps -> New OAuth App, callback URL
# https://grafana.<DOMAIN>/oauth2/callback) — a manual one-time step in the same category as
# this project's other documented manual bootstrap steps (Route53 nameservers, Secrets Manager
# seed values). `<GITHUB_USERNAME>` restricts access to a single operator (replace with your
# own GitHub username) -- without it, any GitHub-authenticated user could log in. Client
# ID/secret/cookie secret come from externalsecret-oauth2-proxy.yaml, never committed here.
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: oauth2-proxy
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "0"
spec:
  project: openlex-eks-demo
  source:
    repoURL: https://oauth2-proxy.github.io/manifests
    chart: oauth2-proxy
    targetRevision: "7.9.*"
    helm:
      valuesObject:
        config:
          existingSecret: oauth2-proxy-secrets
        extraArgs:
          provider: github
          github-user: "<GITHUB_USERNAME>"
          email-domain: "*"
          upstreams: static://202
          http-address: "0.0.0.0:4180"
          cookie-secure: "true"
          cookie-samesite: "lax"
          set-xauthrequest: "true"
        nodeSelector:
          openlex.dev/workload: observability
        tolerations:
          - key: openlex.dev/workload
            operator: Equal
            value: observability
            effect: NoSchedule
        resources:
          requests: { cpu: 25m, memory: 32Mi }
          limits: { cpu: 100m, memory: 64Mi }
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

- [ ] **Step 4: Write the Grafana Ingress**

```yaml
# infra/argocd/apps/eks-demo/ingress-grafana.yaml
#
# nginx.ingress.kubernetes.io/auth-url + auth-signin gate access via oauth2-proxy
# (app-oauth2-proxy.yaml) -- the standard, documented ingress-nginx + oauth2-proxy
# integration pattern. Targets kube-prometheus-stack-grafana (Task 3's bundled Grafana, not a
# standalone chart). Lives here, not infra/kubernetes/overlays/eks-demo/, for the same
# namespace-transformer reason as externalsecret-oauth2-proxy.yaml above. Replace <DOMAIN>
# with the real demo domain.
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana
  namespace: observability
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-staging
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/auth-url: "https://grafana.<DOMAIN>/oauth2/auth"
    nginx.ingress.kubernetes.io/auth-signin: "https://grafana.<DOMAIN>/oauth2/start?rd=$scheme://$host$request_uri"
    nginx.ingress.kubernetes.io/auth-response-headers: "X-Auth-Request-User, X-Auth-Request-Email"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - grafana.<DOMAIN>
      secretName: grafana-tls
  rules:
    - host: grafana.<DOMAIN>
      http:
        paths:
          - path: /oauth2
            pathType: Prefix
            backend:
              service:
                name: oauth2-proxy
                port:
                  number: 4180
          - path: /
            pathType: Prefix
            backend:
              service:
                name: kube-prometheus-stack-grafana
                port:
                  number: 80
```

- [ ] **Step 5: Write the port-forward script for Prometheus/Jaeger (and Grafana/Alertmanager/ArgoCD for convenience)**

```bash
#!/usr/bin/env bash
# scripts/eks-demo-observability-port-forward.sh
#
# Prometheus and Jaeger have no built-in authentication and get no Ingress on eks-demo (see
# infra/argocd/apps/eks-demo/ingress-grafana.yaml's header comment and the design spec's
# revised 7.9) -- this is their only access path, mirroring
# scripts/observability-port-forward.sh's existing pattern for kind service-for-service. A
# brand-new file, not an extension of that script -- 7.3's isolation discipline means
# kind-only files never gain eks-demo-specific logic. Requires a kubeconfig context already
# pointed at the eks-demo cluster (`aws eks update-kubeconfig --name <cluster_name> --region
# <region>`, see infra/terraform/README.md's setup sequence) -- unlike kind's script, this
# doesn't assume it's the only cluster in your kubeconfig, so double-check your current
# context before running this.
set -euo pipefail

NAMESPACE="observability"
ARGOCD_NAMESPACE="argocd"

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
kubectl port-forward -n "${NAMESPACE}" svc/jaeger 16686:16686 &
pids+=($!)
kubectl port-forward -n "${ARGOCD_NAMESPACE}" svc/argocd-server 8080:443 &
pids+=($!)

echo "Grafana:      http://localhost:3000  (admin password: kubectl -n ${NAMESPACE} get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d)"
echo "Prometheus:   http://localhost:9090  (no auth -- port-forward only, see this script's header comment)"
echo "Alertmanager: http://localhost:9093"
echo "Jaeger:       http://localhost:16686  (no auth -- port-forward only, see this script's header comment)"
echo "ArgoCD:       https://localhost:8080  (admin password: kubectl -n ${ARGOCD_NAMESPACE} get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d, or the openlex/argocd-admin Secrets Manager password if already rotated)"
echo
echo "Press Ctrl-C to stop all port-forwards."
wait
```

```bash
chmod +x scripts/eks-demo-observability-port-forward.sh
```

- [ ] **Step 6: Update README.md's setup sequence**

Edit `infra/terraform/README.md`'s step 5 (from Phase 7a Task 1's version) to add, after the existing
`openlex/app`/`openlex/argocd-admin` bullets:

```
   Also create `openlex/oauth2-proxy` (JSON keys `client_id`, `client_secret`, `cookie_secret`)
   after registering a GitHub OAuth App (see
   `infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml`'s header comment for the exact steps).
```

- [ ] **Step 7: Cross-check the integration against oauth2-proxy's own docs**

`WebFetch` `https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview` and
`.../configuration/providers/github`. Confirm `upstreams: static://202` is the documented
auth-only-mode idiom, and that `provider: github` + `github-user` is the correct flag for
restricting to a single GitHub user. Record what was checked in the task report.

- [ ] **Step 8: Validate the new YAML/script**

```bash
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/argocd/apps/eks-demo/ingress-grafana.yaml')))" && echo OK
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml')))" && echo OK
python3 -c "import yaml; list(yaml.safe_load_all(open('infra/argocd/apps/eks-demo/externalsecret-oauth2-proxy.yaml')))" && echo OK
bash -n scripts/eks-demo-observability-port-forward.sh && echo "script syntax OK"
diff <(grep -vE "^#|^NAMESPACE=\"observability\"$" scripts/observability-port-forward.sh) <(grep -vE "^#|^NAMESPACE=\"observability\"$" scripts/eks-demo-observability-port-forward.sh) || true
```

Expected: `OK` printed 3 times, `script syntax OK`, and the final `diff` (informational, not a
strict pass/fail — `|| true` keeps it non-blocking) showing only the expected differences:
`cd "$(dirname...")/.."`'s removal (see the script's header comment on kubeconfig context),
the dropped OTLP/HTTP line (kind's script forwards the collector for `apps/web`'s browser
tracing; this plan's OTel Collector Application doesn't need the same local port-forward use
case documented here), and the updated echo text.

- [ ] **Step 9: Commit**

```bash
git add infra/argocd/apps/eks-demo/app-oauth2-proxy.yaml infra/argocd/apps/eks-demo/externalsecret-oauth2-proxy.yaml infra/argocd/apps/eks-demo/ingress-grafana.yaml infra/argocd/projects/appproject-eks-demo.yaml infra/terraform/README.md scripts/eks-demo-observability-port-forward.sh
git commit -m "Add oauth2-proxy + Ingress for Grafana, port-forward script for Prometheus/Jaeger (7.9 revised)"
```

---

### Task 6: Static CDN — Terraform: S3 + CloudFront + ACM + GitHub OIDC role (7.8b)

**Files:**
- Create: `infra/terraform/static-site.tf`, `infra/terraform/iam_oidc_github_actions.tf`
- Modify: `infra/terraform/providers.tf`, `infra/terraform/versions.tf`,
  `infra/terraform/variables.tf`, `infra/terraform/outputs.tf`,
  `infra/kubernetes/overlays/eks-demo/ingress-api.yaml`

**Interfaces:**
- Consumes: `aws_route53_zone.demo` (`infra/terraform/route53.tf`, exists today),
  `var.domain_name` (exists today).
- Produces: `aws_s3_bucket.web`, `aws_cloudfront_distribution.web`,
  `aws_iam_role.github_actions_deploy_web.arn` — all three consumed by Task 7's
  `deploy-static.yml` (as `terraform output web_bucket_name`, `cloudfront_distribution_id`,
  `github_actions_deploy_web_role_arn`, hand-copied into GitHub Actions repository variables).

- [ ] **Step 1: Add the `tls` provider**

Edit `infra/terraform/versions.tf`:

```hcl
terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }
}
```

- [ ] **Step 2: Add the `us-east-1` provider alias**

Edit `infra/terraform/providers.tf`, appending:

```hcl

# CloudFront/ACM specifically require us-east-1 regardless of var.region — see static-site.tf's
# aws_acm_certificate.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "openlex"
      Environment = "eks-demo"
      ManagedBy   = "terraform"
    }
  }
}
```

- [ ] **Step 3: Add the `github_repository` variable**

Edit `infra/terraform/variables.tf`, appending:

```hcl

variable "github_repository" {
  description = "GitHub \"owner/repo\" this project lives in — scopes the GitHub Actions OIDC trust policy"
  type        = string
  default     = "rozdolsky33/OpenLex"
}
```

- [ ] **Step 4: Write `static-site.tf`**

```hcl
# infra/terraform/static-site.tf
#
# apps/web's production build (vite build -> static dist/) served via S3 + CloudFront instead
# of the ingress-nginx -> web-pod dev-server routing kind/compose use — see
# docs/superpowers/specs/2026-07-14-phase7-aws-rds-secrets-manager-design.md's 7.8.
# app.<domain> moves here; api.<domain> (infra/kubernetes/overlays/eks-demo/ingress-api.yaml)
# stays on ingress-nginx, unchanged in kind.

resource "random_id" "web_bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "web" {
  bucket = "${var.cluster_name}-web-${random_id.web_bucket_suffix.hex}"
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CloudFront reaches the bucket via Origin Access Control, not a public bucket policy or the
# older Origin Access Identity — OAC is AWS's current recommended approach.
resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${var.cluster_name}-web-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

data "aws_iam_policy_document" "web_bucket_policy" {
  statement {
    sid       = "AllowCloudFrontOAC"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.web.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = data.aws_iam_policy_document.web_bucket_policy.json
}

# ACM certificates for CloudFront must be requested in us-east-1 specifically, regardless of
# var.region -- a CloudFront-specific AWS requirement, independent of where the rest of this
# infrastructure lives (var.region already defaults to us-east-1 today, but this alias makes
# it correct even if that ever changes).
resource "aws_acm_certificate" "web" {
  provider          = aws.us_east_1
  domain_name       = "app.${var.domain_name}"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "web_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.web.domain_validation_options : dvo.domain_name => {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  }

  zone_id = aws_route53_zone.demo.zone_id
  name    = each.value.name
  type    = each.value.type
  records = [each.value.value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "web" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.web.arn
  validation_record_fqdns = [for r in aws_route53_record.web_cert_validation : r.fqdn]
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  default_root_object = "index.html"
  aliases             = ["app.${var.domain_name}"]
  # price_class deliberately left unset (defaults to PriceClass_All) — CloudFront's edge
  # network is global by default, Europe included, with no special per-region config needed;
  # explicitly restricting to a smaller price class would work against that.

  origin {
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_id                = "web-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  default_cache_behavior {
    allowed_methods         = ["GET", "HEAD"]
    cached_methods          = ["GET", "HEAD"]
    target_origin_id        = "web-s3"
    viewer_protocol_policy  = "redirect-to-https"
    cache_policy_id         = "658327ea-f89d-4fab-a63d-7e88639e58f6" # AWS-managed "CachingOptimized" policy
  }

  # apps/web is a client-side-routed SPA (React) -- a direct hit on e.g. /login must still
  # serve index.html (200), not CloudFront's default S3 404/403, or a browser refresh on any
  # non-root route breaks.
  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }
  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.web.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_route53_record" "app" {
  zone_id = aws_route53_zone.demo.zone_id
  name    = "app.${var.domain_name}"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.web.domain_name
    zone_id                = aws_cloudfront_distribution.web.hosted_zone_id
    evaluate_target_health = false
  }
}
```

- [ ] **Step 5: Write the GitHub OIDC IAM role**

```hcl
# infra/terraform/iam_oidc_github_actions.tf
#
# Lets .github/workflows/deploy-static.yml (Task 7) authenticate to AWS via GitHub's OIDC
# federation -- no static AWS access keys in GitHub secrets, matching this project's "no
# static cloud credentials" precedent (IRSA everywhere else). Assumes no GitHub Actions OIDC
# provider already exists in this AWS account -- this project's own AWS account has never had
# any Terraform apply of any kind (see "Explicitly out of scope"), so this is safe to create
# fresh.
data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

# Scoped to pushes on main only (deploy-static.yml's own trigger) -- a PR branch's workflow
# run could never assume this role, even if it tried.
data "aws_iam_policy_document" "github_actions_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy_web" {
  name               = "${var.cluster_name}-github-actions-deploy-web"
  assume_role_policy = data.aws_iam_policy_document.github_actions_trust.json
}

data "aws_iam_policy_document" "github_actions_deploy_web_permissions" {
  statement {
    effect  = "Allow"
    actions = ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      aws_s3_bucket.web.arn,
      "${aws_s3_bucket.web.arn}/*",
    ]
  }

  statement {
    effect    = "Allow"
    actions   = ["cloudfront:CreateInvalidation"]
    resources = [aws_cloudfront_distribution.web.arn]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy_web" {
  name   = "github-actions-deploy-web"
  role   = aws_iam_role.github_actions_deploy_web.id
  policy = data.aws_iam_policy_document.github_actions_deploy_web_permissions.json
}
```

- [ ] **Step 6: Add outputs**

Edit `infra/terraform/outputs.tf`, appending:

```hcl

output "web_bucket_name" {
  description = "Paste into the GitHub repo's OPENLEX_WEB_BUCKET Actions variable"
  value       = aws_s3_bucket.web.id
}

output "cloudfront_distribution_id" {
  description = "Paste into the GitHub repo's OPENLEX_CLOUDFRONT_DISTRIBUTION_ID Actions variable"
  value       = aws_cloudfront_distribution.web.id
}

output "github_actions_deploy_web_role_arn" {
  description = "Paste into the GitHub repo's GITHUB_ACTIONS_DEPLOY_WEB_ROLE_ARN Actions variable"
  value       = aws_iam_role.github_actions_deploy_web.arn
}
```

- [ ] **Step 7: Split the domain — `api.<DOMAIN>` replaces `app.<DOMAIN>` for the API ingress**

Edit `infra/kubernetes/overlays/eks-demo/ingress-api.yaml`:

```yaml
# Replace <DOMAIN> with the real demo domain (e.g. openlex-demo.example.com) before applying.
# Start with cluster-issuer: letsencrypt-staging (see infra/argocd/apps/eks-demo/), switch to
# letsencrypt-prod once the staging issuance succeeds end-to-end (avoids burning Let's
# Encrypt's production rate limit while debugging HTTP-01 reachability).
#
# api.<DOMAIN> (not app.<DOMAIN>) -- app.<DOMAIN> now goes to CloudFront/S3 for apps/web's
# static build instead (infra/terraform/static-site.tf, 7.8). This ingress only ever routed
# to the openlex-api Service directly (there was no separate web ingress before this), so the
# fix is a host-value rename, not a routing change.
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: openlex-api
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-staging
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.<DOMAIN>
      secretName: openlex-api-tls
  rules:
    - host: api.<DOMAIN>
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: openlex-api
                port:
                  name: http
```

- [ ] **Step 8: Validate**

```bash
cd infra/terraform
terraform fmt -check
terraform init -backend=false
terraform validate
```

Expected: `Success! The configuration is valid.`

```bash
kubectl kustomize infra/kubernetes/overlays/eks-demo | grep "host:"
```

Expected: only `api.<DOMAIN>` appears (confirm `app.<DOMAIN>` is gone from this file).

- [ ] **Step 9: Commit**

```bash
git add infra/terraform/static-site.tf infra/terraform/iam_oidc_github_actions.tf infra/terraform/providers.tf infra/terraform/versions.tf infra/terraform/variables.tf infra/terraform/outputs.tf infra/kubernetes/overlays/eks-demo/ingress-api.yaml
git commit -m "Add S3 + CloudFront static hosting for apps/web, GitHub OIDC deploy role (7.8)"
```

---

### Task 7: Static CDN — apps/web production build + deploy-static.yml (7.8a + 7.8c)

**Files:**
- Create: `.github/workflows/deploy-static.yml`
- Modify: `infra/terraform/README.md`

**Interfaces:**
- Consumes: `apps/web`'s existing `npm run build` script (`package.json`, unchanged — already
  produces a real `dist/`, confirmed working during this plan's own research, see Step 1),
  Task 6's `web_bucket_name`/`cloudfront_distribution_id`/`github_actions_deploy_web_role_arn`
  outputs.
- Produces: nothing consumed by a later task.

- [ ] **Step 1: Confirm the production build works locally (no AWS needed)**

```bash
cd apps/web
VITE_API_BASE_URL=https://api.example.com npm run build
```

Expected: `tsc -b && vite build` completes with no errors, printing a `dist/` asset summary
(`dist/index.html`, `dist/assets/index-*.css`, `dist/assets/index-*.js`). This already passes
as-is today — no code changes needed in `apps/web` itself.

```bash
grep -o "api.example.com" dist/assets/*.js
```

Expected: prints `api.example.com` — confirms `VITE_API_BASE_URL` really is baked into the
built JS bundle at build time (not read at runtime, unlike kind/compose's dev-server path).

```bash
rm -rf dist
```

(`dist/` is already git-ignored — see root `.gitignore`'s `dist/` entry — so this is just local
cleanup, not required for the commit to be clean, but keeps the working tree tidy.)

- [ ] **Step 2: Write the workflow**

```yaml
# .github/workflows/deploy-static.yml
name: deploy-static

on:
  push:
    branches: [main]
    paths:
      - "apps/web/**"
      - ".github/workflows/deploy-static.yml"

permissions:
  id-token: write # required for GitHub OIDC -> AWS
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    defaults:
      run:
        working-directory: apps/web
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version-file: apps/web/.nvmrc
          cache: npm
          cache-dependency-path: apps/web/package-lock.json

      - run: npm ci

      - name: Build (production, API base URL baked in)
        env:
          VITE_API_BASE_URL: https://api.${{ vars.OPENLEX_DOMAIN }}
        run: npm run build

      - name: Configure AWS credentials (OIDC, no static keys)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.GITHUB_ACTIONS_DEPLOY_WEB_ROLE_ARN }}
          aws-region: us-east-1

      - name: Sync to S3
        run: aws s3 sync dist/ "s3://${{ vars.OPENLEX_WEB_BUCKET }}" --delete

      - name: Invalidate CloudFront
        run: aws cloudfront create-invalidation --distribution-id "${{ vars.OPENLEX_CLOUDFRONT_DISTRIBUTION_ID }}" --paths "/*"
```

- [ ] **Step 3: Document the new repository variables in the README**

Edit `infra/terraform/README.md`, adding a new subsection after "First-time setup" (renumbering
not required — this is additive):

```markdown
## Static site deploy (`apps/web`, 7.8)

After `terraform apply`, set these as GitHub repository (or `production` environment)
**variables** (not secrets — none of these are sensitive), Settings -> Secrets and variables ->
Actions -> Variables:

- `OPENLEX_DOMAIN` — the same value as `var.domain_name`.
- `OPENLEX_WEB_BUCKET` — `terraform output web_bucket_name`.
- `OPENLEX_CLOUDFRONT_DISTRIBUTION_ID` — `terraform output cloudfront_distribution_id`.
- `GITHUB_ACTIONS_DEPLOY_WEB_ROLE_ARN` — `terraform output github_actions_deploy_web_role_arn`.

`.github/workflows/deploy-static.yml` then deploys automatically on every push to `main` that
touches `apps/web/**`.
```

- [ ] **Step 4: Validate the workflow YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-static.yml'))" && echo OK
```

Expected: `OK`, no exceptions.

Manually cross-check the `aws-actions/configure-aws-credentials@v4` step's `role-to-assume`/
`aws-region` inputs and the `permissions: id-token: write` requirement against GitHub's own
OIDC-with-AWS documentation (`WebFetch`
`https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services`,
record what was checked).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy-static.yml infra/terraform/README.md
git commit -m "Add deploy-static.yml: apps/web production build to S3 + CloudFront (7.8)"
```

---

### Task 8: Terraform remote state (7.4)

**Files:**
- Modify: `infra/terraform/backend.tf`, `infra/terraform/README.md`, `.gitignore`
- Create: `infra/terraform/backend.hcl.example`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing consumed by a later task — this is deliberately the last Terraform task
  (see the note below).

**Why this task runs last, not "early/alongside" Phase 7a Task 1 as the spec's own risk note
suggests:** that risk note is about *live deployment* ordering (once someone actually runs
`terraform apply` for real, the RDS-generated password ends up in state, so remote state should
exist before/alongside that real apply). This phase never runs `terraform apply` at all — no
state file, sensitive or not, is ever created during this implementation. Sequencing this task
last instead means every earlier task's `terraform init -backend=false && terraform validate`
keeps working throughout the plan without ever needing a real S3 bucket; had `backend.tf`
switched to a real `backend "s3" {}` block first, every subsequent task would need to either
fight Terraform's "backend configuration changed, re-run init" error or also pass
`-backend=false`, for no real benefit this early. The README documents the correct *live*
ordering (remote state before/alongside a real `terraform apply` of `rds.tf`) for whoever
deploys this for real later.

- [ ] **Step 1: Uncomment and parameterize `backend.tf`**

```hcl
# infra/terraform/backend.tf
#
# Real bucket/key/region/dynamodb_table values are supplied via
# `terraform init -backend-config=backend.hcl` (copy backend.hcl.example -> backend.hcl and
# fill in real values — never commit backend.hcl itself, see .gitignore) rather than
# terraform.tfvars, because Terraform backend blocks cannot reference variables or
# terraform.tfvars at all — this partial-configuration pattern is the standard way to keep
# real bucket names out of a committed file while still using a real S3 backend.
#
# See README.md's "Remote state" section for the one-time bootstrap (the S3 bucket + DynamoDB
# lock table this backend needs can't be created by the same Terraform config that needs them
# to exist first — the classic remote-state chicken-and-egg).
terraform {
  backend "s3" {
    encrypt = true
  }
}
```

- [ ] **Step 2: Write `backend.hcl.example`**

```hcl
# infra/terraform/backend.hcl.example
#
# Copy to backend.hcl (git-ignored), fill in real values, then:
#   terraform init -backend-config=backend.hcl -migrate-state
bucket         = "<your-tfstate-bucket>"
key            = "openlex/eks-demo/terraform.tfstate"
region         = "us-east-1"
dynamodb_table = "<your-tflock-table>"
```

- [ ] **Step 3: Protect local Terraform artifacts in `.gitignore`**

Edit `.gitignore`, appending:

```

# Terraform (infra/terraform/) — local plan/state artifacts and real backend/tfvars values,
# never committed (see infra/terraform/README.md's "Remote state" section and
# terraform.tfvars.example/backend.hcl.example for the committed templates).
infra/terraform/.terraform/
infra/terraform/*.tfstate*
infra/terraform/backend.hcl
infra/terraform/terraform.tfvars
```

- [ ] **Step 4: Add the "Remote state" section to `infra/terraform/README.md`**

Add a new section after "## State" (the existing section, which currently says "Local state by
default... Switch to an S3+DynamoDB backend once that stops being true" — leave that section's
text as-is, since it's still an accurate description of the *default*; this is additive):

```markdown
## Remote state

`backend.tf` is configured for an S3 backend, but the bucket/key/region/table values are
supplied separately (Terraform backend blocks can't reference variables or `terraform.tfvars`
at all) via `-backend-config`. One-time bootstrap, before the very first `terraform init` on a
fresh AWS account (an S3 bucket + DynamoDB table can't be created by the same Terraform config
that needs them to exist first):

```bash
aws s3api create-bucket --bucket <your-tfstate-bucket> --region us-east-1
aws s3api put-bucket-versioning --bucket <your-tfstate-bucket> --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket <your-tfstate-bucket> --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws dynamodb create-table \
  --table-name <your-tflock-table> \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

Then:

```bash
cp backend.hcl.example backend.hcl
# edit backend.hcl: real bucket/table names
terraform init -backend-config=backend.hcl -migrate-state
```

**Do this before or alongside the first real `terraform apply` of `rds.tf`** — a real
`aws_db_instance` password ends up in Terraform state via `random_password`/
`aws_secretsmanager_secret_version`, which makes that state file itself sensitive; remote state
(S3 with encryption + restricted IAM access) is meaningfully safer than a local state file on a
laptop for that reason, not just a "more than one person touches this" convenience upgrade.
```

- [ ] **Step 5: Validate**

```bash
cd infra/terraform
terraform fmt -check
terraform init -backend=false
terraform validate
```

Expected: `Success! The configuration is valid.` (`-backend=false` skips backend
initialization entirely, regardless of what `backend.tf` now declares — this is the one task
in the plan that could not use a real `terraform init` against `backend.tf` as written, since
there is no real S3 bucket to point it at; this is consistent with the phase's own "no live
deployment" scope, not a gap specific to this task.)

- [ ] **Step 6: Commit**

```bash
git add infra/terraform/backend.tf infra/terraform/backend.hcl.example infra/terraform/README.md .gitignore
git commit -m "Configure Terraform S3 remote state backend, document bootstrap (7.4)"
```

---

## Final whole-branch review — explicit isolation checks

7.3 (environment isolation) has no dedicated task — it's a guarantee, not new code. Include
this exact check in the final whole-branch review's dispatch (same check as Phase 7a's, plus
the new port-forward script):

```bash
git diff main...HEAD --stat -- scripts/kind-secrets-bootstrap.sh scripts/observability-port-forward.sh infra/kubernetes/overlays/kind/ infra/argocd/apps/kind/ infra/kubernetes/kind/ docker-compose.yml
```

Expected: **empty output** — zero changes to any of these paths, including
`scripts/observability-port-forward.sh` (Task 5 creates a brand-new
`scripts/eks-demo-observability-port-forward.sh` instead of touching this one). If this shows
any diff, that is a real finding, not a stylistic nit.

## Self-Review

**Spec coverage:** 7.4 → Task 8. 7.6 (revised) → Tasks 1-4. 7.8 → Tasks 6-7. 7.9 (revised) →
Task 5. (7.1, 7.2, 7.5, 7.7 live in Phase 7a.)

**Placeholder scan:** no TBD/TODO markers; the `<PLACEHOLDER>` conventions used (`<DOMAIN>`,
`<GITHUB_USERNAME>`, `<*_ROLE_ARN>`) are the project's own established, real convention for
values a human hand-copies after `terraform apply` or hand-registers externally (e.g.
`<ACME_EMAIL>` in the existing `clusterissuer-letsencrypt.yaml`) — not unresolved plan gaps.

**Type/naming consistency:** `openlex.dev/workload` taint/label key and `observability`/`apps`
values are identical across Tasks 1-5 and kind's existing files (verified by each task's own
`diff`-against-kind step). `POSTGRES_EXPORTER_DSN` key name is consistent between Phase 7a's
`rds.tf` (which writes it) and the shared `infra/monitoring/postgres-exporter/values-base.yaml`
(which reads it via `config.datasourceSecret.key` — unchanged by this plan, already correct).
Service names Task 5's Ingress/port-forward script depend on
(`kube-prometheus-stack-grafana`, `kube-prometheus-stack-prometheus`,
`kube-prometheus-stack-alertmanager`, `jaeger`) all trace back to Task 1/3's Application
`metadata.name` values via each chart's default fullname templating — verified against
`scripts/observability-port-forward.sh`'s existing, live-proven service names for kind (the
same charts, same naming convention).

**No IAM/IRSA left over from the pre-revision design:** Tasks 1-4 (observability) contain zero
`.tf` files and zero `outputs.tf`/README hand-copy steps — confirmed by this plan's own File
Structure section listing only ArgoCD/Kubernetes YAML for those four tasks. This is a
deliberate consequence of the self-hosted design (see "Note on the 7.6/7.9 revision"), not an
oversight.

**Domain wiring:** Task 6's `static-site.tf` and Task 5's `ingress-grafana.yaml` both consume
`var.domain_name` (`openlex.arwest.dev`, already set in `terraform.tfvars.example` — Phase 7a
never touches this variable). No task in this plan needs to add or change a DNS record itself
— Task 6's `aws_route53_record.app` (CloudFront alias) and `external-dns` (everything else)
handle that automatically once actually deployed; the one manual step (NS delegation at
`arwest.dev`'s DNS provider) is documented in this plan's header, not a task.
