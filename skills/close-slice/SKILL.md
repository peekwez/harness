---
name: close-slice
description: The close ceremony — acceptance green, uses/declares reconciled, drift acknowledged, commit + git note, memory compaction, registry flips, worktree merge.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/harness *) Bash(git *)
argument-hint: "<slice-id>"
---

# /harness:close-slice $1

Preconditions, in order — stop at the first failure and fix it:

Every step below runs FROM THE SLICE'S TREE — the worktree
(`.worktrees/$1`) if one exists, else the main tree. Running the ceremony
from the wrong tree closes against the wrong substrate.

1. Acceptance tests green (run the slice's `acceptance` paths).
2. Commit the work (slice = commit boundary), keeping harness state OUT of
   the feature commit — the ceremony commits its own substrate mutations:
   `git add -A -- . ':(exclude).harness' && git commit`
3. Run the ceremony (from the slice's tree):
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" close-slice --slice $1 --commit HEAD`
   (`--commit HEAD` on purpose — the engine resolves it to the sha; a
   `$(git rev-parse HEAD)` substitution can never be
   permission-auto-approved.)

The engine enforces: unit_complete gates pass (G4 freshness, G5 conformance,
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

4. Merge — one command, run from the MAIN tree:
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" merge-slice --slice $1`
   It merges `slice/$1`, regenerates + commits shadows from the merged
   sources (they never content-merge, `merge=ours`), re-runs the
   unit_complete gates (G4 is the parallel-agent safety net), and removes
   the worktree + branch. Parallel closes conflicting on `.harness/*.jsonl`
   resolve mechanically via the merge drivers (union for append-only logs,
   `harness merge-substrate` for keyed rows); a real keyed-row conflict is
   reported with the ids and left for you.
5. Show the user `"${CLAUDE_PLUGIN_ROOT}/bin/harness" status --json` deltas for this slice.
