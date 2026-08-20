"""LLM provider catalog and live cost projection for Tech Desk.

Prices are approximate public list prices (USD per 1,000,000 tokens) and are
intended for planning/estimation only — always confirm against each provider's
current pricing page. Token-per-run assumptions model a full Tech Desk pipeline
run (web-research curation + report generation) for a single desk.
"""

from __future__ import annotations

from typing import Any, Literal

Horizon = Literal["daily", "weekly", "monthly"]

# SDK type: "openai" = OpenAI-compatible (OpenAI SDK + base_url), "anthropic" = Anthropic SDK
PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "label": "OpenAI",
        "sdk": "openai",
        "base_url": "https://api.openai.com/v1",
        "key_hint": "sk-...",
        "docs": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "sdk": "anthropic",
        "base_url": "https://api.anthropic.com",
        "key_hint": "sk-ant-...",
        "docs": "https://console.anthropic.com/settings/keys",
    },
    "azure_openai": {
        "label": "Azure OpenAI",
        "sdk": "azure_openai",
        "base_url": "",
        "key_hint": "your-azure-api-key",
        "docs": "https://learn.microsoft.com/azure/ai-services/openai/",
        "requires_deployment": True,
    },
    "google": {
        "label": "Google (Gemini)",
        "sdk": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_hint": "AIza...",
        "docs": "https://aistudio.google.com/apikey",
    },
    "xai": {
        "label": "xAI (Grok)",
        "sdk": "openai",
        "base_url": "https://api.x.ai/v1",
        "key_hint": "xai-...",
        "docs": "https://console.x.ai",
    },
    "mistral": {
        "label": "Mistral AI",
        "sdk": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "key_hint": "...",
        "docs": "https://console.mistral.ai/api-keys",
    },
    "openai_compatible": {
        "label": "Custom (OpenAI-compatible)",
        "sdk": "openai",
        "base_url": "",
        "key_hint": "your-api-key",
        "docs": "",
    },
}

# id, provider, label, input $/1M, output $/1M, context window
MODELS: list[dict[str, Any]] = [
    # —— OpenAI ——
    {"id": "gpt-4o", "provider": "openai", "label": "GPT-4o", "input": 2.50, "output": 10.00, "context": 128000},
    {"id": "gpt-4o-mini", "provider": "openai", "label": "GPT-4o mini", "input": 0.15, "output": 0.60, "context": 128000},
    {"id": "gpt-4.1", "provider": "openai", "label": "GPT-4.1", "input": 2.00, "output": 8.00, "context": 1000000},
    {"id": "gpt-4.1-mini", "provider": "openai", "label": "GPT-4.1 mini", "input": 0.40, "output": 1.60, "context": 1000000},
    {"id": "gpt-4.1-nano", "provider": "openai", "label": "GPT-4.1 nano", "input": 0.10, "output": 0.40, "context": 1000000},
    {"id": "o3", "provider": "openai", "label": "o3 (reasoning)", "input": 10.00, "output": 40.00, "context": 200000},
    {"id": "o4-mini", "provider": "openai", "label": "o4-mini (reasoning)", "input": 1.10, "output": 4.40, "context": 200000},
    # —— Anthropic ——
    {"id": "claude-opus-4-20250514", "provider": "anthropic", "label": "Claude Opus 4", "input": 15.00, "output": 75.00, "context": 200000},
    {"id": "claude-sonnet-4-20250514", "provider": "anthropic", "label": "Claude Sonnet 4", "input": 3.00, "output": 15.00, "context": 200000},
    {"id": "claude-3-7-sonnet-latest", "provider": "anthropic", "label": "Claude 3.7 Sonnet", "input": 3.00, "output": 15.00, "context": 200000},
    {"id": "claude-3-5-sonnet-latest", "provider": "anthropic", "label": "Claude 3.5 Sonnet", "input": 3.00, "output": 15.00, "context": 200000},
    {"id": "claude-3-5-haiku-latest", "provider": "anthropic", "label": "Claude 3.5 Haiku", "input": 0.80, "output": 4.00, "context": 200000},
    # —— Google Gemini ——
    {"id": "gemini-2.5-pro", "provider": "google", "label": "Gemini 2.5 Pro", "input": 1.25, "output": 10.00, "context": 1000000},
    {"id": "gemini-2.5-flash", "provider": "google", "label": "Gemini 2.5 Flash", "input": 0.30, "output": 2.50, "context": 1000000},
    {"id": "gemini-2.0-flash", "provider": "google", "label": "Gemini 2.0 Flash", "input": 0.10, "output": 0.40, "context": 1000000},
    {"id": "gemini-1.5-pro", "provider": "google", "label": "Gemini 1.5 Pro", "input": 1.25, "output": 5.00, "context": 2000000},
    # —— xAI ——
    {"id": "grok-4", "provider": "xai", "label": "Grok 4", "input": 3.00, "output": 15.00, "context": 256000},
    {"id": "grok-3", "provider": "xai", "label": "Grok 3", "input": 3.00, "output": 15.00, "context": 131072},
    {"id": "grok-3-mini", "provider": "xai", "label": "Grok 3 mini", "input": 0.30, "output": 0.50, "context": 131072},
    # —— Mistral ——
    {"id": "mistral-large-latest", "provider": "mistral", "label": "Mistral Large", "input": 2.00, "output": 6.00, "context": 128000},
    {"id": "mistral-small-latest", "provider": "mistral", "label": "Mistral Small", "input": 0.20, "output": 0.60, "context": 128000},
    # —— Azure OpenAI (reference pricing — actual cost depends on your deployment's
    # region/tier; deployment names are custom, so these aren't shown as a fixed
    # dropdown, but are used to look up pricing if your deployment name matches) ——
    {"id": "gpt-5.4", "provider": "azure_openai", "label": "GPT-5.4 (<272k context)", "input": 2.50, "output": 15.00, "context": 272000},
]

_MODEL_INDEX = {m["id"]: m for m in MODELS}

# Estimated tokens consumed per desk for one full pipeline run, by horizon.
# Longer horizons pull more source material and produce longer syntheses.
TOKENS_PER_DESK_PER_RUN: dict[str, dict[str, int]] = {
    "daily": {"input": 9000, "output": 1800},
    "weekly": {"input": 14000, "output": 3400},
    "monthly": {"input": 22000, "output": 6000},
}

# How many briefs of the chosen horizon are produced in a month.
RUNS_PER_MONTH: dict[str, float] = {
    "daily": 30.0,
    "weekly": 4.33,
    "monthly": 1.0,
}


def get_catalog() -> dict[str, Any]:
    """Serializable provider + model catalog for the frontend."""
    return {
        "providers": [
            {
                "id": pid,
                "label": p["label"],
                "sdk": p["sdk"],
                "base_url": p["base_url"],
                "key_hint": p["key_hint"],
                "docs": p["docs"],
                "requires_deployment": p.get("requires_deployment", False),
                "models": [
                    {k: m[k] for k in ("id", "label", "input", "output", "context")}
                    for m in MODELS
                    # Azure deployment names are user-chosen, not a fixed catalog, so
                    # its models are exposed only via "all_models" below (used for
                    # price lookup, not a restrictive dropdown).
                    if m["provider"] == pid and pid != "azure_openai"
                ],
            }
            for pid, p in PROVIDERS.items()
        ],
        "all_models": [
            {k: m[k] for k in ("id", "label", "input", "output", "context", "provider")} for m in MODELS
        ],
        "horizons": list(RUNS_PER_MONTH.keys()),
        "tokens_per_desk_per_run": TOKENS_PER_DESK_PER_RUN,
        "runs_per_month": RUNS_PER_MONTH,
    }


def get_model(model_id: str) -> dict[str, Any] | None:
    return _MODEL_INDEX.get(model_id)


def provider_for_model(model_id: str) -> str | None:
    m = _MODEL_INDEX.get(model_id)
    return m["provider"] if m else None


def estimate_cost(
    model_id: str,
    horizon: Horizon,
    desk_count: int,
    *,
    input_price: float | None = None,
    output_price: float | None = None,
    input_tokens_per_desk: float | None = None,
    output_tokens_per_desk: float | None = None,
    token_source: str = "modeled",
) -> dict[str, Any]:
    """Project LLM spend for the given model, brief cadence, and number of desks.

    Token volumes default to modeled per-desk estimates, but callers can pass
    measured per-desk tokens (from real runs) to calibrate. For unknown/custom
    models, callers may pass explicit input/output prices.
    """
    horizon = horizon if horizon in TOKENS_PER_DESK_PER_RUN else "daily"
    desk_count = max(1, int(desk_count))

    model = _MODEL_INDEX.get(model_id)
    in_price = input_price if input_price is not None else (model["input"] if model else 0.0)
    out_price = output_price if output_price is not None else (model["output"] if model else 0.0)

    per_desk = TOKENS_PER_DESK_PER_RUN[horizon]
    in_per_desk = input_tokens_per_desk if input_tokens_per_desk is not None else per_desk["input"]
    out_per_desk = output_tokens_per_desk if output_tokens_per_desk is not None else per_desk["output"]
    run_input = int(round(in_per_desk * desk_count))
    run_output = int(round(out_per_desk * desk_count))

    run_input_cost = run_input / 1_000_000 * in_price
    run_output_cost = run_output / 1_000_000 * out_price
    run_cost = run_input_cost + run_output_cost

    runs = RUNS_PER_MONTH[horizon]
    monthly = run_cost * runs
    annual = monthly * 12

    return {
        "model_id": model_id,
        "model_label": model["label"] if model else model_id,
        "provider": model["provider"] if model else None,
        "horizon": horizon,
        "desk_count": desk_count,
        "input_price_per_m": round(in_price, 4),
        "output_price_per_m": round(out_price, 4),
        "tokens_per_run": {"input": run_input, "output": run_output, "total": run_input + run_output},
        "cost_per_run": round(run_cost, 4),
        "cost_per_run_breakdown": {
            "input": round(run_input_cost, 4),
            "output": round(run_output_cost, 4),
        },
        "runs_per_month": runs,
        "projected_monthly": round(monthly, 2),
        "projected_annual": round(annual, 2),
        "currency": "USD",
        "is_estimate": True,
        "token_source": token_source,
    }
