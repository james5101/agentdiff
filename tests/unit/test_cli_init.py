"""Tests for `agentdiff init`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentdiff._init_template import TEMPLATES
from agentdiff.cli import app

runner = CliRunner()


def test_init_creates_all_template_files(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0

    for rel in TEMPLATES:
        target = tmp_path / rel
        assert target.is_file(), f"missing scaffolded file: {rel}"


def test_init_scaffolded_yaml_loads_cleanly(tmp_path: Path) -> None:
    """The scaffolded agentdiff.yaml must parse without DefinitionError."""
    runner.invoke(app, ["init", str(tmp_path)])

    from agentdiff.definition.loader import load_agents

    agents = load_agents(tmp_path)
    assert len(agents) == 1
    assert agents[0].name == "example-classifier"


def test_init_scaffolded_eval_file_loads_cleanly(tmp_path: Path) -> None:
    """The scaffolded golden.jsonl must parse without DefinitionError."""
    runner.invoke(app, ["init", str(tmp_path)])

    from agentdiff.definition.evals import load_eval_cases

    cases = load_eval_cases(tmp_path / "agents/example-classifier/golden.jsonl")
    assert len(cases) == 3
    assert {c.id for c in cases} == {"pos-1", "neg-1", "neu-1"}


def test_init_refuses_to_overwrite_existing(tmp_path: Path) -> None:
    """Default behavior: refuse if agentdiff.yaml already exists."""
    (tmp_path / "agentdiff.yaml").write_text("existing\n", encoding="utf-8")

    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code != 0
    assert "refusing to overwrite" in result.output
    # Original content untouched.
    assert (tmp_path / "agentdiff.yaml").read_text(encoding="utf-8") == "existing\n"


def test_init_force_overwrites(tmp_path: Path) -> None:
    (tmp_path / "agentdiff.yaml").write_text("existing\n", encoding="utf-8")

    result = runner.invoke(app, ["init", str(tmp_path), "--force"])
    assert result.exit_code == 0
    # Content replaced with the template.
    assert "apiVersion: agentdiff/v1" in (tmp_path / "agentdiff.yaml").read_text(encoding="utf-8")
