"""Shared Pydantic models. The spine of agentdiff.

Per HANDOFF.md sec 4, every other package may import from this module,
but the non-orchestrator packages (`providers`, `definition`, `eval`,
`diff`, `github`) must not import from each other.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Reused config: reject unknown fields, freeze instances after validation.
_STRICT_CONFIG = ConfigDict(extra="forbid", frozen=True)


class EvalThresholds(BaseModel):
    """Pass / regression thresholds for one eval set.

    `min_pass_rate` is the fraction of cases that MUST pass (typical for
    golden sets, where 1.0 = "no failures allowed").

    `max_regression_pct` is the fraction of cases that may regress
    head-vs-base (typical for adversarial sets, where 0.05 = "≤5% regression").

    At least one of the two must be set; an empty thresholds block is a
    silent no-op and almost always a YAML mistake.
    """

    model_config = _STRICT_CONFIG

    min_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    max_regression_pct: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _at_least_one(self) -> EvalThresholds:
        if self.min_pass_rate is None and self.max_regression_pct is None:
            raise ValueError(
                "EvalThresholds must specify at least one of min_pass_rate or max_regression_pct"
            )
        return self


class AgentDefinition(BaseModel):
    """A single agent's identity, location, and eval policy.

    Path fields are absolute paths on disk after loading; the loader is
    responsible for resolving the relative paths in `agentdiff.yaml`.
    """

    model_config = _STRICT_CONFIG

    name: str = Field(min_length=1)
    path: Path
    provider: Literal["claude", "openai"]
    model: str = Field(min_length=1)
    prompt_path: Path
    input_schema_path: Path
    output_schema_path: Path
    eval_files: list[Path] = Field(min_length=1)
    thresholds: dict[str, EvalThresholds]


class EvalCase(BaseModel):
    """A single eval input, optionally with a ground-truth output.

    When `expected` is None the case is judged (Milestone 2); when
    present, the case passes iff the agent output exactly matches it
    (after JSON normalization).
    """

    model_config = _STRICT_CONFIG

    id: str = Field(min_length=1)
    input: dict[str, Any]
    expected: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    model_config = _STRICT_CONFIG

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class InvocationResult(BaseModel):
    """Outcome of a single `Provider.invoke` call.

    Exactly one of `output` or `error` is set. `usage` and `latency_ms`
    are populated regardless (latency from the Provider, usage may be
    None if the call failed before token counting).
    """

    model_config = _STRICT_CONFIG

    output: dict[str, Any] | None
    usage: TokenUsage | None
    latency_ms: int = Field(ge=0)
    error: str | None = None

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> InvocationResult:
        has_output = self.output is not None
        has_error = self.error is not None
        if has_output == has_error:
            raise ValueError("InvocationResult must set exactly one of `output` or `error`")
        return self


class CaseResult(BaseModel):
    """Pass/fail outcome of one eval case against one agent version.

    `judge_reasoning` is set whenever the case was judged (regardless
    of pass/fail) so the verbose CLI renderer can show why a case got
    its score. `failure_reason` is set only on fail; for judged-fail
    cases it duplicates the reasoning, but for non-judge failures
    (timeout, schema violation, exact-match miss) it carries
    different content.
    """

    model_config = _STRICT_CONFIG

    case_id: str = Field(min_length=1)
    invocation: InvocationResult
    passed: bool
    failure_reason: str | None = None
    judge_score: float | None = Field(default=None, ge=0.0, le=1.0)
    judge_reasoning: str | None = None


class EvalRun(BaseModel):
    """One eval set executed against one agent version (one git sha).

    `total_cost_usd` is agent invocation cost only; judge model cost is
    reported separately so reviewers can see how much of an eval bill
    is grading vs. running the agent itself (HANDOFF.md sec 3.9).
    """

    model_config = _STRICT_CONFIG

    agent_name: str = Field(min_length=1)
    eval_set: str = Field(min_length=1)
    git_sha: str = Field(min_length=7)
    cases: list[CaseResult]
    total_cost_usd: Decimal
    judge_cost_usd: Decimal = Decimal("0")
    p50_latency_ms: int = Field(ge=0)
    p95_latency_ms: int = Field(ge=0)
    judge_fallback_used: bool = False


class SchemaDriftEntry(BaseModel):
    """One case where output JSON shape changed between base and head."""

    model_config = _STRICT_CONFIG

    case_id: str = Field(min_length=1)
    added_fields: list[str] = Field(default_factory=list)
    removed_fields: list[str] = Field(default_factory=list)
    type_changes: dict[str, tuple[str, str]] = Field(default_factory=dict)


class ThresholdViolation(BaseModel):
    """A configured threshold that the head run failed to meet."""

    model_config = _STRICT_CONFIG

    eval_set: str = Field(min_length=1)
    rule: Literal["min_pass_rate", "max_regression_pct"]
    expected: float
    actual: float


class BehavioralDiff(BaseModel):
    """The end product: base vs. head behavioral comparison for one agent."""

    model_config = _STRICT_CONFIG

    agent_name: str = Field(min_length=1)
    base_run: EvalRun
    head_run: EvalRun
    regressions: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    schema_drift: list[SchemaDriftEntry] = Field(default_factory=list)
    cost_delta_usd: Decimal
    cost_delta_pct: float
    pass_rate_delta_pct: float
    threshold_violations: list[ThresholdViolation] = Field(default_factory=list)
