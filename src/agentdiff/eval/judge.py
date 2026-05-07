"""LLM-as-judge for cases that have no `expected` ground truth.

When a case omits `expected`, the agent's output is graded by Claude
Sonnet against a per-eval-set rubric (HANDOFF.md sec 3.9). The rubric
is a markdown file sitting next to the JSONL: `golden.jsonl` →
`golden.judge.md`. If no rubric file exists, a generic fallback is
used and a flag is raised on the resulting `EvalRun` so downstream
renderers can surface a warning.

The judge model is hardcoded to Claude Sonnet regardless of which
provider the agent itself uses; this is a deliberate choice in §3.9
and not configurable in v1.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import anthropic
import structlog
from pydantic import BaseModel, ConfigDict, Field

from agentdiff._parsing import extract_json_object
from agentdiff.definition.schema import TokenUsage

_logger = structlog.get_logger(__name__)

# Hardcoded per HANDOFF.md sec 3.9.
JUDGE_MODEL = "claude-sonnet-4-6"

# Sonnet pricing per million tokens. Update when rates change.
_INPUT_PRICE_PER_MTOK = Decimal("3")
_OUTPUT_PRICE_PER_MTOK = Decimal("15")
_MILLION = Decimal("1000000")
_MAX_TOKENS = 1024
PASS_THRESHOLD = 0.7

_JUDGE_SYSTEM_PROMPT = """You are an expert evaluator of LLM agent outputs.

You will be given:
- A rubric describing what a good output looks like.
- The case input the agent received.
- The agent's output.

Score the output on a 0.0 to 1.0 scale, where:
- 1.0 = matches the rubric perfectly
- 0.7 = acceptable: meets all critical rubric criteria, may have minor issues
- 0.5 = mixed: meets some criteria but fails others
- 0.0 = bad: violates the rubric or fails to address the input

Respond with ONLY a JSON object of this exact shape - no preamble,
no markdown fences, no trailing commentary:

  {"score": <float 0.0-1.0>, "reasoning": "<one short sentence>"}

Be strict. Half-credit is for outputs that genuinely deserve it."""

_FALLBACK_RUBRIC = """The output should be a reasonable response to the input.
Score high if the output is on-topic, correctly structured, and addresses
the input meaningfully. Score low if the output is off-topic, malformed,
or fails to address what was asked."""


class JudgeResult(BaseModel):
    """One judge call's outcome.

    `passed` is True iff the score met the threshold AND no error
    occurred during the judge call itself.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    reasoning: str
    cost_usd: Decimal
    usage: TokenUsage
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and self.score >= PASS_THRESHOLD


def find_rubric(eval_file: Path) -> tuple[str, bool]:
    """Locate the judge rubric for an eval set.

    Convention: `<eval-file>.judge.md` next to the JSONL. So
    `agents/foo/golden.jsonl` looks for `agents/foo/golden.judge.md`.

    Returns `(rubric_text, fallback_used)`. `fallback_used=True` means
    no rubric file was found and the generic prompt is being used.
    """
    rubric_path = eval_file.with_suffix(".judge.md")
    if rubric_path.is_file():
        return rubric_path.read_text(encoding="utf-8"), False
    return _FALLBACK_RUBRIC, True


class Judger:
    """Holds the judge client + rubric and accumulates total cost.

    Built once per eval set and reused across cases. Cost accumulation
    is safe because all cases run inside one asyncio event loop —
    no thread crossing.
    """

    def __init__(
        self,
        *,
        client: anthropic.AsyncAnthropic,
        rubric: str,
        fallback_used: bool = False,
    ) -> None:
        self._client = client
        self._rubric = rubric
        self.fallback_used = fallback_used
        self.total_cost_usd = Decimal("0")
        self.call_count = 0

    async def judge(
        self,
        *,
        case_input: dict[str, Any],
        agent_output: dict[str, Any],
    ) -> JudgeResult:
        result = await _invoke_judge(
            client=self._client,
            rubric=self._rubric,
            case_input=case_input,
            agent_output=agent_output,
        )
        self.total_cost_usd += result.cost_usd
        self.call_count += 1
        return result


async def _invoke_judge(
    *,
    client: anthropic.AsyncAnthropic,
    rubric: str,
    case_input: dict[str, Any],
    agent_output: dict[str, Any],
) -> JudgeResult:
    """One judge API call. Caller is responsible for cost aggregation."""
    user_content = (
        "RUBRIC:\n"
        f"{rubric}\n\n"
        "CASE INPUT:\n"
        f"{json.dumps(case_input, indent=2, ensure_ascii=False)}\n\n"
        "AGENT OUTPUT:\n"
        f"{json.dumps(agent_output, indent=2, ensure_ascii=False)}"
    )

    try:
        resp = await client.messages.create(
            model=JUDGE_MODEL,
            system=_JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            max_tokens=_MAX_TOKENS,
        )
    except anthropic.APIError as e:
        _logger.warning("judge_api_error", error=str(e))
        return JudgeResult(
            score=0.0,
            reasoning="judge API error",
            cost_usd=Decimal("0"),
            usage=TokenUsage(input_tokens=0, output_tokens=0),
            error=f"judge unavailable: {e}",
        )

    usage = TokenUsage(
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
    cost = (
        Decimal(usage.input_tokens) * _INPUT_PRICE_PER_MTOK / _MILLION
        + Decimal(usage.output_tokens) * _OUTPUT_PRICE_PER_MTOK / _MILLION
    )

    text = "".join(b.text for b in resp.content if b.type == "text")

    try:
        parsed = extract_json_object(text)
    except json.JSONDecodeError as e:
        return JudgeResult(
            score=0.0,
            reasoning="judge returned invalid JSON",
            cost_usd=cost,
            usage=usage,
            error=f"judge JSON parse failed: {e}; raw={text[:200]!r}",
        )

    if parsed is None:
        return JudgeResult(
            score=0.0,
            reasoning="judge response had no JSON object",
            cost_usd=cost,
            usage=usage,
            error=f"no JSON object in judge response; raw={text[:200]!r}",
        )

    raw_score = parsed.get("score")
    raw_reasoning = parsed.get("reasoning", "")

    try:
        score = float(raw_score) if raw_score is not None else 0.0
    except (TypeError, ValueError):
        return JudgeResult(
            score=0.0,
            reasoning="judge returned non-numeric score",
            cost_usd=cost,
            usage=usage,
            error=f"judge score not a number: got {raw_score!r}",
        )

    if not 0.0 <= score <= 1.0:
        return JudgeResult(
            score=0.0,
            reasoning="judge score out of range",
            cost_usd=cost,
            usage=usage,
            error=f"judge score {score} out of [0, 1]",
        )

    reasoning = str(raw_reasoning) if raw_reasoning else "(no reasoning given)"

    return JudgeResult(
        score=score,
        reasoning=reasoning,
        cost_usd=cost,
        usage=usage,
    )
