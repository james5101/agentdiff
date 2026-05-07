"""Loading and parsing user-facing agent definitions."""

from __future__ import annotations


class DefinitionError(Exception):
    """Raised when an `agentdiff.yaml` or eval file is malformed.

    This wraps lower-level YAML, JSON, and Pydantic errors with file/line
    context so the user sees a useful message instead of a stack trace.
    """


__all__ = ["DefinitionError"]
