"""Tests for legal_generation.anthropic_metrics -- see generator.py for where these are called."""

import pytest
from legal_generation.anthropic_metrics import (
    ANTHROPIC_COST_USD_TOTAL,
    ANTHROPIC_PRICING_PER_MILLION_TOKENS,
    ANTHROPIC_REQUEST_DURATION_SECONDS,
    ANTHROPIC_REQUESTS_TOTAL,
    ANTHROPIC_TOKENS_TOTAL,
    record_anthropic_call,
)

MODEL = "claude-sonnet-4-5"


def test_record_anthropic_call_success_increments_all_four_metrics() -> None:
    requests_before = ANTHROPIC_REQUESTS_TOTAL.labels(model=MODEL, status="success")._value.get()
    input_tokens_before = ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="input")._value.get()
    output_tokens_before = ANTHROPIC_TOKENS_TOTAL.labels(
        model=MODEL, direction="output"
    )._value.get()
    cost_before = ANTHROPIC_COST_USD_TOTAL.labels(model=MODEL)._value.get()
    duration_count_before = ANTHROPIC_REQUEST_DURATION_SECONDS.labels(model=MODEL)._sum.get()

    record_anthropic_call(
        model=MODEL, status="success", input_tokens=1000, output_tokens=500, duration_seconds=1.5
    )

    assert ANTHROPIC_REQUESTS_TOTAL.labels(model=MODEL, status="success")._value.get() == (
        requests_before + 1
    )
    assert ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="input")._value.get() == (
        input_tokens_before + 1000
    )
    assert ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="output")._value.get() == (
        output_tokens_before + 500
    )
    input_price, output_price = ANTHROPIC_PRICING_PER_MILLION_TOKENS[MODEL]
    expected_cost = (1000 / 1_000_000) * input_price + (500 / 1_000_000) * output_price
    assert ANTHROPIC_COST_USD_TOTAL.labels(model=MODEL)._value.get() == pytest.approx(
        cost_before + expected_cost
    )
    assert ANTHROPIC_REQUEST_DURATION_SECONDS.labels(model=MODEL)._sum.get() == pytest.approx(
        duration_count_before + 1.5
    )


def test_record_anthropic_call_rate_limited_skips_token_and_cost_counters() -> None:
    tokens_before = ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="input")._value.get()
    cost_before = ANTHROPIC_COST_USD_TOTAL.labels(model=MODEL)._value.get()
    requests_before = ANTHROPIC_REQUESTS_TOTAL.labels(
        model=MODEL, status="rate_limited"
    )._value.get()

    record_anthropic_call(
        model=MODEL, status="rate_limited", input_tokens=0, output_tokens=0, duration_seconds=0.2
    )

    assert ANTHROPIC_REQUESTS_TOTAL.labels(model=MODEL, status="rate_limited")._value.get() == (
        requests_before + 1
    )
    # token/cost counters are meaningless for a call with no usage data -- must not move
    assert (
        ANTHROPIC_TOKENS_TOTAL.labels(model=MODEL, direction="input")._value.get() == tokens_before
    )
    assert ANTHROPIC_COST_USD_TOTAL.labels(model=MODEL)._value.get() == cost_before


def test_record_anthropic_call_unknown_model_falls_back_to_default_pricing() -> None:
    from legal_generation.anthropic_metrics import _DEFAULT_PRICING

    cost_before = ANTHROPIC_COST_USD_TOTAL.labels(model="some-future-model")._value.get()

    record_anthropic_call(
        model="some-future-model",
        status="success",
        input_tokens=1_000_000,
        output_tokens=0,
        duration_seconds=1.0,
    )

    expected_cost = cost_before + _DEFAULT_PRICING[0]
    assert ANTHROPIC_COST_USD_TOTAL.labels(model="some-future-model")._value.get() == pytest.approx(
        expected_cost
    )
