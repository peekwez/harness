harness keeps its state in plain files. This page lists the format of each file that a person or a tool reads. The tables at the end come from `engine/schema.py`.

## `.harness/verify.jsonl`

`compile` writes one row for each statement. A row has four fields:

- `id`: the statement id, such as `V-orders-3`. It matches `V-[a-z0-9-]+-[0-9]+`.
- `feature`: the feature part of the id, such as `orders`.
- `statement`: the claim, in one sentence.
- `source`: the file that holds the statement, such as `explore/VERIFY.md`.

## Test links

A test links to a statement with a comment, in any comment syntax:

```python
# verifies: V-orders-3  kills: commit happens before the rollback check
def test_rollback_leaves_no_event_row(): ...
```

- `verifies:` names one or more statement ids, separated by commas. `--verifies` on the CLI is repeatable and takes commas or spaces.
- `kills:` names the bug that the test must catch. harness does not run it. Close checks that the `kills:` text is present and not empty.

## `.harness/verification/<slice>.json`

This file is the red record. A bind (`harness slice --slice <slice>` or `harness start --slice <slice>`) runs the acceptance suite of the slice. The first bind writes it. A later bind rewrites only a green or `runner_error` record. Close commits it with the rest of `.harness/`.

- `slice`, `commit`, `ran_at`: which slice, at which commit, at what time.
- `exit_code`: the exit code of the acceptance suite.
- `output_tail`: the last lines of the suite output.
- `red`: `true` when the suite failed for a real reason. A red record is never overwritten, so the acceptance tests must be real before bind.
- `green_at_start`: `true` when the suite passed at start. Close then needs an override with a reason.
- `runner_error`: set when the runner gives no verdict. Causes: a command that cannot start, a pytest exit 4 or 5, a missing path or a timeout. A runner error is never red. The next bind runs the suite again.
- `per_test`, `junit_error`: the result of each test. They exist only with `acceptance.junit: true`.

A corrupt record blocks bind and close. When a slice has no record, the advisory reads `No red record for slice <id>: <file> is not a test.` and the fix is `harness slice --slice <id>`.

## `.harness/slice-metrics.jsonl`

Close writes one row for each slice and commits it with the rest of `.harness/`. A row holds the gates that fired, the overrides, the maximum injection size, the compaction count, `parks`, `reversals`, `source`, `red_before_green`, `green_at_start` and, when explore was skipped, `explore_skipped`. Rows of legacy or skipped slices omit the red fields.

## `explore/DECISIONS.md`

This file holds the decision cards. The format is on the [Decision cards](../decision-cards.md) page. `harness explore --freeze` adds `frozen_by`, `frozen_at_commit` and `frozen_digest` to its front matter. An edit after freeze needs a new freeze.

## `.harness/cache/`

git ignores this folder. `shadows/` holds one shadow for each source file in scope. `events.jsonl` holds the local event rows.
