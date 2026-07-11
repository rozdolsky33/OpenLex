import sys
from pathlib import Path

# pipelines/ has no pyproject.toml -- it's a plain directory (Python implicit namespace
# package) imported relative to the repo root, not an installed workspace package (see
# CLAUDE.md). Tests that import `pipelines.*` need the repo root on sys.path.
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
