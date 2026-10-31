"""Token usage -> estimated USD cost, logged per graph run (no message content, no PII).

Prices are Anthropic first-party list prices per million tokens (from the API docs, 2026-10-06).
They are an *estimate*: the invoice is the source of truth. Update the table when prices change.
Thinking tokens are billed as output and are already included in `output_tokens`.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Price:
    input: float  # USD per 1M input tokens
    output: float  # USD per 1M output tokens
    cache_read: float | None = None  # USD per 1M cached input tokens (None: bill as input)


PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(0.10, 0.50),  # prompts up to 100K tokens
    "claude-sonnet-5-5": Price(2.00, 10.00, cache_read=0.20),
    "claude-opus-5-5": Price(4.00, 20.00, cache_read=0.20),
}


@dataclass(frozen=True, slots=True)
class RunCost:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    usd: float
    unpriced_models: tuple[str, ...] = ()  # models seen without a price: cost is a lower bound


def _price_for(model: str) -> Price | None:
    # Responses may report a dated or prefixed id; match on the known id it contains.
    return next((p for known, p in PRICES.items() if known in model), None)


def estimate_cost(usage_by_model: Mapping[str, Mapping[str, Any]]) -> RunCost:
    """`usage_by_model`: LangChain's per-model `usage_metadata` (UsageMetadataCallbackHandler)."""
    total_in = total_out = total_cached = 0
    usd = 0.0
    unpriced: list[str] = []
    for model, usage in usage_by_model.items():
        in_tokens = int(usage.get("input_tokens", 0))
        out_tokens = int(usage.get("output_tokens", 0))
        cached = int((usage.get("input_token_details") or {}).get("cache_read") or 0)  # may be None
        total_in += in_tokens
        total_out += out_tokens
        total_cached += cached
        price = _price_for(model)
        if price is None:
            unpriced.append(model)
            continue
        uncached = max(in_tokens - cached, 0)  # LangChain's input_tokens includes cache reads
        cache_rate = price.cache_read if price.cache_read is not None else price.input
        usd += (uncached * price.input + cached * cache_rate + out_tokens * price.output) / 1e6
    return RunCost(total_in, total_out, total_cached, round(usd, 6), tuple(unpriced))
