"""Smoke tests for the CLI wiring — no real API calls."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agentdiff.cli import app

runner = CliRunner()


def test_help_lists_run_local() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run-local" in result.output


def test_run_local_help_shows_args() -> None:
    result = runner.invoke(app, ["run-local", "--help"])
    assert result.exit_code == 0
    assert "REPO_PATH" in result.output
    assert "concurrency" in result.output.lower()


def test_run_local_without_api_key_errors(monkeypatch: object, tmp_path: Path) -> None:
    """No ANTHROPIC_API_KEY → BadParameter (exit code != 0)."""
    # Build a minimal repo with one agent so the CLI gets past loading.
    (tmp_path / "agentdiff.yaml").write_text(
        """\
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
      g: {minPassRate: 1.0}
""",
        encoding="utf-8",
    )
    agent_dir = tmp_path / "a"
    agent_dir.mkdir()
    (agent_dir / "p.md").write_text("Classify.", encoding="utf-8")
    (agent_dir / "i.json").write_text('{"type": "object"}', encoding="utf-8")
    (agent_dir / "o.json").write_text('{"type": "object"}', encoding="utf-8")
    (agent_dir / "g.jsonl").write_text('{"id": "c1", "input": {"x": 1}}\n', encoding="utf-8")

    # Use Typer's `env` to clear any inherited key.
    result = runner.invoke(
        app,
        ["run-local", str(tmp_path)],
        env={"ANTHROPIC_API_KEY": ""},
    )
    assert result.exit_code != 0
    assert "ANTHROPIC_API_KEY" in result.output
