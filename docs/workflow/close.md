# Close

Close is the ceremony that finishes a slice. The engine checks the proof, records the provenance and commits the substrate. Close is the main place where harness blocks.

Run `/harness:close-slice <slice>` from the slice's worktree. The skill commits the work, then runs the engine command:

```bash
harness close-slice --slice orders-1 --commit HEAD
```

Pass `--commit HEAD`. The engine resolves it to a SHA, and the git note goes onto that commit.

## Close checks

Close blocks when one of the six [close checks](https://github.com/peekwez/harness/blob/main/docs/internal/superpowers/specs/2026-10-02-harness-0.10-design.md#64-close-checks) is false:

1. The acceptance suite of the slice is green.
2. The regression suite of the closed slices is green.
3. A red record exists. When the suite was green at start, an override with a reason exists.
4. Each statement in the slice's `verifies` has at least one test with a `verifies:` comment.
5. Each such test has `kills:` text.
6. Each G6 drift has an acknowledgement.

Close also checks these things:

- The slice is not closed and not parked, and no scaffold placeholder text is left in its row.
- The tested source matches the commit. The bytes that close tested are the bytes that it records.
- The repo's `acceptance.gate_cmd`, such as `make check`, runs once. A non-zero exit is the blocking finding `ACCEPTANCE_GATE_FAILED`.
- A slice that resolves a security-marked decision row has a `pass` verdict from a forked reviewer (ADR-001).
- The review stack runs over the slice diff and finds no blocking finding.
- No parked finding of the slice is open.
- No touched file falls inside a non-goal that a repo-local gate cites.
- The `unit_complete` gates pass: G6, G9, G10 and the repo-local gates. G10 blocks a change to `.claude/memory/shared/` that a human did not promote or accept. A human change needs `harness memory accept <path>`. G5 runs there too, and its findings are advisory.
- Each module that the slice uses is in its declared modules.
- Each added line in a dependency manifest has an override with a reason.

Close stops at the first failed check and names the fix. [Verification](../verification.md#close-checks) explains checks 3 to 5.

A slice with `legacy_verification: true` skips checks 3 to 5. It still runs acceptance and regression.

Close counts each failure on a real problem. At `run.max_close_attempts` failures (default 3), it parks the slice and records `parked_reason`. A human reads the reason and binds the slice again to unpark it. A failure on a guard, a corrupt red record or a green start does not count, because it needs a human, not a retry.

## Drift acknowledgements and overrides

G6 drift needs an acknowledgement:

```bash
harness gates ack-drift --slice orders-1 --module orders --note "adds refund() for V-orders-4"
```

Other checks take an override. An override is an edge with the gate, the target and your reason:

```bash
harness gates override --slice orders-1 --target boundary:<id> --rule-ref gate:G3 --justification "<why>"
harness gates override --slice orders-1 --target deps:pyproject.toml --rule-ref gate:G5 --justification "<why>"
harness gates override --slice orders-1 --target verification:green-at-start --rule-ref verify:red-record --justification "<why>"
```

An override applies only to its gate and its target. It is a record, not a barrier. harness stores who overrode what and why, and it does not judge the reason.

## What close writes

A successful close writes these things:

- A git note on the `--commit` SHA, under `refs/notes/harness`: the slice, the modules touched and the registry entries used.
- One row in `.harness/slice-metrics.jsonl`: gates fired, overrides, reversals, the largest injection, compactions, parks and the verification result.
- Registry flips from `planned` to `built` for modules that the slice produced.
- Provenance edges, and `status: closed` with `closed_commit` and `closed_files` on the slice row.
- One substrate commit, `harness: close-slice <id> substrate`, of the `.harness/` changes.

A completion journal in `.harness/cache/` makes an interrupted close recoverable. When the substrate commit exists, the next `harness close-slice` run finishes the close. Otherwise it restores the substrate files and runs the ceremony again.

In pull request mode, close then pushes the branch and opens the pull request. See [Land](land.md).

## Promote memory

After review and before the commit, the close-slice skill offers personal memory for promotion. It runs `harness memory changed --slice <id>`. The output lists the personal memory files that changed since the slice started.

When the list is not empty, the agent asks the human: "Promote any to shared?" For each file that the human picks, the agent runs `harness memory promote <file>`. On Claude Code, the host asks the human to approve it.

The promoted facts go into the slice commit. See [Memory](../memory.md).
