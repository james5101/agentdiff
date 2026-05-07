"""Tests for `eval.judge` — judge model wrapper, rubric loading, Judger."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import anthropic
import httpx

from agentdiff.eval.judge import (
    JUDGE_MODEL,
    PASS_THRESHOLD,
    Judger,
    _invoke_judge,
    find_rubric,
)


def _fake_message(*, text: str, in_tok: int = 30, out_tok: int = 12) -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
    )


def _fake_client(create_mock: AsyncMock) -> anthropic.AsyncAnthropic:
    fake = SimpleNamespace(messages=SimpleNamespace(create=create_mock))
    return fake  # type: ignore[return-value]


# ---------- find_rubric ----------


def test_find_rubric_uses_adjacent_judge_md(tmp_path: Path) -> None:
    eval_file = tmp_path / "golden.jsonl"
    eval_file.write_text("{}\n", encoding="utf-8")
    rubric_file = tmp_path / "golden.judge.md"
    rubric_file.write_text("Pass if the answer is concise.", encoding="utf-8")

    rubric, fallback = find_rubric(eval_file)
    assert rubric == "Pass if the answer is concise."
    assert fallback is False


def test_find_rubric_falls_back_when_missing(tmp_path: Path) -> None:
    eval_file = tmp_path / "golden.jsonl"
    eval_file.write_text("{}\n", encoding="utf-8")

    rubric, fallback = find_rubric(eval_file)
    assert fallback is True
    assert "reasonable response" in rubric


# ---------- _invoke_judge: success ----------


async def test_invoke_judge_returns_score_and_cost() -> None:
    create = AsyncMock(
        return_value=_fake_message(
            text='"score": 0.9, "reasoning": "matches the rubric well"}',
            in_tok=200,
            out_tok=20,
        )
    )
    result = await _invoke_judge(
        client=_fake_client(create),
        rubric="Be concise.",
        case_input={"text": "hi"},
        agent_output={"intent": "greeting"},
    )
    assert result.error is None
    assert result.score == 0.9
    assert result.passed is True
    assert "matches the rubric" in result.reasoning
    # 200 input tokens * $3/MTok + 20 output tokens * $15/MTok
    expected_cost = Decimal(200) * Decimal(3) / Decimal(1_000_000) + Decimal(20) * Decimal(
        15
    ) / Decimal(1_000_000)
    assert result.cost_usd == expected_cost

    # Verify the judge call shape: hardcoded Sonnet, JSON prefill.
    create.assert_awaited_once()
    assert create.await_args is not None
    kwargs = create.await_args.kwargs
    assert kwargs["model"] == JUDGE_MODEL
    assert kwargs["messages"][-1] == {"role": "assistant", "content": "{"}


async def test_invoke_judge_below_threshold_fails() -> None:
    create = AsyncMock(return_value=_fake_message(text='"score": 0.4, "reasoning": "off-topic"}'))
    result = await _invoke_judge(
        client=_fake_client(create),
        rubric="Be concise.",
        case_input={},
        agent_output={"x": 1},
    )
    assert result.error is None
    assert result.score == 0.4
    assert result.passed is False  # below PASS_THRESHOLD
    assert PASS_THRESHOLD == 0.7  # guard against silent threshold drift


# ---------- _invoke_judge: error branches ----------


async def test_invoke_judge_handles_api_error() -> None:
    fake_request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    create = AsyncMock(side_effect=anthropic.APIConnectionError(request=fake_request))
    result = await _invoke_judge(
        client=_fake_client(create),
        rubric="Be concise.",
        case_input={},
        agent_output={},
    )
    assert result.error is not None
    assert "judge unavailable" in result.error
    assert result.passed is False
    assert result.cost_usd == Decimal("0")


async def test_invoke_judge_handles_invalid_json() -> None:
    create = AsyncMock(return_value=_fake_message(text="this is not json"))
    result = await _invoke_judge(
        client=_fake_client(create),
        rubric="x",
        case_input={},
        agent_output={},
    )
    assert result.error is not None
    assert "JSON parse" in result.error
    assert result.passed is False
    # Cost is still recorded — we paid for the call.
    assert result.cost_usd > Decimal("0")


async def test_invoke_judge_handles_score_out_of_range() -> None:
    create = AsyncMock(return_value=_fake_message(text='"score": 1.5, "reasoning": "too good"}'))
    result = await _invoke_judge(
        client=_fake_client(create),
        rubric="x",
        case_input={},
        agent_output={},
    )
    assert result.error is not None
    assert "out of [0, 1]" in result.error


async def test_invoke_judge_handles_non_numeric_score() -> None:
    create = AsyncMock(return_value=_fake_message(text='"score": "great", "reasoning": "x"}'))
    result = await _invoke_judge(
        client=_fake_client(create),
        rubric="x",
        case_input={},
        agent_output={},
    )
    assert result.error is not None
    assert "not a number" in result.error


# ---------- Judger ----------


async def test_judger_accumulates_cost_across_calls() -> None:
    create = AsyncMock(
        return_value=_fake_message(text='"score": 0.8, "reasoning": "ok"}', in_tok=100, out_tok=10)
    )
    judger = Judger(client=_fake_client(create), rubric="x", fallback_used=False)
    await judger.judge(case_input={}, agent_output={"a": 1})
    await judger.judge(case_input={}, agent_output={"a": 2})

    assert judger.call_count == 2
    # 2 calls * ((100*3 + 10*15) / 1M) = 2 * 0.00045
    expected = Decimal(2) * (
        Decimal(100) * Decimal(3) / Decimal(1_000_000)
        + Decimal(10) * Decimal(15) / Decimal(1_000_000)
    )
    assert judger.total_cost_usd == expected
