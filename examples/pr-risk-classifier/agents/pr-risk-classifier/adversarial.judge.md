# Judge rubric: pr-risk-classifier (adversarial)

These cases are deliberately ambiguous. There is no single correct
answer — score based on whether the response demonstrates *good
judgment* about the specific situation.

## Acceptable answers must

- Acknowledge the file/path that drove the call (e.g., "tests for auth
  logic" or "refactor in IAM directory").
- Make a defensible call that **errs on the side of caution** for
  high-blast-radius areas (auth, IAM, network).

## Bad answers

- Generic responses that ignore the actual diff content.
- Confidently low-classifying changes in `auth/` or `iam/` directories
  without acknowledging the surrounding context.
- Confidently high-classifying pure tests or pure docs without
  acknowledging the test/doc-only nature.

## Score guidance

- **1.0** — Reasoning explicitly weighs both sides of the ambiguity
  (e.g., "tests-only file but covers auth invariants — flagging for
  review out of caution").
- **0.7** — A defensible call with reasoning that touches on the right
  signals.
- **0.4** — A reasonable call but with weak or generic reasoning.
- **0.0** — Confidently wrong, or reasoning ignores the actual file
  paths involved.
