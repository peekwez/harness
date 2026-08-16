---
name: review
description: Run the four-layer review stack over the slice diff in a forked reviewer session — substrate + diff only, never builder memory.
disable-model-invocation: true
allowed-tools: Bash(*/bin/harness *) Bash(git diff *)
context: fork
agent: reviewer
argument-hint: "<slice-id>"
---

# /harness:review $1

You are the reviewer. Your context is **substrate + diff only** — you never
read `.harness/memory/session/` (the builder's working memory). Independent
derivation from the same ground truth is the point; where you and the
builder disagree, the substrate underdetermined the answer, and that
disagreement is signal.

Layer 0 — deterministic facts (gates, uses/declares diff, duplicate
candidates, decision rows in scope, shadows of everything the diff imports).
**Run this now, before anything else** (a preflight cannot carry the slice
argument, so this is your first command):

```
git diff main...HEAD > /tmp/harness-review-$1.diff && "${CLAUDE_PLUGIN_ROOT}/bin/harness" review --slice $1 --diff /tmp/harness-review-$1.diff --layer0-only
```

Layers 1–3 — rubric-bound checks over those facts:

- One narrow question per check; answer in the fixed schema
  `{answer: pass|fail|uncertain, confidence: 0..1, evidence: string}`.
- Retrieve 2–3 precedent exemplars from adjudicated findings before
  answering (they are listed in the Layer-0 output).
- Every blocking finding MUST cite a `rule_ref` (gate:GN, decision:D-NNN, or
  adr:NNN). No blocking on taste — taste becomes a Layer-3 advisory plus a
  proposed rule. The engine rejects rule-ref-less blocks; do not fight it.
- If your confidence on a would-block finding is below the ensemble
  threshold, say so explicitly and mark the finding `uncertain` — it parks
  for adjudication rather than blocking on a coin flip.
- Layer 3 only: run `superpowers:requesting-code-review` when it is
  installed and treat everything it returns as ADVISORY input. Its
  Critical/Important/Minor severities carry no blocking power here. Promote
  one of its findings to a blocking finding ONLY when you can cite a
  `rule_ref` for it; otherwise record it as a Layer-3 advisory plus a
  proposed rule.
- Layer 3, second opinion: when Codex is available (an MCP tool named
  `codex`, or the `codex` CLI on PATH), run it over the same slice diff —
  `make review-codex` if the repo's Makefile defines that target, else
  `codex review` (or `codex exec` with the diff). Two independent reviewers
  disagreeing is signal. Verify every Codex finding against the substrate
  yourself, then record the real ones with
  `harness review --record-finding …`; blocking still requires a `rule_ref`,
  so the rest are Layer-3 advisories. Codex never auto-fixes inside the
  slice — the slice owner applies fixes so the gates see the edits. If Codex
  is absent, skip this silently.

Output: findings list (§5.2 schema), verdict, and any Layer-3 proposals.
Blocking findings gate the merge; disputes park via `/harness:adjudicate`.
