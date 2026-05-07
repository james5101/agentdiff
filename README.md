# agentdiff

> When you change an agent's prompt, schema, or model, you have no idea if it'll be better or worse in production until it ships. agentdiff is a GitHub bot that runs your agent's evals against the old and new versions on every PR and posts a behavioral diff — accuracy changes, regression cases, schema drift, cost delta — so reviewers can approve agent changes the same way they approve code changes.

Status: pre-alpha.

- See [`docs/concepts.md`](docs/concepts.md) for what an "agent" means here and a worked end-to-end example (PR risk classifier).
- See [`examples/pr-risk-classifier/`](examples/pr-risk-classifier/) for a runnable companion to the concepts doc.
- See [`HANDOFF.md`](HANDOFF.md) for the build plan.

The README will be filled out at Milestone 4.
