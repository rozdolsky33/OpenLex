## What & why

<!-- What does this change do, and why? Link an issue/ADR if relevant. -->

## Checklist

- [ ] `ruff check .` && `ruff format --check .` pass
- [ ] `mypy apps packages` passes
- [ ] `pytest -m "not evaluation"` passes
- [ ] `tests/integration` passes (if this touches retrieval, ingestion, migrations, or ORM
      models — run `scripts/test-db.sh up` first)
- [ ] Added/updated an ADR in `docs/decisions/` if this is an architectural decision

## CI workflows expected to run

CI is path-scoped (`.github/workflows/*.yml`), so it's easy to be surprised one didn't
trigger. Note which of these you expect for this PR:

- [ ] `api.yml` (apps/api, packages, schemas, pyproject.toml, uv.lock)
- [ ] `pipelines.yml` (pipelines, apps/worker, relevant packages)
- [ ] `web.yml` (apps/web)
- [ ] `security.yml` (runs on every PR — dependency audit + secret scan)
- [ ] `evaluation.yml` (retrieval/generation/prompts/chunking/eval-test paths)
