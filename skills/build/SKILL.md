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
context — no prompts, no follow-up ceremony. **Run it now, before anything
else** (a preflight cannot carry the slice argument, so this is your first
command):

```
"${CLAUDE_PLUGIN_ROOT}/bin/harness" start --slice $1
```

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
   them first; they must fail before you write implementation. Inside them,
   drive every unit with `superpowers:test-driven-development`: one failing
   unit test, watch it fail, minimal code to green, repeat.
2. **Root cause before retry.** On ANY red test or gate block, run
   `superpowers:systematic-debugging` and name the cause before you change
   anything. Never re-run a fix you cannot explain.
3. **Amend declarations before touching undeclared files.** If you need a
   file outside `predicted_files`, update the slice row in
   `.harness/backlog.jsonl` first — G3 findings must be reconciled before
   close-slice, and wandering is how context dies. (It is also why an
   undeclared edit is the one file operation that still prompts: declared
   work is auto-approved, wandering is not.)
4. **Log abandoned approaches.** Whenever you abandon an approach mid-slice,
   record it before moving on (mandatory, not optional):
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" memory write --slice $1 --kind attempt --content "<what>"
   --approach "<what you tried>" --outcome abandoned --why "<why>"`
5. **Session cycling, not compaction.** When context nears its limit:
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

6. **When acceptance is green, immediately self-review**: run the review
   stack (`"${CLAUDE_PLUGIN_ROOT}/bin/harness" review --slice $1 --diff
   <diff-file>`), fix every blocking finding (each names its rule and fix),
   re-run until clean. Do not present findings to the user — resolve them.
   Apply `superpowers:receiving-code-review` to every finding, whichever
   layer it came from: verify it against the substrate and the diff first,
   then fix it or rebut it with technical reasoning — never apply a finding
   blindly and never agree performatively.
   Record what your review concluded so it becomes substrate:
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" review --record-finding ...` (and
   `--park` anything you are genuinely uncertain about).
7. **Then close without asking**: run
   `superpowers:verification-before-completion` — run the acceptance command
   fresh and read its output — then commit and run close-slice. If it blocks,
   the reason names the mechanical fix (amend declaration, ack-drift,
   extract, override-with-justification); debug the block per step 2, apply
   the fix, and re-close. One block is NOT yours to fix
   directly: `adr:001` (security-relevant slice) means dispatch the
   harness:reviewer agent with fresh context; IT records the fork verdict.
8. **The ONLY reasons to stop and involve the human**: a parked review
   finding (adjudication is theirs by design), an author-gate gap (substrate
   authoring is theirs), or a gate still blocking after
   `superpowers:systematic-debugging` named a root cause you cannot fix
   inside this slice's declared scope (log an attempt memory first, then
   report the finding verbatim).
9. Close releases the binding. How the slice LANDS depends on
   `landing.mode` in `.harness/config.yaml`: in `local` mode (the default)
   `/harness:close-slice` finishes with `harness merge-slice --slice $1`
   from the main tree; in `pr` mode there is no merge-slice — the close
   itself pushed `slice/$1` and opened the PR, and that PR is the landing
   (`merge-slice` refuses). In pr mode the loop may push its own branch and
   drive `gh pr create|view|checks|status` without asking; every other
   remote command still stops for a human.

## Composing with superpowers

`AGENTS.md` carries the full precedence rule (ADR-002, D-014). The three that
bite inside a bound slice:

- `superpowers:using-git-worktrees`: `harness start` already provisioned
  `.worktrees/$1` — detect it and work there; never create a second worktree.
- `superpowers:finishing-a-development-branch`: not used here. `close-slice`
  is the finish and `merge-slice` (or, in `landing.mode: pr`, the pull
  request close-slice opened) is the landing — no menu.
- `superpowers:subagent-driven-development`: its stop-for-side-effects rule
  does not apply. The sandbox and the gates are the permission layer.
