# Verification

harness proves behavior in three parts. A statement says what must be true. A test links to the statement. A red record shows that the test failed before the code existed. Close checks all three.

## Statements

A statement is one claim about a feature, on one line. Its id has the form `V-<feature>-<n>` and matches `V-[a-z0-9-]+-[0-9]+`:

```markdown
- V-orders-1: A paid order writes exactly one event row.
- V-orders-2: A failed payment writes no event row.
```

Statements come from `explore/VERIFY.md`. Without explore, they come from the verification matrix in the architect working document, with the same id format. When `explore/VERIFY.md` exists, compile reads only that file.

`harness compile` writes `.harness/verify.jsonl`, one row per statement: `id`, `feature`, `statement` and `source`.

- Compile replaces only the rows of the source that it compiled. Rows from another source stay.
- An id that another source already uses stops the compile, and nothing is written.
- A malformed id, an empty statement or a repeated id stops the compile too.

`harness backlog add --verifies` assigns statements to a slice. `harness backlog` reports each statement that no slice owns.

## Test links

A test links to a statement with a comment, in any comment syntax:

```python
# verifies: V-orders-3  kills: commit happens before the rollback check
def test_rollback_leaves_no_event_row(): ...
```

- `verifies:` names one or more ids, separated by a comma or space.
- `kills:` names the bug that the test must catch. It can also go on the next comment line. harness does not run that bug as a mutant.
- The link moves with the test. No mapping file exists.

A typo breaks the link (see [the 0.10 design spec](https://github.com/peekwez/harness/blob/main/docs/internal/superpowers/specs/2026-10-02-harness-0.10-design.md#d-010-07-how-a-test-links-to-a-statement)), so harness reports unknown ids in two places:

- `harness compile` warns with `UNKNOWN_TEST_LINK` for each test comment that names an id that is not in `verify.jsonl`.
- Close blocks with `UNKNOWN_STATEMENT` when the slice's `verifies` names an unknown id. It warns with `UNKNOWN_TEST_LINK` for an unknown id in the slice's own acceptance files.

## The red record

Each bind runs the slice's acceptance suite once: `harness slice --slice <id>` or `harness start --slice <id>`. It uses the configured runner, with stdin closed and a timeout. The suite must exit non-zero.

harness writes `.harness/verification/<slice>.json`, and close commits it. The record has these fields:

| Field | Meaning |
|---|---|
| `slice` | the slice id |
| `commit` | `HEAD` at the bind |
| `ran_at` | the time of the run |
| `exit_code` | the exit code of the suite, or null when the suite did not start or timed out |
| `output_tail` | the last 20 lines of output |
| `red` | true when the suite ran and failed |
| `green_at_start` | true when the suite ran and passed |
| `runner_error` | optional: why the suite could not give a result |
| `per_test` | optional: the result of each test, from JUnit XML |
| `junit_error` | optional: why harness could not read the JUnit XML |

These rules apply:

- A red record is never overwritten. A later bind keeps it. Write real assertions before the bind.
- A green record, or a record with `runner_error`, runs again at the next bind.
- A record that is not valid JSON stops the bind and the close. Repair or delete it, then bind again.
- A command that cannot start, a pytest exit 4 or 5, a missing path or a timeout is a runner error. A runner error is never red evidence.
- `acceptance.red_timeout` sets the timeout in seconds. The default is 600.
- With `acceptance.junit: true`, the runner writes JUnit XML and harness records each test in `per_test`. The default pytest command gets `--junitxml`. A custom `cmd` must name `{junit}`.
- With `gates.acceptance_runner: none`, the bind writes no record and close skips the record check.

## Close checks

Close blocks when one of these checks is false:

1. The acceptance suite is green.
2. The regression suite of the closed slices is green.
3. A red record exists. When `green_at_start` is true, an override with a reason exists.
4. Each statement in the slice's `verifies` has at least one test with a `verifies:` comment.
5. Each such test has `kills:` text.
6. Each G6 drift has an acknowledgement.

Checks 3 to 5 use these codes:

| Code | When |
|---|---|
| `RED_RECORD_MISSING` | no record, a corrupt record, or a record that is not red |
| `GREEN_AT_START` | the suite passed at the bind, and no override exists |
| `UNKNOWN_STATEMENT` | a `verifies` id is not in `.harness/verify.jsonl` |
| `STATEMENT_UNTESTED` | no test in an acceptance suite names the statement |
| `KILLS_MISSING` | a `verifies:` comment has no `kills:` text |

For check 4, only tests in an acceptance suite count: the slice's own suite, or the suite of a closed slice.

A pure refactor slice can be green at start. It then needs an override with a reason:

```bash
harness gates override --slice refactor-1 --target verification:green-at-start --rule-ref verify:red-record --justification "pure refactor, behavior unchanged"
```

## Acceptance command

The `acceptance:` block in `.harness/config.yaml` sets the command that decides green:

```yaml
acceptance:
  cmd: "uv run pytest {paths} -q"
  cwd: "."
  env: {PYTHONHASHSEED: "0"}
  junit: false
  red_timeout: 600
  gate_cmd: "make check"
```

- `cmd` defaults to `<python> -m pytest <paths> -q`. The python is `gates.acceptance_python`, then the project's `.venv`, then the engine's interpreter.
- `{paths}` becomes the shell-quoted acceptance paths. A `cmd` without `{paths}` gets the paths at the end.
- harness splits the command with `shlex` and runs it without a shell.
- `cwd` is relative to the repo root and must stay inside the repo.
- `env` values must be strings. harness adds them to the environment.
- `gate_cmd` is the repo's own whole-tree gate. It runs once at close and once at merge. A non-zero exit is `ACCEPTANCE_GATE_FAILED`.

The same runner runs the slice suite at close, the regression suite at close and the regression suite at merge. harness expands globs itself, so a glob that matches no file fails loud.

At the bind, a runner error is never red evidence. At close and at merge, any non-zero exit fails the check. A command that cannot start gives exit 127 there.

## The closed-slice suite

`harness acceptance --closed` runs the acceptance paths of every closed slice, through the configured runner. Close and merge use the same selection.

- `--list` reports `paths`, `owners` and `problems`, and runs nothing.
- `--exclude <slice>` leaves one slice out.
- A missing file or a glob with no match is a problem, and the suite is red. It is never a silent drop.
- With `gates.acceptance_runner: none`, the output reports the suite as disabled.
- `harness verify` never runs this suite. The CI workflow runs it only with the `closed-acceptance` input.

## Verification skill

`/harness:verification` checks the work as a human reviewer would. It maps each acceptance criterion to the implementation, then to a decisive check, then to the observed evidence.

- It returns `VERIFIED` or `NOT VERIFIED`, and `PASS`, `FAIL`, `NOT_RUN` or `INCONCLUSIVE` for each criterion.
- It starts or attaches to the running system, and it inspects logs, stored data and cache effects.
- For a criterion that changes state, it seeds data through the app. Then it checks storage with read-only probes.
- For runtime criteria, it ties each scenario to the production code that ran, with live coverage.

Green tests prove only what they assert. A skipped check, a disabled runner or a stale result is not a `PASS`. The skill reads each test link and asks whether the test would fail if the `kills:` bug existed.

## Slices from before 0.10

`harness upgrade` marks each slice that is not closed and has no `verifies` key with `legacy_verification: true`. Such a slice started before 0.10, so it has no red record and no statement links.

- Close skips checks 3 to 5 for a legacy slice. It still runs acceptance and regression.
- A legacy slice gives no red-record advisory.
- Its slice metrics row has no `red_before_green` and no `green_at_start` field.
- Upgrade marks only the main tree. For each worktree with its own backlog, upgrade prints a `check:` line. Run `harness upgrade` in that worktree.

A slice that you add after the upgrade always carries `verifies`, so it gets the full checks.
