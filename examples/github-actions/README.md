# GitHub Actions integration

The minimal way to wire agentdiff into a GitHub repo.

## Setup

1. Run `agentdiff init` at your repo root if you don't already have an `agentdiff.yaml`. Edit it to declare your real agent.
2. Copy [`agentdiff.yml`](agentdiff.yml) into your repo at `.github/workflows/agentdiff.yml`.
3. In **Settings → Secrets and variables → Actions**, add `ANTHROPIC_API_KEY` as a repo secret.
4. Open a PR.

The workflow runs on `pull_request` events targeting `main`. The `agentdiff diff` step auto-detects the PR's base and head SHAs from the GitHub Actions event payload — no need to plumb them through manually.

## What the user sees on a PR

A check named **agentdiff / diff** appears on the PR. If the diff has threshold violations (regressions exceed `maxRegressionPct`, pass rate drops below `minPassRate`, etc.), the check fails and the PR is blocked from merging (assuming you've enabled branch protection requiring this check). Click the check to view the rendered behavioral diff in the action's logs.

## Customizing

- **Different default branch.** Change `pull_request.branches: [main]` to your branch name.
- **Concurrency cap.** Add `--concurrency 10` to the `agentdiff diff` line if your eval set is large and you want to push more parallel API calls.
- **Verbose reasoning in logs.** Add `--show-reasoning` to see per-case judge reasoning alongside the rendered diff.
- **Different repo path.** Change `agentdiff diff .` to `agentdiff diff path/to/agents-dir/` if your `agentdiff.yaml` isn't at the repo root.

## Forks

By default, GitHub Actions runs `pull_request` workflows from forks **without secrets**, so `ANTHROPIC_API_KEY` won't be available. The workflow will fail with a clear error in that case. This is correct behavior — you generally don't want fork PRs to spend your API budget. If you want to opt in for trusted contributors, use `pull_request_target` with appropriate caution and read [GitHub's security advisories](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#pull_request_target) first.

## Other CI systems

agentdiff is just a CLI. The same `agentdiff diff` invocation works in GitLab CI, Bitbucket Pipelines, Jenkins, etc. — pass the base and head SHAs as positional arguments if your CI doesn't expose them through env vars we recognize. Auto-detection for non-GitHub CIs lands as users ask.
