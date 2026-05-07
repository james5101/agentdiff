"""The OpenAI provider stub must raise loudly, not silently no-op."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentdiff.definition.schema import AgentDefinition, EvalThresholds, TokenUsage
from agentdiff.providers.openai import OpenAIProvider


def _make_agent(tmp_path: Path) -> AgentDefinition:
    return AgentDefinition(
        name="x",
        path=tmp_path,
        provider="openai",
        model="gpt-x",
        prompt_path=tmp_path / "p.md",
        input_schema_path=tmp_path / "i.json",
        output_schema_path=tmp_path / "o.json",
        eval_files=[tmp_path / "g.jsonl"],
        thresholds={"g": EvalThresholds(min_pass_rate=1.0)},
    )


def test_openai_provider_invoke_raises(tmp_path: Path) -> None:
    provider = OpenAIProvider(model="gpt-x", api_key="ignored")
    agent = _make_agent(tmp_path)
    with pytest.raises(NotImplementedError, match="OpenAI support coming soon"):
        asyncio.run(provider.invoke(agent, {"x": 1}))


def test_openai_provider_estimate_cost_raises() -> None:
    provider = OpenAIProvider(model="gpt-x", api_key="ignored")
    with pytest.raises(NotImplementedError, match="OpenAI support coming soon"):
        provider.estimate_cost(TokenUsage(input_tokens=1, output_tokens=1))
