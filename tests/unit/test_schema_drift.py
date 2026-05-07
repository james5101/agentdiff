"""Tests for `diff.schema_drift.detect_schema_drift`."""

from __future__ import annotations

from decimal import Decimal

from agentdiff.definition.schema import (
    CaseResult,
    EvalRun,
    InvocationResult,
    TokenUsage,
)
from agentdiff.diff.schema_drift import detect_schema_drift


def _case(case_id: str, output: dict[str, object] | None, *, passed: bool = True) -> CaseResult:
    inv = InvocationResult(
        output=output,
        usage=TokenUsage(input_tokens=10, output_tokens=5) if output else None,
        latency_ms=100,
        error=None if output else "boom",
    )
    return CaseResult(case_id=case_id, invocation=inv, passed=passed)


def _run(cases: list[CaseResult], *, sha: str = "aaaaaaa") -> EvalRun:
    return EvalRun(
        agent_name="a",
        eval_set="golden.jsonl",
        git_sha=sha,
        cases=cases,
        total_cost_usd=Decimal("0.001"),
        p50_latency_ms=100,
        p95_latency_ms=100,
    )


def test_detect_no_drift_when_shapes_match() -> None:
    base = _run([_case("c1", {"intent": "x"})])
    head = _run([_case("c1", {"intent": "y"})])
    assert detect_schema_drift(base, head) == []


def test_detect_added_field() -> None:
    base = _run([_case("c1", {"intent": "x"})])
    head = _run([_case("c1", {"intent": "x", "confidence": 0.9})])

    drift = detect_schema_drift(base, head)
    assert len(drift) == 1
    assert drift[0].case_id == "c1"
    assert drift[0].added_fields == ["confidence"]
    assert drift[0].removed_fields == []
    assert drift[0].type_changes == {}


def test_detect_removed_field() -> None:
    base = _run([_case("c1", {"intent": "x", "confidence": 0.9})])
    head = _run([_case("c1", {"intent": "x"})])

    drift = detect_schema_drift(base, head)
    assert drift[0].removed_fields == ["confidence"]


def test_detect_type_change() -> None:
    base = _run([_case("c1", {"intent": "x", "score": 1})])  # int
    head = _run([_case("c1", {"intent": "x", "score": "high"})])  # str

    drift = detect_schema_drift(base, head)
    assert drift[0].type_changes == {"score": ("int", "str")}


def test_detect_skips_cases_with_no_output() -> None:
    """If either side errored, we have no shape to compare."""
    base = _run([_case("c1", None, passed=False)])
    head = _run([_case("c1", {"intent": "x"})])
    assert detect_schema_drift(base, head) == []


def test_detect_only_compares_common_case_ids() -> None:
    base = _run([_case("c1", {"a": 1}), _case("c2", {"b": 2})])
    head = _run([_case("c1", {"a": 1, "z": 9}), _case("c3", {"c": 3})])

    drift = detect_schema_drift(base, head)
    # Only c1 is common; c2 and c3 are not compared.
    assert [d.case_id for d in drift] == ["c1"]
    assert drift[0].added_fields == ["z"]
