"""Run a full eval set against one agent version, with bounded concurrency.

A run consists of N independent cases; each is its own coroutine, with
concurrency capped by an `asyncio.Semaphore` so we don't rate-limit the
provider. The wall-clock budget for the whole run is enforced by an
outer `asyncio.timeout()` block; per-case timeouts live inside `run_case`.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from agentdiff.definition.schema import (
    AgentDefinition,
    CaseResult,
    EvalCase,
    EvalRun,
)
from agentdiff.eval.case import (
    DEFAULT_CASE_TIMEOUT_S,
    load_output_schema,
    run_case,
)
from agentdiff.eval.judge import Judger

if TYPE_CHECKING:
    from agentdiff.providers.base import Provider

_logger = structlog.get_logger(__name__)

DEFAULT_CONCURRENCY = 5
DEFAULT_RUN_TIMEOUT_S = 10 * 60.0


async def run_eval_set(
    *,
    agent: AgentDefinition,
    eval_set: str,
    cases: list[EvalCase],
    provider: Provider,
    git_sha: str,
    judger: Judger | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    case_timeout_s: float = DEFAULT_CASE_TIMEOUT_S,
    run_timeout_s: float = DEFAULT_RUN_TIMEOUT_S,
) -> EvalRun:
    """Execute all cases against `agent` via `provider`, return EvalRun.

    `eval_set` is the filename of the JSONL file (e.g. "golden.jsonl"),
    used purely as a label in the resulting `EvalRun`.

    `judger` grades cases that have no `expected` field. If omitted,
    those cases pass on schema validity alone (M1 behavior).
    """
    if concurrency < 1:
        raise ValueError(f"concurrency must be ≥ 1, got {concurrency}")

    output_schema = load_output_schema(agent)
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(c: EvalCase) -> CaseResult:
        async with sem:
            return await run_case(
                c,
                agent,
                provider,
                output_schema=output_schema,
                judger=judger,
                timeout_seconds=case_timeout_s,
            )

    _logger.info(
        "eval_run_start",
        agent=agent.name,
        eval_set=eval_set,
        n_cases=len(cases),
        concurrency=concurrency,
    )

    async with asyncio.timeout(run_timeout_s):
        case_results = await asyncio.gather(*(_bounded(c) for c in cases))

    total_cost = Decimal("0")
    latencies: list[int] = []
    for cr in case_results:
        if cr.invocation.usage is not None:
            total_cost += provider.estimate_cost(cr.invocation.usage)
        latencies.append(cr.invocation.latency_ms)

    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    n_passed = sum(1 for cr in case_results if cr.passed)

    _logger.info(
        "eval_run_complete",
        agent=agent.name,
        eval_set=eval_set,
        n_passed=n_passed,
        n_total=len(case_results),
        cost_usd=str(total_cost),
        p50_latency_ms=p50,
        p95_latency_ms=p95,
    )

    return EvalRun(
        agent_name=agent.name,
        eval_set=eval_set,
        git_sha=git_sha,
        cases=case_results,
        total_cost_usd=total_cost,
        judge_cost_usd=judger.total_cost_usd if judger else Decimal("0"),
        judge_fallback_used=judger.fallback_used if judger else False,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
    )


def _percentile(values: list[int], pct: float) -> int:
    """Linear-interpolated percentile, returns 0 for empty input."""
    if not values:
        return 0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * pct / 100
    lower = int(k)
    upper = min(lower + 1, len(sorted_vals) - 1)
    if lower == upper:
        return sorted_vals[lower]
    fraction = k - lower
    return int(sorted_vals[lower] + (sorted_vals[upper] - sorted_vals[lower]) * fraction)
