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

- `context_cost_estimate` comes from `"${CLAUDE_PLUGIN_ROOT}/bin/harness" backlog`.
  Split any slice that `backlog` flags as oversized at decomposition time,
  not mid-build.
- A COMPACTION_REACHED count in the slice's `.harness/slice-metrics.jsonl`
  row means the slice was too big; fix the decomposition, don't handle the
  compaction.

Declaration completeness:

- `declares_dep` is the full registry closure the work needs — close-slice
  fails on any use outside it (uses within declares).
- `predicted_files` is every file expected to change — G3 reports other
  files as advisory findings, and close lists them under `scope_advisory`.
- Foundations order first: config, telemetry, errors before their consumers
  (`depends_on` encodes this).
