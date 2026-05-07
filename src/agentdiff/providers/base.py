"""Provider protocol — the seam between agentdiff and any model API.

Per HANDOFF.md sec 3.2 the interface is intentionally tiny: invoke +
estimate_cost. Resist any urge to grow it; if a feature seems to need
extra methods, that's a signal the feature is leaking provider-specific
concerns and should be redesigned.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

from agentdiff.definition.schema import AgentDefinition, InvocationResult, TokenUsage


class Provider(Protocol):
    """A model backend that can run an agent and price token usage.

    Implementations are bound to a specific model at construction; the
    caller is responsible for matching `agent.model` to the provider it
    builds for that agent.
    """

    async def invoke(
        self,
        agent: AgentDefinition,
        input_: dict[str, Any],
    ) -> InvocationResult: ...

    def estimate_cost(self, usage: TokenUsage) -> Decimal: ...
