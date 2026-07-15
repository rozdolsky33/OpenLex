# Integration tests

Cross-package tests that hit a real Postgres (e.g. `legal_retrieval` querying actual
`documents`/`chunks` rows), as opposed to unit tests that mock the DB.

## Running

```bash
scripts/test/test-db.sh up     # starts the db-test docker-compose service (pgvector/pg16, port 5544)
uv run pytest             # or: uv run pytest tests/integration
```

`db_session` (`conftest.py`) connects to `postgresql+asyncpg://openlex_test@127.0.0.1:5544/openlex_test`
by default — override with the `TEST_DATABASE_URL` env var to point at any other Postgres+pgvector
instance instead. `db-test` is deliberately separate from docker-compose's dev `db` service (own
port, own container, gated behind the `test` Compose profile) so integration tests never read or
write dev data, and a plain `docker compose up` never starts it.

Each test gets a session on the same long-lived database and rolls its transaction back at
teardown (see `db_session` in `conftest.py`) — tests don't share committed state, but nothing
resets the schema between runs. Re-apply it after changing `migrations/postgres/0001_init.sql`:

```bash
scripts/test/test-db.sh reset
```

`scripts/test/test-db.sh down` stops and removes the container; its data dir is tmpfs (in-memory), so
there's nothing to clean up on disk.
