"""AgentCore — executor/policy.py
ExecutionPolicy: hard budgets that stop runaway loops / API spend.
  max_runtime_s, max_steps, max_cost, max_tokens, max_retries, max_recursion_depth
BudgetTracker accumulates tokens/cost across the run and is consulted before
each LLM call and each step.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ExecutionPolicy:
    max_runtime_s: float = 120.0
    max_steps: int = 8
    max_cost: float = 1.0           # USD; 0 = unlimited
    max_tokens: int = 50_000        # cumulative; 0 = unlimited
    max_retries: int = 2
    max_recursion_depth: int = 3
    step_timeout_s: float = 90.0

    # rough USD per 1M tokens, keyed by provider (0 = unknown → cost not enforced)
    cost_per_1m_in: dict[str, float] = field(default_factory=lambda: {
        "openrouter": 0.15, "openai": 0.15, "gemini": 0.10,
        "claude": 0.80, "deepseek": 0.14, "ollama": 0.0, "mock": 0.0,
    })
    cost_per_1m_out: dict[str, float] = field(default_factory=lambda: {
        "openrouter": 0.60, "openai": 0.60, "gemini": 0.40,
        "claude": 4.00, "deepseek": 0.28, "ollama": 0.0, "mock": 0.0,
    })


class BudgetTracker:
    """Accumulates usage; consult before continuing."""

    def __init__(self, policy: ExecutionPolicy) -> None:
        self.policy = policy
        self.started_at = time.time()
        self.steps_taken = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost = 0.0
        self.recursion_depth = 0

    def record(self, provider: str, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        rate_in = self.policy.cost_per_1m_in.get(provider, 0.0)
        rate_out = self.policy.cost_per_1m_out.get(provider, 0.0)
        self.cost += (tokens_in / 1_000_000) * rate_in + (tokens_out / 1_000_000) * rate_out

    def check(self) -> str | None:
        """Return a violation message, or None if within budget."""
        p = self.policy
        if p.max_runtime_s and (time.time() - self.started_at) > p.max_runtime_s:
            return f"max_runtime exceeded ({p.max_runtime_s}s)"
        if p.max_steps and self.steps_taken >= p.max_steps:
            return f"max_steps exceeded ({p.max_steps})"
        if p.max_tokens and (self.tokens_in + self.tokens_out) >= p.max_tokens:
            return f"max_tokens exceeded ({p.max_tokens})"
        if p.max_cost and self.cost >= p.max_cost:
            return f"max_cost exceeded (${self.cost:.4f})"
        if p.max_recursion_depth and self.recursion_depth >= p.max_recursion_depth:
            return f"max_recursion_depth exceeded ({p.max_recursion_depth})"
        return None

    def summary(self) -> dict:
        return {
            "elapsed_s": round(time.time() - self.started_at, 2),
            "steps": self.steps_taken,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens_total": self.tokens_in + self.tokens_out,
            "cost": round(self.cost, 5),
        }
