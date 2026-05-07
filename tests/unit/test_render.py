"""Tests for `diff.render.render_diff` — the eventual PR comment shape."""

from __future__ import annotations

from decimal import Decimal

from agentdiff.definition.schema import (
    BehavioralDiff,
    CaseResult,
    EvalRun,
    InvocationResult,
    SchemaDriftEntry,
    ThresholdViolation,
    TokenUsage,
)
from agentdiff.diff.render import render_case_details, render_diff


def _case(
    case_id: str,
    *,
    passed: bool,
    judge_score: float | None = None,
    judge_reasoning: str | None = None,
    failure_reason: str | None = None,
) -> CaseResult:
    inv = InvocationResult(
        output={"intent": "x"},
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        latency_ms=100,
    )
    return CaseResult(
        case_id=case_id,
        invocation=inv,
        passed=passed,
        judge_score=judge_score,
        judge_reasoning=judge_reasoning,
        failure_reason=failure_reason,
    )


def _run(
    *,
    sha: str,
    cases: list[CaseResult],
    cost: Decimal = Decimal("0.001"),
    p50: int = 100,
    p95: int = 200,
    judge_cost: Decimal = Decimal("0"),
    fallback: bool = False,
) -> EvalRun:
    return EvalRun(
        agent_name="a",
        eval_set="golden.jsonl",
        git_sha=sha,
        cases=cases,
        total_cost_usd=cost,
        judge_cost_usd=judge_cost,
        judge_fallback_used=fallback,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
    )


def _diff(
    *,
    base: EvalRun,
    head: EvalRun,
    regressions: list[str] | None = None,
    improvements: list[str] | None = None,
    schema_drift: list[SchemaDriftEntry] | None = None,
    threshold_violations: list[ThresholdViolation] | None = None,
    cost_delta_usd: Decimal = Decimal("0"),
    cost_delta_pct: float = 0.0,
    pass_rate_delta_pct: float = 0.0,
) -> BehavioralDiff:
    return BehavioralDiff(
        agent_name="pr-risk-classifier",
        base_run=base,
        head_run=head,
        regressions=regressions or [],
        improvements=improvements or [],
        schema_drift=schema_drift or [],
        threshold_violations=threshold_violations or [],
        cost_delta_usd=cost_delta_usd,
        cost_delta_pct=cost_delta_pct,
        pass_rate_delta_pct=pass_rate_delta_pct,
    )


def test_render_clean_diff_has_no_drama() -> None:
    """No regressions, no violations, no drift → still renders cleanly."""
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)])
    out = render_diff(_diff(base=base, head=head))

    assert "pr-risk-classifier" in out
    assert "golden.jsonl" in out
    assert "Pass rate:" in out
    assert "Cost:" in out
    assert "Latency:" in out
    assert "Threshold violations" not in out
    assert "Regressions" not in out


def test_render_lists_regressions_and_improvements() -> None:
    base = _run(
        sha="aaaaaaa",
        cases=[_case("c1", passed=True), _case("c2", passed=False)],
    )
    head = _run(
        sha="bbbbbbb",
        cases=[_case("c1", passed=False), _case("c2", passed=True)],
    )
    diff = _diff(
        base=base,
        head=head,
        regressions=["c1"],
        improvements=["c2"],
    )
    out = render_diff(diff)

    assert "Regressions (1)" in out
    assert "`c1`" in out
    assert "Improvements (1)" in out
    assert "`c2`" in out


def test_render_threshold_violations_appear_first() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=False)])
    violations = [
        ThresholdViolation(
            eval_set="golden.jsonl",
            rule="min_pass_rate",
            expected=1.0,
            actual=0.0,
        )
    ]
    out = render_diff(
        _diff(
            base=base,
            head=head,
            regressions=["c1"],
            threshold_violations=violations,
            pass_rate_delta_pct=-100.0,
        )
    )

    # Violations section comes before the regression list.
    violation_idx = out.find("Threshold violations")
    regression_idx = out.find("Regressions")
    assert violation_idx != -1
    assert regression_idx != -1
    assert violation_idx < regression_idx
    assert "blocks merge" in out
    assert "minPassRate=1.00" in out


def test_render_max_regression_pct_violation_uses_percent_format() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=False)])
    out = render_diff(
        _diff(
            base=base,
            head=head,
            threshold_violations=[
                ThresholdViolation(
                    eval_set="adversarial.jsonl",
                    rule="max_regression_pct",
                    expected=0.05,
                    actual=0.20,
                )
            ],
        )
    )
    assert "maxRegressionPct=5.00%" in out
    assert "got 20.00%" in out


def test_render_includes_schema_drift() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)])
    drift = [
        SchemaDriftEntry(
            case_id="c1",
            added_fields=["new_field"],
            removed_fields=["old_field"],
            type_changes={"score": ("int", "str")},
        )
    ]
    out = render_diff(_diff(base=base, head=head, schema_drift=drift))

    assert "Schema drift (1)" in out
    assert "added `new_field`" in out
    assert "removed `old_field`" in out
    assert "`score`: int→str" in out


def test_render_warns_on_judge_fallback() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)], fallback=True)
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)], fallback=True)
    out = render_diff(_diff(base=base, head=head))
    assert "fallback rubric" in out
    assert ":warning:" in out


def test_render_shows_judge_cost_when_used() -> None:
    base = _run(
        sha="aaaaaaa",
        cases=[_case("c1", passed=True)],
        judge_cost=Decimal("0.0050"),
    )
    head = _run(
        sha="bbbbbbb",
        cases=[_case("c1", passed=True)],
        judge_cost=Decimal("0.0048"),
    )
    out = render_diff(_diff(base=base, head=head))
    assert "Judge cost" in out
    assert "0.005" in out


def test_render_omits_judge_cost_when_zero() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)])
    out = render_diff(_diff(base=base, head=head))
    assert "Judge cost" not in out


# ---------- render_case_details ----------


def test_case_details_show_judge_reasoning_for_passing_cases() -> None:
    base = _run(
        sha="aaaaaaa",
        cases=[_case("c1", passed=True, judge_score=0.85, judge_reasoning="defensible call")],
    )
    head = _run(
        sha="bbbbbbb",
        cases=[_case("c1", passed=True, judge_score=0.82, judge_reasoning="defensible call")],
    )
    out = render_case_details(_diff(base=base, head=head))

    assert "`c1`" in out
    assert "score=0.85" in out
    assert "score=0.82" in out
    assert "defensible call" in out


def test_case_details_show_failure_reason_for_non_judge_failures() -> None:
    """Timeout / schema-violation cases have failure_reason, not judge_reasoning."""
    base = _run(
        sha="aaaaaaa",
        cases=[_case("c1", passed=False, failure_reason="timeout")],
    )
    head = _run(
        sha="bbbbbbb",
        cases=[_case("c1", passed=True, judge_score=0.9, judge_reasoning="ok")],
    )
    out = render_case_details(_diff(base=base, head=head))
    assert "timeout" in out
    assert "ok" in out


def test_case_details_skip_cases_only_in_one_run() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c2", passed=True)])
    out = render_case_details(_diff(base=base, head=head))
    # Neither c1 nor c2 should appear since they aren't common to both.
    assert "c1" not in out
    assert "c2" not in out


def test_render_pass_rate_format() -> None:
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
    out = render_diff(_diff(base=base, head=head, pass_rate_delta_pct=-50.0))
    assert "100.0% → 50.0%" in out
    assert "-50.0pp" in out
