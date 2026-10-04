# Upgrading 0.9 to 0.10

harness 0.10 breaks 0.9. One command moves a repo to 0.10. This page says what that command changes, what it asks first, and what you check after it.

This page describes the 0.10 upgrade as the engine runs it. It lists each step that the engine has.

## Before you start

1. Commit or stash your work. A clean tree shows exactly what the upgrade changed. Don't edit files while the upgrade runs; edits made during the run land in the proposed commit.
2. Read the plan first. `harness upgrade --plugin --host claude --dry-run` prints only the host commands that it would run. `harness upgrade --dry-run` prints the step plan for the project. Use `--host codex` for Codex.
3. Update the plugin with the host command that the plugin dry run printed, for example `claude plugin update harness@harness-marketplace --scope user`.
4. Start a new session, so that the host loads the 0.10 skills, hooks and engine.
5. In the project, run the new engine: `harness upgrade --yes`.

From 0.9.x, use these two steps: update the plugin, then run the new engine. Do not use `harness upgrade --plugin` from 0.9. The 0.9 CLI has no `--yes`, and the 0.10 engine that it starts gets no terminal. That run skips each step that needs a confirmation. 0.9 then reports the incomplete upgrade as `command failed`, with the 0.10 report inside the message. The changes from that run stay. Run `harness upgrade --yes` with the new engine to finish.

From 0.10 on, `harness upgrade --plugin --host claude --yes` does both steps. `--plugin` updates the plugin through the host, then runs the new engine on the project. That run has no terminal, so without `--yes` each step that needs a confirmation is skipped.

## Run the upgrade

```bash
harness upgrade --dry-run
harness upgrade
harness upgrade --yes
```

- `harness upgrade --dry-run` prints the plan and changes nothing. It shows the schema change, each step with its pending changes, and each `check:` line. A step that waits for an earlier step shows its changes with the earlier step id.
- `harness upgrade` runs the plan. `harness init --migrate` does the same thing.
- A step that moves or deletes files asks first, with a `[y/N]` prompt.
- `--yes` accepts each prompt. Use it in CI or in a script.
- Without a terminal, a step that needs a confirmation is skipped. The report lists it with the fix `harness upgrade --yes`.
- Each run records the files that it changed in `.harness/cache/`. Until you commit them, the next run adds them to its commit proposal. So one commit holds the whole upgrade, and a second run before the commit proposes the same commit.

The upgrade runs in this order:

1. It migrates the schema: `.harness/schema_version` goes from 1 to 2.
2. It repairs old 0.8 and 0.9 overrides and graph records.
3. It runs each 0.10 step that has pending changes.
4. It installs the merge drivers, refreshes the vendored engine in `.harness/engine/` and refreshes a harness-written CI workflow.
5. It refreshes the harness commands in `.codex/hooks.json` and harness-written Claude settings. When this removes something from `.claude/settings.json` or changes `.codex/hooks.json`, upgrade keeps the old file in `.harness/cache/<name>.pre-0.10` and prints a `check:` line. `.claude/settings.local.json` keeps each permission and key that you added, and gets the 0.10 harness entries back. It is gitignored, so upgrade backs it up after any change and prints a `check:` line. Compare that backup with the new file. Remove each entry that you had dropped on purpose. Also remove each stale entry, such as an old forge host or project folder.
6. It refreshes the registry rows whose source did not change before the upgrade.
7. It validates the substrate.
8. It runs `harness doctor --substrate` and `harness verify`, each in a new process.
9. It proposes one commit.

If a step fails, the steps after it do not run. The steps before it keep their changes. If another part of the upgrade fails, the other parts still run. The registry refresh does not run after a failure. In each case the upgrade still prints its report. The report lists each problem in `failures`, with the step or the part that caused it and the fix. Fix the cause, then run `harness upgrade --yes` again.

Upgrade does not commit. Its only change to the git index is `git rm --cached` for `.harness/shadows/` and `.harness/memory/`, which stay out of git from now on. The commit proposal includes these deletions. Read `git status` and `git diff`, then commit.

Upgrade does not rewrite `AGENTS.md`, `CLAUDE.md`, the CI workflow or a Claude settings file that has no harness marker. It edits only the harness lines in two kinds of unmarked files: it adds and removes harness rules in `.gitattributes` and `.gitignore`, and it changes the harness commands in `.codex/hooks.json`. For an unmarked file that it does not edit, upgrade prints a `check:` line that says what to change by hand. A second run finds no pending step, and it prints the `check:` lines again.

Upgrade never overwrites a backup in `.harness/cache/`. When a backup with other content is already there, upgrade uses the next free name, for example `AGENTS.md.pre-0.10.2`. The cache is gitignored, so delete each backup when you are done with it.

## What upgrade changes

The upgrade has 19 steps. Each step runs only when it has pending changes, and a second run of a step changes nothing.

1. `w1.gitignore-cache` — Add .harness/cache/ to .gitignore.
2. `w1.untrack-shadows` — Untrack and delete .harness/shadows/. Shadows now live in the gitignored cache. This step asks first.
3. `w1.drop-registry-shadow` — Remove the shadow field from registry rows.
4. `w1.drop-resolver-config` — Remove resolver.budget_tokens, ranking and degrade from config.yaml.
5. `w2.slice-metrics` — Add .harness/slice-metrics.jsonl and its merge rule.
6. `w2.telemetry` — Convert old telemetry into slice-metrics rows, then delete it. This step asks first. An untracked telemetry file moves to `.harness/cache/legacy-telemetry/`.
7. `w2.config` — Remove retired config keys. Add review.ensemble and gates.exempt_paths.
8. `w2.skill-names` — Rename removed skills in harness-marked AGENTS.md, CLAUDE.md and the CI workflow.
9. `w2.contracts` — Report that harness no longer checks contracts/.
10. `w3.retire-durable-memory` — Export kept memory rows for review, then move .harness/memory/ to .harness/cache/legacy-memory/. This step asks first.
11. `w3.memory-git-lines` — Remove .harness/memory/ lines from .gitattributes and .gitignore.
12. `w3.shared-memory-index` — Create the shared memory index .claude/memory/shared/MEMORY.md.
13. `w3.claude-md-import` — Add the shared memory import to a harness CLAUDE.md.
14. `w4.glossary` — Create docs/glossary.md when it does not exist.
15. `w4.agents-md-ste80` — Add the STE-80 rule to a harness-marked AGENTS.md.
16. `w5.legacy-verification` — Mark each slice that is not closed legacy_verification: true.
17. `w6.agents-md-explore` — Add explore to the AGENTS.md workflow line.
18. `w8.agents-md` — Replace a harness-written AGENTS.md with the 0.10 template. This step asks first. The old file is kept at `.harness/cache/AGENTS.md.pre-0.10`, with the skill renames from `w2.skill-names` already applied.
19. `w8.stale-merge-rules` — Remove merge and ignore rules for files that 0.10 removed. A rule stays while its file still exists.

Upgrade moves the old memory to `.harness/cache/legacy-memory/`. It does not delete it. [Memory](memory.md#upgrading-from-09) explains the export and how to promote a fact.

These steps can print `check:` lines:

- `w2.config`: non-goals that no gate cites no longer block, and `gates.g3_mode: block` was removed.
- `w2.skill-names`: an unmarked file names a removed skill.
- `w2.contracts`: harness no longer checks `contracts/`. See the [Contracts recipe](extending/contracts.md).
- `w3.retire-durable-memory`: read the export and promote the facts that the team needs.
- `w3.shared-memory-index`: a `gates.extra` gate uses the id G10, which is now a builtin gate.
- `w3.claude-md-import`, `w4.agents-md-ste80` and `w6.agents-md-explore`: the file has no harness marker, the file is missing, or upgrade cannot find the place for the new line.
- `w8.agents-md`: the file has no harness marker, so upgrade leaves it alone. After a replacement, compare the backup with the new file and carry over local edits. Upgrade never creates a missing AGENTS.md.
- `w4.glossary`: `docs` is a file, so upgrade cannot create the glossary.
- `w5.legacy-verification`: a worktree holds its own backlog.

## Renamed and removed

Skills, from [the 0.10 design spec](https://github.com/peekwez/harness/blob/main/docs/internal/superpowers/specs/2026-10-02-harness-0.10-design.md#101-skills-18-to-11):

| Old skill | Its content is now in |
|---|---|
| `premortem` | `architect` |
| `contract-first` | `architect`, as a decision card |
| `decision-tables` | `adr-authoring` |
| `slice-decomposition` | `backlog` |
| `shadow-context` | `build` |
| `review-rubrics` | `review` |
| `adjudicate` | `harness`; adjudication runs in the main session through `/harness:harness` |
| `status` | `harness` |

Each line below names something that was removed or added in the engine:

- `harness run` was removed.
- `harness memory write`, `flush` and `compact` were removed.
- Gates G2, G4, G7 and G8 were removed. Their ids stay reserved, and old override edges stay as history.
- The config keys `resolver.budget_tokens`, `resolver.ranking`, `resolver.degrade`, `telemetry.compaction_is_defect` and the top-level `ensemble` were removed.
- `gates.g5_override` was removed, and `gates.g3_mode: block` was removed. G3 scope findings are advisory. A non-goal blocks only when a gate cites it.
- The upgrade added `review.ensemble: false` and `gates.exempt_paths`. When `contracts/` exists, upgrade adds it to `gates.exempt_paths`.

Run `ls skills/` in the plugin to confirm the skill list.

## Slices in flight

A slice that is not closed and has no `verifies` key started before 0.10. Upgrade marks it `legacy_verification: true`.

- Close skips the red-record and statement checks for a legacy slice. It still runs acceptance and regression.
- A legacy slice gives no red-record advisory.
- A slice that you add after the upgrade always carries `verifies`, so it gets the full checks.

Upgrade marks only the backlog of the main tree. For each worktree in `.worktrees/` that holds its own backlog, it prints a `check:` line. Run `harness upgrade` in that worktree. [Verification](verification.md#slices-from-before-010) gives the details.

## Check the result

Read the upgrade report. It is JSON with these parts:

- `status`: the result of the upgrade. The values are in the table below.
- `steps`: each step that ran, with its changes and its report lines.
- `advice`: each `check:` line, with the step id.
- `files`: the files that the upgrade added, modified and removed.
- `checks`: the result of `harness doctor --substrate` and `harness verify`.
- `failures`: each problem, with the step that caused it, or `none` if the problem was there before the upgrade, and the fix.
- `human_checks`: each thing that you must do by hand. This includes a skipped step, your uncommitted edits in a file that the upgrade changed, and staged changes from before the upgrade. It also names each backup of a refreshed file.
- `commit`: the one commit to run from the repo root. It is `null` unless the status is `upgraded`. `git commit` commits the whole index, so upgrade proposes no commit while the index holds staged changes that the upgrade did not make.
- `warnings`: skipped steps, kept files and registry rows that were not refreshed.
- `vendored_engine`, `workflow`, `claude` and `codex_adapter`: what upgrade did to each file that it refreshes.

| Status | Meaning |
|---|---|
| `upgraded` | The upgrade changed files and all checks passed. Run the `commit` command. |
| `already on 0.10` | The upgrade found nothing to change, and you committed its earlier changes. |
| `incomplete` | A step was skipped or still has changes. Run `harness upgrade --yes`. |
| `checks failed` | Doctor, verify or validation found a problem, or the index holds staged changes that the upgrade did not make. Do the fix in `failures` or in `human_checks`. |
| `failed` | A step or another part of the upgrade stopped with an error. Fix the cause, then run `harness upgrade --yes`. |

The command exits 0 for `upgraded`, `already on 0.10` and `--dry-run`. It exits 1 for `incomplete`, `checks failed` and `failed`, so CI stops. The JSON report prints in every case. Without a terminal, upgrade never prompts: it skips each step that needs confirmation and reports `incomplete`. Pass `--yes` to accept every prompt.

The upgrade already ran doctor and verify. Read `git status` before you commit:

```bash
git status
```

- Do each `check:` line. Upgrade does not edit `AGENTS.md`, `CLAUDE.md` or the CI workflow when the file has no harness marker.
- For Codex, approve the project hooks again with `/hooks`.
- Commit the changes in one commit. The `commit` command in the report uses the message `harness: upgrade to 0.10`.
