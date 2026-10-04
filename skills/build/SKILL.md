---
name: build
description: Start or resume the slice loop — one command provisions the worktree, sandbox, binding and Phase-1 context, then the slice runs to close without interruption. Also covers loading module context: read a module's shadow before its source.
allowed-tools: Bash(*/bin/harness *) Bash(git *) Bash(pytest *) Bash(python3 -m pytest *)
argument-hint: "<slice-id>"
---

Run this workflow for work the user has requested. In Codex, resolve the
plugin root from this skill path and invoke `python3 <plugin-root>/bin/harness`
with an explicit project `--root`; the `!` substitutions and
`${CLAUDE_PLUGIN_ROOT}` examples below use Claude Code syntax.


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
guidance, decision rows, shared memory). `acceptance_python` is the
interpreter for the acceptance tests. **From here on run every command —
harness, git, pytest — from the `worktree` path in that output.** Mixing
trees splits substrate state.

Module context: read another module's shadow before its source. A built
module's shadow replaces the ADR guidance listed in its `supersedes_guidance`.

Loop discipline — in order:

1. **Read the red record.** `harness start` runs the slice's acceptance suite once.
   It writes `.harness/verification/$1.json` and prints `red_record`.
   - `red: true`: the tests fail. Continue.
   - `green_at_start: true`: the tests pass before you write code. Make each test fail for the missing behaviour. Then run `"${CLAUDE_PLUGIN_ROOT}/bin/harness" slice --slice $1` to record red again.
   - A pure refactor stays green. Record the reason:
     `"${CLAUDE_PLUGIN_ROOT}/bin/harness" gates override --slice $1 --target verification:green-at-start --rule-ref verify:red-record --justification "<why>"`.
   - `runner_error`: the suite did not run. A spawn failure, a pytest usage error or a timeout is a runner error, not red. Fix the test command, then bind again.
   - A corrupt record blocks bind and close. Repair or delete it, then bind again.

   **Work the red tests.** The slice's `acceptance` tests define done. Inside them,
   drive every unit with `superpowers:test-driven-development`: one failing
   unit test, watch it fail, minimal code to green, repeat.
   Use `harness:verification` to map the actual ACs to implementation and
   decisive checks before coding. A failing environment is not a feature
   regression; a green mock-call assertion is not proof of the promised
   behavior. Keep the map in the existing slice/review record and expose
   observable outputs or narrow test seams where verification is difficult.
   For state changes, define sample inputs and expected outcomes before running
   the app. Build an app-only seed driver and independent read-only Python probes
   of actual DB/cache/blob effects, with app-produced write fingerprints; follow
   `verification/integrity.md`. Direct storage seeding cannot prove app behavior.
   Follow the feature's verification design (`verification/design.md`), including
   concrete happy and relevant edge/failure/recovery cases. Fill missing methods
   before implementing. Collect live app and worker block and branch coverage
   for each scenario. Join it to trace IDs and to independently checked
   outcomes. Aggregate test or probe coverage cannot prove which app path
   produced a result.
2. **Root cause before retry.** On ANY red test or gate block, run
   `superpowers:systematic-debugging` and name the cause before you change
   anything. Never re-run a fix you cannot explain.
3. **Amend declarations before touching undeclared files.** If you need a
   file outside `predicted_files`, add it to `predicted_files` on the
   slice row in `.harness/backlog.jsonl` first. G3 reports an undeclared file as an advisory finding and
   close lists it under `scope_advisory`. Declared work is auto-approved;
   an undeclared edit still prompts.
4. **Record abandoned approaches.** Record abandoned approaches in your personal
   memory. Never write `.claude/memory/shared/`; a human promotes facts there.
5. **Session cycling, not compaction.** When context nears its limit:
   checkpoint at a Stop boundary, end the session, start fresh — `harness
   start --slice $1` resumes from substrate. If compaction fires, a compaction
   is counted in slice metrics as a sizing hint, not a convenience.

## Autonomous slice completion — do not stop for permission

A bound slice runs END TO END without human intervention: implement → green
→ review → fix → close. The gates are the guardrails and the permission layer.
The harness auto-approves work inside the declared scope of the slice. A
prompt means that you went outside the declaration: amend it, do not ask.

Command hygiene keeps it that way. A chained command auto-approves only when
EVERY segment is in the loop's surface. Command substitution `$(...)` never
auto-approves. Run plain commands, and use symbolic refs that the engine
resolves: `close-slice --commit HEAD`, never `$(git rev-parse HEAD)`.

6. **When acceptance is green, immediately self-review.**
   1. Run the review stack: `"${CLAUDE_PLUGIN_ROOT}/bin/harness" review --slice $1 --diff <diff-file>`.
   2. Fix every blocking finding. Each one names its rule and fix.
   3. Re-run until clean. Do not present findings to the user; resolve them.

   Apply `superpowers:receiving-code-review` to every finding from every
   layer. First verify it against the substrate and the diff. Then fix it, or
   rebut it with technical reasoning. Never apply a finding blindly, and never
   agree performatively.
   Record what your review concluded so it becomes substrate:
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" review --record-finding ...` (and
   `--park` anything you are genuinely uncertain about).
   The reviewer applies `harness:verification` to the ACs and current evidence.
   For a gap, reproduce the expected/actual mismatch, distinguish product/test/
   environment causes, fix the cause and rerun affected checks. Do not weaken
   criteria to satisfy a test. A required unrun or inconclusive check leaves
   completion unverified even when other checks are green.
7. **Then close without asking**: run
   `superpowers:verification-before-completion` — run the acceptance command
   fresh and read its output — then commit and run close-slice. If it blocks,
   the reason names the mechanical fix (amend declaration, ack-drift,
   extract, override-with-justification); debug the block per step 2, apply
   the fix, and re-close. One block is NOT yours to fix
   directly: `adr:001` (security-relevant slice) means dispatch the
   harness:reviewer agent with fresh context; IT records the fork verdict.
8. **Stop and involve the human only for these reasons:**
   1. A parked review finding. Adjudication is theirs by design.
   2. An author-gate gap. Substrate authoring is theirs.
   3. A required verification check that is still unavailable after diagnosis and authorized in-scope repair. Report NOT VERIFIED with the exact missing prerequisite and next action.
   4. A gate that still blocks after `superpowers:systematic-debugging` named a root cause you cannot fix inside the declared scope of the slice. Note it in personal memory first. Then report the finding verbatim.
9. Close releases the binding. `landing.mode` in `.harness/config.yaml` decides how the slice LANDS:
   1. `local` (the default): `/harness:close-slice` finishes with `harness merge-slice --slice $1` from the main tree.
   2. `pr`: the close itself pushed `slice/$1` and opened the PR. That PR is the landing, and `merge-slice` refuses.

   In pr mode the loop may push its own branch and drive `gh pr create|view|checks|status` without asking. Every other remote command still stops for a human.

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
