# Status

Run these from the project. In Codex, call
`python3 <plugin-root>/bin/harness --root <project> <command>`.

    "${CLAUDE_PLUGIN_ROOT}/bin/harness" status --json
    "${CLAUDE_PLUGIN_ROOT}/bin/harness" doctor --substrate

`status` reads the committed slice summaries in `.harness/slice-metrics.jsonl`.
Close writes one row per slice. Event rows stay in the local file
`.harness/cache/events.jsonl` and never reach git.

Render the JSON as a short dashboard:

1. **Slice progress:** the planned, in_progress, parked and closed counts in `slices`.
2. **Totals:** gates fired and overrides per rule, compactions, parks, and the
   largest injection size, from `totals`.
3. **Per slice:** one line for each row in `summaries`. With `--since`, only
   slices closed at or after that date count.
4. **Parks per slice:** `parks_per_slice` joins closed-slice parks with the
   open adjudication queue.
5. **Context cost:** show the always-on cost block that `status` prints.

Rules:

- Telemetry is advisory. It does not prove correctness or authorize a change.
- Report compactions as a count. A compaction alone is not a defect.
- Do not promote or retire a rule from these counts alone. Review the rule
  and its history first.

`doctor --substrate` is the health view: schemas, stale bindings and
worktrees, open parks, missing provenance notes, and source files that no
extractor enforces (`unshadowed_files`).
