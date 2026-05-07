"""Round-trip + invalid-rejection tests for every model in §5.

Per HANDOFF.md sec 5: every Pydantic model has a test that round-trips a
valid example and rejects an invalid one. Both checks per model live
together so failures are easy to attribute.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from agentdiff.definition.schema import (
    AgentDefinition,
    BehavioralDiff,
    CaseResult,
    EvalCase,
    EvalRun,
    EvalThresholds,
    InvocationResult,
    SchemaDriftEntry,
    ThresholdViolation,
    TokenUsage,
)


def _round_trip(model: BaseModel) -> None:
    """Dump → re-validate; the rebuilt model must equal the original."""
    rebuilt = model.__class__.model_validate(model.model_dump())
    assert rebuilt == model


# ---------- EvalThresholds ----------


def test_eval_thresholds_round_trip() -> None:
    t = EvalThresholds(min_pass_rate=1.0)
    _round_trip(t)
    t2 = EvalThresholds(min_pass_rate=0.9, max_regression_pct=0.05)
    _round_trip(t2)


def test_eval_thresholds_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        EvalThresholds()


def test_eval_thresholds_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        EvalThresholds(min_pass_rate=1.5)


# ---------- AgentDefinition ----------


def _agent_def_kwargs() -> dict[str, Any]:
    return {
        "name": "invoice-extractor",
        "path": Path("/repo/agents/invoice-extractor"),
        "provider": "claude",
        "model": "claude-sonnet",
        "prompt_path": Path("/repo/agents/invoice-extractor/prompt.md"),
        "input_schema_path": Path("/repo/agents/invoice-extractor/schemas/input.json"),
        "output_schema_path": Path("/repo/agents/invoice-extractor/schemas/output.json"),
        "eval_files": [Path("/repo/agents/invoice-extractor/golden.jsonl")],
        "thresholds": {"golden": EvalThresholds(min_pass_rate=1.0)},
    }


def test_agent_definition_round_trip() -> None:
    a = AgentDefinition(**_agent_def_kwargs())
    _round_trip(a)


def test_agent_definition_rejects_unknown_field() -> None:
    bad = _agent_def_kwargs() | {"unexpected": True}
    with pytest.raises(ValidationError):
        AgentDefinition(**bad)


def test_agent_definition_rejects_unknown_provider() -> None:
    bad = _agent_def_kwargs() | {"provider": "bedrock"}
    with pytest.raises(ValidationError):
        AgentDefinition(**bad)


def test_agent_definition_rejects_empty_eval_files() -> None:
    bad = _agent_def_kwargs() | {"eval_files": []}
    with pytest.raises(ValidationError):
        AgentDefinition(**bad)


# ---------- EvalCase ----------


def test_eval_case_round_trip() -> None:
    c = EvalCase(id="case-001", input={"text": "hi"}, expected={"intent": "greet"})
    _round_trip(c)
    judged = EvalCase(id="case-002", input={"text": "ok"})
    _round_trip(judged)


def test_eval_case_rejects_blank_id() -> None:
    with pytest.raises(ValidationError):
        EvalCase(id="", input={"text": "x"})


# ---------- TokenUsage ----------


def test_token_usage_round_trip() -> None:
    u = TokenUsage(input_tokens=120, output_tokens=45)
    _round_trip(u)


def test_token_usage_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        TokenUsage(input_tokens=-1, output_tokens=0)


# ---------- InvocationResult ----------


def test_invocation_result_round_trip_success() -> None:
    r = InvocationResult(
        output={"answer": 42},
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        latency_ms=250,
    )
    _round_trip(r)


def test_invocation_result_round_trip_failure() -> None:
    r = InvocationResult(
        output=None,
        usage=None,
        latency_ms=100,
        error="rate limit exceeded",
    )
    _round_trip(r)


def test_invocation_result_rejects_both_output_and_error() -> None:
    with pytest.raises(ValidationError):
        InvocationResult(
            output={"x": 1},
            usage=None,
            latency_ms=10,
            error="boom",
        )


def test_invocation_result_rejects_neither_output_nor_error() -> None:
    with pytest.raises(ValidationError):
        InvocationResult(output=None, usage=None, latency_ms=10)


# ---------- CaseResult ----------


def test_case_result_round_trip() -> None:
    inv = InvocationResult(
        output={"x": 1},
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        latency_ms=100,
    )
    r = CaseResult(case_id="c1", invocation=inv, passed=True)
    _round_trip(r)


def test_case_result_rejects_judge_score_out_of_range() -> None:
    inv = InvocationResult(
        output={"x": 1},
        usage=TokenUsage(input_tokens=1, output_tokens=1),
        latency_ms=1,
    )
    with pytest.raises(ValidationError):
        CaseResult(case_id="c1", invocation=inv, passed=True, judge_score=1.5)


# ---------- EvalRun ----------


def _eval_run_kwargs() -> dict[str, Any]:
    inv = InvocationResult(
        output={"x": 1},
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        latency_ms=100,
    )
    return {
        "agent_name": "invoice-extractor",
        "eval_set": "golden.jsonl",
        "git_sha": "abc1234",
        "cases": [CaseResult(case_id="c1", invocation=inv, passed=True)],
        "total_cost_usd": Decimal("0.0123"),
        "p50_latency_ms": 100,
        "p95_latency_ms": 250,
    }


def test_eval_run_round_trip() -> None:
    r = EvalRun(**_eval_run_kwargs())
    _round_trip(r)


def test_eval_run_rejects_short_sha() -> None:
    bad = _eval_run_kwargs() | {"git_sha": "abc"}
    with pytest.raises(ValidationError):
        EvalRun(**bad)


# ---------- SchemaDriftEntry ----------


def test_schema_drift_entry_round_trip() -> None:
    e = SchemaDriftEntry(
        case_id="c1",
        added_fields=["new_field"],
        removed_fields=["old_field"],
        type_changes={"amount": ("int", "str")},
    )
    _round_trip(e)


def test_schema_drift_entry_rejects_blank_case_id() -> None:
    with pytest.raises(ValidationError):
        SchemaDriftEntry(case_id="")


# ---------- ThresholdViolation ----------


def test_threshold_violation_round_trip() -> None:
    v = ThresholdViolation(
        eval_set="golden.jsonl",
        rule="min_pass_rate",
        expected=1.0,
        actual=0.9,
    )
    _round_trip(v)


def test_threshold_violation_rejects_unknown_rule() -> None:
    # Confirm Pydantic rejects values outside the Literal at runtime as
    # well as at static-check time.
    with pytest.raises(ValidationError):
        ThresholdViolation(
            eval_set="golden.jsonl",
            rule="ad_hoc",  # type: ignore[arg-type]
            expected=1.0,
            actual=0.9,
        )


# ---------- BehavioralDiff ----------


def test_behavioral_diff_round_trip() -> None:
    base = EvalRun(**_eval_run_kwargs())
    head_kwargs = _eval_run_kwargs() | {"git_sha": "def5678"}
    head = EvalRun(**head_kwargs)
    d = BehavioralDiff(
        agent_name="invoice-extractor",
        base_run=base,
        head_run=head,
        cost_delta_usd=Decimal("0.0010"),
        cost_delta_pct=8.13,
        pass_rate_delta_pct=0.0,
    )
    _round_trip(d)
