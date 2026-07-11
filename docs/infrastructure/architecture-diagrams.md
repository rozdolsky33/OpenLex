# Architecture diagrams

Companion to [`aws-eks-cost-estimate.md`](./aws-eks-cost-estimate.md) and
[`mlops-guide.md`](./mlops-guide.md). These render as diagrams directly on GitHub (Mermaid).
Reflects the target architecture from
`docs/decisions/0001-monorepo-restructure.md` plus the AWS/EKS deployment layer, which does
not exist yet (see "Current state" in the root `CLAUDE.md`) — this is where things go once
`infra/kubernetes` and `infra/terraform` stop being placeholders.

## 1. Service topology (logical, environment-agnostic)

```mermaid
flowchart TB
    User(["Browser"])
    Web["apps/web<br/>(Vite/React/TS)"]
    API["apps/api<br/>(FastAPI)"]
    DB[("PostgreSQL + pgvector<br/>documents, chunks<br/>hybrid: cosine ANN + FTS")]
    Claude[["Anthropic API<br/>(claude-sonnet)"]]
    Worker["apps/worker<br/>(scheduled ingestion)"]
    NYAPI[["NY Open Legislation API"]]
    CaseSeed[("seed_cases.json<br/>hand-curated, no public API")]

    User --> Web --> API
    API -- hybrid retrieval --> DB
    API -- grounded generation, answer-only-from-context --> Claude
    Worker -- ingest/normalize/chunk/embed --> DB
    Worker --> NYAPI
    Worker --> CaseSeed
```

## 2. AWS / EKS deployment topology (target — not built yet)

```mermaid
flowchart TB
    subgraph AWS["AWS Account — us-east-1"]
        subgraph VPC["VPC"]
            subgraph Public["Public subnet(s)"]
                NAT["NAT Gateway<br/>(optional — see cost doc)"]
                ALB["ALB / Ingress<br/>(optional in dev)"]
            end
            subgraph Private["Private subnet(s) — or public w/ locked-down SG in lean dev"]
                subgraph EKS["EKS cluster (control plane: $0.10/hr flat, managed by AWS)"]
                    subgraph NodeGroup["Managed node group — e.g. 1x t4g.medium, Spot"]
                        PodAPI["Pod: openlex-api<br/>(FastAPI, HPA 1-2 replicas)"]
                        PodWorker["Pod: openlex-worker<br/>(CronJob or scheduled Deployment)"]
                        PodWeb["Pod: openlex-web<br/>(static, optional in dev)"]
                        PodPG["Pod: postgres+pgvector<br/>StatefulSet + PVC<br/>(or swap for RDS)"]
                    end
                end
            end
        end
        ECR[["ECR<br/>api/worker/web images"]]
        Secrets[["Secrets Manager /<br/>K8s Secret (dev)"]]
        RDS[("RDS PostgreSQL<br/>(alternative to in-cluster PG,<br/>see cost doc)")]
    end

    Internet(("Internet"))
    Claude[["Anthropic API"]]
    NYAPI[["NY Open Legislation API"]]

    Internet --> ALB --> PodAPI
    PodAPI --> PodPG
    PodAPI -.optional swap.-> RDS
    PodWorker --> PodPG
    PodWorker --> NYAPI
    PodAPI --> NAT --> Internet --> Claude
    PodWorker --> NAT
    EKS --> ECR
    PodAPI --> Secrets
    PodWorker --> Secrets
```

Notes:
- No GPU nodes anywhere — `BAAI/bge-small-en-v1.5` embeds on CPU in-process in `apps/api`/
  `apps/worker` (see `ml/model_cards/bge-small-en-v1.5.md`); there is no standalone
  model-serving component (confirmed in `docs/decisions/0001-monorepo-restructure.md`).
- `NAT`, `ALB`, and `RDS` are drawn as optional/alternative because the cost doc recommends
  cutting them for a lean dev environment — see that doc for the tradeoffs.

## 3. Ingestion pipeline data flow

```mermaid
flowchart LR
    NYAPI[["NY Open Legislation API"]] -->|client.py, throttled| Fetch["Fetch raw statute text"]
    CaseSeed[("seed_cases.json<br/>hand-curated")] --> Fetch2["Load raw case text"]
    Fetch --> Normalize["pipelines/normalization"]
    Fetch2 --> Normalize
    Normalize --> Chunk["pipelines/chunking<br/>(legal_parsing)"]
    Chunk --> Embed["pipelines/embeddings<br/>bge-small-en-v1.5, CPU, in-process<br/>(passage text, no prefix)"]
    Embed --> Index["pipelines/indexing"]
    Index --> DB[("documents + chunks<br/>Postgres + pgvector")]
```

## 4. Query-time sequence (grounded answer contract)

```mermaid
sequenceDiagram
    participant U as User
    participant API as apps/api
    participant DB as Postgres (pgvector + FTS)
    participant C as Anthropic API

    U->>API: POST /query {question}
    API->>API: embed query (bge-small, with retrieval-instruction prefix)
    API->>DB: hybrid search (cosine ANN + FTS, combined ranking)
    DB-->>API: top-k chunks + citations
    API->>C: prompt = question + retrieved chunks only
    C-->>API: answer grounded in context (or abstain)
    API-->>U: QueryResponse {answer, citations, abstained, disclaimer}
```

Every `QueryResponse` includes `citations`, `abstained`, and the fixed `DISCLAIMER` string —
see `packages/legal_models/src/legal_models/schemas.py` and the `grounded-answer-contract`
skill. Retrieval and generation code do not exist yet; this is the target flow.
