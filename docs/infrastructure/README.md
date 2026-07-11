# Infrastructure & cost planning

Docs for running OpenLex on AWS EKS, written while `infra/kubernetes` and `infra/terraform`
are still placeholders (see `docs/decisions/0001-monorepo-restructure.md`) — these describe
the target, not something already deployed.

- **[architecture-diagrams.md](./architecture-diagrams.md)** — service topology, AWS/EKS
  deployment layout, ingestion data flow, and the query-time sequence.
- **[aws-eks-cost-estimate.md](./aws-eks-cost-estimate.md)** — line-item monthly cost estimate
  for a cost-effective dev EKS setup (~$83–95/mo lean, ~$185–230/mo with managed DB/NAT/ALB),
  plus the Anthropic API's separate usage-based cost.
- **[mlops-guide.md](./mlops-guide.md)** — a from-scratch walkthrough of what "MLOps" means
  for this project (it's closer to LLMOps/retrieval-ops — no training pipeline, no GPUs),
  how the pipeline stages map to cost, and how to build/run it efficiently.

**TL;DR if you only read one thing**: the EKS control-plane fee ($73/mo flat, regardless of
workload) is the biggest fixed cost for a project this size — bigger than the compute it
actually needs. Keep using local `docker-compose` for day-to-day iteration (already fully
wired up, $0), and only stand up EKS when you need to test k8s-specific behavior or demo to
someone else — ideally tearing the cluster down between sessions, since that fee is billed
hourly per cluster.
