CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source          TEXT NOT NULL,           -- 'ny_open_legislation' | 'ny_official_reports_seed'
    doc_type        TEXT NOT NULL,           -- 'statute' | 'case'
    jurisdiction    TEXT NOT NULL DEFAULT 'NY',
    citation        TEXT NOT NULL,           -- e.g. 'RPAPL § 711' or a case citation
    title           TEXT,
    source_id       TEXT NOT NULL,           -- lawId+locationId, or seed case key
    effective_date  DATE,
    decision_date   DATE,
    court           TEXT,
    version         INT NOT NULL DEFAULT 1,
    raw_snapshot    JSONB NOT NULL,          -- immutable raw fetched/seed content
    url             TEXT,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id, version)
);

CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INT NOT NULL,
    section_label   TEXT,                    -- '(a)', 'background', 'holding', etc.
    heading_path    TEXT,                    -- e.g. 'RPAPL > Art 7 > § 711 > (2)'
    text            TEXT NOT NULL,
    token_count     INT,
    embedding       VECTOR(384),             -- must match EMBEDDING_MODEL_NAME dim
    tsv             TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);
CREATE INDEX IF NOT EXISTS idx_documents_doc_type ON documents (doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_jurisdiction ON documents (jurisdiction);
CREATE INDEX IF NOT EXISTS idx_documents_citation ON documents (citation);
