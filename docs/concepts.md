# Concepts: what agentdiff actually diffs

> If you read one doc, read this one. The 60-second pitch in the README
> tells you *what* agentdiff is; this doc tells you *what an "agent" is*
> in agentdiff's vocabulary, and *what diffing one looks like in practice*.

## What is an "agent"?

In agentdiff, an **agent** is a production-shipped LLM feature with three
parts:

1. **A system prompt** (`prompt.md`) — defines the agent's role.
2. **An input + output JSON schema pair** — defines its API contract.
3. **A model name** — `claude-sonnet-4-6`, `claude-haiku-4-5-20251001`, etc.

That tuple is the unit of definition. At runtime, "invoking the agent"
means: send the prompt as `system`, send the input as a user message,
get JSON back, validate it against the output schema. agentdiff doesn't
care where the agent is hosted (Lambda, Kubernetes, Claude Code subagent,
LangChain pipeline, …) — only the `(prompt, schemas, model)` tuple matters.

Concrete examples of agents in the wild:

- An invoice-extraction service: scanned invoice text → `{vendor, total, line_items}`.
- A code-review bot: a diff → `{severity, comments[]}`.
- A DevSecOps agent: a Terraform plan → `{findings[]}`.
- A support-ticket router: a message → `{queue, priority}`.

All of these are prompt + schemas + model. agentdiff diffs them.

---

## A worked example: a PR risk classifier

Imagine your team has an agent that auto-routes pull requests by risk
level. Critical and high-risk changes auto-assign to a security reviewer;
low-risk changes get auto-approved.

The repo containing the agent looks like this:

```
your-platform-tools/
├── agentdiff.yaml
└── agents/
    └── pr-risk-classifier/
        ├── prompt.md
        ├── schemas/
        │   ├── input.json
        │   └── output.json
        ├── golden.jsonl              # known cases — must pass 100%
        ├── golden.judge.md           # rubric for the judge model
        └── adversarial.jsonl         # edge cases — small regression budget
```

### `agentdiff.yaml`

```yaml
apiVersion: agentdiff/v1
agents:
  - name: pr-risk-classifier
    path: agents/pr-risk-classifier
    provider: claude
    model: claude-sonnet-4-6
    prompt: prompt.md
    schemas:
      input: schemas/input.json
      output: schemas/output.json
    evals:
      - golden.jsonl
      - adversarial.jsonl
    thresholds:
      golden:
        minPassRate: 1.0           # zero tolerance on known-good cases
      adversarial:
        maxRegressionPct: 0.05     # ≤5% may regress on edge cases
```

### `prompt.md`

```markdown
You classify pull requests for routing. Given a diff, file list, and title,
emit a single JSON object with:

- `risk`: "critical" | "high" | "medium" | "low"
- `reasoning`: one short sentence
- `requires_security_review`: true if the change touches auth, crypto,
  secrets handling, dependency upgrades to packages with known CVE history,
  or IAM/network policy

Critical: changes to auth flows, crypto primitives, or secret rotation logic.
High:     changes to authz checks, IAM policies, network ACLs.
Medium:   dependency upgrades (non-major) or build-pipeline changes.
Low:      docs, tests, refactors with no behavior change.
```

### `schemas/input.json`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "title":         {"type": "string"},
    "files_changed": {"type": "array", "items": {"type": "string"}},
    "diff":          {"type": "string"}
  },
  "required": ["title", "files_changed", "diff"]
}
```

### `schemas/output.json`

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "risk":                     {"enum": ["critical", "high", "medium", "low"]},
    "reasoning":                {"type": "string", "minLength": 1},
    "requires_security_review": {"type": "boolean"}
  },
  "required": ["risk", "reasoning", "requires_security_review"]
}
```

### `golden.jsonl` — known cases, exact-match grading

```jsonl
{"id": "auth-001", "input": {"title": "Refactor JWT signing to use ed25519", "files_changed": ["auth/jwt.go"], "diff": "..."}, "expected": {"risk": "critical", "requires_security_review": true, "reasoning": "..."}}
{"id": "deps-001", "input": {"title": "Bump lodash from 4.17.20 to 4.17.21", "files_changed": ["package.json", "package-lock.json"], "diff": "..."}, "expected": {"risk": "medium", "requires_security_review": true, "reasoning": "..."}}
{"id": "docs-001", "input": {"title": "Fix typo in README", "files_changed": ["README.md"], "diff": "..."}, "expected": {"risk": "low", "requires_security_review": false, "reasoning": "..."}}
```

### `adversarial.jsonl` — judged, not exact-matched

When `expected` is omitted, the case is graded by the judge model
(see `golden.judge.md`) against a rubric. Use this for "the right
answer is debatable" cases.

```jsonl
{"id": "ambig-001", "input": {"title": "Update tests", "files_changed": ["auth/jwt_test.go"], "diff": "..."}}
{"id": "ambig-002", "input": {"title": "Refactor: extract helper", "files_changed": ["iam/policy.go"], "diff": "..."}}
```

### `golden.judge.md`

```markdown
A response is good if:
- The risk level matches the actual blast-radius of the change.
- `requires_security_review` is true whenever the change touches auth,
  authz, secrets, crypto, IAM, network policy, or upgrades a dep with
  prior CVEs.
- `reasoning` cites the specific file or pattern that drove the call.

A response is bad if it under-classifies auth/IAM changes, over-classifies
docs/tests, or gives generic reasoning that doesn't reference the diff.
```

---

## The payoff: what a PR comment looks like

Suppose someone proposes a tweak to `prompt.md` along the lines of *"be
less aggressive about flagging dependency upgrades — too many false
positives."* When that PR opens, agentdiff runs the evals against both
the old and new versions of the prompt, and posts a comment on the PR:

> ### `pr-risk-classifier`
>
> **Regressions (3):** `deps-001`, `deps-002`, `auth-005` — these now
> classify as `low` where they previously classified as `medium` or
> `critical`.
> **Improvements (1):** `noisy-deps-001` (previously over-classified, now correct).
> **Pass rate (golden):** 100% → 87.5% (**-12.5%**)
> **Threshold violation:** `golden.minPassRate=1.0`, got 0.875 ❌ — **blocks merge**.
> **Cost:** $0.0142 → $0.0138 (-2.8%)
> **Latency p95:** 1820ms → 1750ms

The reviewer sees, before merging: *your "reduce false positives" change
accidentally downgraded a critical auth-flow case.* That's the entire
product.

---

## What agentdiff is NOT

To keep scope honest:

- It is **not** an eval framework. It uses your evals; it doesn't
  generate or manage them.
- It is **not** a prompt management UI. Your prompts live in your repo,
  versioned by git, like any other code.
- It is **not** an agent runtime, observability platform, or deployment
  system. It runs evals at PR time and shuts up.
- It is **not** a marketplace, catalog, or registry of prompts.

The success state is a developer changing a prompt, opening a PR, and
seeing a behavioral diff in the review thread within a few minutes —
nothing more, nothing less.
