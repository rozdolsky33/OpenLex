# Integration tests

Cross-package tests that hit a real Postgres (e.g. `legal_retrieval` querying actual
`documents`/`chunks` rows), as opposed to unit tests that mock the DB. Nothing here yet —
`apps/api/`, `packages/legal_retrieval/`, and `packages/legal_generation/` don't have
implementations to integration-test yet.
