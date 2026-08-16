---
name: backlog
description: Turn the spec and ADRs into dependency-ordered slices with declared deps, red acceptance-test stubs, and context-cost estimates; oversized slices are split at decomposition time.
disable-model-invocation: true
allowed-tools: Bash(*/bin/harness *)
---

# /harness:backlog

Precondition — the author-gate must have passed:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" author-gate --doc docs/architecture.md`

If it reports gaps, stop and send the user back to `/harness:architect`.

Generate slices via the CLI — never hand-edit `.harness/backlog.jsonl`
(hand-edited rows are the historical EDIT-ME defect source):

`"${CLAUDE_PLUGIN_ROOT}/bin/harness" backlog add --id <slice-id> --title "…"
--spec <spec> --declares <registry-ids…> --predicts <files…>
--acceptance tests/slices/NNN_x.py --depends <slice-ids…>`

It validates ids and declared deps against the registry, dedupes predicted
files, and computes the context-cost estimate. Row semantics (schema per
the slice-decomposition skill):

- `declares_dep`: complete registry closure the slice needs. Foundations
  first — the config/telemetry/errors sequence orders before consumers.
- `acceptance`: red acceptance-test stubs under `tests/slices/NNN_*.py`.
  Write the stubs (failing tests) as part of this skill.
- `predicted_files`: every file the slice is expected to touch.
- `depends_on`: slice ordering derived from the registry dependency graph.

Then compute cost estimates and split anything oversized (estimate >
resolver budget × 0.8):

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" backlog --split`

Present the resulting decomposition graph (slices, deps, estimates) to the
human for approval **once, at the graph level** — not slice by slice. Record
their approval in the working document. Next: `/harness:build`.
