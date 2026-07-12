"""Loader for the hand-curated NY case-law seed file. Unlike
pipelines/ingestion/ny_legislation/client.py, there is no live fetch here -- every free
public case-law full-text source tried (CourtListener's detail API without a token,
CourtListener's public opinion HTML page, the linked court PDF, Justia) is either
auth-gated or bot-blocked, so seed_cases.json carries the full opinion text as static
content, obtained once out-of-band via an authenticated CourtListener API token, not
fetched at ingestion runtime. See ADR-0006.
"""

import json
from pathlib import Path
from typing import Any

SEED_CASES_PATH = Path(__file__).parent / "seed_cases.json"


def load_seed_cases() -> list[dict[str, Any]]:
    return json.loads(SEED_CASES_PATH.read_text())
