# CLAUDE.md

Orientation for AI assistants working in this repo. Quick read; the long-form spec is in [`HANDOFF.md`](HANDOFF.md).

## What is this?

`agentdiff` is a **CLI tool** that runs an LLM agent's evals against the old and new versions of its definition on every PR and prints a behavioral diff (regressions, improvements, threshold violations, schema drift, cost delta, latency delta). Merge gating is via the CLI's exit code in CI.

It is **not** a GitHub bot. The hosted bot is reserved as the eventual paid open-core product (Milestone 5+) — see HANDOFF.md "Status update — 2026-05-07" for the architectural pivot rationale. Don't introduce webhook/queue/worker infrastructure; defer it explicitly.

## Status

- M1 + M2 + M3 shipped. M4 (real-work dogfood for a week) not yet started.
- Public repo: https://github.com/james5101/agentdiff
- Branch protection on `main` requires `check` (ruff/format/mypy/pytest) AND `diff` (agentdiff dogfood) to pass before merge.

## Test loop

Always use `uv` (this repo's only supported package manager):

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src tests
uv run pytest -q
```

CI runs all four on every PR. Don't merge with anything red.

The CLI itself:

```bash
uv run agentdiff --help              # three subcommands: run, diff, init
uv run agentdiff run <repo>          # run all agents' evals on the current state
uv run agentdiff diff <repo> [base] [head]   # base/head auto-detect from CI env
uv run agentdiff init <path>         # scaffold a starter agent
```

## Project layout (canonical version in HANDOFF.md §4)

```
src/agentdiff/
├── cli.py              # Typer entry point: run, diff, init
├── config.py           # pydantic-settings (ANTHROPIC_API_KEY, etc.)
├── _ci.py              # auto-detect PR refs from GITHUB_EVENT_PATH
├── _parsing.py         # lenient JSON extraction from LLM text
├── _init_template.py   # files written by `agentdiff init`
├── definition/         # agentdiff.yaml + JSONL parsing; the §5 Pydantic models
├── providers/          # Provider protocol + ClaudeProvider + OpenAI stub
├── eval/               # case + run + judge
└── diff/               # compare + schema_drift + render
```

## Import rules (HANDOFF.md §4)

- `cli.py` may import from anything else.
- `providers/`, `definition/`, `eval/`, `diff/` may **not** import from each other except through `definition.schema` (the shared Pydantic types).
- `_parsing` and `_ci` are top-level utility modules anything may import.

These rules exist to prevent tight coupling and make modules independently testable. Violations should be rare and need explicit justification.

## Common patterns

| Task | Where to change | Test to update |
| --- | --- | --- |
| Add/change a Pydantic model in §5 | `src/agentdiff/definition/schema.py` | `tests/unit/test_schema.py` (round-trip + invalid-rejection per HANDOFF §7.2) |
| Change agent invocation behavior | `src/agentdiff/providers/claude.py` | `tests/unit/test_provider_claude.py` (mocked AsyncAnthropic, no real API) |
| Change judge behavior | `src/agentdiff/eval/judge.py` | `tests/unit/test_judge.py` |
| Change rendered diff output | `src/agentdiff/diff/render.py` | `tests/unit/test_render.py` (golden-output assertions) |
| Add an example agent | `examples/<name>/` | None required (loader smoke-tests via `agentdiff run`) |
| Update dogfood thresholds | root `agentdiff.yaml` | None — config-only |

## Gotchas

- **Sonnet 4.6 rejects assistant prefill.** Both `ClaudeProvider` and the judge use `_parsing.extract_json_object` (lenient, handles preambles + markdown fences) instead of prefilling `{`. Don't re-introduce prefill without first verifying the target model supports it.
- **PowerShell 5.1 + em-dashes.** Em-dash characters (`—`) in `.ps1` scripts get mis-decoded by PowerShell 5.1's default cp1252 reader and break the parser. Use ASCII hyphens in scripts. Em-dashes are fine in markdown / Python / stdout.
- **Dogfood thresholds are deliberately loose** in the root `agentdiff.yaml` (`minPassRate=0.83` for the email-triager golden set, `maxRegressionPct=0.34` for adversarial). This absorbs single-case judge nondeterminism so unrelated PRs don't trigger false-alarm CI failures. Don't tighten without explicit human approval. The strict thresholds in `examples/email-triager/` are unchanged — they're what a user with tight production controls would set.
- **`pipx run --spec git+...` installs from `main`.** The dogfood workflow (`.github/workflows/agentdiff.yml`) installs agentdiff from the *main* branch on every PR, not from the PR branch. So a PR that changes the renderer will only see its new output applied to subsequent PRs after the renderer change merges. This is correct security posture but surprising at first.
- **The `diff` workflow only runs on PR events**, not on push to main. `agentdiff diff` requires two refs; main has no base to compare against.

## When in doubt

- HANDOFF.md is authoritative for design decisions and milestone status.
- `docs/concepts.md` explains what an "agent" means in agentdiff vocabulary.
- `examples/pr-risk-classifier/` and `examples/email-triager/` are runnable templates.
- The user prefers boring/typed/observable code, terse responses, and one sharp question with a recommendation rather than menus of options. Don't over-explain platform/CI concepts they already know.
