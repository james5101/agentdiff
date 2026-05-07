"""Golden tests for `diff.compare.compare`."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from agentdiff.definition.schema import (
    AgentDefinition,
    CaseResult,
    EvalRun,
    EvalThresholds,
    InvocationResult,
    TokenUsage,
)
from agentdiff.diff.compare import compare


def _case(case_id: str, *, passed: bool, output: dict[str, object] | None = None) -> CaseResult:
    inv = InvocationResult(
        output=output if output is not None else {"intent": "x"},
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        latency_ms=100,
    )
    return CaseResult(case_id=case_id, invocation=inv, passed=passed)


def _run(
    *,
    sha: str,
    cases: list[CaseResult],
    cost: Decimal = Decimal("0.0010"),
    p50: int = 100,
    p95: int = 200,
) -> EvalRun:
    return EvalRun(
        agent_name="a",
        eval_set="golden.jsonl",
        git_sha=sha,
        cases=cases,
        total_cost_usd=cost,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
    )


def _agent_with_thresholds(
    make_agent: Callable[..., AgentDefinition],
    *,
    thresholds: dict[str, EvalThresholds],
) -> AgentDefinition:
    a = make_agent(name="a")
    return a.model_copy(update={"thresholds": thresholds})


# ---------- regressions / improvements ----------


def test_compare_identifies_regressions_and_improvements(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"golden": EvalThresholds(min_pass_rate=0.5)},
    )
    base = _run(
        sha="aaaaaaa",
        cases=[
            _case("c1", passed=True),
            _case("c2", passed=True),
            _case("c3", passed=False),
        ],
    )
    head = _run(
        sha="bbbbbbb",
        cases=[
            _case("c1", passed=True),
            _case("c2", passed=False),  # regression
            _case("c3", passed=True),  # improvement
        ],
    )

    diff = compare(agent=agent, base=base, head=head)
    assert diff.regressions == ["c2"]
    assert diff.improvements == ["c3"]
    # Pass rate: 2/3 → 2/3 = 0% delta.
    assert diff.pass_rate_delta_pct == 0.0


def test_compare_skips_cases_only_in_one_run(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    """Cases added/removed in the PR don't appear as regressions."""
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"golden": EvalThresholds(min_pass_rate=0.0)},
    )
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True), _case("c2", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True), _case("c3", passed=True)])

    diff = compare(agent=agent, base=base, head=head)
    assert diff.regressions == []
    assert diff.improvements == []


# ---------- pass rate / cost / threshold violations ----------


def test_compare_computes_pass_rate_delta(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"golden": EvalThresholds(min_pass_rate=0.0)},
    )
    base = _run(
        sha="aaaaaaa",
        cases=[_case(f"c{i}", passed=True) for i in range(4)],
    )
    head = _run(
        sha="bbbbbbb",
        cases=[
            _case("c0", passed=True),
            _case("c1", passed=True),
            _case("c2", passed=False),
            _case("c3", passed=False),
        ],
    )

    diff = compare(agent=agent, base=base, head=head)
    # 100% → 50% = -50% delta.
    assert diff.pass_rate_delta_pct == -50.0


def test_compare_flags_min_pass_rate_violation(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"golden": EvalThresholds(min_pass_rate=1.0)},
    )
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=False)])

    diff = compare(agent=agent, base=base, head=head)
    assert len(diff.threshold_violations) == 1
    v = diff.threshold_violations[0]
    assert v.rule == "min_pass_rate"
    assert v.expected == 1.0
    assert v.actual == 0.0


def test_compare_flags_max_regression_pct_violation(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"golden": EvalThresholds(max_regression_pct=0.05)},
    )
    base = _run(sha="aaaaaaa", cases=[_case(f"c{i}", passed=True) for i in range(10)])
    head = _run(
        sha="bbbbbbb",
        cases=[_case(f"c{i}", passed=(i > 1)) for i in range(10)],  # 2 regressions
    )

    diff = compare(agent=agent, base=base, head=head)
    rules = {v.rule for v in diff.threshold_violations}
    assert "max_regression_pct" in rules


def test_compare_no_thresholds_no_violations(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    """Eval set with no threshold entry → no violations possible."""
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"adversarial": EvalThresholds(min_pass_rate=1.0)},
    )
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=False)])

    diff = compare(agent=agent, base=base, head=head)
    assert diff.threshold_violations == []


def test_compare_computes_cost_delta(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"golden": EvalThresholds(min_pass_rate=0.0)},
    )
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)], cost=Decimal("0.0100"))
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)], cost=Decimal("0.0150"))

    diff = compare(agent=agent, base=base, head=head)
    assert diff.cost_delta_usd == Decimal("0.0050")
    assert diff.cost_delta_pct == 50.0


def test_compare_handles_zero_base_cost(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"golden": EvalThresholds(min_pass_rate=0.0)},
    )
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)], cost=Decimal("0"))
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)], cost=Decimal("0.005"))

    diff = compare(agent=agent, base=base, head=head)
    # Zero-base cost → don't compute % (would be div by 0).
    assert diff.cost_delta_pct == 0.0
    assert diff.cost_delta_usd == Decimal("0.005")


# ---------- input validation ----------


def test_compare_rejects_agent_mismatch(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"golden": EvalThresholds(min_pass_rate=0.0)},
    )
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head_kwargs = base.model_dump()
    head_kwargs["git_sha"] = "bbbbbbb"
    head_kwargs["agent_name"] = "different-agent"
    head = EvalRun.model_validate(head_kwargs)

    with pytest.raises(ValueError, match="agent_name mismatch"):
        compare(agent=agent, base=base, head=head)


def test_compare_rejects_eval_set_mismatch(
    make_agent: Callable[..., AgentDefinition],
) -> None:
    agent = _agent_with_thresholds(
        make_agent,
        thresholds={"golden": EvalThresholds(min_pass_rate=0.0)},
    )
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head_kwargs = base.model_dump()
    head_kwargs["git_sha"] = "bbbbbbb"
    head_kwargs["eval_set"] = "adversarial.jsonl"
    head = EvalRun.model_validate(head_kwargs)

    with pytest.raises(ValueError, match="eval_set mismatch"):
        compare(agent=agent, base=base, head=head)
