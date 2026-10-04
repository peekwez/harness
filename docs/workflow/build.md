# Build

Build starts a slice and runs it to close. One command prepares the worktree, the sandbox, the binding, the red record and the context. Then the agent works without prompts inside the slice's declared scope.

## One command starts a slice

Run `/harness:build <slice>`, or the engine command:

```bash
harness start --slice orders-1
```

`harness start` does these things, in order:

1. It checks that the slice is not closed and that each `depends_on` slice is closed. `--force` with `--justification "<why>"` starts it anyway and records an override edge.
2. It creates the worktree `.worktrees/<slice>` on the branch `slice/<slice>`. When the worktree exists, it resumes there.
3. It writes a sandbox profile to `.claude/settings.local.json` in the worktree. Git does not track that file.
4. It binds the slice to the session and as the repo default. It sets the status to `in_progress` and records `started_at_commit`.
5. It takes the G6 baseline of the public interfaces.
6. It writes the red record.
7. It prints the slice context, under the cap.

The sandbox profile has these parts:

- `sandbox.enabled: true`, with writes confined to the worktree.
- Network egress limited to package registries: PyPI, npm, crates.io and the Go proxy.
- Allow rules for harness, the test runners and local git.
- Deny rules for `git push`, `git remote`, `git clone`, `git fetch` and `git pull`.
- Ask rules for `harness memory promote`.

In pull request mode, the profile drops the `git push` and `git fetch` denies and adds the forge hosts. The permit layer then decides each push. See [Land](land.md#egress-permits).

- `--no-worktree` binds in the current tree and writes the profile to `.claude/settings.json`. Pull request mode refuses it.
- `harness init --autonomy` writes the same profile to `.claude/settings.json` at the repo root.
- `harness slice --slice <id>` binds only. It creates no worktree and no profile.

The shipped profile sets `failIfUnavailable: false`. Where the host cannot start its sandbox, the work runs without one.

## The red record

Each bind runs the slice's acceptance suite once and records the result in `.harness/verification/<slice>.json`. The suite must exit non-zero: the tests fail before the code exists.

- A red record is never overwritten. Write real assertions before the bind, because a later fix to a weak test does not change the record.
- A green record, or a record with `runner_error`, runs again at the next bind.
- A record that is not valid JSON stops the bind. Repair or delete it, then bind again.
- A command that cannot run, a pytest exit 4 or 5, a missing path or a timeout is a runner error. A runner error is never red.

Before a red record exists, an edit to a file that is not a test gives one advisory line:

```text
No red record for slice <id>: <file> is not a test.
```

Its fix is `harness slice --slice <id>`. The advisory never blocks. Test files, acceptance files and `gates.exempt_paths` give no advisory. A slice with `legacy_verification: true` gives none either.

[Verification](../verification.md#the-red-record) lists the record fields and the close checks.

## Context injection

The resolver builds the slice context from five blocks, in priority order:

1. gate findings that are still open;
2. decision rows that the slice cites;
3. non-goals;
4. the slice card: title, statements and predicted files;
5. module pointers: `harness resolve --module <id>` for each declared module.

The hooks inject the context at SessionStart and with the first prompt after a binding. Later prompts get only the blocks whose text changed. No change sends nothing. PreCompact clears the stored block hashes, so the next prompt injects the full context again.

The cap is `MAX_INJECTION_CHARS`, 9,000 characters. When the blocks do not fit, the resolver cuts from the lowest priority. Each cut block becomes a one-line pointer, and the cut adds the advisory finding `CONTEXT_OVER_CAP`. The adapter clips its output at 9,500 characters as a safety net.

- `harness resolve --slice <id>` prints the whole context with no cap.
- `harness resolve --module <id>` prints one module's shadow and guidance. A guidance ref can name a section with `#anchor`. When the anchor is missing, it prints the whole file and reports `anchor-missing`.
- `harness status` prints the always-on cost for each source: skill listing, agent listing, `AGENTS.md`, the shared memory index and the last injection. Each is in characters and estimated tokens.

## Gates on each edit

The host hooks run the gates on each edit through the host's edit tools:

| When | Engine event | Gates |
|---|---|---|
| before an edit | `pre_change` | G1, G3, G10, and the red-record advisory |
| after an edit | `post_change` | G5, G9 |
| at the end of a turn, at close and at merge | `unit_complete` | G5, G6, G9 |

Repo-local gates from `gates.extra` run at the events that they declare.

- A block before an edit stops the edit. On Claude Code, the PreToolUse hook denies the tool call.
- A block after an edit reports the finding. The edit has already landed.
- A block at the end of a turn stops the turn once.

G6 compares the public symbols of each touched module against the baseline from the bind. A changed public interface needs an acknowledgement before close. G3 scope findings and G5 findings are advisory.

A file that a shell command writes does not pass through these gates. Close finds it from git. [Gates](../reference/gates.md) lists each gate in full.

## The permission layer

The PreToolUse hook also answers the host's approval question. It uses the same verdict as the gates, so a bound slice does not stop for a prompt.

- An edit is approved when the gates allow it and each path is inside the slice's declaration. The declaration is the predicted files, the acceptance paths, the sources of the declared modules and `gates.exempt_paths`.
- A shell command is approved when it is in the loop's command set: harness, the test runners and local git.
- A command that talks to a remote is not approved. In local mode the profile denies it.
- `harness memory promote`, and a command that names `.claude/memory/shared`, asks a human.
- Anything else falls through to the host's normal prompt.

A prompt during a bound slice means the agent went outside its declaration. The build skill tells the agent to add the file to `predicted_files` on the slice row first. Do not approve the prompt to get past it.

Only the Claude Code hook runs the permit layer on shell commands. [Trade-offs and limits](../trade-offs.md#where-enforcement-depends-on-the-host) lists the other hosts.

## Composing with superpowers

The superpowers plugin can run beside harness. Decision row D-014 in [ADR-002](https://github.com/peekwez/harness/blob/main/adr/002-kente-capable-superpowers-composable.md) splits the work:

- harness owns the outer loop: session start, slice binding and scope, the review contract (`rule_ref`), close and landing.
- superpowers owns the inner loop: `superpowers:brainstorming` as architect stage 1, writing `docs/architecture.md`.
- `superpowers:test-driven-development` runs for each unit.
- `superpowers:systematic-debugging` runs on any red test or gate block.
- `superpowers:verification-before-completion` runs before close.
- Inside a bound slice, `superpowers:finishing-a-development-branch` is not used. Close is the finish.
- Inside a bound slice, the stop-for-side-effects rule of `superpowers:subagent-driven-development` is not used.
- `superpowers:using-git-worktrees` must detect and reuse `.worktrees/<slice>`.
- `superpowers:requesting-code-review` runs only as review layer 3, and its findings are advisory.
