# agentdiff — Handoff for Claude Code

> **Read this entire document before writing any code.** It contains opinionated decisions that constrain implementation choices. Do not deviate from §3 without explicit human approval. Implementation tactics in §6+ are open to your judgment.

> **Name:** `agentdiff` is a placeholder. The human will rename later. Use it consistently in code and docs for now. Do not suggest alternatives unprompted.

---

## 1. Project mission

`agentdiff` is a GitHub bot that runs an agent's evals against the old and new versions of its definition on every PR, and posts a behavioral diff so reviewers can approve agent changes the same way they approve code changes.

**The product succeeds when** a developer changes an agent's prompt, schema, or model in a PR, and within a few minutes sees a comment that tells them: which test cases regressed, which improved, what the cost delta is, and whether any previously passing cases now fail. The reviewer can then merge or block with the same confidence they have for code review.

**The product is not** an eval framework, a prompt management UI, an agent runtime, an observability tool, or a deployment system. Resist all of these. They are explicitly out of scope and adding any of them dilutes the spine.

**The pitch (single paragraph, for the README):**

> When you change an agent's prompt, schema, or model, you have no idea if it'll be better or worse in production until it ships. agentdiff is a GitHub bot that runs your agent's evals against the old and new versions on every PR and posts a behavioral diff — accuracy changes, regression cases, schema drift, cost delta — so reviewers can approve agent changes the same way they approve code changes.

---

## 2. The vertical slice

Build one path end-to-end at 80% depth. Do not build features horizontally.

**The path:**

```
PR opened/updated on a repo with agentdiff installed
  → webhook received
    → clone PR base + head
      → discover agent definitions (per agentdiff.yaml)
        → load eval cases
          → run base version against evals (parallel)
          → run head version against evals (parallel)
            → compute behavioral diff
              → post PR comment
                → set check run status
```

Every component above must function on this single path before any second path is considered.

---

## 3. Architectural decisions (non-negotiable for MVP)

These are settled. Do not propose alternatives unless you discover a hard blocker.

### 3.1 Language & framework
- **Python 3.12+** for everything.
- **Pydantic v2** for all schemas and data validation.
- **FastAPI** for the webhook receiver.
- **Typer** for any CLI surface (e.g., `agentdiff init` to scaffold a repo).
- **uv** for dependency management. Not Poetry. Not pip-tools.
- **ruff** for lint + format.
- **mypy --strict** for type checking. Clean or it doesn't merge.

### 3.2 Provider abstraction
A `Provider` protocol exists from day one. Only `ClaudeProvider` is implemented in v1. `OpenAIProvider` is stubbed with `NotImplementedError("OpenAI support coming soon — see issue #X")`.

The interface is intentionally tiny:

```python
class Provider(Protocol):
    async def invoke(
        self,
        agent: AgentDefinition,
        input_: dict,
    ) -> InvocationResult: ...

    def estimate_cost(
        self,
        usage: TokenUsage,
    ) -> Decimal: ...
```

Resist any urge to grow this interface beyond ~5 methods. If a feature requires expanding the interface, that is a signal the feature is leaking provider-specific concerns and needs to be redesigned.

### 3.3 No persistence layer in v1
- No database. No object store.
- All state lives in: GitHub (PR comments, check runs), the cloned repo (agent definitions, evals), and short-lived job queues (Redis as a queue broker only).
- When v1 is shipped and validated, persistence will be added for historical metrics. Not before.

### 3.4 Job execution
- **Arq** (async Redis queue) for the eval-run worker.
- One Redis instance, used purely as a queue broker. Not as a cache, not as a store.
- Workers run in the same container as the webhook receiver in dev; separate container in any deployed environment.
- No Celery. No RabbitMQ. No Kafka. Boring, async-native, single-purpose.

### 3.5 GitHub integration
- Implement as a **GitHub App** (not an OAuth app, not a personal access token).
- Use the official `githubkit` Python library for typed GitHub API access.
- Webhook signature verification is mandatory. Reject unsigned webhooks with 401.
- The bot posts **one comment per PR** and updates it on subsequent pushes (don't spam new comments).
- The bot creates **one check run per PR** that reflects the merge gate decision.

### 3.6 Agent definition format
Agents in a user's repo are discovered via an `agentdiff.yaml` at the repo root:

```yaml
apiVersion: agentdiff/v1
agents:
  - name: invoice-extractor
    path: agents/invoice-extractor/
    provider: claude
    model: claude-sonnet
    prompt: prompt.md
    schemas:
      input: schemas/input.json
      output: schemas/output.json
    evals:
      - golden.jsonl
      - adversarial.jsonl
    thresholds:
      golden:
        minPassRate: 1.0
      adversarial:
        maxRegressionPct: 0.05
```

The agent's prompt is plain markdown. The evals are JSONL files with `{"input": ..., "expected": ...}` per line. `expected` is optional — if absent, the case is judged rather than exact-matched.

This format is **the contract with the user**. Do not change it without explicit approval. If a feature seems to require a format change, propose the change and wait for human review.

### 3.7 Eval execution
- Each eval case runs as an isolated coroutine.
- Cases run with bounded concurrency (default 5, configurable per repo) to avoid rate-limiting the model provider.
- Per-case timeout: 60 seconds default.
- Per-eval-run total timeout: 10 minutes. If exceeded, post a comment saying "eval run timed out" and exit cleanly.
- All API calls go through the `Provider` interface. No direct `anthropic` SDK calls outside `ClaudeProvider`.

### 3.8 The behavioral comparator
The comparator takes two `EvalRun` objects (base and head) over the same eval cases and produces a `BehavioralDiff`. The diff has these required components:

1. **Regression list** — cases that passed in base but failed in head. Listed by ID. This is the most important section of the comment.
2. **Improvement list** — cases that failed in base but passed in head.
3. **Aggregate pass rate per eval set** — base %, head %, delta.
4. **Schema drift** — cases where the output JSON shape changed (extra fields, missing fields, type changes).
5. **Cost delta** — total tokens and dollar cost for base vs head, percentage change.
6. **Latency delta** — p50 and p95 wall-clock per case, base vs head.

A case "passes" if:
- It has an `expected` field and the output matches exactly (after JSON normalization), OR
- It has no `expected` field, the output validates against the schema, and the judge model rates it ≥ the configured threshold.

### 3.9 Judge model
- v1 uses **Claude Sonnet** as the judge model regardless of the provider being judged. Hardcoded.
- Judge rubric is a per-eval-set markdown file (e.g., `evals/golden.judge.md`) describing what "good" looks like.
- If no judge rubric exists, fall back to a generic "is this a reasonable response to the input?" rubric. Surface a warning in the PR comment when this happens.
- Judge calls are themselves observable (cost is tracked separately and shown in the diff).

### 3.10 Out of scope for v1 (reject if requested)
- A web UI of any kind
- A database / persistence layer
- Production sampling / replay
- Deploy / canary / rollback features
- Multi-tenancy beyond "one GitHub App installation per org"
- OpenAI / Bedrock / any provider other than Claude (stubbed only)
- Custom judge models or judge model swap
- Eval generation / synthesis
- Prompt optimization / suggestions
- Slack/Discord notifications (the comment is the notification)
- Cost budgets / spend alerts
- Auth beyond GitHub App installation
- Anything called "marketplace," "catalog," or "registry"

If the human asks for one of these mid-build, push back and reference this section.

---

## 4. Repository layout

```
agentdiff/
├── HANDOFF.md                       # this file
├── README.md                        # written last
├── pyproject.toml                   # uv-managed
├── ruff.toml
├── mypy.ini
│
├── src/
│   └── agentdiff/
│       ├── __init__.py
│       ├── cli.py                   # `agentdiff init`, etc.
│       ├── config.py                # env vars, settings via pydantic-settings
│       │
│       ├── webhook/                 # FastAPI app
│       │   ├── app.py
│       │   ├── github.py            # signature verification, event parsing
│       │   └── handlers.py          # webhook → enqueue job
│       │
│       ├── worker/                  # Arq worker
│       │   ├── tasks.py             # the eval-run job
│       │   └── runner.py            # orchestrates clone → run → diff → post
│       │
│       ├── providers/
│       │   ├── base.py              # Provider protocol + types
│       │   ├── claude.py            # ClaudeProvider
│       │   └── openai.py            # OpenAIProvider (stub, raises)
│       │
│       ├── definition/              # parsing agentdiff.yaml + agent files
│       │   ├── schema.py            # Pydantic models
│       │   ├── loader.py            # repo → list[AgentDefinition]
│       │   └── evals.py             # JSONL eval case loading
│       │
│       ├── eval/                    # running evals
│       │   ├── case.py              # single-case execution
│       │   ├── run.py               # full eval-set execution
│       │   └── judge.py             # LLM-as-judge logic
│       │
│       ├── diff/                    # behavioral comparison
│       │   ├── compare.py           # base vs head → BehavioralDiff
│       │   ├── schema_drift.py
│       │   └── render.py            # BehavioralDiff → markdown comment
│       │
│       └── github/
│           ├── client.py            # githubkit wrapper
│           ├── comment.py           # upsert PR comment
│           └── check_run.py         # set check status
│
├── tests/
│   ├── unit/
│   ├── integration/                 # require real GitHub App + Anthropic key
│   └── fixtures/
│       ├── sample-repo/             # a fake user repo for end-to-end tests
│       └── eval-cases/
│
└── deploy/
    ├── docker-compose.yml           # local dev: webhook + worker + redis
    └── Dockerfile
```

Cross-module imports flow downward only: `webhook` and `worker` may import from anything else. `providers`, `definition`, `eval`, `diff`, `github` may not import from each other except through `definition.schema` (the shared types).

---

## 5. Data model (the load-bearing types)

These Pydantic models are the spine. Get them right early.

```python
# definition/schema.py

class AgentDefinition(BaseModel):
    name: str
    path: Path
    provider: Literal["claude", "openai"]
    model: str
    prompt_path: Path
    input_schema_path: Path
    output_schema_path: Path
    eval_files: list[Path]
    thresholds: dict[str, EvalThresholds]

class EvalCase(BaseModel):
    id: str                          # stable ID (hash of input if not provided)
    input: dict
    expected: dict | None = None     # if None, judged
    metadata: dict = Field(default_factory=dict)

class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int

class InvocationResult(BaseModel):
    output: dict | None              # None if errored
    usage: TokenUsage | None
    latency_ms: int
    error: str | None = None

class CaseResult(BaseModel):
    case_id: str
    invocation: InvocationResult
    passed: bool
    failure_reason: str | None
    judge_score: float | None = None

class EvalRun(BaseModel):
    agent_name: str
    eval_set: str                    # filename of the .jsonl
    git_sha: str
    cases: list[CaseResult]
    total_cost_usd: Decimal
    p50_latency_ms: int
    p95_latency_ms: int

class BehavioralDiff(BaseModel):
    agent_name: str
    base_run: EvalRun
    head_run: EvalRun
    regressions: list[str]           # case IDs
    improvements: list[str]
    schema_drift: list[SchemaDriftEntry]
    cost_delta_usd: Decimal
    cost_delta_pct: float
    pass_rate_delta_pct: float
    threshold_violations: list[ThresholdViolation]
```

Every one of these models has tests that round-trip a valid example and reject an invalid one. Write the model and its test in the same commit.

---

## 6. Build sequence (4 weeks)

Milestones, not sprints. Do not start a milestone until the previous one passes its acceptance test.

### Milestone 1 — Definition + provider, no GitHub yet
**Goal:** prove we can load an agent definition and invoke it.

Build:
- All Pydantic models in §5.
- `definition.loader`: read `agentdiff.yaml` from a directory, return `list[AgentDefinition]`.
- `definition.evals`: load `.jsonl` eval files into `list[EvalCase]`.
- `providers.base` + `providers.claude`: real implementation that calls Anthropic and returns `InvocationResult`.
- `providers.openai`: stub that raises with a clear message.
- `eval.case`: run a single case against an agent, return `CaseResult` (no judging yet, just exact match or schema validation).
- `eval.run`: run a full eval set with bounded concurrency, return `EvalRun`.
- A simple `agentdiff run-local <path-to-repo>` CLI command that does all of the above and prints results to stdout.

**Acceptance test:** create a fixture repo at `tests/fixtures/sample-repo/` with one agent and one eval set. Run `agentdiff run-local tests/fixtures/sample-repo/`. See the eval pass/fail results printed.

### Milestone 2 — Behavioral diff + judge
**Goal:** prove we can compare two runs meaningfully.

Build:
- `eval.judge`: LLM-as-judge with a configurable rubric, falling back to generic.
- `diff.compare`: take two `EvalRun`s, produce a `BehavioralDiff`.
- `diff.schema_drift`: detect output shape changes between runs.
- `diff.render`: render a `BehavioralDiff` as a markdown string suitable for a PR comment.
- Extend the CLI: `agentdiff diff-local <repo-path> <base-sha> <head-sha>` checks out both, runs evals on each, prints the diff.

**Acceptance test:** in the fixture repo, make a commit that intentionally breaks one eval case in the prompt. Run `agentdiff diff-local`. The output identifies the broken case as a regression.

### Milestone 3 — GitHub integration
**Goal:** the bot works on real PRs.

Build:
- `webhook.app`: FastAPI app, single endpoint `/webhook`.
- `webhook.github`: signature verification.
- `worker.tasks`: the Arq job that does clone → diff → comment.
- `github.client`, `github.comment`, `github.check_run`: post and update PR comments and check runs.
- `deploy/docker-compose.yml`: local dev stack (webhook + worker + redis).
- Register a GitHub App in the human's account and document the setup in `README.md`.

**Acceptance test:** the human installs the GitHub App on a test repo, opens a PR that modifies an agent definition, and within 5 minutes sees a comment with a behavioral diff and a check run with the correct status.

### Milestone 4 — Use it on real work
**Goal:** the human uses this on a real DevSecOps agent in their own work for a week.

Build:
- Whatever rough edges surface in actual use. The human will report bugs as GitHub issues; you'll fix them.
- Polish the comment formatting.
- Write the `README.md` and a `docs/getting-started.md`.
- Add `agentdiff init` CLI that scaffolds a sample `agentdiff.yaml` in a repo.

**Acceptance test:** the human reports they used it on at least 5 real PRs and it caught at least one issue they would have otherwise shipped. After this milestone, they'll show it to 3 people; if all 3 say "I'd use that," it goes public per their stated trigger.

---

## 7. Implementation rules

### 7.1 Code style
- Type hints everywhere. `mypy --strict` clean.
- Pydantic models for every cross-boundary data structure.
- No bare exceptions.
- Logging via `structlog`, JSON in production, pretty in dev.
- Async by default for I/O. Sync for pure computation and CLI commands.

### 7.2 Testing
- Every Pydantic model: round-trip + invalid-rejection test.
- Comparator: golden tests with handcrafted `EvalRun` pairs and asserted `BehavioralDiff` outputs.
- Provider: contract tests using a recorded-cassette pattern (vcrpy or similar) so they don't hit the real API in CI.
- GitHub integration: tested against fixtures, not the real API. Real-API integration tests are a separate suite, gated by env var, run manually.
- **Do not write speculative tests for features that don't exist yet.**

### 7.3 Commits & PRs
- One milestone per branch. Open the PR at milestone start with the acceptance test as the description.
- Commit messages: imperative mood, scope prefix (e.g., `diff: detect schema drift on nested fields`).
- Do not merge a milestone PR until the acceptance test passes.

### 7.4 Defaults
- **Prefer boring.** The product's job is reliability. Boring is reliable.
- **Prefer fewer features.** Each feature is permanent maintenance cost.
- **Prefer explicit over magic.** Pydantic > dataclasses with hand-rolled validation. FastAPI DI > globals. Typer > custom argparse.
- **Ask before adding a dependency.** The current allowlist: `pydantic`, `pydantic-settings`, `fastapi`, `uvicorn`, `typer`, `structlog`, `arq`, `redis`, `httpx`, `anthropic`, `githubkit`, `jsonschema`, `gitpython`, `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `vcrpy`. Anything else needs human approval.

---

## 8. Known unknowns (flag, do not decide unilaterally)

1. **Judge model determinism.** LLM-as-judge introduces noise. How do we report judge confidence in the diff? Should we run the judge multiple times and average? Defer until Milestone 2 reveals how bad the noise is in practice.

2. **Eval case storage at scale.** A repo with 10,000 eval cases is going to be slow. v1 punts and assumes O(100) cases. If a real user shows up with O(10,000), we'll deal with it then.

3. **Forked PRs.** A PR from a fork can't be safely run against the bot's secrets (model API keys). v1 will refuse to run on PRs from forks and post a comment explaining why. Confirm before Milestone 3.

4. **Concurrent PRs on the same agent.** If two PRs touch the same agent simultaneously, do we serialize, run both, or queue? v1 assumption: run both independently, no coordination. Confirm before Milestone 3.

5. **Cost guardrails.** A malicious or accidental PR with 100,000 eval cases could rack up real money. v1 hardcodes a per-PR-run cost cap (e.g., $5) and refuses to start runs estimated to exceed it. Confirm the cap value with the human.

---

## 9. First action

When you start work:

1. Read this entire document again.
2. Create the repo skeleton from §4. Empty packages with `__init__.py`. Skeleton `pyproject.toml`, `ruff.toml`, `mypy.ini`, and a minimal CI workflow that runs ruff + mypy + pytest.
3. Open a PR titled `chore: scaffold repo` and stop. Wait for human review before starting Milestone 1.

Do not start Milestone 1 in the same PR as scaffolding.

---

## 10. Things the human cares about (context for judgment calls)

- The human is a senior platform/DevSecOps engineer. Assume Kubernetes, Terraform, IaC, observability, and security fluency. Do not over-explain platform concepts. Do explain Pydantic v2 idioms and Arq specifics if non-obvious.
- The human values code that is **boring, typed, and observable**. They will reject clever code that obscures intent.
- The human has **no commercial pressure** but does intend to commercialize eventually. Do not optimize for "future paying customers" — optimize for the human using it themselves successfully. The product becoming commercial-grade is a downstream consequence of being useful, not a thing you design for upfront.
- The human is going to show this to 3 people in their network after Milestone 4. **The product needs to be self-explanatory enough that a senior engineer can install it on a test repo and understand the value within 10 minutes**, with no live demo. The README and `getting-started.md` matter as much as the code.
- The human explicitly does not want this entangled with their other projects (Agentic Landing Zones, `agentctl`, CKAD studying, LaunchGazer, Valon job hunt). Treat this as a clean-room project with no shared code or infrastructure.
- When uncertain, ask one sharp question. Do not present five options with "what do you think?" — that wastes the human's time. Make a recommendation and ask for confirmation.

---

*End of handoff.*
