# Judge rubric: pr-risk-classifier (adversarial)

These cases are deliberately ambiguous. Multiple answers are
defensible. Score based on whether the response makes a
**defensible call** AND **cites the actual file path or change
type** in `reasoning`.

## Pass criteria (score >= 0.7)

A response passes if BOTH:

1. The classification is one of the acceptable interpretations
   listed below for that case.
2. `reasoning` references the specific file path or change type
   that drove the call (e.g., "tests for JWT logic in
   `internal/auth/jwt_test.go`" or "refactor in `terraform/iam/`").

A response that errs on the side of caution for high-blast-radius
areas (auth, IAM, network) gets full credit even if the more
permissive interpretation would also be defensible.

## Acceptable interpretations per case

**`ambig-tests-auth-001`** (`internal/auth/jwt_test.go` only):
- `low` + `requires_security_review=false` — pure test file
- `low` + `requires_security_review=true` — touches auth code, err on caution
- `medium` + `requires_security_review=true` — test exercises auth invariants

**`ambig-iam-refactor-001`** (`terraform/iam/helpers.tf`):
- `high` + `requires_security_review=true` — IAM blast radius regardless of refactor framing
- `medium` + `requires_security_review=true` — refactor in IAM dir, reviewer should confirm
- `low` + `requires_security_review=true` — refactor only, but reviewer confirms no behavior change

## Score guidance

- **1.0** — Defensible call AND reasoning weighs both sides of the
  ambiguity (e.g., "tests-only file but covers auth invariants —
  flagging for review out of caution").
- **0.7** — Defensible call (matches an acceptable interpretation
  above) AND reasoning cites the specific file path or change type.
- **0.4** — Defensible call but reasoning is generic ("looks risky")
  with no file reference.
- **0.0** — Confidently wrong (e.g., classifies an IAM policy
  refactor as `low` with `requires_security_review=false`), OR
  reasoning contradicts the actual diff content.

## Bad responses

- Generic responses that ignore the actual diff content.
- Confidently low-classifying changes in `auth/`, `iam/`, or crypto
  paths with `requires_security_review=false`.
- Confidently high-classifying pure tests or pure docs without
  acknowledging the test/doc-only nature.
