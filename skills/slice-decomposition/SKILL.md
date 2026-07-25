---
name: slice-decomposition
description: Sizing and declaring slices — the smallest unit of autonomous work. Use when decomposing a spec into tasks, sizing work, writing a backlog, "break this down", "split this feature", "how big should", declaring dependencies, estimating context cost, or when a slice keeps blowing its context window.
---

# Slice decomposition

A slice is the smallest unit of autonomous work: declared deps, red
acceptance tests, and a working set that fits one context window **by
construction** — not by hope. Schema (§5.6): `{id, spec, title, status,
declares_dep[], acceptance[], predicted_files[], context_cost_estimate,
depends_on[], worktree}`.

The spec bar: a slice description must be survivable by a junior engineer
with poor taste, no judgment, and no project context. If the slice needs
taste to interpret, the decomposition failed — push detail into decision
rows and acceptance tests instead.

Sizing rules:

- `context_cost_estimate` = declared deps run through the resolver's budget
  logic (`"${CLAUDE_PLUGIN_ROOT}/bin/harness" backlog` computes it). Anything above budget × 0.8 splits
  at decomposition time, not mid-build.
- COMPACTION_REACHED in telemetry = a slice that lied about its size; fix
  the decomposition, don't handle the compaction.

Declaration completeness:

- `declares_dep` is the full registry closure the work needs — G5 fails
  close-slice on any use outside it.
- `predicted_files` is every file expected to change — G3 findings on
  others must be reconciled before close.
- Foundations order first: config, telemetry, errors before their consumers
  (`depends_on` encodes this).
