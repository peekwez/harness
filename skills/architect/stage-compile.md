# Stage 4 — Compile protocol

Run the transform:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" compile --doc docs/architecture.md`

Then walk the human through what compiled where — prose is for
extrapolation; the compiled form is what gates read:

- ADR frontmatter `decision_table_rows` -> `.harness/decisions.jsonl`
- ADR frontmatter `abstractions` -> `.harness/registry.jsonl` skeleton
  (all `status: planned`; `replaces:` prunes merged-away planned entries)
- the working document's fenced ```` ```harness-decisions ```` /
  ```` ```harness-abstractions ```` pipe tables -> the SAME two files, rows
  landing as `origin: phase0` (ADR-002 D-013, schema §5.5). An id claimed by
  both an ADR and the doc is a hard error naming both sources; a malformed
  row names the document and the line. Fix the source and re-run
- ADR frontmatter `api_surface` -> `contracts/*.yaml` stubs for NEW
  contracts only. Existing contracts are authored and never rewritten:
  compile reports uncovered surface as `contract_gaps` (and author-gate
  blocks until the contract covers them or the ADR drops them)
- `[non-goal]` blocks -> `.harness/boundaries.jsonl` (G3 scope boundaries).
  boundaries.jsonl is REGENERATED on every run from ADRs + this doc — fix
  the source, recompile, stale boundaries disappear

Read out the compile report's `warnings` (pattern-less non-goals, coerced
kinds, contract gaps) to the human — each one is a silent-degradation
candidate the compiler refused to hide.
- `[non-goal]` blocks -> `.harness/boundaries.jsonl` (G3 scope boundaries)

Show the human the diff of each substrate file and confirm nothing compiled
surprisingly. If a decision row reads wrong, fix the ADR frontmatter and
re-run compile — never hand-edit the compiled row (it regenerates).

Exit criteria: compile ran clean; human has seen the output. Mark
`<!-- stage: 5 -->`.
