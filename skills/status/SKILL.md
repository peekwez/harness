---
name: status
description: Render harness telemetry — slice progress, gate block rates, override and reversal rates, compaction defects, parks per slice.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/harness *)
---

# /harness:status

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" status --json`

Repo health (schemas, stale bindings/worktrees, unadjudicated parks, missing
provenance notes, unflushed telemetry) is a separate, complementary view:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" doctor --substrate`

Render the JSON as a short dashboard and interpret it — this is the view
that proves human withdrawal is safe:

- **Slice progress**: planned / in_progress / parked / closed counts.
- **G2-block rate**: the Phase-1 completeness signal. Rising rate = the
  resolver or slice declarations are missing context; fix declarations, not
  the agent.
- **Override & reversal rates per rule**: rules with ~zero variance and zero
  reversals are Layer-0 promotion candidates (name them).
- **COMPACTION_REACHED count**: a decomposition-quality defect signal —
  each one means a slice didn't fit its window; point at the slice.
- **Parks per slice**: should trend down; the same question must never park
  twice (if it does, the adjudication failed to write substrate — flag it).
