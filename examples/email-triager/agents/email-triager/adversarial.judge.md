# Judge rubric: email-triager (adversarial)

These cases are deliberately ambiguous. The "right answer" is debatable.
Score based on whether the response demonstrates **good judgment** about
the specific situation, not whether it matches one specific labeling.

## Pass criteria (score >= 0.7)

- The classification is one of the acceptable interpretations below.
- `reasoning` cites the specific phrase, signal, or contextual cue
  that drove the call.
- For high-blast-radius cases (anything possibly involving legal,
  security, or hostile sentiment), the agent errs toward
  `requires_human_review=true`.

## Per-case acceptable interpretations

**`ambig-mixed-001`** (order delay + refund question + billing dispute):
- `category` in {`support`, `billing`} — both defensible. Support is
  best if "shipping fix" is the primary need; billing is best if
  "refund and price correction" is the primary need.
- `urgency` in {`high`, `normal`} — high if 5-day delay + multiple
  issues is treated as escalation, normal otherwise.
- `reasoning` MUST acknowledge BOTH the shipping issue AND the
  billing discount issue. A response that only mentions one and
  ignores the other shows the agent didn't read carefully.

**`ambig-sarcasm-001`** (sarcastic praise that's a complaint):
- `sentiment` in {`negative`, `hostile`} — `positive` is a clear fail
  (the agent missed the sarcasm).
- `category=support` ✓
- `urgency=high` ✓ (multiple failures, locked account, customer
  clearly at the breaking point)
- `requires_human_review=true` ✓ (don't auto-reply to a furious
  customer with a canned message)
- `reasoning` must show the agent caught the sarcasm — phrases like
  "sarcastic," "ironic praise," or pointing at the contradiction
  between tone and content.

**`ambig-thread-context-001`** (short reply on a long thread):
- `requires_human_review=true` ✓ (mandatory — `thread_msg_count=7`,
  the agent has no context for "option 2")
- `category` whatever it picks — not the focus here
- `reasoning` MUST cite the long thread length / lack of context.
  A response that confidently classifies a 7-message thread without
  acknowledging the context gap is wrong regardless of category.

## Hard rules (any violation = automatic 0.0)

- `ambig-sarcasm-001` with `sentiment=positive` — fundamental misread.
- `ambig-thread-context-001` with `requires_human_review=false` — the
  agent is hallucinating context.
- Any case with generic reasoning that doesn't cite specific phrases
  from the email.

## Score guidance

- **1.0** — Defensible call AND reasoning explicitly weighs the
  ambiguity (e.g., "mixed signals — primary issue is shipping but
  billing discrepancy also flagged").
- **0.7** — Defensible call AND reasoning cites specific email
  content driving the decision.
- **0.4** — Defensible call but reasoning is generic.
- **0.0** — Hard-rule violation OR confidently wrong on the
  high-blast-radius signals (sarcasm read as positive, thread
  context ignored, etc.).
