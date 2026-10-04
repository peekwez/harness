# Backlog

Backlog turns the design into slices. A slice is the smallest unit of autonomous work. Each slice starts from red acceptance tests.

## What a slice holds

Each slice is one row in `.harness/backlog.jsonl`. These fields come from `engine/schema.py`:

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | the slice id |
| `status` | yes | `planned`, `in_progress`, `parked` or `closed` |
| `declares_dep` | yes | registry ids of the modules the slice may use |
| `acceptance` | yes | paths or globs of the red acceptance tests |
| `predicted_files` | yes | files the slice expects to touch |
| `depends_on` | no | slice ids that must close first |
| `title` | no | a short name; the default is the id |
| `spec` | no | a reference to the spec text |
| `verifies` | no | statement ids from `.harness/verify.jsonl` that the slice proves |
| `legacy_verification` | no | `true` for a slice that was in flight at the upgrade to 0.10 |
| `linear` | no | a tracker id such as `GOO-73`, for the pull request title |
| `landed_via`, `pr_url`, `landing_error` | no | how the slice reached the base branch |

The engine adds other fields as the slice moves, such as `context_cost_estimate`, `started_at_commit`, `parked_reason` and `closed_commit`. [File formats](../reference/file-formats.md) describes the substrate files.

## Add a slice

Add each slice with the CLI. Never edit the JSONL by hand.

```bash
harness backlog add --id orders-1 --title "Paid order writes one event" \
  --acceptance tests/slices/test_orders_1.py \
  --declares orders --predicts src/orders/service.py \
  --depends billing-1 --verifies V-orders-1,V-orders-2 --linear GOO-73
```

- `--acceptance` is required, because each slice starts from red tests. Its paths also go into `predicted_files`.
- `--declares` takes registry ids. An unknown id fails the command.
- `--verifies` takes ids separated by commas or spaces. You can repeat it. Each id must be in `.harness/verify.jsonl`.
- `--linear` must look like `GOO-73`.
- The command refuses an id that the backlog already holds.

The row always gets a `verifies` list, also when it is empty. The upgrade reads a row with no `verifies` key as a row from before 0.10.

## Context cost

`harness backlog` with no subcommand sizes each slice. It builds the context that the slice would get at its first prompt: findings, cited decision rows, non-goals, the slice card and module pointers.

- It writes `context_cost_estimate` on each row, in estimated tokens. One token is about 4 characters.
- It warns with `CONTEXT_OVER_CAP` when the blocks do not fit in `MAX_INJECTION_CHARS` (9,000 characters).
- Its output gives `chars`, `demand_chars`, the `cut` blocks and `tokens` for each slice.

A warning at plan time is cheaper than a cut at build time. Split the slice, or shorten the decision rows that it cites.

## Split proposals

A slice is oversized when its context does not fit the cap and it declares two or more modules. `harness backlog` proposes a split for each oversized slice. `--no-split` turns proposals off.

- The command never splits a slice by itself. The parent row stays.
- A proposal goes into `split_proposals`, with child ids `<id>-a` and `<id>-b` and the declared modules in two halves.
- The same slice also goes into `split_refused`, with the reason that children need their own contracts.
- Each child needs its own acceptance tests and predicted files. You add each child with `harness backlog add`.
- A slice that is not `planned` goes into `split_refused`, because closed, bound and parked rows are not rewritten.
- A parent that other slices depend on goes into `split_refused`, because a split would leave their `depends_on` pointing at nothing.
- A child id that already exists stops the command before any write, with exit 1.

## Statements without a slice

`harness backlog` also reports `unowned_statements`: each statement in `.harness/verify.jsonl` that no slice lists in `verifies`. A statement that no slice owns never gets a test that close checks.
