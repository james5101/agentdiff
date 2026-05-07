"""Files written by `agentdiff init`.

Kept separate from `cli.py` so the templates are easy to read and
maintain — change the prompt or eval cases here without scrolling
past 200 lines of CLI plumbing.

The templates produce a runnable example: a sentiment classifier
with three golden cases. A fresh user can run `agentdiff run .`
immediately and see passing eval results, then edit to make it
their own agent.
"""

from __future__ import annotations

# Map of repo-relative path → file content. Order doesn't matter
# (we mkdir parents per file). The trailing newline on each file
# matters for clean diffs and POSIX text-file convention.

TEMPLATES: dict[str, str] = {
    "agentdiff.yaml": """\
# Minimal agentdiff config. Edit the agent name, prompt, schemas,
# and eval cases under agents/ to match your real agent.
# See https://github.com/james5101/agentdiff for full docs.
apiVersion: agentdiff/v1
agents:
  - name: example-classifier
    path: agents/example-classifier
    provider: claude
    model: claude-haiku-4-5-20251001
    prompt: prompt.md
    schemas:
      input: schemas/input.json
      output: schemas/output.json
    evals:
      - golden.jsonl
    thresholds:
      golden:
        minPassRate: 1.0
""",
    "agents/example-classifier/prompt.md": """\
You are a sentiment classifier.

Classify the user's message as exactly one of: `positive`, `neutral`,
`negative`.

Respond with ONLY a JSON object - no preamble, no markdown fences,
no trailing text - in this exact shape:

```json
{"sentiment": "<value>"}
```
""",
    "agents/example-classifier/schemas/input.json": """\
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "text": {"type": "string", "minLength": 1}
  },
  "required": ["text"]
}
""",
    "agents/example-classifier/schemas/output.json": """\
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "sentiment": {"enum": ["positive", "neutral", "negative"]}
  },
  "required": ["sentiment"]
}
""",
    "agents/example-classifier/golden.jsonl": """\
{"id": "pos-1", "input": {"text": "I love this product, it works great!"}, "expected": {"sentiment": "positive"}}
{"id": "neg-1", "input": {"text": "This is broken and I want a refund."}, "expected": {"sentiment": "negative"}}
{"id": "neu-1", "input": {"text": "The package arrived on Tuesday."}, "expected": {"sentiment": "neutral"}}
""",
}
