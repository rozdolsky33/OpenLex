# MLOps guide for OpenLex (start here if you're new to this)

This is a walkthrough of what "MLOps" actually means *for this specific project*, written for
someone who hasn't run an ML/LLM pipeline in production before. Pair it with
[`architecture-diagrams.md`](./architecture-diagrams.md) (what the system looks like) and
[`aws-eks-cost-estimate.md`](./aws-eks-cost-estimate.md) (what it costs) — this doc is the
"why" and "how to run it well" connective tissue between them.

## First, recalibrate what "MLOps" means here

Classic MLOps content assumes you're training and redeploying models. **OpenLex doesn't train
anything.** There's no training loop, no GPU cluster, no model registry to babysit. What you
actually have is closer to **"LLMOps" / "retrieval-ops"**:

- A **retrieval pipeline** (statutes/cases → chunks → embeddings → a searchable index).
- A **generation step** that's just an API call to Claude, constrained to answer only from
  retrieved context (the `grounded-answer-contract`).
- An **evaluation harness** (`tests/evaluation`) that checks retrieval+generation quality
  against a golden question set, instead of checking model accuracy metrics.

This matters for cost and effort: the hard, expensive parts of "real" MLOps (training
infrastructure, GPU scheduling, model versioning/rollback, feature stores) don't apply. Your
job is closer to running a well-behaved data pipeline + API service than to running an ML
platform.

## The pipeline, stage by stage

```
Ingest → Normalize → Chunk → Embed → Index → Retrieve → Generate → Evaluate → Monitor
└──────────── apps/worker, pipelines/ ────────────┘   └── apps/api ──┘   └ tests/evaluation ┘
```

| Stage | Code location | What it does | Where cost comes from |
|---|---|---|---|
| Ingest | `pipelines/ingestion/{ny_legislation,ny_case_law}` | Fetch statute text from NY Open Legislation API; load hand-curated case-law seed JSON | Free (public API, no infra needed beyond the worker pod) |
| Normalize | `pipelines/normalization` | Clean/standardize raw text into a common `Document` shape | CPU, negligible |
| Chunk | `pipelines/chunking` (via `packages/legal_parsing`) | Split documents into retrieval-sized passages | CPU, negligible |
| Embed | `pipelines/embeddings` | Run `bge-small-en-v1.5` (CPU, in-process) over each chunk to get a 384-dim vector | CPU time on whatever node runs the worker — no GPU, no external API cost |
| Index | `pipelines/indexing` | Write `documents`/`chunks` rows into Postgres, populate `embedding` (pgvector) and `tsv` (FTS) columns | Postgres storage (cheap — see cost doc) |
| Retrieve | `packages/legal_retrieval` (not yet implemented) | Hybrid pgvector cosine-ANN + Postgres full-text search, combined at query time | Postgres compute, already paid for |
| Generate | `packages/legal_generation` (not yet implemented) | Build a prompt from *only* retrieved chunks, call Claude, enforce citations/abstain/disclaimer | **This is the variable, usage-based cost** — see cost doc |
| Evaluate | `tests/evaluation` (no `golden_questions.yaml` yet) | Run golden questions through the full pipeline, check retrieval/citation/abstain correctness | Same Claude API cost as generation, run less often — batch it |

Everything left of "Retrieve" runs on a schedule (`apps/worker`); everything from "Retrieve"
onward runs per-request (`apps/api`). That split is why the worker can be a low-frequency
CronJob-style workload while the API needs to stay responsive — they have very different
scaling needs, which matters once you're deciding pod counts/HPA settings on EKS.

## Environments: use the right one for the job

| Environment | Run via | Use for | Cost |
|---|---|---|---|
| **Local** | `docker compose up --build` (already works today) | 95% of your iteration: writing retrieval/generation code, debugging ingestion, running `pytest` | $0 |
| **Dev on EKS** | `infra/kubernetes` + `infra/terraform` (placeholders today — build these when you actually need k8s-shaped testing) | Validating deploy manifests, autoscaling behavior, secrets wiring, demoing to someone else | ~$83–230/mo, see cost doc — and only while the cluster exists |
| **Staging/Prod** | Same manifests, hardened config (RDS, NAT, ALB, real monitoring, alerting) | Actual users | Scales with real traffic — budget separately when you get there |

**The single most common MLOps-newcomer mistake is developing directly against a cloud
cluster.** Every code-test-fix loop against EKS costs money and is slower (image build → push
→ pod restart) than against local `docker-compose` (hot reload, `apps/api/Dockerfile` already
runs `uvicorn --reload`). Keep using `docker compose` for day-to-day work; treat EKS as a
periodic checkpoint, not your main dev loop.

## CI/CD — what already exists and why

`.github/workflows/{api,web,pipelines,evaluation,security}.yml` are path-filtered (see
`docs/decisions/0001-monorepo-restructure.md`) so a frontend change doesn't re-run the Python
suite. The intended stage order:

```
lint → unit tests → schema validation → integration tests → container build
     → retrieval/generation evaluation → security scanning → deploy
```

Two things worth understanding as you build this out:

1. **The evaluation stage is the expensive one.** It's the only stage that calls the real
   Claude API (or should — don't let unit tests hit the live API; mock/stub there). Gate it to
   only run when `packages/legal_retrieval`, `packages/legal_generation`, or `ml/prompts/**`
   change — already the plan per the path-filtering strategy — and use the Batch API (50% off)
   for the golden-question run since it's not latency-sensitive.
2. **GitHub Actions minutes have their own cost** (free tier, then per-minute) separate from
   AWS — usually immaterial at this scale, but worth knowing it's a second, smaller bill if the
   test suite grows slow.

## Cost-efficiency practices specific to this kind of pipeline

1. **Separate your three cost buckets mentally**: (a) fixed AWS infra (EKS control plane,
   nodes, storage — see cost doc), (b) variable Anthropic API usage (scales with query/eval
   volume), (c) free/near-free ingestion (public API + local seed file). Don't let infra
   decisions (a) leak into how you think about (b) — they're optimized completely differently
   (a: right-size and don't over-provision; b: cache and batch).
2. **Cache and batch the expensive calls.** Prompt caching (repeated system prompt/disclaimer
   text, and potentially repeated retrieved-context across similar eval questions) is up to 90%
   cheaper input; the Batch API is 50% off for anything non-interactive like the eval harness.
3. **No GPU, ever, for this architecture** — if a future change (e.g., fine-tuning embeddings
   in `ml/experiments`, per the decision doc's "known limitation" note in the model card) makes
   you consider self-hosting a model, that's the point to redo this cost estimate, since GPU
   nodes are a different cost tier entirely (5–20x+ CPU nodes).
4. **Don't stand up monitoring before there's a signal.** `infra/monitoring/{prometheus,
   grafana}` are placeholders on purpose. Managed Prometheus/CloudWatch Container Insights cost
   money and add operational surface — wire them up once `apps/api`/`apps/worker` actually
   expose metrics worth alerting on, not preemptively.
5. **Right-size storage growth, not just compute.** `documents.raw_snapshot` is JSONB in
   Postgres (no object storage yet, per the decision doc) — as case-law/statute volume grows,
   watch Postgres storage cost, not just compute; that's a much slower-growing number here than
   in a typical file-heavy ML pipeline, but it's not zero.
6. **Cluster lifecycle is the biggest lever, not instance size** — see the cost doc's section
   on this. Internalize that a $73/mo control-plane fee exists whether the cluster is busy or
   idle; the way to not pay it is to not have the cluster exist when you're not using it.

## A concrete "first time running this on EKS" checklist

Once `infra/terraform`/`infra/kubernetes` have real content (they don't yet — this is the
sequence to build toward, not a today-list):

1. Build and push `apps/api`, `apps/worker`, `apps/web` images to ECR.
2. Provision the cheapest viable cluster: 1 managed node group, `t4g.medium`, Spot, public
   subnet with outbound-only security group (skip NAT — see cost doc).
3. Deploy Postgres as a StatefulSet + 20GB gp3 PVC, initialized from
   `migrations/postgres/0001_init.sql` (same file `docker-compose.yml` already uses — no
   drift between local and cluster schema).
4. Deploy `openlex-api` and `openlex-worker` as separate Deployments — the API wants an HPA
   (it's request-driven); the worker wants a CronJob or a low-replica Deployment (it's
   schedule-driven, per the pipeline table above).
5. Wire secrets (`ANTHROPIC_API_KEY`, `DATABASE_URL`, `NY_OPEN_LEG_API_KEY`) via a plain K8s
   `Secret` in dev — reach for Secrets Manager + IRSA only once you're past solo-dev.
6. Skip the ALB; use `kubectl port-forward svc/openlex-api 8000:8000` for access. Add the ALB
   back only when you need a stable public URL.
7. When you're done for the session: `eksctl delete cluster` (or `terraform destroy` once
   that's the real tool). You keep all your code, images (in ECR), and migrations — you're
   only tearing down the hourly-billed control plane and nodes.

## Glossary (short, for the k8s/AWS terms above)

- **Control plane**: the managed Kubernetes brain (API server, scheduler, etcd) — AWS runs
  this for you on EKS, billed flat hourly regardless of your workload.
- **Node group**: the actual EC2 instances that run your pods. Autoscales independently of the
  control plane.
- **Spot vs. On-Demand**: Spot is spare EC2 capacity at a steep discount that AWS can reclaim
  with ~2 min notice; fine for a stateless API pod behind an HPA, less fine for something with
  no replicas.
- **HPA (Horizontal Pod Autoscaler)**: scales pod *replica count* up/down based on load —
  relevant for `openlex-api`, not really for `openlex-worker`.
- **PVC (Persistent Volume Claim)**: how a pod gets a durable EBS volume — used for the
  in-cluster Postgres option.
- **Ingress / ALB**: how traffic gets from the internet into the cluster — optional cost in
  dev (see cost doc).
- **IRSA (IAM Roles for Service Accounts)**: lets a pod assume an AWS IAM role (e.g., to read
  Secrets Manager) without static credentials — a staging/prod concern, skippable in dev.
