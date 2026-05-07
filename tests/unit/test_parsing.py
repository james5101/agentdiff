"""Tests for `_parsing.extract_json_object`."""

from __future__ import annotations

import json

import pytest

from agentdiff._parsing import extract_json_object


def test_plain_json_object() -> None:
    assert extract_json_object('{"x": 1}') == {"x": 1}


def test_leading_whitespace() -> None:
    assert extract_json_object('  \n  {"x": 1}') == {"x": 1}


def test_preamble_text_is_skipped() -> None:
    assert extract_json_object('Sure, here is the JSON: {"x": 1}') == {"x": 1}


def test_trailing_text_is_ignored() -> None:
    assert extract_json_object('{"x": 1}\nHope this helps!') == {"x": 1}


def test_markdown_fence_is_stripped() -> None:
    assert extract_json_object('```json\n{"x": 1}\n```') == {"x": 1}


def test_markdown_fence_without_lang_tag() -> None:
    assert extract_json_object('```\n{"x": 1}\n```') == {"x": 1}


def test_returns_none_when_no_brace() -> None:
    assert extract_json_object("just plain text") is None


def test_returns_none_when_top_level_is_array() -> None:
    """raw_decode picks up the first JSON value; if that's not a dict we
    return None rather than guessing the user meant something else."""
    # `[1,2,3]` doesn't have `{`, so we never even try to decode.
    assert extract_json_object("[1, 2, 3]") is None


def test_raises_on_malformed_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json_object('{"x":')


def test_raises_on_garbage_after_brace() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json_object("{not valid")
