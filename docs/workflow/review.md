# Review

Review checks the slice diff against the substrate. A separate reviewer session does it, so the review does not share the builder's assumptions. Close runs the deterministic part of the review again and blocks on its findings.

## The forked reviewer

`/harness:review <slice>` runs in a forked session with the reviewer agent. The reviewer reads the substrate and the slice diff only. It never reads the builder's personal memory. It can read `.claude/memory/shared/`, because shared memory is substrate.

The reviewer starts with layer 0:

```bash
git diff --output=/tmp/harness-review-orders-1.diff main...HEAD
harness review --slice orders-1 --diff /tmp/harness-review-orders-1.diff --layer0-only
```

Use `landing.base` from `.harness/config.yaml` as the diff base. The default is `main`.

Then the reviewer runs `/harness:verification` and traces each acceptance criterion to evidence. Where the builder and the reviewer disagree, the substrate did not settle the answer. That disagreement is a signal.

`harness review --record-fork pass|block --slice <id>` records the verdict of a forked reviewer as an edge. ADR-001 makes it required for some slices. A slice that resolves a decision row marked `security: true` cannot close until a forked reviewer records `pass`. `review.fork_for_security_rows: false` turns this off.

## Four layers

1. **Layer 0: deterministic facts.** Gate output, uses against declares, duplicate candidates, decision rows in scope and the shadows of the diff's imports. It also flags glossary synonyms on added lines of changed Markdown files, as advisory findings.
2. **Layer 1: rubrics.** One narrow question per check, with a fixed answer: `pass`, `fail` or `uncertain`, a confidence and the evidence. The reviewer reads 2 or 3 precedents first.
3. **Layer 2: ensemble.** Only with `review.ensemble: true`. A would-block answer with confidence below 0.7 is sampled 3 times, and a split parks. With the ensemble off, that answer parks without new samples.
4. **Layer 3: advisory reviewers.** A holistic review gives proposals only, such as a new decision row or a new gate. It never blocks. Codex runs here as a second opinion when it is available.

Close runs layer 0 and the deterministic rubrics over the slice's own diff. A blocking finding stops the close. A blocking finding that the reviewer recorded also stops the close, until a later record of the same code clears it.

## The findings contract

Each finding has these fields:

| Field | Meaning |
|---|---|
| `finding_id` | a stable id, from the code, the rule and a key |
| `layer` | 0 to 3 |
| `severity` | `block`, `gate` or `advisory` |
| `code` | a code from the finding catalog |
| `rule_ref` | the rule, such as `gate:G6`, `decision:D-014` or `adr:002`; a reviewer cites a gate, a decision row or an ADR |
| `message` | the rule, what is wrong and the file, in 25 words or fewer |
| `fix` | one action that resolves the finding |
| `inject` | extra lines, such as the evidence or the failure scenario |
| `precedents` | ids of earlier adjudicated findings on the same question |

- A `block` finding stops the action. It must have a `rule_ref`, and the engine rejects a block without one.
- A `gate` finding waits for a human, such as a parked finding.
- An `advisory` finding informs and never stops anything.

No finding blocks on taste. A real problem that no rule covers becomes a layer 3 advisory and a proposed rule. The next slice can then block on it.

`harness gates explain <CODE>` prints the catalog entry for a code.

`harness review --record-finding` writes a reviewer finding as an edge. It needs `--slice`, `--message` and `--rule-ref`.

- `--message` must have 25 words or fewer. The CLI rejects a longer one with exit 2.
- `--failure-scenario` gives a concrete input and the wrong result.
- `--fix` gives one action. A `--severity block` finding needs it.
- `--code` must be a code from the catalog.

## Park and adjudicate

A reviewer that is not sure about a would-block finding parks it. It does not decide on a coin flip.

- `harness review --park` records the finding in `.harness/parked.jsonl` with severity `gate`.
- The review stack also parks an `uncertain` rubric answer.
- A slice with an open park cannot close.

A human resolves parks in the main session through `/harness:harness`, never inside the forked review:

```bash
harness adjudicate --list
harness adjudicate --finding-id F-1a2b3c4d5e --resolution "Raise OrderError" --decision-id D-031 --domain errors
harness adjudicate --finding-id F-1a2b3c4d5e --resolution "Accept the copy in this test helper"
```

- Each resolution writes a `decided_by` adjudication edge and removes the park.
- With `--decision-id` and `--domain`, it also writes a decision row with `origin: adjudication`. It refuses an id that exists.
- A one-off ruling writes the edge only. The output suggests a `harness memory promote --text` command, and the human decides whether to run it.
- `--reverses` marks a ruling that reverses an override. Slice metrics count reversals.

A question that a human already decided does not park again. The review shows the precedent as an advisory finding. The goal is fewer parks per slice over time.
