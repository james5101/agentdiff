# Judge rubric: email-triager (golden)

A response is good if every field is correct OR justifiably defensible
given the email content. The judge should not penalize defensible
alternative classifications (e.g., `urgency=critical` vs `high` for a
clearly serious case) but should penalize wrong classifications (e.g.,
classifying a security report as `support` instead of `compliance`).

## Per-case acceptable interpretations

**`legal-threat-001`** (notice of intent to file suit):
- `category=legal` ✓ (mandatory)
- `urgency` in {`high`, `critical`} ✓
- `sentiment` in {`negative`, `hostile`} ✓
- `suggested_queue` mentioning legal review ✓
- `requires_human_review=true` ✓ (mandatory — never auto-reply to legal threats)
- `contains_security_signal=false` ✓ (this is a legal threat, not a security signal)
- `suggested_template_id=null` ✓ (mandatory — never canned-respond to legal)

**`security-vuln-001`** (responsible vulnerability disclosure):
- `category` in {`compliance`, `support`} (compliance is best; support is acceptable if it routes to security team)
- `urgency` in {`critical`, `high`} ✓
- `requires_human_review=true` ✓ (mandatory)
- `contains_security_signal=true` ✓ (mandatory)
- `suggested_queue` mentioning security/incident ✓
- `suggested_template_id=null` ✓

**`billing-refund-001`** (accidental upgrade refund request):
- `category=billing` ✓ (mandatory)
- `urgency=normal` (`high` is too aggressive; `low` is too dismissive)
- `sentiment` in {`neutral`, `negative`} ✓
- `requires_human_review` may be `true` or `false` (refund authority varies)
- `suggested_template_id=tmpl-refund-ack` is ideal but not mandatory

**`support-frustrated-001`** (third-time angry customer):
- `category=support` ✓ (mandatory)
- `urgency=high` ✓ (mandatory — third contact + cancellation threat)
- `sentiment` in {`negative`, `hostile`} ✓
- `requires_human_review=true` ✓ (mandatory — escalation needed)
- `contains_security_signal=false` ✓ (cancellation threat is not a security signal)

**`sales-inquiry-001`** (qualified prospect demo request):
- `category=sales` ✓ (mandatory)
- `urgency=normal` ✓ (no time pressure stated)
- `sentiment=positive` ✓
- `requires_human_review=false` is acceptable; `true` is also fine
- `suggested_template_id=tmpl-sales-demo-link` is ideal

**`spam-cold-001`** (cold lead-gen pitch):
- `category=spam` ✓ (mandatory)
- `urgency=low` ✓ (mandatory)
- `requires_human_review=false` ✓ (mandatory — don't burn human time on spam)
- `suggested_template_id=null` ✓ (mandatory — never reply to spam)
- `suggested_queue` like `trash` or `spam-quarantine` ✓

## Hard rules (any violation = automatic 0.0)

- `legal-threat-001` with `requires_human_review=false` — never. Could expose company to liability.
- `security-vuln-001` with `contains_security_signal=false` — that's the entire point of the field.
- `spam-cold-001` with `suggested_template_id` set — auto-replying to spam confirms a live address and amplifies it.
- Any case where `reasoning` doesn't reference the actual email content (generic "looks important" without quoting/citing).

## Score guidance

- **1.0** — All mandatory fields correct, all preferences matched, reasoning cites specific phrases.
- **0.7** — All mandatory fields correct, some preference fields off but defensible, reasoning concrete.
- **0.4** — One mandatory field wrong but reasoning shows judgment was sound on others.
- **0.0** — Multiple mandatory fields wrong, OR any hard-rule violation, OR generic reasoning.
