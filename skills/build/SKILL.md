---
name: build
description: Start or resume the slice loop — one command provisions the worktree, sandbox, binding and Phase-1 context, then the slice runs to close without interruption.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/harness *) Bash(git *) Bash(pytest *) Bash(python3 -m pytest *)
argument-hint: "<slice-id>"
---

# /harness:build $1

Start (or resume) the slice. This one command creates the isolated worktree
`.worktrees/$1` on branch `slice/$1`, provisions its sandboxed autonomy
profile, binds the slice, snapshots the G6 baseline, and emits the Phase-1
context — no prompts, no follow-up ceremony:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" start --slice $1`

If it refuses because a `depends_on` slice is still open, close that one
first — foundations exist so consumers can rely on them. Overriding needs a
recorded reason: `--force --justification "<why>"`.

Read the `injections` from that output — that is your context (shadows,
guidance, decision rows, durable memories). `acceptance_python` is the
interpreter for the acceptance tests. **From here on run every command —
harness, git, pytest — from the `worktree` path in that output.** Mixing
trees splits substrate state.

Loop discipline — in order:

1. **Work the red tests.** The slice's `acceptance` tests define done. Run
   them first; they must fail before you write implementation.
2. **Amend declarations before touching undeclared files.** If you need a
   file outside `predicted_files`, update the slice row in
   `.harness/backlog.jsonl` first — G3 findings must be reconciled before
   close-slice, and wandering is how context dies. (It is also why an
   undeclared edit is the one file operation that still prompts: declared
   work is auto-approved, wandering is not.)
3. **Log abandoned approaches.** Whenever you abandon an approach mid-slice,
   record it before moving on (mandatory, not optional):
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" memory write --slice $1 --kind attempt --content "<what>"
   --approach "<what you tried>" --outcome abandoned --why "<why>"`
4. **Session cycling, not compaction.** When context nears its limit:
   checkpoint at a Stop boundary, end the session, start fresh — `harness
   start --slice $1` resumes from substrate. If compaction fires, that is a
   defect signal in telemetry, not a convenience.

## Autonomous slice completion — do not stop for permission

A bound slice runs END TO END without human intervention: implement → green
→ review → fix → close. The gates are the guardrails and they are also the
permission layer: work inside the slice's declared scope is auto-approved by
the harness itself, so a prompt means you have wandered outside the
declaration — amend it rather than asking.

Command hygiene keeps it that way: chained commands auto-approve only when
EVERY segment is in the loop's surface, and command substitution `$(...)`
never auto-approves — run plain commands and use symbolic refs the engine
resolves (`close-slice --commit HEAD`), never `$(git rev-parse HEAD)`.

5. **When acceptance is green, immediately self-review**: run the review
   stack (`"${CLAUDE_PLUGIN_ROOT}/bin/harness" review --slice $1 --diff
   <diff-file>`), fix every blocking finding (each names its rule and fix),
   re-run until clean. Do not present findings to the user — resolve them.
   Record what your review concluded so it becomes substrate:
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" review --record-finding ...` (and
   `--park` anything you are genuinely uncertain about).
6. **Then close without asking**: commit and run close-slice. If it blocks,
   the reason names the mechanical fix (amend declaration, ack-drift,
   extract, override-with-justification) — apply it and re-close. Budget up
   to 3 fix-and-retry iterations per gate. One block is NOT yours to fix
   directly: `adr:001` (security-relevant slice) means dispatch the
   harness:reviewer agent with fresh context; IT records the fork verdict.
7. **The ONLY reasons to stop and involve the human**: a parked review
   finding (adjudication is theirs by design), an author-gate gap (substrate
   authoring is theirs), or the same gate blocking after 3 honest fix
   attempts (log an attempt memory first, then report the finding verbatim).
8. Close releases the binding; then `/harness:close-slice` finishes the
   merge with `harness merge-slice --slice $1` from the main tree.
