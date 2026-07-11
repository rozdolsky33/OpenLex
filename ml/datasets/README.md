# Datasets

Manifests and content hashes for evaluation/training datasets — not the data itself. See
"Data does not live in Git" in `docs/decisions/0001-monorepo-restructure.md`. The golden
evaluation question set lives in `tests/evaluation/` (small enough to check in directly);
this directory is for larger datasets that need manifest + hash tracking instead (e.g. via
DVC) once they exist.
