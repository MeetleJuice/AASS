"""Non-negotiable upper bounds; callers may only lower these limits."""

from dataclasses import dataclass

MAX_TOKENS = 64_000
MAX_ITERATIONS = 20
MAX_CALL_TOKENS = 4096


class SafetyStop(RuntimeError):
    pass


@dataclass
class CircuitBreaker:
    token_limit: int = MAX_TOKENS
    iteration_limit: int = MAX_ITERATIONS
    tokens: int = 0
    iterations: int = 0

    def __post_init__(self):
        if not 0 < self.token_limit <= MAX_TOKENS:
            raise ValueError("Token limit exceeds hard ceiling")
        if not 0 < self.iteration_limit <= MAX_ITERATIONS:
            raise ValueError("Iteration limit exceeds hard ceiling")

    def tick(self):
        if self.iterations >= self.iteration_limit:
            raise SafetyStop("Iteration kill-switch")
        self.iterations += 1

    def reserve(self, prompt: str, output_tokens=MAX_CALL_TOKENS):
        # UTF-8 bytes is a conservative upper bound for byte-pair tokenizers.
        if not 0 < output_tokens <= MAX_CALL_TOKENS:
            raise SafetyStop("Per-call output ceiling")
        allowance = len(prompt.encode()) + output_tokens
        if self.tokens + allowance > self.token_limit:
            raise SafetyStop("Token kill-switch")
        # Charge before the request: failed requests consume the same reserved budget.
        self.tokens += allowance
