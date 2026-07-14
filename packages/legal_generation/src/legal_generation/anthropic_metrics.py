"""Prometheus metrics for Anthropic API calls made from generate_answer (see generator.py).

Mirrors apps/api/src/openlex_api/http_metrics.py's hand-rolled prometheus_client pattern --
this project already rejected a second OTel *metrics* pipeline for the same reason
(apps/api/src/openlex_api/telemetry.py's module docstring), so these business-level metrics go
straight to prometheus_client, same as the HTTP RED metrics and quota.py's counters.

ANTHROPIC_PRICING_PER_MILLION_TOKENS is a static, manually-maintained constant -- like
TIER_LIMITS in apps/api/src/openlex_api/quota.py, this is a product-level constant, not
something fetched live. Anthropic's pricing changes over time; revisit this table when it
does -- it will not self-update, and an unrecognized model silently falls back to
_DEFAULT_PRICING rather than raising, so a cost estimate always exists even if imprecise for a
brand-new model this table hasn't been updated for yet.
"""

from prometheus_client import Counter, Histogram

# USD per 1M tokens, as (input_price, output_price). Source: published Anthropic pricing at
# the time this table was last updated (2026-07). No live pricing lookup exists -- update this
# dict by hand when Anthropic reprices.
ANTHROPIC_PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4-5": (15.00, 75.00),
    "claude-haiku-4-5": (0.80, 4.00),
}
_DEFAULT_PRICING: tuple[float, float] = (
    3.00,
    15.00,
)  # Sonnet-tier fallback for an unrecognized model

ANTHROPIC_REQUESTS_TOTAL = Counter(
    "openlex_anthropic_requests_total",
    "Anthropic messages.create calls by requested model and outcome",
    ["model", "status"],
)
ANTHROPIC_TOKENS_TOTAL = Counter(
    "openlex_anthropic_tokens_total",
    "Anthropic token usage by requested model and direction",
    ["model", "direction"],
)
ANTHROPIC_COST_USD_TOTAL = Counter(
    "openlex_anthropic_cost_usd_total",
    "Estimated Anthropic API cost in USD by requested model, from a static pricing table",
    ["model"],
)
ANTHROPIC_REQUEST_DURATION_SECONDS = Histogram(
    "openlex_anthropic_request_duration_seconds",
    "Anthropic messages.create call duration in seconds by requested model",
    ["model"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30),
)


def record_anthropic_call(
    *, model: str, status: str, input_tokens: int, output_tokens: int, duration_seconds: float
) -> None:
    """Records one Anthropic messages.create call's outcome across all four metrics at once,
    so callers can't update one counter and forget another. `model` is the requested model
    (settings.anthropic_model), not the API's echoed response.model -- keeps label cardinality
    bounded to configured aliases and matches ANTHROPIC_PRICING_PER_MILLION_TOKENS's keys
    exactly, rather than dated model snapshots the pricing table isn't keyed by.
    """
    ANTHROPIC_REQUESTS_TOTAL.labels(model=model, status=status).inc()
    ANTHROPIC_REQUEST_DURATION_SECONDS.labels(model=model).observe(duration_seconds)

    if status != "success":
        return  # token/cost counts are meaningless for a call that never returned usage data

    ANTHROPIC_TOKENS_TOTAL.labels(model=model, direction="input").inc(input_tokens)
    ANTHROPIC_TOKENS_TOTAL.labels(model=model, direction="output").inc(output_tokens)

    input_price, output_price = ANTHROPIC_PRICING_PER_MILLION_TOKENS.get(model, _DEFAULT_PRICING)
    cost = (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price
    ANTHROPIC_COST_USD_TOTAL.labels(model=model).inc(cost)
