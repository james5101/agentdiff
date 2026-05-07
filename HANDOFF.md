# agentdiff — Handoff for Claude Code

> **Read this entire document before writing any code.** It contains opinionated decisions that constrain implementation choices. Do not deviate from §3 without explicit human approval. Implementation tactics in §6+ are open to your judgment.

> **Name:** `agentdiff` is a placeholder. The human will rename later. Use it consistently in code and docs for now. Do not suggest alternatives unprompted.

---

## Status update — 2026-05-07

**Architectural pivot from "GitHub bot" to "CLI."** After M1+M2 shipped and were dogfooded against a real-feeling agent (PR risk classifier example), we revisited the M3 plan and changed direction:

- agentdiff is now positioned as **a CLI tool** that runs anywhere — locally on a developer's laptop, or as a step inside any CI/CD pipeline (GitHub Actions, GitLab CI, Jenkins, etc.). The CLI's exit code gates merges; the rendered markdown shows up in CI logs.
- The originally planned **GitHub App + webhook + worker + Redis stack is deferred** to a future milestone framed as a *hosted-bot product* (potentially paid, open-core split). The CLI is the foundation; the bot would wrap the CLI.
- Three of §8's known unknowns (forked PRs, concurrent PRs, cost cap) **dissolve under the CLI model** — they're handled by the user's existing CI rules and secrets management.

Sections affected: §3.4 (job execution), §3.5 (GitHub integration), §3.10 (out of scope), §4 (layout), §6 milestones 3+, §7.4 (deps), §8 (known unknowns). Each has been rewritten in place. The original "GitHub bot" framing is preserved in this preamble for historical context.

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
- **Synchronous CLI process.** No daemons, no queue, no Redis. The user's CI runner (or laptop) is the worker.
- All state for a single invocation lives in process memory and the cloned worktrees in `tempfile.TemporaryDirectory`.
- The eventual hosted-bot product (deferred milestone) MAY introduce an async worker pool, but it would still shell out to / import from the same CLI logic — the queue is *its* concern, not the CLI's.

### 3.5 Distribution and CI integration
- agentdiff is shipped as a **Python CLI** installable via `uv tool install` (or `pipx install`). No GitHub App. No webhook receiver. No service to host.
- CI integration is "run the CLI in a CI step." When `GITHUB_BASE_REF` and `GITHUB_HEAD_REF` (or equivalents) are set in the environment, `agentdiff diff` auto-resolves the refs; otherwise it takes explicit positional args.
- Merge gating relies on the **CI's native check status** + **CLI exit code** (non-zero on threshold violation). The rendered markdown surfaces in CI job logs.
- **No PR comments in v1.** They're a UX nicety, not a correctness mechanism — and they would force authentication, idempotency, and platform-specific posting logic that the CLI sidesteps entirely. Reserved for the eventual hosted-bot product.

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

**Permanent no** — these are out of scope at every milestone:

- A web UI of any kind
- Production sampling / replay
- Deploy / canary / rollback features
- Custom judge models or judge model swap
- Eval generation / synthesis
- Prompt optimization / suggestions
- Slack/Discord notifications
- Anything called "marketplace," "catalog," or "registry"

**Deferred to the eventual hosted-bot product** — out of scope for the CLI, but reserved for a future paid milestone:

- A database / persistence layer (historical metrics across runs)
- A GitHub App, webhook receiver, or any persistent service
- PR comments and check runs posted automatically
- Multi-tenancy
- Cost budgets / spend alerts (the bot would enforce them; in CLI mode the user's CI bills cap themselves)
- Auth beyond local CLI use

**Out of scope for v1 specifically** — may come in a future CLI milestone:

- OpenAI / Bedrock / any provider other than Claude (stubbed only)

If the human asks for one of these mid-build, push back and reference this section.

---

## 4. Repository layout

```
agentdiff/
├── HANDOFF.md                       # this file
├── README.md
├── pyproject.toml                   # uv-managed
├── ruff.toml
├── mypy.ini
│
├── src/
│   └── agentdiff/
│       ├── __init__.py
│       ├── cli.py                   # `agentdiff run`, `diff`, `init`
│       ├── config.py                # env vars, settings via pydantic-settings
│       ├── _parsing.py              # lenient JSON extraction from LLM text
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
│       └── diff/                    # behavioral comparison
│           ├── compare.py           # base vs head → BehavioralDiff
│           ├── schema_drift.py
│           └── render.py            # BehavioralDiff → markdown
│
├── examples/
│   ├── pr-risk-classifier/          # runnable companion to docs/concepts.md
│   └── github-actions/              # sample workflow file users copy in
│
├── scripts/                         # local-only demo + acceptance harnesses
│
└── tests/
    ├── unit/
    └── fixtures/
        └── sample-repo/             # the M1 toy intent-classifier
```

Cross-module imports flow downward only: `cli` may import from anything else. `providers`, `definition`, `eval`, `diff` may not import from each other except through `definition.schema` (the shared types). The `_parsing` module is a tiny utility that any package may import.

The `webhook/`, `worker/`, `github/`, and `deploy/` directories called out in earlier drafts are gone — they were premised on the bot architecture, which is now deferred (see Status update).

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

### Milestone 3 — CLI ergonomics + CI runnability
**Goal:** the same CLI runs cleanly on a developer's laptop or as a step in any CI/CD pipeline. Exit codes gate merges; CI logs carry the rendered diff.

Build:
- Rename `run-local` → `run` and `diff-local` → `diff`. The "-local" suffix was a holdover from when there was a planned remote/bot equivalent; there isn't anymore.
- `agentdiff diff` (no positional args) auto-detects PR base/head from `GITHUB_BASE_REF` + `GITHUB_HEAD_REF` (and equivalents for other CIs as users ask). Explicit positional shas still override.
- `agentdiff init` scaffolds a starter `agentdiff.yaml` plus a working sample agent under `agents/example-classifier/` (prompt, schemas, golden cases) so a fresh user can run `agentdiff run` immediately and see something pass.
- `examples/github-actions/agentdiff.yml` — a copy-pasteable sample workflow that pip-installs agentdiff and runs `agentdiff diff` on `pull_request`.
- Drop unused runtime deps (`fastapi`, `uvicorn`, `arq`, `redis`, `githubkit`) from `pyproject.toml`. Move `httpx` to dev-only since it's only used in test fakes.

**Acceptance test:** open a PR on a real repo (the human's own, or a fresh test repo) where the workflow file is in place and an `agentdiff.yaml` declares one agent. The PR's CI check runs `agentdiff diff`, fails on a deliberate prompt regression, and the rendered markdown shows up in the action's job log.

### Milestone 4 — Use it on real work
**Goal:** the human uses this on a real DevSecOps agent in their own work for a week.

Build:
- Whatever rough edges surface in actual use. The human will report bugs as GitHub issues; you'll fix them.
- Polish the rendered-diff formatting.
- Round out `README.md` and write `docs/getting-started.md`.

**Acceptance test:** the human reports they used it on at least 5 real PRs and it caught at least one issue they would have otherwise shipped. After this milestone, they'll show it to 3 people; if all 3 say "I'd use that," it goes public per their stated trigger.

### Milestone 5+ — Hosted bot (paid product)
**Goal:** offer a managed GitHub bot that wraps the CLI, for teams who don't want to wire it into their own CI.

This milestone is **deferred and out of scope for the current build**. It exists in the document only so the architecture stays compatible with it. Sketch:

- The bot is a thin web service (FastAPI or similar) that subscribes to GitHub webhook events for PRs, materializes the same git worktrees the CLI does, **shells out to or imports** the same CLI logic, and posts the rendered markdown as a PR comment + sets a check run.
- All M3-deferred concerns live here: webhook signature verification, GitHub App registration, comment idempotency, forked-PR policy, per-PR cost cap, multi-tenant isolation, historical metrics persistence, cross-repo dashboards.
- Open-core split: CLI stays MIT/Apache-licensed and free. Bot is the paid SaaS layer. Conversation around licensing happens at M5 start, not before.

Do not start work on this milestone without explicit human direction.

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
- **Ask before adding a dependency.** Current runtime allowlist: `pydantic`, `pydantic-settings`, `typer`, `structlog`, `anthropic`, `jsonschema`, `gitpython`, `pyyaml`. Current dev allowlist: `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `vcrpy`, `httpx` (test fakes), `types-pyyaml`, `types-jsonschema`. Anything else needs human approval.

  Dependencies removed at M3 architecture pivot: `fastapi`, `uvicorn`, `arq`, `redis`, `githubkit` — these were premised on the bot architecture. They'd be re-added if/when the deferred hosted-bot milestone (M5+) is started, scoped to that subpackage only.

---

## 8. Known unknowns (flag, do not decide unilaterally)

1. **Judge model determinism.** LLM-as-judge introduces noise. M2 dogfooding showed the noise is mostly tractable when rubrics are explicit; the `--show-reasoning` flag exposes the judge's actual thinking so users can iterate on rubrics or prompts. No multi-sample averaging in v1.

2. **Eval case storage at scale.** A repo with 10,000 eval cases is going to be slow. v1 punts and assumes O(100) cases. If a real user shows up with O(10,000), we'll deal with it then.

### Resolved by the M3 CLI pivot

Three known unknowns from earlier drafts dissolved when we moved off the bot architecture:

- **~~Forked PRs.~~** Now the user's CI's problem (GitHub Actions has well-understood `pull_request` vs `pull_request_target` semantics; the user picks).
- **~~Concurrent PRs on the same agent.~~** Now the user's CI concurrency rules.
- **~~Per-PR cost cap.~~** Now the user's CI minutes + their own Anthropic spend cap.

These will return as concerns when the deferred hosted-bot milestone (M5+) is started; they'll need to be solved there.

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
