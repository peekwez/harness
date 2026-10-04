---
name: close-slice
description: The close ceremony — acceptance green, shared memory promotion offer, uses/declares reconciled, drift acknowledged, commit + git note, registry flips, worktree merge.
allowed-tools: Bash(*/bin/harness *) Bash(git *)
argument-hint: "<slice-id>"
---

Run this workflow for work the user has requested. In Codex, resolve the
plugin root from this skill path and invoke `python3 <plugin-root>/bin/harness`
with an explicit project `--root`; the `!` substitutions and
`${CLAUDE_PLUGIN_ROOT}` examples below use Claude Code syntax.


# /harness:close-slice $1

Preconditions, in order — stop at the first failure and fix it:

Every step below runs FROM THE SLICE'S TREE — the worktree
(`.worktrees/$1`) if one exists, else the main tree. Running the ceremony
from the wrong tree closes against the wrong substrate.

0. Run `superpowers:verification-before-completion` first: run the
   acceptance command fresh and read its output. Evidence before assertions.
   Apply `harness:verification` to the review's AC evidence map. Every required
   criterion/check needs current PASS evidence; skipped, disabled, inconclusive
   or stale checks are not done. Resolve gaps within authorized scope before
   continuing. This is a completion-evidence obligation, not a new engine gate.
   State-changing ACs also need the pre-action case, app receipts and independent
   read-only DB/cache/blob probe results. Directly seeded outputs and forged
   write fingerprints are invalid evidence, even when the tests read them back.
   Runtime ACs also require scenario-attributed production block/branch coverage
   linked to the same app action and result, including the design's required
   edge/failure/recovery cases. Missing instrumentation remains NOT VERIFIED.
1. Acceptance tests green (run the slice's `acceptance` paths).
2. Offer personal memory for promotion, after review and before the commit.
   Run:
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" memory changed --slice $1`
   The output lists the personal memory files that changed since the slice
   started (`files`), the folder it read (`dir`) and whether that folder
   exists (`dir_exists`). Harness finds the folder in this order:
   1. `autoMemoryDirectory` in `.claude/settings.local.json`, then in
      `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json`).
   2. Else `~/.claude/projects/<slug>/memory/`. The slug is the main repo
      path with each character that is not a letter or digit changed to `-`.
      All worktrees of the repo share this folder.
   If `dir_exists` is false, tell the human that harness found no personal
   memory folder at `dir`, then go to the next step.
   If `files` is empty, go to the next step.
   Otherwise show the list and ask the human: "Promote any to shared?"
   For each file the human picks, run:
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" memory promote <file>`
   The host asks the human to approve each run. Never write
   `.claude/memory/shared/` yourself. Gate G10 blocks it.
   Promote writes `.claude/memory/shared/<fact>.md` and updates
   `.claude/memory/shared/MEMORY.md` in this tree. The next step commits
   them with the slice, so they ride the slice commit, the PR or the merge.
3. Commit the work (slice = commit boundary), keeping harness state OUT of
   the feature commit — the ceremony commits its own substrate mutations:
   `git add -A -- . ':(exclude).harness' && git commit`
   This commit includes any promoted shared memory files.
4. Run the ceremony (from the slice's tree):
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" close-slice --slice $1 --commit HEAD`
   (`--commit HEAD` on purpose — the engine resolves it to the sha; a
   `$(git rev-parse HEAD)` substitution can never be
   permission-auto-approved. `--commit` is REQUIRED in a git repo: the
   slice's provenance note is written onto that commit, and a close that
   records no provenance is not a close.)

The engine enforces these checks:

- The acceptance tests pass. The cumulative regression suite passes.
- The review stack runs over this slice's own diff and records its verdict.
  A blocking finding stops the close. That finding can come from the engine
  or from a reviewer agent. Nothing may stay parked for this slice.
- The unit_complete gates pass: G1 manifest, G6 drift acknowledged, and
  every `gates.extra` gate that runs at unit_complete. A touched file inside
  a non-goal that a `gates.extra` gate cites blocks (G3).
  Other G3 scope findings and G5 conformance advise; close lists undeclared
  files under `scope_advisory`.
- Reconciliation passes: uses ⊆ declares.
- A slice that resolves security-marked decision rows needs a pass verdict
  from an independent forked reviewer (ADR-001). Dispatch the
  harness:reviewer agent. It records `harness review --record-fork`.

Shadows are a gitignored cache under `.harness/cache/`. The engine builds a
shadow when it needs one. The close commits no shadows.
If it reports a block, the fix is named in the finding — G6 drift needs
`"${CLAUDE_PLUGIN_ROOT}/bin/harness" gates ack-drift`, a use outside `declares_dep` needs a declaration
amendment or a recorded override with justification.

On success the engine has: written the git note (slice, modules touched,
registry used), flipped registry statuses planned->built,
marked the slice closed, and committed
those substrate mutations itself (`substrate_commit` in the output — no
manual follow-up commit needed). You finish the mechanical tail:

5. Land it. Which command depends on `landing.mode` in
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
tree hash; if `harness verify` ever reports `ORPHANED_NOTE` or
`MISSING_PROVENANCE_NOTE`, repair it with
`"${CLAUDE_PLUGIN_ROOT}/bin/harness" graph note --repoint $1 <merged-sha>`.

If the base branch moves while the PR is open, update the branch LOCALLY
from the slice's worktree (`git fetch <remote> && git merge <remote>/<base>`)
— never GitHub's "Update branch" button, whose server-side merge cannot run
the repo's `harness-substrate` merge driver and conflicts inside
`.harness/backlog.jsonl`. Then re-land:
`"${CLAUDE_PLUGIN_ROOT}/bin/harness" land --slice $1`
It is idempotent: it re-notes HEAD (the update gave it a tree no recorded
note keyed, which would otherwise be `MISSING_PROVENANCE_NOTE` after the
squash), pushes, and skips the PR command because the row already has one.

**`landing.mode: local`** (the default) — merge, one command, run from the
MAIN tree:
   `"${CLAUDE_PLUGIN_ROOT}/bin/harness" merge-slice --slice $1`
   It merges `slice/$1` and runs the accumulated acceptance suite and the
   unit_complete gates on the merged tree. Then it commits the substrate and
   removes the worktree + branch. It commits no shadows: they are a
   gitignored cache. Parallel closes conflicting on `.harness/*.jsonl`
   resolve mechanically via the merge drivers (union for append-only logs,
   `harness merge-substrate` for keyed rows); a real keyed-row conflict is
   reported with the ids and left for you.
6. Show the user this slice's row in `.harness/slice-metrics.jsonl` (close wrote it): gates fired, overrides, compactions, parks and the maximum injection size.
