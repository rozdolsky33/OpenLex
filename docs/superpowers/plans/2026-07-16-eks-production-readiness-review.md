# EKS production-readiness review + remediation plan

**Date:** 2026-07-16
**Cluster:** `openlex-eks-demo` (us-east-1)
**Reviewer:** kubernetes-specialist pass over live cluster state
**Context:** OpenLex is a portfolio POC where **SRE/Platform depth is the product being
demonstrated** (see `CLAUDE.md`). So platform/prod-readiness gaps are high-value to close, even
though the legal corpus itself is only "credible, not complete." This review assesses the
cluster against standard production-readiness criteria, records the gaps found against **live**
state, and lays out a phased remediation plan.

## What's already solid (baseline)

Verified present and healthy — not gaps, recorded so the review is honest about the baseline:

- **Secrets:** External Secrets Operator + AWS Secrets Manager; no plaintext creds in ConfigMaps
  (checked). RDS creds, Anthropic key, JWT secret all sourced via `ExternalSecret`.
- **TLS:** cert-manager + Let's Encrypt prod on the public API/Grafana ingresses; `ssl-redirect`.
- **Identity:** app pods use dedicated ServiceAccounts (`openlex-api`, `openlex-worker`), not
  `default`; no k8s RBAC granted to them (correct — they don't call the API server).
- **Resources:** requests+limits set on api and worker (`250m/512Mi` → `1/1Gi`).
- **Disruption:** `openlex-api` PDB (`minAvailable: 1`).
- **Observability:** 36 PrometheusRules incl. `kube-prometheus-stack-openlex-symptom-alerts`
  (symptom-based) + apiserver SLOs; Alertmanager configured. This is a real strength.
- **Data durability:** RDS `storage_encrypted=true`, `publicly_accessible=false`,
  `backup_retention_period` set, final snapshot on delete.

## Findings

Severity: 🔴 P0 = availability/security risk · 🟠 P1 = resilience/operational · 🟡 P2 = hardening.

### 🔴 P0-1 — App HA is illusory (both replicas, one node, one AZ)

Both `openlex-api` replicas were scheduled onto the **same node** (`ip-10-42-22-132`), and
**both `apps` nodes are in us-east-1b** — no AZ redundancy. A single node or AZ failure takes
the whole API down despite `replicas: 2` + a PDB.

- **Cause:** the `apps` node group is SPOT with `min=max=2`; spot capacity placed both instances
  in 1b, and `overlays/eks-demo/patch-resources.yaml` uses `preferredDuringScheduling` (soft)
  pod anti-affinity, which permits co-location.
- The soft anti-affinity was itself a workaround for `t4g.medium`'s low max-pods (a hard rule
  stranded the 2nd replica Pending). That constraint is **gone** — nodes now report
  `max-pods=110` (see the 2026-07-16 postmortem), so hard spreading is safe again.

### 🔴 P0-2 — Kubernetes API server open to the internet — ACCEPTED RISK (not remediating)

`endpointPublicAccess=true`, `publicAccessCidrs=["0.0.0.0/0"]`, private access off. The control
plane is reachable from anywhere.

**Decision (2026-07-16):** left public **by choice** for this demo — the operator runs `kubectl`
from changing home/mobile networks and locking to a CIDR adds friction disproportionate to a
POC with no real data. Recorded here as a **known, accepted risk**, not an open gap. Mitigations
that remain in force: EKS AuthN/AuthZ (IAM + access entries), audit logging, and no anonymous
access. If this ever moved toward real GA, the fix is
`cluster_endpoint_public_access_cidrs = [<admin CIDR>]` and/or enabling the private endpoint.

### 🔴 P0-3 — App pods run unconfined; no Pod Security Admission

`securityContext` is empty on both api and worker → containers run as **root**, writable root
filesystem, all Linux capabilities, `allowPrivilegeEscalation` defaulting true. No namespace
carries a `pod-security.kubernetes.io/enforce` label, so nothing stops a privileged pod.

### 🔴 P0-4 — No NetworkPolicies (default allow-all)

Only the argocd chart ships NetworkPolicies. `openlex` and `observability` have none, so any
pod can reach RDS, every other namespace, and the internet unrestricted — no blast-radius
containment if a pod is compromised.

### 🟠 P1-5 — Worker has no health probes

`openlex-worker` has neither liveness nor readiness probe. A hung/deadlocked worker won't be
detected or restarted; it just silently stops making progress.

### 🟠 P1-6 — ingress-nginx is a single replica

`ingress-nginx-controller` runs `replicas: 1`. It terminates TLS and serves every north-south
request (and the oauth2 auth subrequests). If that pod dies, all ingress is down until it
reschedules — a SPOF for the entire public surface.

### 🟠 P1-7 — RDS is single-AZ

No `multi_az` in `rds.tf`. The database — the one truly stateful component — is a single-AZ
SPOF. An AZ event takes the app down and risks an RTO measured by restore time.

### 🟡 P2-8 — Observability is a single node (undocumented tradeoff)

All of Prometheus/Grafana/Loki/Tempo/Jaeger/Alertmanager (12 pods) run on one `observability`
node in us-east-1a, with PVCs AZ-pinned there. The node is now `ON_DEMAND` (good — no spot
reclaim), but it's still a SPOF: losing it takes down all telemetry **and** Grafana SSO, and
the PVCs can't move AZs. Acceptable for a cost-conscious demo — but should be an **explicit,
documented** decision, not an accident.

### 🟡 P2-9 — ServiceAccount tokens auto-mounted unnecessarily

`automountServiceAccountToken` is unset (defaults true) on the app SAs, yet the app never calls
the k8s API. A mounted token is needless credential exposure.

### 🟡 P2-10 — No ResourceQuota / LimitRange

No namespace has a quota or default LimitRange. Nothing bounds aggregate namespace consumption
or supplies default limits to a pod that forgets them.

### 🟡 P2-11 — Public API ingress lacks edge protections

No rate-limiting, `proxy-body-size` cap, or security-header annotations on the `openlex-api`
ingress — a public, unauthenticated-at-the-edge endpoint.

### 🟡 P2-12 — No HPA

Fixed replica counts; no horizontal autoscaling on load. Fine for steady demo traffic, but no
burst handling and nothing to demonstrate reactive scaling.

## Remediation plan (phased, each phase = one `develop → main` PR)

### Phase A — P0 (manifest-first; highest ROI)

1. **HA spread (P0-1):** in `overlays/eks-demo/patch-resources.yaml`, replace the soft pod
   anti-affinity with a hard **`topologySpreadConstraints`**: `maxSkew: 1`,
   `topologyKey: topology.kubernetes.io/zone`, `whenUnsatisfiable: DoNotSchedule`,
   `labelSelector` = api. Also ensure the node group actually straddles both AZs — the module
   already passes both public subnets; add ASG capacity-rebalance / one-subnet-per-AZ so SPOT
   doesn't pool both nodes in one AZ. Verify: the two api pods land in different AZs.
2. **securityContext (P0-3):** on api + worker containers — `runAsNonRoot: true`,
   `runAsUser: <uid>`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`,
   `readOnlyRootFilesystem: true` with an `emptyDir` for any writable path (e.g. the HF/BGE
   model cache the api warms at startup — must confirm the image's writable dirs, flag if the
   image needs a change rather than a manifest-only fix).
3. **Pod Security Admission (P0-3):** label namespaces —
   `pod-security.kubernetes.io/enforce=restricted` on `openlex`; `baseline` on `observability`
   and `ingress-nginx` (they legitimately need more). Add `warn`/`audit` first if we want a dry
   run before enforce.
4. **NetworkPolicies (P0-4):** default-deny ingress+egress in `openlex`, then explicit allows:
   ingress-nginx→api:8000, api/worker→RDS:5432, api/worker→OTel collector, and DNS egress
   (kube-dns:53). Mirror a default-deny + scoped-allow set in `observability`.

*API endpoint (P0-2) is intentionally excluded — accepted risk, see above.*

### Phase B — P1

5. **Worker probes (P1-5):** add liveness/readiness (a lightweight process/health check or
   queue-heartbeat; the worker isn't an HTTP server, so likely an `exec` probe).
6. **ingress-nginx HA (P1-6):** `controller.replicaCount: 2` + PDB + pod anti-affinity across
   nodes/AZs in `app-ingress-nginx.yaml`.
7. **RDS multi-AZ (P1-7):** `multi_az = true` in `rds.tf` — note the ~2× instance cost; flag as
   a deliberate cost decision the reviewer signs off on before applying.

### Phase C — P2 (hardening/polish)

8. SA `automountServiceAccountToken: false` (P2-9).
9. `LimitRange` (default requests/limits) + `ResourceQuota` per app namespace (P2-10).
10. Ingress edge protections: `nginx.ingress.kubernetes.io/limit-rps`, `proxy-body-size`,
    security-header annotations (P2-11).
11. Optional HPA on api (CPU + a custom RPS metric) (P2-12).
12. **Document** the single-node observability tradeoff in `docs/infrastructure/aws-eks-cost-estimate.md` (P2-8).

## Validation (after each phase)

Run `scripts/eks/verify.sh` (added 2026-07-16) plus, per phase:

- **A:** `kubectl -n openlex get pods -l app.kubernetes.io/name=openlex-api -o wide` shows two
  different AZs; `kubectl auth`/PSA dry-run shows no `restricted` violations; a test pod in
  `openlex` cannot reach a disallowed endpoint (NetPol enforced).
- **B:** kill the ingress-nginx pod → no request drop (2nd replica serves); `kubectl -n openlex
  describe pod <worker>` shows probes; RDS console shows Multi-AZ.
- **C:** SA token absent from pod (`ls /var/run/secrets/...` fails); LimitRange applied; ingress
  returns 429 past the rate limit.

## Sequencing note

Every change flows `feature/fix → develop → main` (never a feature branch straight to `main`).
Phase A should go out as one reviewable PR so the P0s land together; B and C can follow
independently. RDS Multi-AZ (B-7) and any node-group AZ change (A-1) trigger slow AWS
operations (~10-min rolls / DB modify) — batch and expect the apply to take time.
