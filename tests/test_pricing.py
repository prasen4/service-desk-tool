from __future__ import annotations

import pytest

from tech_desk.pricing import (
    MODELS,
    PROVIDERS,
    estimate_cost,
    get_catalog,
    get_model,
    provider_for_model,
)


def test_every_model_maps_to_a_known_provider():
    for model in MODELS:
        assert model["provider"] in PROVIDERS
        assert model["input"] >= 0
        assert model["output"] >= 0
        assert model["context"] > 0


def test_provider_for_model_and_get_model():
    assert provider_for_model("gpt-4o") == "openai"
    assert provider_for_model("claude-sonnet-4-20250514") == "anthropic"
    assert provider_for_model("does-not-exist") is None
    assert get_model("gpt-4o")["label"] == "GPT-4o"
    assert get_model("nope") is None


def test_catalog_is_serializable_and_grouped():
    catalog = get_catalog()
    provider_ids = {p["id"] for p in catalog["providers"]}
    assert provider_ids == set(PROVIDERS)
    openai = next(p for p in catalog["providers"] if p["id"] == "openai")
    assert any(m["id"] == "gpt-4o" for m in openai["models"])
    assert set(catalog["horizons"]) == {"daily", "weekly", "monthly"}


def test_estimate_cost_scales_with_desks_and_horizon():
    one_desk = estimate_cost("gpt-4o", "daily", 1)
    five_desks = estimate_cost("gpt-4o", "daily", 5)
    assert five_desks["tokens_per_run"]["total"] > one_desk["tokens_per_run"]["total"]
    assert five_desks["cost_per_run"] > one_desk["cost_per_run"]

    # A longer horizon is a bigger one-time generation (more tokens per run).
    daily = estimate_cost("gpt-4o", "daily", 3)
    monthly = estimate_cost("gpt-4o", "monthly", 3)
    assert monthly["tokens_per_run"]["total"] > daily["tokens_per_run"]["total"]
    assert monthly["cost_per_run"] > daily["cost_per_run"]


def test_estimate_cost_uses_measured_tokens_when_provided():
    modeled = estimate_cost("gpt-4o", "daily", 2)
    measured = estimate_cost(
        "gpt-4o", "daily", 2,
        input_tokens_per_desk=50_000, output_tokens_per_desk=10_000,
        token_source="measured (3 runs)",
    )
    assert measured["tokens_per_run"]["input"] == 100_000
    assert measured["tokens_per_run"]["output"] == 20_000
    assert measured["cost_per_run"] > modeled["cost_per_run"]
    assert measured["token_source"] == "measured (3 runs)"


def test_estimate_cost_handles_unknown_model_with_explicit_prices():
    result = estimate_cost(
        "custom-model", "weekly", 4,
        input_price=1.0, output_price=2.0,
    )
    assert result["model_label"] == "custom-model"
    assert result["provider"] is None
    assert result["input_price_per_m"] == 1.0
    assert result["cost_per_run"] > 0


@pytest.mark.parametrize("horizon", ["daily", "weekly", "monthly"])
def test_projected_annual_is_about_twelve_months(horizon):
    result = estimate_cost("gpt-4o-mini", horizon, 5)
    # monthly and annual are each rounded to cents independently, so allow for
    # rounding drift rather than exact equality.
    assert result["projected_annual"] == pytest.approx(result["projected_monthly"] * 12, abs=0.12)
    assert result["projected_annual"] >= result["projected_monthly"]


def test_estimate_cost_falls_back_to_daily_for_bad_horizon():
    result = estimate_cost("gpt-4o", "yearly", 1)  # type: ignore[arg-type]
    assert result["horizon"] == "daily"
