"""Read JSONL eval files into `EvalCase` lists.

Each line is one JSON object. If a line lacks an `id` field, we
generate a stable ID from a SHA-256 of the canonical-JSON of `input`.
That way the same case keeps the same ID across runs even if the
order of dict keys in the source file changes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agentdiff.definition import DefinitionError
from agentdiff.definition.schema import EvalCase


def load_eval_cases(jsonl_path: Path) -> list[EvalCase]:
    """Read a JSONL file into a list of `EvalCase`.

    Empty / whitespace-only lines are skipped (common when files are
    edited by hand). At least one valid case must remain or we raise.
    Case IDs must be unique within the file.
    """
    if not jsonl_path.is_file():
        raise DefinitionError(f"eval file not found: {jsonl_path}")

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()

    with jsonl_path.open(encoding="utf-8") as f:
        for line_num, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise DefinitionError(f"{jsonl_path}:{line_num}: invalid JSON: {e}") from e

            if not isinstance(obj, dict):
                raise DefinitionError(
                    f"{jsonl_path}:{line_num}: expected JSON object, got {type(obj).__name__}"
                )

            if "id" not in obj:
                input_payload = obj.get("input", {})
                if not isinstance(input_payload, dict):
                    raise DefinitionError(f"{jsonl_path}:{line_num}: `input` must be an object")
                obj["id"] = _stable_id(input_payload)

            try:
                case = EvalCase.model_validate(obj)
            except ValidationError as e:
                raise DefinitionError(
                    f"{jsonl_path}:{line_num}: case validation failed:\n{e}"
                ) from e

            if case.id in seen_ids:
                raise DefinitionError(f"{jsonl_path}:{line_num}: duplicate case id {case.id!r}")
            seen_ids.add(case.id)
            cases.append(case)

    if not cases:
        raise DefinitionError(f"{jsonl_path}: no eval cases found")

    return cases


def _stable_id(input_payload: dict[str, Any]) -> str:
    """Deterministic 12-char ID from canonical JSON of `input`."""
    canonical = json.dumps(input_payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"case-{digest[:12]}"
