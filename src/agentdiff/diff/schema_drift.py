"""Detect output JSON shape changes between two `EvalRun`s.

v1 does **top-level** shape diffing only: added fields, removed fields,
and type changes on shared fields. Nested-object recursion is left for
later — a real user with deep schemas will tell us if it matters.
"""

from __future__ import annotations

from typing import Any

from agentdiff.definition.schema import EvalRun, SchemaDriftEntry


def detect_schema_drift(base: EvalRun, head: EvalRun) -> list[SchemaDriftEntry]:
    """Compare each case's output shape between base and head.

    Cases that don't appear in both runs are skipped; cases where
    either side errored (output is None) are skipped — there's no
    shape to compare. Returns one entry per case with detected drift.
    """
    base_by_id = {c.case_id: c for c in base.cases}
    head_by_id = {c.case_id: c for c in head.cases}

    drift: list[SchemaDriftEntry] = []
    for case_id in sorted(set(base_by_id) & set(head_by_id)):
        base_output = base_by_id[case_id].invocation.output
        head_output = head_by_id[case_id].invocation.output
        if base_output is None or head_output is None:
            continue

        entry = _compare_shapes(case_id, base_output, head_output)
        if entry is not None:
            drift.append(entry)

    return drift


def _compare_shapes(
    case_id: str,
    base_output: dict[str, Any],
    head_output: dict[str, Any],
) -> SchemaDriftEntry | None:
    base_shape = {k: type(v).__name__ for k, v in base_output.items()}
    head_shape = {k: type(v).__name__ for k, v in head_output.items()}

    added = sorted(set(head_shape) - set(base_shape))
    removed = sorted(set(base_shape) - set(head_shape))
    type_changes = {
        k: (base_shape[k], head_shape[k])
        for k in sorted(set(base_shape) & set(head_shape))
        if base_shape[k] != head_shape[k]
    }

    if not (added or removed or type_changes):
        return None

    return SchemaDriftEntry(
        case_id=case_id,
        added_fields=added,
        removed_fields=removed,
        type_changes=type_changes,
    )
