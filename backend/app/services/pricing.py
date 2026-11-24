"""
Price table and cost arithmetic for the Week 11 per-span cost numbers.

One place, because a cost that is computed in three files drifts in three
directions. Prices are USD per token for the models this app calls on Groq.
`openai/gpt-oss-120b` is $0.15 in / $0.60 out per million tokens (the same
constants the Week 10 race used); a model not listed is priced at that rate and
flagged `estimated`, so an unknown model never silently reads as free.

Local stages cost nothing in dollars (MiniLM embeddings and the cross-encoder
run on the app's own CPU), so their cost is 0.0 and their *time* is what the
span records.
"""

from __future__ import annotations

PER_MILLION: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
}
DEFAULT_RATE: tuple[float, float] = PER_MILLION["openai/gpt-oss-120b"]


def rates(model: str | None) -> tuple[float, float, bool]:
    """(input $/M, output $/M, estimated?)."""
    if model in PER_MILLION:
        return (*PER_MILLION[model], False)
    return (*DEFAULT_RATE, True)


def call_cost(model: str | None, prompt_tokens: int | None, completion_tokens: int | None) -> float:
    inp, out, _ = rates(model)
    return ((prompt_tokens or 0) * inp + (completion_tokens or 0) * out) / 1_000_000
