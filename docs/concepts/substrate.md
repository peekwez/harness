# Substrate files

The substrate is the set of harness files in your repo. This page lists each file, who writes it, and whether git tracks it.

## Two trees

harness lives in two places:

- **The plugin.** You install it once. It is versioned and holds no project state. It holds the skills, the agents, the hooks and the engine.
- **The substrate.** It lives in each repo. `/harness:init` creates it, and `harness upgrade` migrates it.

The engine reads the substrate and writes its verdicts there. Two repos with one plugin share nothing.

## Authored, derived and cache

Each substrate file is one of three kinds:

- **Authored** files hold human judgement. They change when a human decides, for example through adjudication or a freeze.
- **Derived** files are regenerated from authored files or written by the engine. To edit one by hand is a bug.
- **Cache** files are gitignored. The engine rebuilds them when it needs them.

When you cannot tell which kind a file is, report it in review as a design defect.

## File map

A fresh `harness init` creates the files that name init in the last column. The other files appear when the step that writes them first runs.

| Path | Kind | Committed | Written by |
|---|---|---|---|
| `.harness/config.yaml` | authored | yes | init writes the template; you edit it |
| `.harness/schema_version` | derived | yes | init and upgrade; the value is `2` |
| `.harness/registry.jsonl` | derived | yes | init seeds it; `harness compile` writes it; close flips `planned` to `built` |
| `.harness/decisions.jsonl` | derived | yes | init (empty); `harness compile`; `harness adjudicate --decision-id` |
| `.harness/boundaries.jsonl` | derived | yes | init (empty); `harness compile`, from `[non-goal]` blocks |
| `.harness/verify.jsonl` | derived | yes | `harness compile` |
| `.harness/backlog.jsonl` | authored through `harness backlog add` | yes | init (empty); `backlog add`; the engine updates `status` and estimates |
| `.harness/edges.jsonl` | derived history, append only | yes | init (empty); the engine |
| `.harness/notes.jsonl` | derived history, append only | yes | init (empty); close, the tree-hash keys of provenance notes |
| `.harness/parked.jsonl` | runtime queue | yes | review parks a finding; `harness adjudicate` removes it |
| `.harness/verification/<slice>.json` | derived | yes | each bind writes the red record |
| `.harness/slice-metrics.jsonl` | derived | yes | init (empty); close writes one row per slice |
| `.harness/cache/` | cache | no | shadows, `events.jsonl`, JUnit files, upgrade exports |
| `.harness/sidecar.db` | cache | no | session state in SQLite: bindings, context hashes, close attempts |
| `.harness/engine/` | derived | yes | init and upgrade vendor the engine for CI; never edit it |
| `adr/` | authored | yes | init writes `000-template.md`; `harness architect --from-explore` writes one ADR per chosen card |
| `explore/` | authored | yes | `harness explore`; see [Explore](../workflow/explore.md) |
| `docs/architecture.md` | authored working document | yes | `harness architect` seeds it; the architect skill edits it |
| `docs/glossary.md` | authored | yes | init writes it when it is missing |
| `AGENTS.md` and `CLAUDE.md` | authored | yes | init writes each one once and never overwrites it |
| `.claude/memory/shared/` | authored, by promotion only | yes | init creates `MEMORY.md`; `harness memory promote` adds facts |
| `.github/workflows/harness-verify.yml` | derived | yes | init and upgrade |
| `.gitattributes` | derived lines | yes | init adds the merge driver lines |
| `.claude/settings.json` | derived profile | yes | `harness init --autonomy` |
| `.claude/settings.local.json` | derived profile | no | `harness start`, in the slice worktree |
| git notes under `refs/notes/harness` | derived | yes, as a git ref | close |

[File formats](../reference/file-formats.md) gives the fields of `backlog.jsonl`, `registry.jsonl`, `decisions.jsonl`, `slice-metrics.jsonl` and `verify.jsonl`. `harness verify` checks these files row by row.

Two other files have no row schema:

- Each row of `.harness/edges.jsonl` is one edge: `ts`, `type`, `from`, `to`, `commit` and `meta`. The engine accepts only its known edge types, for example `implements`, `uses`, `supersedes` and `override`.
- Each row of `.harness/parked.jsonl` is one parked finding: `slice` and `finding`. `finding` is the full finding, with its `finding_id`.

## Merge drivers

Two slices in two worktrees often change the same `.harness/*.jsonl` file. Git merges these files with drivers that init installs:

- `.harness/edges.jsonl` and `.harness/notes.jsonl` merge with `merge=union`, because they are append-only logs.
- `.harness/backlog.jsonl`, `.harness/registry.jsonl`, `.harness/decisions.jsonl` and `.harness/slice-metrics.jsonl` use `merge=harness-substrate`.

`harness merge-substrate` is the `harness-substrate` driver. It merges row by row, keyed by `id`, as a 3-way merge. A row that both sides changed in different ways is a real conflict. The driver then exits 1 and leaves your side for a manual merge.

The `.gitattributes` lines travel with the repo. The git config half does not travel with a clone, so each bind writes it again.

Update a slice branch on your machine, where the driver runs. GitHub's "Update branch" button cannot run the driver, so it conflicts inside `.harness/backlog.jsonl`.

## CI workflow

`.github/workflows/harness-verify.yml` runs `harness verify` on each pull request and each push to `main`. It needs no plugin.

- CI installs `pyyaml`, `tree-sitter` and `tree-sitter-language-pack` from PyPI. It clones nothing when the repo has `.harness/engine/`.
- The job runs `.harness/engine/bin/harness verify`. Run `harness upgrade` to vendor the current engine.
- Without `.harness/engine/`, the job clones the engine from the `harness-repo` input or the `HARNESS_REPO` repository variable.
- A private engine repo also needs the `HARNESS_TOKEN` secret: a fine-grained token with Contents: read.
- The opt-in input `closed-acceptance` runs `harness acceptance --closed`. The input `acceptance-setup` installs your project first.

`harness verify` checks the substrate. It does not run your application tests.
