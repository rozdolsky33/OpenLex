ALTER TABLE users
    ADD COLUMN tier TEXT NOT NULL DEFAULT 'silver'
        CHECK (tier IN ('silver', 'gold', 'platinum')),
    ADD COLUMN request_count INT NOT NULL DEFAULT 0,
    ADD COLUMN period_started_at TIMESTAMPTZ NOT NULL DEFAULT now();
