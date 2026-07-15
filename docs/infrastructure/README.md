# Infrastructure & cost planning

Docs for how OpenLex actually runs, locally and on AWS EKS. `infra/kubernetes/overlays/kind`
and its ArgoCD/CI-CD pipeline are real and live as of 2026-07-14 (see
`dev-workflow-and-branching.md`); `infra/terraform`'s EKS layer is still a placeholder
target, not something deployed (see `docs/decisions/0001-monorepo-restructure.md`).

- **[dev-workflow-and-branching.md](./dev-workflow-and-branching.md)** — how a change actually
  flows through the repo day to day: `docker-compose` (local) → `develop`/kind (staging,
  real ArgoCD GitOps pipeline) → `main` (production, not built yet). Diagrams, a day-to-day
  cheat sheet, and an honest tradeoff writeup (including two real bugs this pipeline caught).
- **[kubernetes-topology.md](./kubernetes-topology.md)** — the kind cluster's actual node
  topology: taints, labels, scheduling/anti-affinity, PodDisruptionBudgets, an honest
  explanation of what this does and doesn't prove about HA, local hardware/tooling
  requirements to run it, and how it contrasts with `eks-demo`'s (currently single-node,
  no-HA) topology.
- **[architecture-diagrams.md](./architecture-diagrams.md)** — service topology, AWS/EKS
  deployment layout, ingestion data flow, and the query-time sequence.
- **[aws-eks-cost-estimate.md](./aws-eks-cost-estimate.md)** — line-item monthly cost estimate
  for a cost-effective dev EKS setup (~$83–95/mo lean, ~$185–230/mo with managed DB/NAT/ALB),
  plus the Anthropic API's separate usage-based cost.
- **[mlops-guide.md](./mlops-guide.md)** — a from-scratch walkthrough of what "MLOps" means
  for this project (it's closer to LLMOps/retrieval-ops — no training pipeline, no GPUs),
  how the pipeline stages map to cost, and how to build/run it efficiently.
- **[dns-subdomain-delegation.md](./dns-subdomain-delegation.md)** — the one manual,
  registrar-side step to point a subdomain (e.g. `openlex.example.com`) at its Route 53 hosted
  zone: take the zone's four nameservers and publish them as `NS` records at the parent
  domain's DNS host. Registrar-agnostic, with verification and gotchas.
- **[web-deploy.md](./web-deploy.md)** — how `apps/web` ships to prod (S3 + CloudFront via
  `deploy-static.yml`), the four GitHub Actions variables it needs and where each comes from,
  the `scripts/eks/github-deploy-vars.sh` automation that sets them from Terraform outputs, the
  DNS/ACM gate that blocks the apply, and a troubleshooting matrix.
- **[eks-argocd-bootstrap.md](./eks-argocd-bootstrap.md)** — the one-time GitOps bootstrap for
  the in-cluster app + platform stack on `openlex-eks-demo`: the ordered prerequisites (kube
  access, the full table of manifest placeholders to fill and where each value comes from, the
  GHCR→ECR image gap, secrets), running `argocd-bootstrap.sh eks-demo`, and the steady-state
  image-update flow.

**TL;DR if you only read one thing**: the EKS control-plane fee ($73/mo flat, regardless of
workload) is the biggest fixed cost for a project this size — bigger than the compute it
actually needs. Keep using local `docker-compose` for day-to-day iteration ($0, and now has
its own observability stack — see `dev-workflow-and-branching.md`), use the local kind cluster
when you want the real GitOps/CI-CD pipeline exercised, and only stand up EKS when you
actually need to test k8s-specific cloud behavior or demo to someone else — ideally tearing
the cluster down between sessions, since that fee is billed hourly per cluster.
