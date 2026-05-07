# Judge rubric: pr-risk-classifier (golden)

A response is good if all three fields are correct.

## `risk`

Must match the intended classification for the change:

- **critical** for auth-flow / crypto / signing-algorithm changes
- **high** for IAM / authz / network-policy changes
- **medium** for dependency upgrades or CI/CD changes
- **low** for docs, tests, behavior-preserving refactors, comment-only
  edits

## `requires_security_review`

Must be `true` when the change touches:

- Authentication, authorization, or session management
- Cryptography or secret handling
- IAM, RBAC, or network policy
- Dependency upgrades for packages with a history of CVEs — lodash,
  log4j, jackson, urllib3, requests, openssl, axios, fastjson,
  struts2, spring-core, etc.

Must be `false` for:

- Docs, comments, tests, behavior-preserving refactors
- Dev-only tooling upgrades that don't ship to production
  (formatters, linters, type-checkers, build tools)

## `reasoning`

Must cite the specific file path or pattern that drove the
classification. Generic reasoning ("looks risky", "could affect
security") without referencing the actual diff content is **bad**.

## Score guidance

- **1.0** — All three fields correct and reasoning is specific.
- **0.7** — Risk and review-flag correct; reasoning is acceptable but
  borderline-generic.
- **0.4** — One field wrong (e.g., review flag flipped) but the others
  are correct.
- **0.0** — Multiple fields wrong, or reasoning is generic / hallucinated.

A response is **bad** (score < 0.7) if it under-classifies auth/IAM
changes, over-classifies docs/tests, or sets `requires_security_review`
incorrectly given the rules above.
