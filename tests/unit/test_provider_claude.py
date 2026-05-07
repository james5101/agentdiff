"""ClaudeProvider unit tests with a fake Anthropic client.

Real wire-format coverage belongs in `tests/integration/` with
recorded cassettes; these are fast contract tests for the parsing
and error branches.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest

from agentdiff.definition.schema import AgentDefinition, EvalThresholds, TokenUsage
from agentdiff.providers.claude import ClaudeProvider, UnknownModelError

# ---------- helpers ----------


def _make_agent(tmp_path: Path) -> AgentDefinition:
    """Build a real AgentDefinition with a real on-disk prompt file."""
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Classify the input.", encoding="utf-8")
    return AgentDefinition(
        name="test-agent",
        path=tmp_path,
        provider="claude",
        model="claude-haiku-4-5-20251001",
        prompt_path=prompt,
        input_schema_path=tmp_path / "input.json",
        output_schema_path=tmp_path / "output.json",
        eval_files=[tmp_path / "golden.jsonl"],
        thresholds={"golden": EvalThresholds(min_pass_rate=1.0)},
    )


def _fake_message(*, text: str, in_tok: int = 20, out_tok: int = 10) -> Any:
    """Approximate the shape of `anthropic.types.Message`."""
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


def _fake_client(create_mock: AsyncMock) -> anthropic.AsyncAnthropic:
    """Build a stand-in AsyncAnthropic whose messages.create is `create_mock`."""
    fake = SimpleNamespace(messages=SimpleNamespace(create=create_mock))
    return fake  # type: ignore[return-value]


def _make_provider(create_mock: AsyncMock) -> ClaudeProvider:
    return ClaudeProvider(
        model="claude-haiku-4-5-20251001",
        api_key="test-key",
        client=_fake_client(create_mock),
    )


# ---------- invoke: success / parsing ----------


async def test_invoke_returns_parsed_json_output(tmp_path: Path) -> None:
    create = AsyncMock(return_value=_fake_message(text='{"intent": "greeting"}'))
    provider = _make_provider(create)
    agent = _make_agent(tmp_path)

    result = await provider.invoke(agent, {"text": "hello"})

    assert result.error is None
    assert result.output == {"intent": "greeting"}
    assert result.usage == TokenUsage(input_tokens=20, output_tokens=10)
    assert result.latency_ms >= 0

    # Verify the call shape: single user message, no assistant prefill
    # (Sonnet 4.6+ rejects prefill so we don't use it on any model).
    create.assert_awaited_once()
    assert create.await_args is not None
    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
    assert kwargs["system"] == "Classify the input."
    assert kwargs["messages"] == [{"role": "user", "content": '{"text": "hello"}'}]


async def test_invoke_concatenates_multiple_text_blocks(tmp_path: Path) -> None:
    """If the SDK returns several text blocks we concat them before parsing."""
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text='{"a":'),
                SimpleNamespace(type="text", text=" 1}"),
            ],
            usage=SimpleNamespace(input_tokens=5, output_tokens=3),
        )
    )
    provider = _make_provider(create)
    agent = _make_agent(tmp_path)

    result = await provider.invoke(agent, {})
    assert result.output == {"a": 1}


# ---------- invoke: error branches ----------


async def test_invoke_marks_invalid_json_as_error(tmp_path: Path) -> None:
    """Text with `{` but malformed JSON → JSONDecodeError path."""
    create = AsyncMock(return_value=_fake_message(text='{"intent": '))
    provider = _make_provider(create)

    result = await provider.invoke(_make_agent(tmp_path), {})
    assert result.output is None
    assert result.error is not None
    assert "not valid JSON" in result.error
    # Usage is still populated — we billed for those tokens.
    assert result.usage == TokenUsage(input_tokens=20, output_tokens=10)


async def test_invoke_marks_text_with_no_json_as_error(tmp_path: Path) -> None:
    """Text with no `{` at all → no-JSON-object path."""
    create = AsyncMock(return_value=_fake_message(text="Sorry, I can't help with that."))
    provider = _make_provider(create)

    result = await provider.invoke(_make_agent(tmp_path), {})
    assert result.output is None
    assert result.error is not None
    assert "no JSON object" in result.error


async def test_invoke_marks_empty_content_as_error(tmp_path: Path) -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[],
            usage=SimpleNamespace(input_tokens=5, output_tokens=0),
        )
    )
    provider = _make_provider(create)

    result = await provider.invoke(_make_agent(tmp_path), {})
    assert result.error == "response contained no text content"


async def test_invoke_catches_anthropic_api_error(tmp_path: Path) -> None:
    fake_request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    create = AsyncMock(side_effect=anthropic.APIConnectionError(request=fake_request))
    provider = _make_provider(create)

    result = await provider.invoke(_make_agent(tmp_path), {})
    assert result.output is None
    assert result.error is not None
    assert "anthropic API error" in result.error
    # Usage isn't known on connection failure.
    assert result.usage is None


# ---------- estimate_cost ----------


def test_estimate_cost_haiku() -> None:
    provider = _make_provider(AsyncMock())
    # 1M input tokens * $1 + 1M output tokens * $5 = $6.
    cost = provider.estimate_cost(TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000))
    assert cost == Decimal("6")


def test_estimate_cost_unknown_model_raises() -> None:
    provider = ClaudeProvider(
        model="claude-mystery-9000",
        api_key="test",
        client=_fake_client(AsyncMock()),
    )
    with pytest.raises(UnknownModelError, match="no pricing for model"):
        provider.estimate_cost(TokenUsage(input_tokens=1, output_tokens=1))
