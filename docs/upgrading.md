# Upgrading 0.9 to 0.10

harness 0.10 breaks 0.9. One command moves a repo to 0.10. This page says what that command changes, what it asks first, and what you check after it.

This page describes the upgrade as the engine runs it today. W8 adds more: a final `harness doctor` and `harness verify` run, a proposed commit command, an `AGENTS.md` refresh and an "already on 0.10" report. W8 updates this page when it lands them.

## Before you start

1. Commit or stash your work. A clean tree shows exactly what the upgrade changed.
2. Read the plan first: `harness upgrade --plugin --host claude --dry-run`. Use `--host codex` for Codex.
3. Update the plugin and the project: `harness upgrade --plugin --host claude`.
4. Start a new session, so that the host loads the 0.10 skills and hooks.

`--plugin` updates the plugin through the host, then runs the new engine on the project. That run has no terminal, so each step that needs a confirmation is skipped. Add `--yes`, or run `harness upgrade` again in a terminal.

## Run the upgrade

```bash
harness upgrade --dry-run
harness upgrade
harness upgrade --yes
```

- `harness upgrade --dry-run` prints the plan and changes nothing. It shows the schema change, each step with its pending changes, and each `check:` line.
- `harness upgrade` runs the plan. `harness init --migrate` does the same thing.
- A step that moves or deletes files asks first, with a `[y/N]` prompt.
- `--yes` accepts each prompt. Use it in CI or in a script.
- Without a terminal, a step that needs a confirmation is skipped. The report lists it with the fix `harness upgrade --yes`.

The upgrade runs in this order:

1. It migrates the schema: `.harness/schema_version` goes from 1 to 2.
2. It runs each 0.10 step that has pending changes.
3. It installs the merge drivers, refreshes the vendored engine in `.harness/engine/` and refreshes a harness-written CI workflow.
4. It refreshes harness-written Claude settings and the harness commands in `.codex/hooks.json`.
5. It repairs old overrides and graph records, and refreshes the registry rows whose source did not change.
6. It validates the substrate. A problem stops the upgrade with an error that names it.

Upgrade does not commit. Its only change to the git index is `git rm --cached` for `.harness/shadows/` and `.harness/memory/`, which stay out of git from now on. Read `git status` and `git diff`, then commit.

A file without a harness marker is never edited. For such a file, upgrade prints a `check:` line that says what to change by hand. A second run finds no pending step, and it prints the `check:` lines again.

## What upgrade changes

The upgrade has 17 steps. Each step runs only when it has pending changes, and a second run of a step changes nothing.

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

Upgrade moves the old memory to `.harness/cache/legacy-memory/`. It does not delete it. [Memory](memory.md#upgrading-from-09) explains the export and how to promote a fact.

These steps can print `check:` lines:

- `w2.config`: non-goals that no gate cites no longer block, and `gates.g3_mode: block` was removed.
- `w2.skill-names`: an unmarked file names a removed skill.
- `w2.contracts`: harness no longer checks `contracts/`. See the [Contracts recipe](extending/contracts.md).
- `w3.retire-durable-memory`: read the export and promote the facts that the team needs.
- `w3.shared-memory-index`: a `gates.extra` gate uses the id G10, which is now a builtin gate.
- `w3.claude-md-import`, `w4.agents-md-ste80` and `w6.agents-md-explore`: the file has no harness marker, the file is missing, or upgrade cannot find the place for the new line.
- `w4.glossary`: `docs` is a file, so upgrade cannot create the glossary.
- `w5.legacy-verification`: a worktree holds its own backlog.

## Renamed and removed

Skills, from spec 10.1:

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
- `gates.g5_override` was removed, and `gates.g3_mode: block` was removed. G3 is advisory.
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

- `steps`: each step that ran, with its changes and its report lines.
- `advice`: each `check:` line, with the step id.
- `warnings`: skipped steps, kept files and registry rows that were not refreshed.
- `vendored_engine`, `workflow`, `claude` and `codex_adapter`: what upgrade did to each file that it refreshes.

Then run the checks yourself:

```bash
harness doctor --substrate
harness verify
git status
```

- Do each `check:` line. Upgrade does not edit `AGENTS.md`, `CLAUDE.md` or the CI workflow when the file has no harness marker.
- For Codex, approve the project hooks again with `/hooks`.
- Commit the changes in one commit, for example `harness: upgrade to 0.10`.
