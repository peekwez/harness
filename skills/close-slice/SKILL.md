---
name: close-slice
description: The close ceremony — acceptance green, uses/declares reconciled, drift acknowledged, commit + git note, memory compaction, registry flips, worktree merge.
disable-model-invocation: true
allowed-tools: Bash(*/bin/harness *) Bash(git *)
argument-hint: "<slice-id>"
---

# /harness:close-slice $1

Preconditions, in order — stop at the first failure and fix it:

Every step below runs FROM THE SLICE'S TREE — the worktree
(`.worktrees/$1`) if one exists, else the main tree. Running the ceremony
from the wrong tree closes against the wrong substrate.

0. Run `superpowers:verification-before-completion` first: run the
   acceptance command fresh and read its output. Evidence before assertions.
1. Acceptance tests green (run the slice's `acceptance` paths).
2. Commit the work (slice = commit boundary), keeping harness state OUT of
   the feature commit — the ceremony commits its own substrate mutations:
   `git add -A -- . ':(exclude).harness' && git commit`
3. Run the ceremony (from the slice's tree):
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" close-slice --slice $1 --commit HEAD`
   (`--commit HEAD` on purpose — the engine resolves it to the sha; a
   `$(git rev-parse HEAD)` substitution can never be
   permission-auto-approved. `--commit` is REQUIRED in a git repo: the
   slice's provenance note is written onto that commit, and a close that
   records no provenance is not a close.)

The engine enforces: the review stack runs over this slice's own diff and
its verdict is recorded (blocking findings — engine-side or reviewer-agent
recorded — stop the close, and nothing may still be parked for this slice),
unit_complete gates pass (G4 freshness, G5 conformance,
G6 drift acknowledged, G7 derivation integrity), uses ⊆ declares reconciled,
and — for slices resolving security-marked decision rows — an independent
forked reviewer's pass verdict (ADR-001; dispatch the harness:reviewer
agent, which records `harness review --record-fork`).
Documented contract: touched files MISSING a shadow get one extracted by the
ceremony itself (`shadows_extracted` in the output) — derived artifacts are
the engine's job; G7 still blocks anything stale or hand-edited.
If it reports a block, the fix is named in the finding — G6 drift needs
`"${CLAUDE_PLUGIN_ROOT}/bin/harness" gates ack-drift`, G5 needs a declaration amendment or a recorded
override with justification.

On success the engine has: written the git note (slice, modules touched,
registry used, memory ids), flipped registry statuses planned->built,
compacted session memory to durable, marked the slice closed, and committed
those substrate mutations itself (`substrate_commit` in the output — no
manual follow-up commit needed). You finish the mechanical tail:

4. Land it. Which command depends on `landing.mode` in
   `.harness/config.yaml` (ADR-002 / D-009) — check it before you reach for
   `merge-slice`.

**`landing.mode: pr`** — there is no merge step. The close you just ran WAS
the landing: it pushed `slice/$1` to `landing.remote` and opened the pull
request (`landed`, `pr_url` in the output; the PR title/body carry the
slice's `linear` id when the row has one). `merge-slice` refuses here with
`LANDING_MODE_PR` — merging locally is how a protected base branch gets
bypassed. If the output says `"landed": false`, the close is recorded but the
PR is not: the row now carries `landed_via: pending` + `landing_error` and
`harness verify` reports `LANDING_PENDING`. Read `error`, fix the cause
(wrong branch? no remote? `gh` not authenticated? — authentication is the
human's, not yours), then re-land from the slice's worktree with one
command, which re-runs ONLY the push and the PR:
`"${CLAUDE_PLUGIN_ROOT}/bin/harness" land --slice $1`
Do NOT re-run close-slice — the slice is already closed. Then watch the PR:
`gh pr checks`. After it merges, provenance survives the squash by
tree hash; if `harness verify` ever reports an orphan, repair it with
`"${CLAUDE_PLUGIN_ROOT}/bin/harness" graph note --repoint $1 <merged-sha>`.

**`landing.mode: local`** (the default) — merge, one command, run from the
MAIN tree:
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" merge-slice --slice $1`
   It merges `slice/$1`, regenerates + commits shadows from the merged
   sources (they never content-merge, `merge=ours`), re-runs the
   unit_complete gates (G4 is the parallel-agent safety net), and removes
   the worktree + branch. Parallel closes conflicting on `.harness/*.jsonl`
   resolve mechanically via the merge drivers (union for append-only logs,
   `harness merge-substrate` for keyed rows); a real keyed-row conflict is
   reported with the ids and left for you.
5. Show the user `"${CLAUDE_PLUGIN_ROOT}/bin/harness" status --json` deltas for this slice.
