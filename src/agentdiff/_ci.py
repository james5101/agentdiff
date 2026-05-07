"""Detect PR base/head SHAs from CI environment variables.

Currently supports GitHub Actions. Other CIs (GitLab CI, Bitbucket
Pipelines, Jenkins) can be added as users ask. The contract is
small: take the OS environment, return `(base_sha, head_sha)` or
None if no recognized PR context is found.

We prefer GitHub Actions' event JSON (`GITHUB_EVENT_PATH`) over
branch-name env vars because it carries the actual SHAs the
runner saw, independent of how the workspace was checked out.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


def autodetect_refs(env: Mapping[str, str]) -> tuple[str, str] | None:
    """Return `(base_sha, head_sha)` from CI env, or None.

    Pure function over the env mapping for testability — production
    callers pass `os.environ`, tests pass a dict.
    """
    detected = _from_github_actions(env)
    if detected is not None:
        return detected
    return None


def _from_github_actions(env: Mapping[str, str]) -> tuple[str, str] | None:
    """GitHub Actions on a `pull_request` event.

    The action runner writes the full webhook payload to a temp file
    pointed at by `GITHUB_EVENT_PATH`. For PR events the payload
    contains `pull_request.base.sha` and `pull_request.head.sha` —
    the canonical refs we want to diff.
    """
    event_path = env.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None

    path = Path(event_path)
    if not path.is_file():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    pr = payload.get("pull_request")
    if not isinstance(pr, dict):
        return None

    base = pr.get("base", {}).get("sha") if isinstance(pr.get("base"), dict) else None
    head = pr.get("head", {}).get("sha") if isinstance(pr.get("head"), dict) else None

    if not isinstance(base, str) or not isinstance(head, str):
        return None
    if not base or not head:
        return None

    return base, head
