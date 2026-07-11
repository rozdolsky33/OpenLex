# Legal-accuracy evaluation

Golden-question regression suite for the retrieval + generation pipeline: a fixed set of
landlord-tenant questions with expected citations/answer characteristics, run against a live
API to catch answer-quality regressions (not just code correctness).

`golden_questions.yaml` doesn't exist yet — see `scripts/evaluate.sh` (which checks for it
before running) and `docs/decisions/0001-monorepo-restructure.md` for where this fits in CI
(runs only when `packages/legal_retrieval/**`, `packages/legal_generation/**`, or
`ml/prompts/**` change).
