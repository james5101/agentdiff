"""Produce a `BehavioralDiff` from a base + head `EvalRun` pair.

A `BehavioralDiff` is per (agent, eval_set). Agents with multiple
eval sets get one BehavioralDiff per set; callers iterate.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from agentdiff.definition.schema import (
    AgentDefinition,
    BehavioralDiff,
    EvalRun,
    EvalThresholds,
    ThresholdViolation,
)
from agentdiff.diff.schema_drift import detect_schema_drift


def compare(
    *,
    agent: AgentDefinition,
    base: EvalRun,
    head: EvalRun,
) -> BehavioralDiff:
    """Compare two `EvalRun`s of the same agent + eval_set.

    Raises `ValueError` if the agent name or eval set don't match —
    these are programming errors, not user data, so loud failure
    beats silent reporting on incomparable runs.
    """
    if base.agent_name != head.agent_name:
        raise ValueError(f"agent_name mismatch: base={base.agent_name!r}, head={head.agent_name!r}")
    if base.eval_set != head.eval_set:
        raise ValueError(f"eval_set mismatch: base={base.eval_set!r}, head={head.eval_set!r}")

    base_by_id = {c.case_id: c for c in base.cases}
    head_by_id = {c.case_id: c for c in head.cases}
    common_ids = sorted(set(base_by_id) & set(head_by_id))

    regressions = [
        cid for cid in common_ids if base_by_id[cid].passed and not head_by_id[cid].passed
    ]
    improvements = [
        cid for cid in common_ids if not base_by_id[cid].passed and head_by_id[cid].passed
    ]

    base_pass_rate = _pass_rate(base)
    head_pass_rate = _pass_rate(head)
    pass_rate_delta_pct = (head_pass_rate - base_pass_rate) * 100

    cost_delta_usd = head.total_cost_usd - base.total_cost_usd
    cost_delta_pct = _pct_change(base.total_cost_usd, head.total_cost_usd)

    schema_drift = detect_schema_drift(base, head)

    threshold_violations = _check_thresholds(
        agent=agent,
        eval_set=head.eval_set,
        head=head,
        regressions=regressions,
    )

    return BehavioralDiff(
        agent_name=agent.name,
        base_run=base,
        head_run=head,
        regressions=regressions,
        improvements=improvements,
        schema_drift=schema_drift,
        cost_delta_usd=cost_delta_usd,
        cost_delta_pct=cost_delta_pct,
        pass_rate_delta_pct=pass_rate_delta_pct,
        threshold_violations=threshold_violations,
    )


def _pass_rate(run: EvalRun) -> float:
    if not run.cases:
        return 0.0
    return sum(1 for c in run.cases if c.passed) / len(run.cases)


def _pct_change(before: Decimal, after: Decimal) -> float:
    if before == 0:
        return 0.0
    return float((after - before) / before * 100)


def _check_thresholds(
    *,
    agent: AgentDefinition,
    eval_set: str,
    head: EvalRun,
    regressions: list[str],
) -> list[ThresholdViolation]:
    """Compare head run against the agent's thresholds for this eval set.

    Threshold keys in `agentdiff.yaml` use the eval set's stem (e.g.,
    "golden" for "golden.jsonl"); we honor that convention.
    """
    key = Path(eval_set).stem
    thresholds: EvalThresholds | None = agent.thresholds.get(key)
    if thresholds is None:
        return []

    violations: list[ThresholdViolation] = []
    n_cases = len(head.cases)

    if thresholds.min_pass_rate is not None:
        actual = _pass_rate(head)
        if actual < thresholds.min_pass_rate:
            violations.append(
                ThresholdViolation(
                    eval_set=eval_set,
                    rule="min_pass_rate",
                    expected=thresholds.min_pass_rate,
                    actual=actual,
                )
            )

    if thresholds.max_regression_pct is not None:
        actual_pct = (len(regressions) / n_cases) if n_cases else 0.0
        if actual_pct > thresholds.max_regression_pct:
            violations.append(
                ThresholdViolation(
                    eval_set=eval_set,
                    rule="max_regression_pct",
                    expected=thresholds.max_regression_pct,
                    actual=actual_pct,
                )
            )

    return violations
