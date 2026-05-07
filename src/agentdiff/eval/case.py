"""Run a single eval case against an agent and grade the result.

Pass criteria (HANDOFF.md sec 3.8):
- If the case has `expected`: deep-equality of agent output with expected.
- If the case has no `expected`: agent output validates against the
  agent's output JSON Schema.

Milestone 1 stops there; the judge model branch arrives in Milestone 2.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jsonschema
import structlog

from agentdiff.definition.schema import (
    AgentDefinition,
    CaseResult,
    EvalCase,
    InvocationResult,
)

if TYPE_CHECKING:
    from agentdiff.providers.base import Provider

_logger = structlog.get_logger(__name__)

DEFAULT_CASE_TIMEOUT_S = 60.0


def load_output_schema(agent: AgentDefinition) -> dict[str, Any]:
    """Read and parse the agent's output JSON Schema once per run."""
    return _load_json_object(agent.output_schema_path)


def _load_json_object(path: Path) -> dict[str, Any]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path}: expected a JSON object at the top level, got {type(raw).__name__}"
        )
    return raw


async def run_case(
    case: EvalCase,
    agent: AgentDefinition,
    provider: Provider,
    *,
    output_schema: dict[str, Any],
    timeout_seconds: float = DEFAULT_CASE_TIMEOUT_S,
) -> CaseResult:
    """Invoke the agent with `case.input` and grade the result.

    The per-case timeout wraps only the provider invocation; grading is
    pure-Python and never blocks.
    """
    try:
        result = await asyncio.wait_for(
            provider.invoke(agent, case.input),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        _logger.warning(
            "case_timeout",
            agent=agent.name,
            case=case.id,
            timeout_s=timeout_seconds,
        )
        return CaseResult(
            case_id=case.id,
            invocation=InvocationResult(
                output=None,
                usage=None,
                latency_ms=int(timeout_seconds * 1000),
                error=f"timed out after {timeout_seconds:.0f}s",
            ),
            passed=False,
            failure_reason="timeout",
        )

    if result.error is not None:
        return CaseResult(
            case_id=case.id,
            invocation=result,
            passed=False,
            failure_reason=result.error,
        )

    # `result.error is None` implies `result.output is not None`
    # (enforced by InvocationResult's validator), but mypy doesn't know
    # that, so assert for clarity and type narrowing.
    assert result.output is not None

    if case.expected is not None:
        if result.output == case.expected:
            return CaseResult(case_id=case.id, invocation=result, passed=True)
        return CaseResult(
            case_id=case.id,
            invocation=result,
            passed=False,
            failure_reason=(f"output mismatch: got {result.output!r}, expected {case.expected!r}"),
        )

    schema_error = _validate(result.output, output_schema)
    if schema_error is not None:
        return CaseResult(
            case_id=case.id,
            invocation=result,
            passed=False,
            failure_reason=f"schema violation: {schema_error}",
        )

    # Milestone 1: schema-valid is pass. Judge model arrives in M2.
    return CaseResult(case_id=case.id, invocation=result, passed=True)


def _validate(output: dict[str, Any], schema: dict[str, Any]) -> str | None:
    """Return None on success, an error message on failure."""
    try:
        jsonschema.validate(instance=output, schema=schema)
    except jsonschema.ValidationError as e:
        return str(e.message)
    except jsonschema.SchemaError as e:
        return f"output schema is invalid: {e.message}"
    return None
