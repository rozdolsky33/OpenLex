# Legal-accuracy evaluation

Golden-question regression suite for the retrieval + generation pipeline: a fixed set of
landlord-tenant questions with expected citations/answer characteristics
(`golden_questions.yaml`), run against a live API to catch answer-quality regressions (not just
code correctness).

## Running

```bash
docker compose up -d db api      # or the full stack
scripts/ingest.sh statutes       # golden_questions.yaml expects the seeded statutes present
scripts/seed-demo-users.sh       # POST /auth/register is disabled -- the harness logs in as
                                  # the seeded Platinum demo user, see DEMO_PLATINUM_EMAIL/
                                  # DEMO_PLATINUM_PASSWORD in .env.example
scripts/evaluate.sh
```

Each question in `golden_questions.yaml` becomes its own pytest case (`test_golden_question`,
parametrized by `id`) so a regression in one question doesn't hide failures in the others.
`test_golden_questions.py` is marked `evaluation` and excluded from the default `uv run pytest`
run (see the root `pyproject.toml`'s `addopts`) — it makes real Anthropic API calls and needs a
running server, so it isn't part of the fast local/CI test loop. Per
`docs/decisions/0001-monorepo-restructure.md`, it's meant to run in CI only when
`packages/legal_retrieval/**`, `packages/legal_generation/**`, or `ml/prompts/**` change.

Point it at a non-default API with `EVAL_API_BASE_URL` (defaults to `http://localhost:8000`).
