"""Render a `BehavioralDiff` as a markdown PR comment.

The output is one self-contained block per (agent, eval_set). When a
PR touches multiple agents or eval sets, the caller concatenates
multiple rendered blocks separated by `---`.
"""

from __future__ import annotations

from decimal import Decimal

from agentdiff.definition.schema import (
    BehavioralDiff,
    SchemaDriftEntry,
    ThresholdViolation,
)


def render_diff(diff: BehavioralDiff) -> str:
    """Return a self-contained markdown block describing one diff."""
    lines: list[str] = []
    lines.append(f"### `{diff.agent_name}` — `{diff.head_run.eval_set}`")
    lines.append("")

    if diff.threshold_violations:
        lines.extend(_render_violations(diff.threshold_violations))
        lines.append("")

    if diff.regressions:
        lines.append(_render_case_list("Regressions", diff.regressions, ":x:"))
    if diff.improvements:
        lines.append(_render_case_list("Improvements", diff.improvements, ":white_check_mark:"))

    lines.extend(_render_pass_rate(diff))
    lines.extend(_render_cost(diff))
    lines.extend(_render_latency(diff))

    if diff.schema_drift:
        lines.append("")
        lines.extend(_render_schema_drift(diff.schema_drift))

    if diff.head_run.judge_fallback_used or diff.base_run.judge_fallback_used:
        lines.append("")
        lines.append(
            "> :warning: judge model used the generic fallback rubric — "
            "consider adding a `<eval-set>.judge.md` rubric file for better grading."
        )

    if diff.head_run.judge_cost_usd > Decimal("0") or diff.base_run.judge_cost_usd > Decimal("0"):
        lines.append("")
        lines.append(
            f"_Judge cost: base ${diff.base_run.judge_cost_usd:.6f}, "
            f"head ${diff.head_run.judge_cost_usd:.6f}_"
        )

    return "\n".join(lines).rstrip() + "\n"


def _render_violations(violations: list[ThresholdViolation]) -> list[str]:
    lines = ["**:no_entry: Threshold violations (blocks merge):**"]
    for v in violations:
        if v.rule == "min_pass_rate":
            lines.append(f"- `{v.eval_set}` minPassRate={v.expected:.2f} → got {v.actual:.2f}")
        else:  # max_regression_pct
            lines.append(f"- `{v.eval_set}` maxRegressionPct={v.expected:.2%} → got {v.actual:.2%}")
    return lines


def _render_case_list(title: str, ids: list[str], emoji: str) -> str:
    formatted = ", ".join(f"`{cid}`" for cid in ids)
    return f"**{emoji} {title} ({len(ids)}):** {formatted}"


def _render_pass_rate(diff: BehavioralDiff) -> list[str]:
    base = _pass_rate(diff.base_run.cases)
    head = _pass_rate(diff.head_run.cases)
    arrow = _delta_arrow(diff.pass_rate_delta_pct)
    return [f"**Pass rate:** {base:.1%} → {head:.1%} ({arrow}{diff.pass_rate_delta_pct:+.1f}pp)"]


def _render_cost(diff: BehavioralDiff) -> list[str]:
    base = diff.base_run.total_cost_usd
    head = diff.head_run.total_cost_usd
    arrow = _delta_arrow(-diff.cost_delta_pct)  # cheaper is good, so flip
    return [f"**Cost:** ${base:.6f} → ${head:.6f} ({arrow}{diff.cost_delta_pct:+.1f}%)"]


def _render_latency(diff: BehavioralDiff) -> list[str]:
    return [
        f"**Latency:** "
        f"p50 {diff.base_run.p50_latency_ms}ms → {diff.head_run.p50_latency_ms}ms, "
        f"p95 {diff.base_run.p95_latency_ms}ms → {diff.head_run.p95_latency_ms}ms"
    ]


def _render_schema_drift(entries: list[SchemaDriftEntry]) -> list[str]:
    lines = [f"**Schema drift ({len(entries)}):**"]
    for e in entries:
        bits: list[str] = []
        if e.added_fields:
            bits.append(f"added {', '.join(f'`{f}`' for f in e.added_fields)}")
        if e.removed_fields:
            bits.append(f"removed {', '.join(f'`{f}`' for f in e.removed_fields)}")
        if e.type_changes:
            tc = ", ".join(f"`{k}`: {old}→{new}" for k, (old, new) in e.type_changes.items())
            bits.append(f"type changes: {tc}")
        lines.append(f"- `{e.case_id}`: {'; '.join(bits)}")
    return lines


def _pass_rate(cases: list) -> float:  # type: ignore[type-arg]
    if not cases:
        return 0.0
    return sum(1 for c in cases if c.passed) / len(cases)


def _delta_arrow(pct: float) -> str:
    """Tiny visual nudge: positive→up arrow, negative→down arrow.

    Caller passes the value where positive == good. Returns just an
    emoji + nbsp so the number that follows lines up nicely.
    """
    if pct > 0.05:
        return ":arrow_up_small: "
    if pct < -0.05:
        return ":arrow_down_small: "
    return ""
