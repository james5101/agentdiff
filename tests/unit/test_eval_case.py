"""Tests for `eval.case.run_case`."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic

from agentdiff.definition.schema import (
    AgentDefinition,
    EvalCase,
    InvocationResult,
    TokenUsage,
)
from agentdiff.eval.case import load_output_schema, run_case
from agentdiff.eval.judge import Judger
from tests.conftest import FakeProvider


def _fake_judge_client(judge_text: str) -> anthropic.AsyncAnthropic:
    """Build an AsyncAnthropic-shaped object whose messages.create
    returns a single text block with `judge_text` (the post-`{` JSON
    continuation, since the judge prefills `{`)."""
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text=judge_text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=10),
        )
    )
    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    return fake  # type: ignore[return-value]


async def test_pass_when_output_matches_expected(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    schema = load_output_schema(agent)
    provider = FakeProvider(lambda _: {"intent": "greeting"})

    case = EvalCase(
        id="c1",
        input={"text": "hi"},
        expected={"intent": "greeting"},
    )
    result = await run_case(case, agent, provider, output_schema=schema)

    assert result.passed
    assert result.failure_reason is None
    assert result.invocation.output == {"intent": "greeting"}


async def test_fail_when_output_differs_from_expected(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    schema = load_output_schema(agent)
    provider = FakeProvider(lambda _: {"intent": "complaint"})

    case = EvalCase(
        id="c1",
        input={"text": "hi"},
        expected={"intent": "greeting"},
    )
    result = await run_case(case, agent, provider, output_schema=schema)

    assert not result.passed
    assert result.failure_reason is not None
    assert "output mismatch" in result.failure_reason


async def test_pass_when_no_expected_and_schema_valid(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    """No `expected` → schema-valid output passes (M1; judge follows in M2)."""
    agent = make_agent()
    schema = load_output_schema(agent)
    provider = FakeProvider(lambda _: {"intent": "greeting"})

    case = EvalCase(id="c1", input={"text": "hi"})
    result = await run_case(case, agent, provider, output_schema=schema)
    assert result.passed


async def test_fail_when_no_expected_and_schema_invalid(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    schema = load_output_schema(agent)
    # Output is missing the required `intent` field.
    provider = FakeProvider(lambda _: {"unrelated": "field"})

    case = EvalCase(id="c1", input={"text": "hi"})
    result = await run_case(case, agent, provider, output_schema=schema)

    assert not result.passed
    assert result.failure_reason is not None
    assert "schema violation" in result.failure_reason


async def test_fail_when_provider_returns_error(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    schema = load_output_schema(agent)

    err_result = InvocationResult(
        output=None,
        usage=TokenUsage(input_tokens=5, output_tokens=0),
        latency_ms=12,
        error="rate limited",
    )
    provider = FakeProvider(lambda _: err_result)

    case = EvalCase(id="c1", input={"text": "hi"}, expected={"intent": "greeting"})
    result = await run_case(case, agent, provider, output_schema=schema)

    assert not result.passed
    assert result.failure_reason == "rate limited"


async def test_pass_when_judger_says_pass(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    """No `expected` + schema-valid + judger pass → CaseResult.passed."""
    agent = make_agent()
    schema = load_output_schema(agent)
    provider = FakeProvider(lambda _: {"intent": "greeting"})
    judger = Judger(
        client=_fake_judge_client('{"score": 0.95, "reasoning": "good"}'),
        rubric="Pass if relevant.",
    )

    case = EvalCase(id="c1", input={"text": "hi"})
    result = await run_case(case, agent, provider, output_schema=schema, judger=judger)

    assert result.passed
    assert result.judge_score == 0.95
    assert judger.call_count == 1


async def test_fail_when_judger_says_fail(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    schema = load_output_schema(agent)
    provider = FakeProvider(lambda _: {"intent": "other"})
    judger = Judger(
        client=_fake_judge_client('{"score": 0.3, "reasoning": "off-topic"}'),
        rubric="Pass if relevant.",
    )

    case = EvalCase(id="c1", input={"text": "hi"})
    result = await run_case(case, agent, provider, output_schema=schema, judger=judger)

    assert not result.passed
    assert result.judge_score == 0.3
    assert result.failure_reason is not None
    assert "off-topic" in result.failure_reason


async def test_judger_skipped_when_expected_set(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    """If the case has `expected`, judger is never called."""
    agent = make_agent()
    schema = load_output_schema(agent)
    provider = FakeProvider(lambda _: {"intent": "greeting"})
    judger = Judger(
        client=_fake_judge_client('{"score": 0.0, "reasoning": "x"}'),
        rubric="x",
    )

    case = EvalCase(
        id="c1",
        input={"text": "hi"},
        expected={"intent": "greeting"},
    )
    result = await run_case(case, agent, provider, output_schema=schema, judger=judger)

    assert result.passed
    assert judger.call_count == 0  # judger never invoked
    assert result.judge_score is None


async def test_fail_on_timeout(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    schema = load_output_schema(agent)
    # Sleep longer than the timeout the test sets.
    provider = FakeProvider(lambda _: 1.0)

    case = EvalCase(id="c1", input={"text": "hi"})
    result = await run_case(case, agent, provider, output_schema=schema, timeout_seconds=0.05)

    assert not result.passed
    assert result.failure_reason == "timeout"
    assert result.invocation.error is not None
    assert "timed out" in result.invocation.error
