# AWS EKS cost estimate (dev environment)

Prices below are **us-east-1, on-demand list pricing as of July 2026** (see Sources). Actual
bills vary with region, Savings Plans/Reserved Instances, and usage — treat this as a planning
estimate, not an invoice. Nothing in this doc is deployed yet; `infra/kubernetes` and
`infra/terraform` are still placeholders (see `docs/decisions/0001-monorepo-restructure.md`).
See [`architecture-diagrams.md`](./architecture-diagrams.md) for the topology these numbers
describe, and [`mlops-guide.md`](./mlops-guide.md) for the reasoning behind "which pieces does
this project actually need."

## TL;DR

For a solo-dev POC at OpenLex's current scope (small CPU embedding model, low query volume, no
training pipeline), **the EKS control plane fee is the single largest fixed cost** — bigger
than the compute this workload actually needs. The second-largest avoidable cost is the NAT
Gateway. Cutting both (or running EKS only when actively testing k8s-specific behavior) is the
highest-leverage lever you have.

| Scenario | Monthly infra cost | What's included |
|---|---|---|
| **Leanest dev** (recommended default) | **~$85–95/mo** | EKS control plane, 1 Spot `t4g.medium`, in-cluster Postgres+pgvector, no NAT, no ALB |
| **Robust dev** (RDS + NAT + ALB) | **~$185–230/mo** | Same, plus managed RDS Postgres, a NAT Gateway, and an ALB for external access |
| **Local only** (docker-compose, no AWS) | **$0** | What you already have — see the recommendation in the MLOps guide about when to actually spin up EKS |

Anthropic API usage (Claude generation) is **separate and usage-based** — see [Variable costs](#variable-costs-not-infrastructure) below; it's not an AWS bill line item.

## Fixed infrastructure costs — line by line

| Component | Config | Monthly cost | Notes |
|---|---|---|---|
| **EKS control plane** | 1 cluster, standard support | **$73.00** | Flat `$0.10/hr × 730hr`, regardless of node count or whether pods are running. This is *the* fixed floor of choosing EKS at all. If a cluster's Kubernetes version ages into "extended support" (>14 months old), this jumps to **$0.60/hr (~$438/mo)** — stay current on version upgrades to avoid this. |
| **Node group compute** | 1× `t4g.medium` (2 vCPU, 4GB, Graviton/arm64), **Spot** | **~$7–10** | On-demand is $24.53/mo; Spot for this instance family typically runs 60–70% off. `t4g` (arm64) is ~20% cheaper than equivalent `t3` (x86) and the project's `python:3.11-slim` base images run fine on arm64. One node is enough — FastAPI + a periodic ingestion worker + CPU-only embeddings is a light workload. |
| **Node group compute (on-demand alt.)** | 1× `t4g.medium`, On-Demand | **$24.53** | Use this if you need guaranteed availability (Spot can be reclaimed with 2 min notice) — rarely justified for solo dev. |
| **EBS storage (in-cluster Postgres)** | 20GB gp3, PVC-backed StatefulSet | **~$1.60** | `$0.08/GB-mo`. Cheapest way to get pgvector in dev — same Postgres image/migration (`migrations/postgres/0001_init.sql`) as `docker-compose.yml` already uses. |
| **ECR** | <1GB of images (api/worker/web) | **~$0.10** | Negligible at this scale. |
| **Secrets** (Anthropic key, DB creds, NY Open Leg key) | K8s `Secret` (free) or AWS Secrets Manager | **$0 or ~$1.20** | Use a plain K8s `Secret` in dev (free); reach for Secrets Manager (`$0.40/secret/mo`) only when you need audit trail / rotation, typically staging+. |
| **Data transfer (intra-VPC, low volume)** | dev traffic only | **~$0–2** | Immaterial until you have real users. |
| **NAT Gateway** *(optional — see recommendation)* | 1 gateway, light traffic | **$32.40 + $0.045/GB processed** | Needed only if nodes sit in a private subnet and need outbound internet (pulling images, calling the Anthropic/NY Open Legislation APIs). **Recommendation for lean dev: skip it** — put the node group in a public subnet with a security group that allows outbound-only (no inbound from the internet except from the ALB/your IP if you add one). This is the second-biggest cost lever after the control plane fee. |
| **ALB / Ingress** *(optional — see recommendation)* | 1 ALB, low request volume | **$16.20 + ~$/LCU-hr** | Only needed if you want a stable public URL. For solo dev, `kubectl port-forward` or a `NodePort` gets you access without paying for a load balancer at all. Add the ALB back when you want to demo to others or move toward staging. |
| **RDS PostgreSQL** *(alternative to in-cluster PG)* | `db.t4g.micro`, Single-AZ, 20GB gp3 | **~$14** (`$11.68` compute + `~$2.30` storage) | pgvector is supported on RDS PostgreSQL 15.9+/16.5+/17.1+ (pgvector 0.8.2 as of mid-2026), so this is a drop-in option. Costs more than self-hosting on the cluster you're already paying for, but gets you automated backups/PITR and no StatefulSet to babysit. **Recommendation: self-host in dev, move to RDS for staging/prod** once you care about durability guarantees more than dev-loop cost. |
| **CloudWatch Container Insights / Managed Prometheus** *(optional)* | not enabled | **$0** | Skip until there's real traffic worth alerting on. `infra/monitoring/{grafana,prometheus}` are still placeholders for a reason — don't pay for observability infra before there's a signal to observe (see MLOps guide). |
| **Self-hosted observability stack** *(optional — see `docs/superpowers/specs/2026-07-12-production-observability-design.md`)* | not enabled on `eks-demo` (kind-only for now) | **~$15–25/mo if enabled** | The kind design (kube-prometheus-stack + Tempo + Jaeger + Loki + OTel Collector + postgres_exporter) is built to be portable via shared Helm values files, but it will not fit alongside the app on the current single Spot `t4g.medium` — needs either a second Spot `t4g.medium` (~$8–10) or bumping the existing node to `t4g.large` Spot (~$15–20), plus a few GB of extra gp3 for Tempo/Loki local storage (~$0.50–1). This replaces the vague "Managed Prometheus, optional, $0" framing above with the actual cost of the design this repo is standardizing on, if/when `eks-demo` turns it on. |

### Leanest dev total

```
EKS control plane        $73.00
Node (1x t4g.medium Spot)  $8.00
EBS 20GB gp3               $1.60
ECR                        $0.10
Secrets (K8s Secret)       $0.00
NAT Gateway                $0.00   (skipped — public subnet + locked-down SG)
ALB                        $0.00   (skipped — port-forward for access)
----------------------------------
≈ $83/month
```

### Robust dev total (adds managed DB, NAT, public ingress)

```
EKS control plane          $73.00
Node (1x t4g.medium, OD)   $24.53
NAT Gateway (+ light data) $35–40
ALB (+ light LCU)          $17–20
RDS db.t4g.micro + 20GB    $14.00
ECR                         $0.10
----------------------------------
≈ $185–230/month, before AWS Free Tier credit
```

## The biggest cost-reduction lever: don't run EKS 24/7

Because the EKS control plane bills **hourly per cluster**, the cheapest possible EKS bill is
achieved by not having a cluster running when you're not using it — not by shrinking nodes
further (nodes are already the cheap part here).

- **Use `docker-compose` for day-to-day iteration.** It's already fully wired up
  (`docker compose up --build`) and costs $0. Reach for EKS only when you specifically need to
  validate k8s-shaped behavior: autoscaling, rolling deploys, ingress, secrets wiring, or a
  demo environment.
- **Spin the cluster up/down around sessions**: `eksctl create cluster` /
  `eksctl delete cluster` (or equivalent Terraform apply/destroy once `infra/terraform` is
  real). A cluster that exists 40 hours/month instead of 730 costs **~$4/mo** in control-plane
  fees instead of $73.
- If you want an always-on dev cluster anyway (e.g., for a persistent demo URL), scale the
  node group to 0 outside working hours via a scheduled Cluster Autoscaler/Karpenter policy or
  a cron-triggered `eksctl scale nodegroup` — this saves the ~$8–25/mo node cost but **not**
  the $73/mo control-plane fee, which is why cluster lifecycle (not node count) is the real
  lever.

## Variable costs (not infrastructure)

These scale with usage, not with the AWS resources above, and won't show up on an AWS bill:

| Item | Rate (Claude Sonnet 4.5, July 2026) | Example |
|---|---|---|
| Anthropic API — input tokens | $3.00 / 1M tokens | |
| Anthropic API — output tokens | $15.00 / 1M tokens | |
| Anthropic API — cached input | up to 90% cheaper | worth using for repeated system prompts / retrieved-context reuse across the eval harness |
| Anthropic API — Batch API | 50% off both directions | good fit for `tests/evaluation`'s golden-question runs, which aren't latency-sensitive |

**Example**: 200 dev/test queries/day, ~1,500 input tokens (question + retrieved chunks) +
500 output tokens each ≈ 300K input + 100K output tokens/day ≈ 9M input + 3M output
tokens/month → `9 × $3 + 3 × $15 = $27 + $45 = ~$72/month` at list price, well under half of
that if you lean on prompt caching for the shared system prompt/disclaimer text and batch the
evaluation harness runs. This is genuinely bursty/usage-driven — track it separately from the
AWS bill, since it has nothing to do with cluster size.

The NY Open Legislation API is free (public, rate-limited, already throttled by
`_REQUEST_DELAY_SECONDS` in `pipelines/ingestion/ny_legislation/client.py`); case-law is a
hand-curated local seed file, so ingestion itself has no external API cost.

## What this project deliberately does NOT need (and why that keeps cost down)

- **No GPU nodes.** `bge-small-en-v1.5` is a ~130M-parameter CPU-friendly embedding model,
  loaded in-process — see `ml/model_cards/bge-small-en-v1.5.md`. This avoids by far the
  largest typical "ML infra" cost (GPU instances are 5–20x+ the price of the CPU nodes used
  here).
- **No training pipeline / no managed training service** (SageMaker, etc.) — generation calls
  the Anthropic API; embeddings are off-the-shelf. `ml/training` and `ml/experiments` are
  intentionally empty stubs, not a cost center today (see
  `docs/decisions/0001-monorepo-restructure.md`).
- **No object storage** — documents are stored as JSONB in Postgres, not as files in S3, so
  there's no S3 storage/request cost to budget for yet.
- **No standalone model-serving component** — one less service to run, patch, and pay compute
  for.

## Sources

- [Amazon EKS Pricing](https://aws.amazon.com/eks/pricing/)
- [EKS Pricing in 2026: The $438/Month Trap](https://cloudburn.io/blog/amazon-eks-pricing)
- [Amazon VPC Pricing (NAT Gateway)](https://aws.amazon.com/vpc/pricing/)
- [t4g.small pricing](https://www.economize.cloud/resources/aws/pricing/ec2/t4g.small/) /
  [t4g.medium pricing](https://www.economize.cloud/resources/aws/pricing/ec2/t4g.medium/)
- [Amazon RDS for PostgreSQL Pricing](https://aws.amazon.com/rds/postgresql/pricing/)
- [RDS PostgreSQL pgvector extension support](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html)
- [Claude Sonnet 4.5 API pricing](https://platform.claude.com/docs/en/about-claude/pricing)
