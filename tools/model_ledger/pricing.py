"""Pricing lookup table for common LLM models."""

from __future__ import annotations

from typing import Optional

# Price per 1M tokens: (input_price_usd, output_price_usd)
PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Anthropic
    "claude-opus-4": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-3-5": (0.80, 4.00),
    # Google
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
}


def estimate_cost(
    model: str, prompt_tokens: int, completion_tokens: int
) -> Optional[float]:
    """Estimate the USD cost of a call given model name and token counts.

    Returns None if the model is not in the pricing table.
    """
    prices = PRICING.get(model)
    if prices is None:
        return None
    input_price, output_price = prices
    cost = (prompt_tokens / 1_000_000) * input_price + (
        completion_tokens / 1_000_000
    ) * output_price
    return round(cost, 8)
