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


# ---------- verdict line ----------


def test_clean_diff_renders_pass_verdict() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)])
    out = render_diff(_diff(base=base, head=head))

    assert "**PASS**" in out
    assert "no behavioral changes" in out
    # No drama sections.
    assert "Threshold violation" not in out
    assert "Regressions" not in out


def test_threshold_violation_yields_fail_verdict() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=False)])
    out = render_diff(
        _diff(
            base=base,
            head=head,
            regressions=["c1"],
            threshold_violations=[
                ThresholdViolation(
                    eval_set="golden.jsonl",
                    rule="min_pass_rate",
                    expected=1.0,
                    actual=0.0,
                )
            ],
            pass_rate_delta_pct=-100.0,
        )
    )

    assert "**FAIL**" in out
    assert "merge blocked" in out
    # Verdict line appears before the regression list.
    assert out.find("**FAIL**") < out.find("Regressions")
    # Threshold details surface as a CAUTION callout with the rule name.
    assert "Threshold violation" in out
    assert "minPassRate=1.00" in out


def test_regression_without_violation_yields_warn_verdict() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True), _case("c2", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True), _case("c2", passed=False)])
    out = render_diff(_diff(base=base, head=head, regressions=["c2"], pass_rate_delta_pct=-50.0))
    assert "**WARN**" in out
    assert "1 regression" in out


def test_only_improvements_yields_pass_verdict() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=False)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)])
    out = render_diff(_diff(base=base, head=head, improvements=["c1"], pass_rate_delta_pct=100.0))
    assert "**PASS**" in out
    assert "1 improvement" in out


# ---------- stats table ----------


def test_stats_table_present_with_pipe_delimiters() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)], cost=Decimal("0.0010"))
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)], cost=Decimal("0.0015"))
    out = render_diff(_diff(base=base, head=head, cost_delta_pct=50.0))

    # Markdown-table delimiters.
    assert "| --- | --- | --- | --- |" in out
    # Each row label.
    assert "Pass rate" in out
    assert "Cost (USD)" in out
    assert "Latency p50" in out
    assert "Latency p95" in out


def test_stats_table_pass_rate_cells() -> None:
    base = _run(sha="aaaaaaa", cases=[_case(f"c{i}", passed=True) for i in range(4)])
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
    # Pass rate row has both percentages and the delta with directional arrow.
    assert "100.0%" in out
    assert "50.0%" in out
    assert "-50.0pp" in out


# ---------- regressions / improvements ----------


def test_regressions_listed_one_per_line() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True), _case("c2", passed=True)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=False), _case("c2", passed=False)])
    out = render_diff(_diff(base=base, head=head, regressions=["c1", "c2"]))

    assert "Regressions (2)" in out
    # One bullet per case ID.
    assert "- `c1`" in out
    assert "- `c2`" in out


def test_improvements_have_their_own_section() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=False)])
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)])
    out = render_diff(_diff(base=base, head=head, improvements=["c1"]))

    assert "Improvements (1)" in out
    assert "- `c1`" in out


# ---------- schema drift ----------


def test_schema_drift_renders_per_case() -> None:
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
    assert "`score`: `int` → `str`" in out


# ---------- footer (judge cost / fallback) ----------


def test_render_warns_on_judge_fallback() -> None:
    base = _run(sha="aaaaaaa", cases=[_case("c1", passed=True)], fallback=True)
    head = _run(sha="bbbbbbb", cases=[_case("c1", passed=True)], fallback=True)
    out = render_diff(_diff(base=base, head=head))
    assert "fallback rubric" in out


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
    assert "0.85" in out
    assert "0.82" in out
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
    assert "c1" not in out
    assert "c2" not in out
