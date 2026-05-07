"""Shared test fixtures and helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agentdiff.definition.schema import (
    AgentDefinition,
    EvalThresholds,
    InvocationResult,
    TokenUsage,
)


@pytest.fixture
def make_agent(tmp_path: Path) -> Callable[..., AgentDefinition]:
    """Build a real `AgentDefinition` rooted at `tmp_path`.

    Writes a default prompt and output schema to disk so callers can
    invoke ClaudeProvider / run_case against the agent without setting
    up files themselves.
    """

    def _factory(
        *,
        name: str = "test-agent",
        model: str = "claude-haiku-4-5-20251001",
        prompt_text: str = "Classify the input.",
        output_schema: dict[str, Any] | None = None,
    ) -> AgentDefinition:
        prompt = tmp_path / f"{name}-prompt.md"
        prompt.write_text(prompt_text, encoding="utf-8")

        output_schema_path = tmp_path / f"{name}-output.json"
        schema = output_schema or {
            "type": "object",
            "properties": {"intent": {"type": "string"}},
            "required": ["intent"],
            "additionalProperties": False,
        }
        import json

        output_schema_path.write_text(json.dumps(schema), encoding="utf-8")

        input_schema_path = tmp_path / f"{name}-input.json"
        input_schema_path.write_text(json.dumps({"type": "object"}), encoding="utf-8")

        return AgentDefinition(
            name=name,
            path=tmp_path,
            provider="claude",
            model=model,
            prompt_path=prompt,
            input_schema_path=input_schema_path,
            output_schema_path=output_schema_path,
            eval_files=[tmp_path / "g.jsonl"],
            thresholds={"g": EvalThresholds(min_pass_rate=1.0)},
        )

    return _factory


class FakeProvider:
    """Test double satisfying the `Provider` protocol structurally.

    Behavior is driven by `responder`, which maps a case input dict to
    one of:
      - dict: a successful agent output
      - InvocationResult: a fully-formed result (use to inject errors)
      - float: seconds to sleep before returning a default success
        (drives timeout tests)
    """

    def __init__(
        self,
        responder: Callable[[dict[str, Any]], dict[str, Any] | InvocationResult | float],
        *,
        cost_per_call: Decimal = Decimal("0.001"),
        default_usage: TokenUsage | None = None,
        default_latency_ms: int = 100,
    ) -> None:
        self._responder = responder
        self._cost_per_call = cost_per_call
        self._default_usage = default_usage or TokenUsage(input_tokens=10, output_tokens=5)
        self._default_latency_ms = default_latency_ms
        self.invocation_count = 0
        self.max_inflight = 0
        self._inflight = 0
        self._lock = asyncio.Lock()

    async def invoke(
        self,
        agent: AgentDefinition,
        input_: dict[str, Any],
    ) -> InvocationResult:
        async with self._lock:
            self._inflight += 1
            self.max_inflight = max(self.max_inflight, self._inflight)
            self.invocation_count += 1
        try:
            response = self._responder(input_)
            if isinstance(response, float):
                await asyncio.sleep(response)
                return InvocationResult(
                    output={"ok": True},
                    usage=self._default_usage,
                    latency_ms=int(response * 1000),
                )
            if isinstance(response, InvocationResult):
                return response
            return InvocationResult(
                output=response,
                usage=self._default_usage,
                latency_ms=self._default_latency_ms,
            )
        finally:
            async with self._lock:
                self._inflight -= 1

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        return self._cost_per_call
