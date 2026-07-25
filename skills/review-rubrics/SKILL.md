---
name: review-rubrics
description: The four-layer review stack and the findings contract. Use when reviewing code or diffs, writing review findings, "review this", assessing a PR, blocking a merge, disputing a finding, review confidence, ensembles, or when tempted to block on style or taste.
---

# Review rubrics

The stack (C7):

- **Layer 0 — deterministic facts.** Gate outputs, uses/declares diff,
  duplicate candidates, decision rows in scope, shadows of the diff's
  imports. Assembled by `"${CLAUDE_PLUGIN_ROOT}/bin/harness" review --layer0-only`; no judgment.
- **Layer 1 — rubric-bound checks.** One narrow question per check. Fixed
  output schema: `{answer: pass|fail|uncertain, confidence, evidence}`.
  Retrieve 2–3 precedent exemplars from adjudicated findings first.
- **Layer 2 — ensemble.** Only when confidence < threshold AND the finding
  would block: sample 3×. Splits escalate as `uncertain` and park — never
  average a coin flip into a verdict.
- **Layer 3 — holistic, advisory-only.** Its findings can only spawn
  proposals (new decision row / ADR / gate). It cannot block anything.

The findings contract (§5.2): every blocking finding cites a `rule_ref` —
gate:GN, decision:D-NNN, or adr:NNN. The engine rejects rule-ref-less
blocks. **No blocking on taste**: if something offends your sensibilities
but no rule covers it, that is a Layer-3 advisory plus a proposed rule, and
next slice it can block legitimately.

Reviewer hygiene: substrate + diff only; never the builder's session memory.
Golden-set replay (`"${CLAUDE_PLUGIN_ROOT}/bin/harness" review --replay`) re-runs stored diff+verdict
pairs whenever rubrics change — reviewer changes get reviewed too.
