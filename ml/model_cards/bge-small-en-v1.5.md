# Model card: BAAI/bge-small-en-v1.5

- **Used for**: chunk + query embeddings (`chunks.embedding`, `VECTOR(384)` in
  `migrations/postgres/0001_init.sql`), loaded in-process via `sentence-transformers`
  wherever `settings.embedding_model_name` is read (currently `packages/shared`'s config).
- **Output dimension**: 384. This is a hard constraint — see the `openlex-data-model` skill.
  Changing `EMBEDDING_MODEL_NAME` to a model with a different output dimension requires a
  migration to resize the `embedding` column and re-embedding every existing chunk.
- **Family**: BGE ("BAAI General Embedding"), small English variant, from BAAI's
  FlagEmbedding project. General-purpose sentence/passage embedding model, not
  legal-domain-specific or fine-tuned on legal text.
- **License**: MIT (verify against the upstream model card/repo before relying on this for
  compliance purposes — don't treat this doc as the license source of truth).
- **Retrieval usage note**: BGE models are trained asymmetrically for retrieval — query text
  is conventionally prefixed with an instruction (e.g. `"Represent this sentence for
  searching relevant passages: "`) before embedding, while passage/chunk text is embedded
  as-is, with no prefix. Whoever implements `packages/legal_retrieval`'s query-embedding path
  should apply this prefix; skipping it measurably hurts retrieval quality for this model
  family. Passage text stored in `chunks.embedding` should NOT include the prefix.
- **Known limitation for this project**: general-purpose training means it wasn't tuned on
  landlord-tenant statute/case language specifically — if retrieval quality on legal jargon
  or citation-style queries turns out weak, that's a candidate root cause, and `ml/experiments`
  is a plausible place to try fine-tuning on the golden question set (see
  `docs/decisions/0001-monorepo-restructure.md`).
