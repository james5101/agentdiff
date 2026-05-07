"""Tests for `definition.evals`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentdiff.definition import DefinitionError
from agentdiff.definition.evals import load_eval_cases

FIXTURE_GOLDEN = (
    Path(__file__).parent.parent
    / "fixtures"
    / "sample-repo"
    / "agents"
    / "intent-classifier"
    / "golden.jsonl"
)


def test_load_eval_cases_from_fixture() -> None:
    cases = load_eval_cases(FIXTURE_GOLDEN)
    assert len(cases) == 3
    ids = {c.id for c in cases}
    assert ids == {"greet-1", "question-1", "complaint-1"}
    greet = next(c for c in cases if c.id == "greet-1")
    assert greet.input == {"text": "Hello there!"}
    assert greet.expected == {"intent": "greeting"}


def test_load_eval_cases_skips_blank_lines(tmp_path: Path) -> None:
    f = tmp_path / "evals.jsonl"
    f.write_text(
        '\n{"id": "a", "input": {"x": 1}}\n\n   \n{"id": "b", "input": {"y": 2}}\n',
        encoding="utf-8",
    )
    cases = load_eval_cases(f)
    assert [c.id for c in cases] == ["a", "b"]


def test_load_eval_cases_generates_stable_id(tmp_path: Path) -> None:
    """Cases without `id` get a deterministic hash-based ID."""
    f = tmp_path / "evals.jsonl"
    f.write_text(
        '{"input": {"a": 1, "b": 2}}\n{"input": {"b": 2, "a": 1}}\n',
        encoding="utf-8",
    )
    with pytest.raises(DefinitionError, match="duplicate case id"):
        load_eval_cases(f)


def test_load_eval_cases_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DefinitionError, match="not found"):
        load_eval_cases(tmp_path / "missing.jsonl")


def test_load_eval_cases_rejects_invalid_json(tmp_path: Path) -> None:
    f = tmp_path / "evals.jsonl"
    f.write_text('{"id": "good", "input": {}}\n{not json}\n', encoding="utf-8")
    with pytest.raises(DefinitionError, match=r"evals\.jsonl:2"):
        load_eval_cases(f)


def test_load_eval_cases_rejects_non_object_line(tmp_path: Path) -> None:
    f = tmp_path / "evals.jsonl"
    f.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(DefinitionError, match="expected JSON object"):
        load_eval_cases(f)


def test_load_eval_cases_rejects_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "evals.jsonl"
    f.write_text("", encoding="utf-8")
    with pytest.raises(DefinitionError, match="no eval cases"):
        load_eval_cases(f)


def test_load_eval_cases_rejects_duplicate_ids(tmp_path: Path) -> None:
    f = tmp_path / "evals.jsonl"
    f.write_text(
        '{"id": "x", "input": {}}\n{"id": "x", "input": {"a": 1}}\n',
        encoding="utf-8",
    )
    with pytest.raises(DefinitionError, match="duplicate case id"):
        load_eval_cases(f)
