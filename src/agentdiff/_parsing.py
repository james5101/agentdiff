"""Lenient JSON-object extraction from LLM text.

Some models (e.g., Claude Sonnet 4.6+) reject assistant-message prefill.
For those, we rely on the prompt to ask for JSON output and then parse
defensively: strip markdown fences, skip preamble text, locate the
first `{`, and `raw_decode` from there. Trailing text after the
top-level object is ignored — that lets the model say "Hope this
helps!" without breaking the parse.
"""

from __future__ import annotations

import json
from typing import Any


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse the first top-level JSON object from a string.

    Returns:
        dict — the parsed object on success.
        None — the text contains no `{`, so there's no JSON to parse.

    Raises:
        json.JSONDecodeError — a `{` was found but the JSON is malformed.

    Handles:
        - Plain JSON: '{"x": 1}'
        - Leading whitespace / preamble: 'Sure! {"x": 1}'
        - Markdown fences: '```json\\n{"x": 1}\\n```'
        - Trailing text: '{"x": 1}\\nHope this helps!'
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        if first_nl != -1:
            cleaned = cleaned[first_nl + 1 :]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()

    start = cleaned.find("{")
    if start == -1:
        return None

    parsed, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    if not isinstance(parsed, dict):
        return None
    return parsed
