"""OpenAI provider stub.

Per HANDOFF.md sec 3.2, only `ClaudeProvider` is implemented in v1.
This stub exists so the `provider: openai` literal in `agentdiff.yaml`
fails loudly with a clear message instead of silently degrading.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from agentdiff.definition.schema import AgentDefinition, InvocationResult, TokenUsage

_MESSAGE = (
    "OpenAI support is not yet implemented. v1 only supports the Claude "
    "provider; set `provider: claude` in your agentdiff.yaml."
)


class OpenAIProvider:
    def __init__(self, *, model: str, api_key: str) -> None:
        self._model = model
        self._api_key = api_key

    async def invoke(
        self,
        agent: AgentDefinition,
        input_: dict[str, Any],
    ) -> InvocationResult:
        raise NotImplementedError(_MESSAGE)

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        raise NotImplementedError(_MESSAGE)
