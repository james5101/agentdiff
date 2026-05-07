"""Tests for `eval.run.run_eval_set`."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest

from agentdiff.definition.schema import AgentDefinition, EvalCase
from agentdiff.eval.judge import Judger
from agentdiff.eval.run import _percentile, run_eval_set
from tests.conftest import FakeProvider


def _fake_judge_client(judge_text: str) -> anthropic.AsyncAnthropic:
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text=judge_text)],
            usage=SimpleNamespace(input_tokens=50, output_tokens=8),
        )
    )
    fake = SimpleNamespace(messages=SimpleNamespace(create=create))
    return fake  # type: ignore[return-value]


async def test_run_eval_set_aggregates_cost_and_latency(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    cases = [
        EvalCase(id=f"c{i}", input={"i": i}, expected={"intent": "greeting"}) for i in range(3)
    ]
    provider = FakeProvider(
        lambda _: {"intent": "greeting"},
        cost_per_call=Decimal("0.0050"),
    )

    run = await run_eval_set(
        agent=agent,
        eval_set="golden.jsonl",
        cases=cases,
        provider=provider,
        git_sha="abc1234",
        concurrency=2,
    )

    assert run.agent_name == agent.name
    assert run.eval_set == "golden.jsonl"
    assert len(run.cases) == 3
    assert all(cr.passed for cr in run.cases)
    assert run.total_cost_usd == Decimal("0.0150")  # 3 * 0.005
    # All cases use FakeProvider's default_latency_ms=100.
    assert run.p50_latency_ms == 100
    assert run.p95_latency_ms == 100


async def test_run_eval_set_respects_concurrency_cap(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    # 6 cases that each sleep 50ms — without the cap they'd run all at
    # once; with concurrency=2 we expect max_inflight==2.
    cases = [EvalCase(id=f"c{i}", input={"i": i}) for i in range(6)]
    provider = FakeProvider(lambda _: 0.05)

    await run_eval_set(
        agent=agent,
        eval_set="g.jsonl",
        cases=cases,
        provider=provider,
        git_sha="abc1234",
        concurrency=2,
    )

    assert provider.invocation_count == 6
    assert provider.max_inflight == 2


async def test_run_eval_set_run_timeout_propagates(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    """Run-level timeout cancels in-flight cases and raises."""
    agent = make_agent()
    cases = [EvalCase(id=f"c{i}", input={"i": i}) for i in range(3)]
    provider = FakeProvider(lambda _: 5.0)  # each case sleeps 5s

    with pytest.raises(TimeoutError):
        await run_eval_set(
            agent=agent,
            eval_set="g.jsonl",
            cases=cases,
            provider=provider,
            git_sha="abc1234",
            concurrency=3,
            run_timeout_s=0.1,
        )


async def test_run_eval_set_zero_concurrency_rejected(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    provider = FakeProvider(lambda _: {"intent": "greeting"})
    with pytest.raises(ValueError, match="concurrency"):
        await run_eval_set(
            agent=agent,
            eval_set="g.jsonl",
            cases=[],
            provider=provider,
            git_sha="abc1234",
            concurrency=0,
        )


async def test_run_eval_set_handles_empty_cases(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = make_agent()
    provider = FakeProvider(lambda _: {"intent": "greeting"})
    run = await run_eval_set(
        agent=agent,
        eval_set="g.jsonl",
        cases=[],
        provider=provider,
        git_sha="abc1234",
    )
    assert run.cases == []
    assert run.total_cost_usd == Decimal("0")
    assert run.p50_latency_ms == 0
    assert run.p95_latency_ms == 0


async def test_run_eval_set_records_judge_cost_and_fallback(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    """Cases without `expected` get judged; judge_cost rolls up on EvalRun."""
    agent = make_agent()
    cases = [EvalCase(id=f"c{i}", input={"i": i}) for i in range(3)]
    provider = FakeProvider(lambda _: {"intent": "greeting"})
    judger = Judger(
        client=_fake_judge_client('"score": 0.9, "reasoning": "ok"}'),
        rubric="x",
        fallback_used=True,
    )

    run = await run_eval_set(
        agent=agent,
        eval_set="adversarial.jsonl",
        cases=cases,
        provider=provider,
        git_sha="abc1234",
        judger=judger,
        concurrency=2,
    )

    assert all(cr.passed for cr in run.cases)
    assert all(cr.judge_score == 0.9 for cr in run.cases)
    # 3 judge calls * cost-per-call > 0.
    assert run.judge_cost_usd > Decimal("0")
    assert run.judge_cost_usd == judger.total_cost_usd
    assert run.judge_fallback_used is True


# ---------- percentile helper ----------


def test_percentile_empty_returns_zero() -> None:
    assert _percentile([], 50) == 0


def test_percentile_single_value() -> None:
    assert _percentile([42], 50) == 42
    assert _percentile([42], 95) == 42


def test_percentile_p50_p95() -> None:
    values = list(range(1, 101))  # 1..100
    assert _percentile(values, 50) == 50
    assert _percentile(values, 95) == 95
