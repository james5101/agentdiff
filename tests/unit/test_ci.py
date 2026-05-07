"""Tests for `_ci.autodetect_refs`."""

from __future__ import annotations

import json
from pathlib import Path

from agentdiff._ci import autodetect_refs


def _write_event(tmp_path: Path, payload: dict[str, object]) -> Path:
    f = tmp_path / "event.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


def test_no_env_returns_none() -> None:
    assert autodetect_refs({}) is None


def test_github_actions_pull_request_resolves_to_shas(tmp_path: Path) -> None:
    event_path = _write_event(
        tmp_path,
        {
            "pull_request": {
                "base": {"sha": "aaaaaaa1111"},
                "head": {"sha": "bbbbbbb2222"},
            }
        },
    )
    refs = autodetect_refs({"GITHUB_EVENT_PATH": str(event_path)})
    assert refs == ("aaaaaaa1111", "bbbbbbb2222")


def test_github_actions_missing_event_file_returns_none(tmp_path: Path) -> None:
    """GITHUB_EVENT_PATH set but file doesn't exist → None, not a crash."""
    refs = autodetect_refs({"GITHUB_EVENT_PATH": str(tmp_path / "nope.json")})
    assert refs is None


def test_github_actions_malformed_json_returns_none(tmp_path: Path) -> None:
    f = tmp_path / "event.json"
    f.write_text("{not json", encoding="utf-8")
    refs = autodetect_refs({"GITHUB_EVENT_PATH": str(f)})
    assert refs is None


def test_github_actions_non_pr_event_returns_none(tmp_path: Path) -> None:
    """`push` events have no `pull_request` key — skip cleanly."""
    event_path = _write_event(tmp_path, {"ref": "refs/heads/main", "after": "abcdef0"})
    refs = autodetect_refs({"GITHUB_EVENT_PATH": str(event_path)})
    assert refs is None


def test_github_actions_pr_with_missing_sha_returns_none(tmp_path: Path) -> None:
    event_path = _write_event(tmp_path, {"pull_request": {"base": {}, "head": {}}})
    refs = autodetect_refs({"GITHUB_EVENT_PATH": str(event_path)})
    assert refs is None


def test_github_actions_payload_not_object_returns_none(tmp_path: Path) -> None:
    event_path = _write_event(tmp_path, ["this is a list, not an object"])  # type: ignore[arg-type]
    refs = autodetect_refs({"GITHUB_EVENT_PATH": str(event_path)})
    assert refs is None
