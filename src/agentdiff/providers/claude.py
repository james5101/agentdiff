"""ClaudeProvider — calls Anthropic Messages API, returns InvocationResult.

The agent's prompt becomes the system message; the case input dict is
JSON-stringified into a single user message. The response is expected
to be one JSON object — anything else (text-only, malformed JSON, JSON
array) is reported via `InvocationResult.error`.

A provider instance is bound to a single model at construction; cost
estimation reads from a hardcoded USD-per-million-token table. An
unknown model raises rather than silently under-counting cost.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Any

import anthropic
import structlog
from anthropic.types import Message

from agentdiff.definition.schema import AgentDefinition, InvocationResult, TokenUsage

_logger = structlog.get_logger(__name__)

# (input_per_mtok_usd, output_per_mtok_usd). Update when rates change.
_PRICE_TABLE: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-4-7": (Decimal("15"), Decimal("75")),
    "claude-sonnet-4-6": (Decimal("3"), Decimal("15")),
    "claude-haiku-4-5-20251001": (Decimal("1"), Decimal("5")),
}

_MILLION = Decimal("1000000")
_MAX_TOKENS = 4096

# Anthropic prefill: by sending an assistant turn that ends mid-token,
# the model is forced to continue from there. Prefilling "{" makes
# the next character a JSON value, eliminating the "Sure, here's
# your JSON:" preambles and markdown fences that otherwise wreck
# json.loads(). The "{" is reattached client-side before parsing.
_JSON_PREFILL = "{"


class UnknownModelError(ValueError):
    """The configured model isn't in `_PRICE_TABLE`."""


class ClaudeProvider:
    """Provider implementation for Anthropic's Messages API."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        """Bind to a model and (optionally) an injected SDK client.

        `client` is an injection seam for tests; production callers pass
        only `model` and `api_key`.
        """
        self._model = model
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def model(self) -> str:
        return self._model

    async def invoke(
        self,
        agent: AgentDefinition,
        input_: dict[str, Any],
    ) -> InvocationResult:
        system_prompt = agent.prompt_path.read_text(encoding="utf-8")
        user_content = json.dumps(input_, ensure_ascii=False)

        start = time.monotonic()
        try:
            resp = await self._client.messages.create(
                model=self._model,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": _JSON_PREFILL},
                ],
                max_tokens=_MAX_TOKENS,
            )
        except anthropic.APIError as e:
            elapsed_ms = _elapsed_ms(start)
            _logger.warning(
                "anthropic_api_error",
                agent=agent.name,
                model=self._model,
                error=str(e),
                latency_ms=elapsed_ms,
            )
            return InvocationResult(
                output=None,
                usage=None,
                latency_ms=elapsed_ms,
                error=f"anthropic API error: {e}",
            )

        latency_ms = _elapsed_ms(start)
        usage = TokenUsage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

        text = _extract_text(resp)
        # Even an empty response is a JSON-parse failure once we add
        # the prefill, but we still want to flag the underlying "no
        # content" case explicitly for diagnostics.
        if text is None:
            return InvocationResult(
                output=None,
                usage=usage,
                latency_ms=latency_ms,
                error="response contained no text content",
            )

        full_text = _JSON_PREFILL + text

        try:
            parsed: object = json.loads(full_text)
        except json.JSONDecodeError as e:
            return InvocationResult(
                output=None,
                usage=usage,
                latency_ms=latency_ms,
                error=(
                    f"agent output is not valid JSON: {e}; "
                    f"raw={full_text[:200]!r}"
                ),
            )

        # The prefill `{` guarantees that any successful parse is a
        # JSON object; an array or scalar would have raised above.
        assert isinstance(parsed, dict)

        return InvocationResult(
            output=parsed,
            usage=usage,
            latency_ms=latency_ms,
        )

    def estimate_cost(self, usage: TokenUsage) -> Decimal:
        if self._model not in _PRICE_TABLE:
            raise UnknownModelError(
                f"no pricing for model {self._model!r}; add it to providers.claude._PRICE_TABLE"
            )
        in_price, out_price = _PRICE_TABLE[self._model]
        return (Decimal(usage.input_tokens) * in_price / _MILLION) + (
            Decimal(usage.output_tokens) * out_price / _MILLION
        )


def _extract_text(resp: Message) -> str | None:
    parts: list[str] = [block.text for block in resp.content if block.type == "text"]
    return "".join(parts) if parts else None


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
