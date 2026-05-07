"""Tests for `definition.loader`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentdiff.definition import DefinitionError
from agentdiff.definition.loader import load_agents

FIXTURE_REPO = Path(__file__).parent.parent / "fixtures" / "sample-repo"


def test_load_agents_from_sample_repo() -> None:
    agents = load_agents(FIXTURE_REPO)
    assert len(agents) == 1
    a = agents[0]
    assert a.name == "intent-classifier"
    assert a.provider == "claude"
    assert a.model == "claude-haiku-4-5-20251001"
    assert a.path == (FIXTURE_REPO / "agents/intent-classifier").resolve()
    assert a.prompt_path.name == "prompt.md"
    assert a.input_schema_path.name == "input.json"
    assert a.output_schema_path.name == "output.json"
    assert len(a.eval_files) == 1
    assert a.eval_files[0].name == "golden.jsonl"
    assert a.thresholds["golden"].min_pass_rate == 1.0


def test_load_agents_resolves_paths_to_absolute(tmp_path: Path) -> None:
    """Paths in the YAML are relative; the model holds absolute paths."""
    agents = load_agents(FIXTURE_REPO)
    a = agents[0]
    assert a.prompt_path.is_absolute()
    assert a.input_schema_path.is_absolute()
    assert a.eval_files[0].is_absolute()


def test_load_agents_missing_yaml(tmp_path: Path) -> None:
    with pytest.raises(DefinitionError, match="not found"):
        load_agents(tmp_path)


def test_load_agents_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "agentdiff.yaml").write_text(": :\nbroken: [", encoding="utf-8")
    with pytest.raises(DefinitionError, match="not valid YAML"):
        load_agents(tmp_path)


def test_load_agents_top_level_not_mapping(tmp_path: Path) -> None:
    (tmp_path / "agentdiff.yaml").write_text("- just a list\n", encoding="utf-8")
    with pytest.raises(DefinitionError, match="must be a mapping"):
        load_agents(tmp_path)


def test_load_agents_unsupported_api_version(tmp_path: Path) -> None:
    (tmp_path / "agentdiff.yaml").write_text(
        "apiVersion: agentdiff/v999\nagents: []\n", encoding="utf-8"
    )
    with pytest.raises(DefinitionError, match="unsupported apiVersion"):
        load_agents(tmp_path)


def test_load_agents_unknown_field_rejected(tmp_path: Path) -> None:
    (tmp_path / "agentdiff.yaml").write_text(
        "apiVersion: agentdiff/v1\nagents: []\nmysteryKey: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(DefinitionError, match="validation failed"):
        load_agents(tmp_path)


def test_load_agents_duplicate_names(tmp_path: Path) -> None:
    yaml_text = """\
apiVersion: agentdiff/v1
agents:
  - name: dup
    path: a/
    provider: claude
    model: claude-haiku-4-5-20251001
    prompt: p.md
    schemas: {input: i.json, output: o.json}
    evals: [g.jsonl]
    thresholds:
      g: {minPassRate: 1.0}
  - name: dup
    path: b/
    provider: claude
    model: claude-haiku-4-5-20251001
    prompt: p.md
    schemas: {input: i.json, output: o.json}
    evals: [g.jsonl]
    thresholds:
      g: {minPassRate: 1.0}
"""
    (tmp_path / "agentdiff.yaml").write_text(yaml_text, encoding="utf-8")
    with pytest.raises(DefinitionError, match="duplicate agent name"):
        load_agents(tmp_path)


def test_load_agents_threshold_block_empty_rejected(tmp_path: Path) -> None:
    yaml_text = """\
apiVersion: agentdiff/v1
agents:
  - name: a
    path: a/
    provider: claude
    model: claude-haiku-4-5-20251001
    prompt: p.md
    schemas: {input: i.json, output: o.json}
    evals: [g.jsonl]
    thresholds:
      g: {}
"""
    (tmp_path / "agentdiff.yaml").write_text(yaml_text, encoding="utf-8")
    with pytest.raises(DefinitionError, match="thresholds invalid"):
        load_agents(tmp_path)
