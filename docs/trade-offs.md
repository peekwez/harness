# Trade-offs and limits

This page lists what harness does not do. Read it before you adopt harness. Each limit names the part of harness that it affects.

## What harness does not catch

### Tests that check the wrong thing

harness checks that each statement has a linked test and that the suite failed at slice start. It does not check that a test asserts the right thing.

- A test can carry `verifies: V-orders-3` and still test the wrong object.
- The red record proves that the suite failed. It does not prove that the suite failed for the right reason.
- A stub test that fails, such as `assert False`, records red. A JUnit check for each test that would flag stubs is not built.
- A red record is never overwritten. Write real assertions before the bind, because a later fix to a stub does not change the record.
- The `kills:` text names the bug that the test must catch. harness does not run that bug as a mutant.

The forked reviewer reads each test. It can still miss a weak test.

### Edits outside the host's edit tools

The pre-change gates see edits that go through the host's edit tools. A file that a shell command writes does not pass through those gates.

Close finds each changed file from git and runs its close checks on the full set. So the close checks see a shell edit, but later than the edit. G10 does not run at close, so close does not flag a shell write to shared memory.

### Scope and non-goals

- G3 scope findings are advisory. An agent can edit a file outside its slice. harness reports the edit and does not stop it.
- A non-goal blocks only when a repo-local gate cites it. `compile` reports each other non-goal as "advisory only".
- In 0.9, path-only non-goals produced 46 overrides against 45 firings in one consumer repo. That evidence made them advisory.

### Duplicate code

G5 checks that a module uses only what its slice declares, and it looks for reimplementation. Its findings are advisory. Close blocks when uses are not within declares. G5 does not find a copy that has a different shape.

### Imports from the toy

G9 blocks production code that imports from `explore/`. It is active only when `explore/DECISIONS.md` exists. It runs after each edit, at close and in `harness verify`.

- G9 reads static imports only. It does not see a dynamic or templated import, an `importlib` call or a path built at run time.
- It does not see code that an agent copied from the toy.
- It can block by mistake. A bare npm package named `explore`, a Rust `mod explore` inside a crate, or an unrelated `explore` package under a source root can match.

To clear a false block, move or rename the module.

### Shared memory writes

G10 blocks each write to `.claude/memory/shared/` through the host's edit tools. G10 sees only edit-tool writes. It does not run at close or in the review. For shell commands, the permit layer reads the command text and asks a human when the command names that folder or runs `harness memory promote`.

Text-level checks are best effort. These spellings do not ask:

- `python3 -m engine.cli memory promote`, or a copy of the `harness` binary under another name.
- A `cd` into the folder in one call, then a write with a relative path in a later call.
- A redirect target with a glob, such as `.claude/memory/sh*/a.md`.
- A wrapper such as `env`, `nohup`, `xargs` or `eval` in front of a program word that the permit layer cannot read.
- An allowed tool that can run any code, such as `pytest` on tests that an agent wrote, `git apply` or a `git config core.fsmonitor` value.

Nothing in harness flags a file that a shell command wrote under `.claude/memory/shared/`. The backstop is a human who reads the committed diff.

We recommend a sandbox write-deny rule. Add `.claude/memory/shared` to `sandbox.filesystem.denyWrite` in `.claude/settings.json`. The shipped profile sets `failIfUnavailable: false`, so the rule holds only where the sandbox runs. A permission deny rule for the Edit and Write tools on that folder adds a second layer. harness does not write these rules for you.

### Text quality

`harness lint-text` checks sentence length, banned words and glossary synonyms. It does not detect passive voice. It does not check meaning.

### Model review

A finding blocks only when it cites a gate, a decision row or an ADR. A real problem that no rule covers stays advisory. The holistic review layer never blocks. A model finding with low confidence parks for a human. Ensemble sampling is off by default.

### Decision cards on the skip paths

`harness architect --from-explore` checks the format of each card in `explore/DECISIONS.md`. On the `--skip-explore` and `--from-spec` paths, only the skill text asks for cards. No engine check enforces the card format there.

### Codes from repo-local gates

`harness gates explain <code>` prints the catalog entry for a builtin code. It has no entry for a code that a `gates.extra` gate emits. Put the fix in that gate's finding text.

### Overrides

An override is a record with a justification. It is not a barrier. harness stores who overrode which finding and why. It does not judge the reason.

## Where enforcement depends on the host

- harness enforces through host hooks. A host without hooks gets instructions only.
- Claude Code is the reference host. The [host matrix](extending/hosts.md#host-matrix) lists full, degraded and instruction-only hosts.
- Only the Claude Code hook runs the permit layer on shell commands. The other hosts' shipped profiles approve shell commands, so the shared-memory asks apply only on Claude Code.
- Those profiles are `adapters/codex/autonomy.toml` (`approval_policy = "never"`), `adapters/gemini/autonomy-policy.toml` (`toolName = "*"`), `adapters/opencode/opencode-permissions.json` (`"*": "allow"`) and `adapters/cursor/cli-permissions.json` (`Shell(python3)`).
- Cursor CLI runs in degraded mode. The edit lands first. Gates run after the edit and at stop, and they do not undo the edit. `harness verify` in CI is the backstop.
- Gemini CLI hooks fail open. When the hook crashes, the edit goes through.
- The host supplies the sandbox. harness writes the sandbox profile. It does not run a sandbox of its own. The shipped profile sets `failIfUnavailable: false`.
- In pull request mode, the permit layer approves `gh pr create --body-file` with any path. An agent could point the body file at a secret. Read each pull request body.

## Languages

Shadows exist for Python, TypeScript and TSX, Rust, Go, YAML and HCL. G5 and G6 need shadows. For a file in another language, these gates see nothing. `harness doctor` lists source files that have no shadow.

G9 reads Python imports from the shadow. It reads TypeScript, JavaScript, Go and Rust imports from the source text. It does not check other languages.

Two machines with different tree-sitter versions can build different shadows. `harness doctor` reports the version.

## Costs you pay

- **Time at design.** New designs start with explore. A skip needs a recorded reason.
- **Time per slice.** The acceptance suite runs at slice start and again at close. A slow suite makes each slice slow. A timeout stops only the direct child process. Processes under a wrapper such as `uv run` can stay running.
- **Tokens.** The forked reviewer and the Claude and Codex design review use model tokens. harness does not claim a net saving.
- **Context.** The first injection after a binding can be up to 9,000 characters. Later prompts get only the blocks that changed.
- **CI time.** The shadow cache is not committed. CI rebuilds shadows when G5 or G6 needs them.
- **Fail closed.** In an initialised repo, an engine error denies edits until you repair the substrate. In a repo without init, the hooks enforce nothing, and the host's own permissions still decide.
- **Upgrades.** 0.10 breaks 0.9. `harness upgrade` migrates a repo. A slice in flight during the upgrade that has no `verifies` list gets `legacy_verification: true`. At close, it skips the red-record and statement checks.

## Design choices you may disagree with

- **Personal memory stays with the host.** harness manages only `.claude/memory/shared/`. It does not know who wrote a personal note.
- **Telemetry stays local.** Event rows stay in `.harness/cache/events.jsonl` on each machine. Close commits one summary row for each slice. There is no central dashboard. `.harness/cache/events.jsonl` grows without a limit.
- **No context budget per repo.** The injection cap is a constant. A slice that does not fit gets the advisory finding `CONTEXT_OVER_CAP`. You split the slice or shorten its rows.
- **Contracts are not in core.** harness does not check OpenAPI files. You add a repo-local gate or a CI linter. See the [Contracts recipe](extending/contracts.md).
- **The toy is never production code.** harness does not turn `explore/` code into production code. You write the production code in a slice.

## When not to use harness

- A short script or a one-off change. The ceremony costs more than it saves.
- A repo with no automated tests. Close needs an acceptance suite that can fail.
- A codebase mostly in a language that has no shadows.
- A team that needs a hard security boundary. harness records and checks. It is not a sandbox.
- A host with no hooks, when you need enforcement and not only instructions.
- A harness root in a subfolder of a larger git repo. The CLI expects the harness root to be the git root.

## How to change a limit

harness is plain Python. Each limit on this page maps to code that you can change.

- Add a deterministic check as a repo-local gate. See [Repo-local gates](extending/extra-gates.md).
- Add a host with one adapter file and the conformance tests. See [Other hosts](extending/hosts.md).
- Read [Internals](internals.md) for the engine layout and the event flow.
