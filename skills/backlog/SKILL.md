---
name: backlog
description: Turn the spec and ADRs into dependency-ordered slices with declared deps, red acceptance-test stubs, and context-cost estimates; oversized slices receive decomposition proposals for independently scoped children. Also for sizing and declaring slices: "break this down", "split this feature", "how big should", declaring dependencies, estimating context cost.
allowed-tools: Bash(*/bin/harness *)
---

Run this workflow for work the user has requested. In Codex, resolve the
plugin root from this skill path and invoke `python3 <plugin-root>/bin/harness`
with an explicit project `--root`; the `!` substitutions and
`${CLAUDE_PLUGIN_ROOT}` examples below use Claude Code syntax.


# /harness:backlog

Precondition — the author-gate must have passed:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" author-gate --report --doc docs/architecture.md`

If the JSON above has `"passed": false`, stop and send the user back to
`/harness:architect` with the gap list.

Generate slices via the CLI — never hand-edit `.harness/backlog.jsonl`
(hand-edited rows are the historical EDIT-ME defect source):

`"${CLAUDE_PLUGIN_ROOT}/bin/harness" backlog add --id <slice-id> --title "…"
--spec <spec> --declares <registry-ids…> --predicts <files…>
--acceptance tests/slices/NNN_x.py --depends <slice-ids…>
--verifies <V-ids,…>`

It validates ids and declared deps against the registry, dedupes predicted
files, and computes the context-cost estimate. Row semantics (schema and
sizing rules in `slice-decomposition.md`):

- `declares_dep`: complete registry closure the slice needs. Foundations
  first — the config/telemetry/errors sequence orders before consumers.
- `acceptance`: red acceptance-test stubs under `tests/slices/NNN_*.py`.
  Write the stubs (failing tests) as part of this skill.
  Carry the design's happy/edge/failure/recovery matrix into slice scope via
  `verification/design.md`; fill undefined required methods before implementation.
  Include real app instrumentation, scenario coverage/trace attribution, test
  seams and environment/probe dependencies, not only unit-test files.
  Use `harness:verification` to turn each actual AC into an observable result
  and a check that would detect it being broken. Name needed fixtures/services
  and any required integration/browser check in the existing slice spec.
  For state changes, put four things in scope: app-only sample seeding,
  predeclared expected effects, app write-fingerprint observability and
  read-only Python storage probes. A direct storage fixture never proves an app write.
  Stubs are starting points; they must become behavior assertions before done.
  Put a link comment above each red test, in the test's comment syntax:
  `# verifies: V-orders-3  kills: <the bug this test catches>`.
  Close blocks when a statement in `verifies` has no linked test, or a link has no `kills:` text.
- `verifies`: the statement IDs this slice proves, from `.harness/verify.jsonl`.
  Run `harness compile` first. `backlog add` refuses an ID that is not there.
  Repeat `--verifies` or separate IDs with commas.
- `predicted_files`: every file the slice is expected to touch.
- `depends_on`: slice ordering derived from the registry dependency graph.

Then compute cost estimates and request proposals for oversized slices
(estimate > resolver budget × 0.8):

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" backlog --split`

Read `unowned_statements` in the same output. Give each statement to one slice with
`--verifies`. If no slice proves a statement, tell the human why.

Read `split_proposals` and `split_refused`. For each proposal, author separate
acceptance tests and predicted files for every child, create the children
through the backlog CLI, and explicitly reconcile parent/dependent rows. A
proposal never creates executable children by copying the full parent scope.

Present the resulting decomposition graph (slices, deps, estimates) to the
human for approval **once, at the graph level** — not slice by slice. Record
their approval in the working document. Next: `/harness:build`.
