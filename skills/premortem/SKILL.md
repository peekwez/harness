---
name: premortem
description: Failure-mode elicitation and the silent-degradation checklist. Use during red-team passes, risk review, "what could go wrong", "premortem", hunting silent failures, missing-artifact behavior, no-op bugs, fallback paths, or reviewing error handling of any loader/resolver/config code.
---

# Premortem

Run the imagined-failure exercise: "it's six months later and this design
failed — write the incident report." Then work the checklists.

**The md-file-bug class** (highest priority — hunt silent degradation).
The defining defect: a required file goes missing and the system *no-ops
instead of erroring*. For every artifact the design reads, ask:

- What happens when it's missing? (Correct: hard error naming the artifact.
  Defect: empty default, skipped step, cached stale copy.)
- What happens when it's present but stale? Who checks the hash?
- What happens when it's present but malformed? Parse errors must fail
  loud with the path and line, not fall back.
- Is there a manifest asserting it exists — validated against the **built
  artifact**, not just the source tree? (Files lost in packaging are the
  canonical instance of this bug.)
- Grep the design for "fallback", "default", "or empty", "if exists" —
  each one is either justified in writing or a latent no-op bug.

**Standard failure families** to elicit after the silent-degradation pass:
scale cliffs (what breaks at 10×/100×), concurrency (two writers, one
file), partial failure (step 3 of 5 dies — what state remains), permission
and secret expiry, clock and timezone assumptions, retry storms,
schema-version skew between components.

Every risk found resolves into a decision or an explicit `[accepted-risk]`
block — a risk that's merely "noted" is a defect in the premortem itself.
