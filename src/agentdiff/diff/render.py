"""Render a `BehavioralDiff` as a markdown PR comment.

The output is one self-contained block per (agent, eval_set). When a
PR touches multiple agents or eval sets, the caller concatenates
multiple rendered blocks separated by `---`.

Layout principle: lead with the verdict line, then violations, then
stats in a table, then the per-case lists. A reader skimming should
be able to tell within one second whether a PR is green / warning /
blocked. The verdict line carries an emoji + bold word that survives
both terminal rendering (Rich substitutes shortcodes) and GitHub PR
markdown (literal emoji renders natively).
"""

from __future__ import annotations

from decimal import Decimal

from agentdiff.definition.schema import (
    BehavioralDiff,
    CaseResult,
    SchemaDriftEntry,
    ThresholdViolation,
)


def render_diff(diff: BehavioralDiff) -> str:
    """Return a self-contained markdown block describing one diff."""
    lines: list[str] = []
    lines.append(f"### `{diff.agent_name}` · `{diff.head_run.eval_set}`")
    lines.append("")
    lines.append(_render_verdict(diff))
    lines.append("")

    if diff.threshold_violations:
        lines.extend(_render_violation_details(diff.threshold_violations))
        lines.append("")

    lines.extend(_render_stats_table(diff))
    lines.append("")

    if diff.regressions:
        lines.append(f"**:small_red_triangle_down: Regressions ({len(diff.regressions)})**")
        lines.extend(f"- `{cid}`" for cid in diff.regressions)
        lines.append("")
    if diff.improvements:
        lines.append(f"**:sparkles: Improvements ({len(diff.improvements)})**")
        lines.extend(f"- `{cid}`" for cid in diff.improvements)
        lines.append("")

    if diff.schema_drift:
        lines.extend(_render_schema_drift(diff.schema_drift))
        lines.append("")

    footer = _render_footer(diff)
    if footer:
        lines.append(footer)

    return "\n".join(lines).rstrip() + "\n"


def render_case_details(diff: BehavioralDiff) -> str:
    """Verbose per-case breakdown: pass/fail, judge score, reasoning.

    Not suitable for PR comments — `render_diff` is the comment.
    This is for human inspection during local development when you
    want to see *why* a case got the score it got.
    """
    lines = ["#### Case details", ""]
    base_by_id = {c.case_id: c for c in diff.base_run.cases}
    head_by_id = {c.case_id: c for c in diff.head_run.cases}
    common = sorted(set(base_by_id) & set(head_by_id))

    for case_id in common:
        b = base_by_id[case_id]
        h = head_by_id[case_id]
        lines.append(f"**`{case_id}`**")
        lines.append(_render_case_side("base", b))
        lines.append(_render_case_side("head", h))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------- verdict (the headline) ----------


def _render_verdict(diff: BehavioralDiff) -> str:
    """One line summarizing the whole diff. Emoji + status + numbers."""
    base_pass = _pass_rate(diff.base_run.cases)
    head_pass = _pass_rate(diff.head_run.cases)
    n_reg = len(diff.regressions)
    n_imp = len(diff.improvements)
    n_drift = len(diff.schema_drift)

    if diff.threshold_violations:
        return (
            f":rotating_light: **FAIL** · pass rate {base_pass:.0%} → {head_pass:.0%} "
            f"({diff.pass_rate_delta_pct:+.1f}pp) · "
            f"{n_reg} regression{_s(n_reg)} · merge blocked"
        )
    if n_reg > 0:
        return (
            f":warning: **WARN** · pass rate {base_pass:.0%} → {head_pass:.0%} "
            f"({diff.pass_rate_delta_pct:+.1f}pp) · "
            f"{n_reg} regression{_s(n_reg)}, {n_imp} improvement{_s(n_imp)} · "
            f"no threshold breached"
        )
    if n_imp > 0:
        return (
            f":white_check_mark: **PASS** · pass rate {base_pass:.0%} → {head_pass:.0%} · "
            f"{n_imp} improvement{_s(n_imp)}, 0 regressions"
        )
    if n_drift > 0:
        return (
            f":heavy_minus_sign: **PASS** · pass rate stable at {head_pass:.0%} · "
            f"output shape changed in {n_drift} case{_s(n_drift)}"
        )
    return f":white_check_mark: **PASS** · no behavioral changes · pass rate {head_pass:.0%}"


def _render_violation_details(violations: list[ThresholdViolation]) -> list[str]:
    """One bullet per violation, after the verdict line that announces them."""
    lines = ["> [!CAUTION]", "> **Threshold violation"]
    if len(violations) > 1:
        lines[-1] += "s"
    lines[-1] += ":**"
    for v in violations:
        if v.rule == "min_pass_rate":
            lines.append(
                f"> - `{v.eval_set}` · `minPassRate={v.expected:.2f}`, got `{v.actual:.2f}`"
            )
        else:  # max_regression_pct
            lines.append(
                f"> - `{v.eval_set}` · `maxRegressionPct={v.expected:.2%}`, got `{v.actual:.2%}`"
            )
    return lines


# ---------- stats table ----------


def _render_stats_table(diff: BehavioralDiff) -> list[str]:
    base_pass = _pass_rate(diff.base_run.cases)
    head_pass = _pass_rate(diff.head_run.cases)
    base_cost = diff.base_run.total_cost_usd
    head_cost = diff.head_run.total_cost_usd

    rows = [
        (
            "Pass rate",
            f"{base_pass:.1%}",
            f"{head_pass:.1%}",
            _delta_str_pp(diff.pass_rate_delta_pct),
        ),
        (
            "Cost (USD)",
            f"${base_cost:.4f}",
            f"${head_cost:.4f}",
            _delta_str_pct(diff.cost_delta_pct),
        ),
        (
            "Latency p50",
            f"{diff.base_run.p50_latency_ms}ms",
            f"{diff.head_run.p50_latency_ms}ms",
            _delta_str_ms(diff.head_run.p50_latency_ms - diff.base_run.p50_latency_ms),
        ),
        (
            "Latency p95",
            f"{diff.base_run.p95_latency_ms}ms",
            f"{diff.head_run.p95_latency_ms}ms",
            _delta_str_ms(diff.head_run.p95_latency_ms - diff.base_run.p95_latency_ms),
        ),
    ]
    return [
        "| | base | head | Δ |",
        "| --- | --- | --- | --- |",
        *(f"| {label} | {b} | {h} | {d} |" for label, b, h, d in rows),
    ]


# ---------- schema drift ----------


def _render_schema_drift(entries: list[SchemaDriftEntry]) -> list[str]:
    lines = [f"**:triangular_ruler: Schema drift ({len(entries)})**"]
    for e in entries:
        bits: list[str] = []
        if e.added_fields:
            bits.append(f"added {', '.join(f'`{f}`' for f in e.added_fields)}")
        if e.removed_fields:
            bits.append(f"removed {', '.join(f'`{f}`' for f in e.removed_fields)}")
        if e.type_changes:
            tc = ", ".join(f"`{k}`: `{old}` → `{new}`" for k, (old, new) in e.type_changes.items())
            bits.append(tc)
        lines.append(f"- `{e.case_id}` · {' · '.join(bits)}")
    return lines


# ---------- footer ----------


def _render_footer(diff: BehavioralDiff) -> str:
    parts: list[str] = []
    if diff.head_run.judge_cost_usd > Decimal("0") or diff.base_run.judge_cost_usd > Decimal("0"):
        parts.append(
            f"Judge cost: base ${diff.base_run.judge_cost_usd:.4f}, "
            f"head ${diff.head_run.judge_cost_usd:.4f}"
        )
    if diff.head_run.judge_fallback_used or diff.base_run.judge_fallback_used:
        parts.append(
            ":warning: judge used the generic fallback rubric — "
            "write a `<eval-set>.judge.md` for better grading"
        )
    if not parts:
        return ""
    return "_" + " · ".join(parts) + "_"


# ---------- case-details rendering ----------


def _render_case_side(label: str, c: CaseResult) -> str:
    mark = ":white_check_mark:" if c.passed else ":x:"
    score_part = f" `{c.judge_score:.2f}`" if c.judge_score is not None else ""
    reasoning = c.judge_reasoning or c.failure_reason
    if reasoning is None and c.invocation.output is not None:
        reasoning = f"output={c.invocation.output!r}"
    reasoning = reasoning or "(no reasoning)"
    return f"- {label}: {mark}{score_part} — {reasoning}"


# ---------- helpers ----------


def _pass_rate(cases: list[CaseResult]) -> float:
    if not cases:
        return 0.0
    return sum(1 for c in cases if c.passed) / len(cases)


def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _delta_str_pp(pct: float) -> str:
    """Format a pass-rate pp delta. Up = good, down = bad."""
    if abs(pct) < 0.05:
        return "—"
    if pct > 0:
        return f":arrow_up_small: +{pct:.1f}pp"
    return f":small_red_triangle_down: {pct:.1f}pp"


def _delta_str_pct(pct: float) -> str:
    """Format a percentage delta. No directional emoji — sign is enough."""
    if abs(pct) < 0.05:
        return "—"
    return f"{pct:+.1f}%"


def _delta_str_ms(diff_ms: int) -> str:
    if diff_ms == 0:
        return "—"
    return f"{diff_ms:+d}ms"
