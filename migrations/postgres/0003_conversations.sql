CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id      UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_index           INT NOT NULL,
    question             TEXT NOT NULL,
    standalone_question  TEXT,             -- reformulated query used for retrieval; null on turn 0
    answer               TEXT NOT NULL,
    citations            JSONB NOT NULL,   -- serialized Citation[]
    abstained            BOOLEAN NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, turn_index)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages (conversation_id);
