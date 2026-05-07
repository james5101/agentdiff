# agentdiff

> When you change an agent's prompt, schema, or model, you have no idea if it'll be better or worse in production until it ships. **agentdiff** is a GitHub bot that runs your agent's evals against the old and new versions on every PR and posts a behavioral diff — accuracy changes, regression cases, schema drift, cost delta — so reviewers can approve agent changes the same way they approve code changes.

## What's an "agent"?

A `(prompt + input schema + output schema + model)` tuple. agentdiff doesn't care about your runtime — Lambda, Kubernetes, Claude Code subagent, LangChain pipeline — only the tuple. You declare them in an `agentdiff.yaml` at the root of any repo:

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
        minPassRate: 1.0
      adversarial:
        maxRegressionPct: 0.05
```

See [`docs/concepts.md`](docs/concepts.md) for the full conceptual model.

## What does the diff actually look like?

Excerpt from the included PR-risk-classifier example, after a developer "simplified" the dependency-CVE rule in `prompt.md`:

```markdown
### `pr-risk-classifier` — `golden.jsonl`

**:no_entry: Threshold violations (blocks merge):**
- `golden.jsonl` minPassRate=1.00 → got 0.80

**:x: Regressions (1):** `deps-cve-history-001`
**Pass rate:** 100.0% → 80.0% (-20.0pp)
**Cost:** $0.013 → $0.011 (-14.0%)
**Latency:** p50 2188ms → 1891ms, p95 2441ms → 2195ms
```

Reviewer sees, before merging: *the "reduce false positives" change accidentally downgraded the lodash CVE-history case.* That's the entire product.

## Status

**Pre-alpha.** What works today:

- **`agentdiff run <repo>`** — load agents from `agentdiff.yaml`, run their evals, print pass/fail.
- **`agentdiff diff <repo> <base-sha> <head-sha>`** — materialize both refs as git worktrees, run evals on each, render the markdown diff to stdout. Pass `--show-reasoning` to also see per-case judge reasoning. Same command works in CI — when `GITHUB_BASE_REF`/`GITHUB_HEAD_REF` are set, the refs auto-resolve.
- **Provider:** Claude (Anthropic). OpenAI is stubbed and raises with a clear message.
- **Grading:** exact-match on `expected`, or LLM-as-judge (Sonnet) against a per-eval-set rubric file when `expected` is absent.

What's deferred:

- **A hosted GitHub bot** (eventual paid product) that posts the rendered diff as a PR comment + sets a check run automatically. The current CLI gets you the same merge-gating behavior via your CI's exit-code check — see [Milestone 5+](HANDOFF.md#milestone-5--hosted-bot-paid-product).
- OpenAI, Bedrock, or any non-Claude provider.
- Persistence of historical metrics across runs.

See [`HANDOFF.md`](HANDOFF.md) for the full build plan and what's deliberately out of scope.

## Try it locally

Requires Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and an Anthropic API key.

```powershell
# Install dependencies
uv sync

# Set your key
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# Run the included example
uv run agentdiff run examples/pr-risk-classifier
```

To see a full diff against a deliberate prompt regression (sets up a temp git repo with two commits, runs both versions, prints the comparison):

```powershell
.\scripts\demo-pr-risk-classifier.ps1
```

Total Anthropic spend for the demo: ~$0.10.

## Read more

- [`docs/concepts.md`](docs/concepts.md) — what "an agent" means here and a worked end-to-end PR-risk-classifier example.
- [`examples/pr-risk-classifier/`](examples/pr-risk-classifier/) — the runnable companion: `agentdiff.yaml`, prompt, schemas, eval cases, judge rubrics. Read it or copy it as a template for your own agent.
- [`HANDOFF.md`](HANDOFF.md) — the full project plan and milestone status.

## What this is *not*

- Not an eval framework — it uses your evals; it doesn't generate or manage them.
- Not a prompt management UI — your prompts live in your repo, versioned by git, like any other code.
- Not an agent runtime, observability platform, or deployment system.

The success state is: a developer changes a prompt, opens a PR, and sees a behavioral diff in the review thread within a few minutes. Nothing more, nothing less.
