# Memory

harness 0.10 manages one kind of memory: shared team facts that a human chose. Each person's own agent memory stays with the host. The [0.10 design spec](https://github.com/peekwez/harness/blob/main/docs/internal/superpowers/specs/2026-10-02-harness-0.10-design.md#d-010-02-memory) gives the reasons.

## Personal memory

Claude Code keeps each person's memory, in `~/.claude/projects/<slug>/memory/` or in the folder that `autoMemoryDirectory` names. harness does not write, move or inject it.

harness reads only the location of that folder. At close, `harness memory changed --slice <id>` lists the personal memory files that changed since the slice started, so a human can choose what to share.

- Personal notes and client context never reach git through harness.
- The forked reviewer never reads the builder's personal memory.
- The agent keeps its calibration levels and its failed approaches in personal memory.

## Shared memory

`.claude/memory/shared/` is committed. It holds these files:

- `MEMORY.md`, the index, with one line per fact: `- [title](file.md) — summary`.
- One file per fact, with front matter: `name`, `description`, `promoted_by` and `promoted_at`.

`harness init` creates the index. The `CLAUDE.md` template imports `@.claude/memory/shared/MEMORY.md`, so each session loads the index. Agents read shared memory, and they never edit it. `harness status` counts the index in the always-on cost.

## Promote a fact

A human promotes each shared fact with one of these commands:

```bash
harness memory promote ~/.claude/projects/-Users-me-shop/memory/payments-retry.md
harness memory promote --text "Retry a failed payment at most 3 times."
```

`harness memory promote` does these things:

1. It copies the fact into `.claude/memory/shared/<name>.md`. `--name` sets the file name. The default comes from the fact.
2. It adds `promoted_by`, your git identity, and `promoted_at` to the front matter. It refuses to run without a git identity.
3. It adds one line to `MEMORY.md`, 120 characters or fewer.

The same fact a second time gives "already shared" and writes no new file. It adds the index line only when the line is missing. A different fact under a name that exists is refused: pass `--name`. Promote refuses the index file and a symbolic link.

Promote writes into the current tree. At close, the promoted files go into the slice commit.

## Guards

Three layers stop an agent from writing shared memory:

- **G10** blocks each write to `.claude/memory/shared/` through the host's edit tools. It runs in the engine at `pre_change`. On Claude Code it stops the write. On Cursor CLI (degraded mode) it runs only after the edit lands, so it reports the write and does not undo it. No override and no exempt path applies. Its fix names `harness memory promote`.
- **G10 at close** checks the slice diff. Close blocks when the slice adds, changes or deletes a file in `.claude/memory/shared/`, unless `harness memory promote` wrote those bytes. Promote records a hash of each file that it writes in `.harness/promotions.jsonl`. So close blocks a shell write such as `echo x > .claude/memory/shared/a.md`.
- **The permit layer** asks a human for each `harness memory promote`, and for each other `harness memory` subcommand except `changed`. It also asks for a shell command that names the shared folder. It never approves these on its own.

The shipped Claude Code profile also has `ask` rules for `harness memory promote`. A human approves each promotion.

These guards have limits:

- G10 at close sees only the slice diff. It does not see a shell write outside a slice, or one that is undone before close.
- G10 at close trusts the hash rows in `.harness/promotions.jsonl`. A shell command that adds a row there passes the check.
- Only the Claude Code hook runs the permit layer on shell commands. Other hosts' profiles approve shell commands.
- The permit layer reads the command text. Some spellings, such as a renamed binary, do not ask.

For these gaps, the backstop is a human who reads the committed diff. We recommend a sandbox rule: add `.claude/memory/shared` to `sandbox.filesystem.denyWrite` in `.claude/settings.json`. [Trade-offs and limits](trade-offs.md#shared-memory-writes) lists each gap.

`harness doctor --substrate` warns when `MEMORY.md` has more than 40 entries. A small index stays useful, because a human chose each line.

## Upgrading from 0.9

harness 0.9 kept its own memory in `.harness/memory/`. `harness upgrade` retires it in these steps:

1. It asks first. When you answer no, it changes nothing.
2. It exports the rows that 0.9 kept on purpose to `.harness/cache/durable-memory-export.md`: attempts, adjudications and reasoning marked `promote`. Each exported row has a ready `harness memory promote --text` command.
3. It moves `.harness/memory/` to `.harness/cache/legacy-memory/<stamp>/`. It does not delete the folder.
4. It removes the `.harness/memory/` lines from `.gitattributes` and `.gitignore`.
5. It creates `.claude/memory/shared/MEMORY.md` when the index is missing.
6. It adds the shared memory import to a harness-written `CLAUDE.md`. For a `CLAUDE.md` with no harness marker, it prints a `check:` line with the import to add by hand.

Upgrade never promotes a fact. Read the export, and run the commands for the facts that the team should share.

`harness memory write`, `flush` and `compact` were removed in 0.10.
