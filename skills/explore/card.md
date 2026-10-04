# The decision card

Use this format for each big decision in `explore/DECISIONS.md`. The
command `harness explore --freeze` checks it. Architect and design review
use the same format.

A big decision is a store, a transport, a tier, a seam, a trust boundary,
or anything that is hard to undo. Choose a seam (for example an API
contract, shared types, or none; see `../architect/coverage-map.md`) with a
card.

```markdown
## D-E1: <question in plain words>

**Why now:** <one sentence>
**Evidence:** <what the toy showed: file, command or observation> | no evidence: <reason>
**Domain:** <optional: the decision-table domain, for example storage>

### Option A: <name> (recommended)
- Solves: <plain words>
- Example: <concrete case>
- Trade-off: <what you give up>
- 1st order: <direct effect>
- 2nd order: <effect of the effect>
- 3rd order: <longer-term effect>
- Undo cost: low | medium | high, <why>

### Option B: <name>
<same fields>

**Would change it:** <fact that would change the recommendation>
**Chosen:** A | B | parked
**Reason:** <the human's reason, in their words>
```

## Field rules

1. Each field is one or two sentences in plain words.
2. Each option has all seven fields: Solves, Example, Trade-off, 1st order, 2nd order, 3rd order and Undo cost.
3. `Solves` names the problem in plain words. `Example` shows one concrete case of that problem.
4. `Undo cost` starts with low, medium or high. Then it says why.
5. A card has two or more options. Mark exactly one option `(recommended)`.
6. `Evidence` names a file, a command or an observation from the toy.
7. When the toy cannot show it, write `no evidence: <reason>`.
8. `Chosen` is an option letter or `parked`. Only the human sets it.
9. `Domain` is optional. Architect uses it as the domain of the decision row. The default is `architecture`.
10. Each card id has the form `D-E<n>` and is unique in the file.

The other card fields are `Why now`, `Would change it` and `Reason`.

The skill level of the human changes how much you explain around the card.
It never removes a field. See [calibrate.md](calibrate.md).

## Orders of effect

- 1st order: what changes at once when you pick the option.
- 2nd order: what that change causes, for example in tests, CI or operations.
- 3rd order: what it means in a year, for example cost, hiring or the next big decision.

## Example

```markdown
## D-E1: Where do orders live?

**Why now:** The toy needs a store before the second feature.
**Evidence:** explore/bench.sh wrote 10,000 orders in 2 s on SQLite.
**Domain:** storage

### Option A: SQLite file (recommended)
- Solves: One file holds all orders. No server runs.
- Example: The toy wrote 10,000 orders in 2 s.
- Trade-off: One writer at a time.
- 1st order: No database server to run.
- 2nd order: Tests use a temp file.
- 3rd order: A second writer needs a move to Postgres.
- Undo cost: medium, the SQL is portable but the file path is everywhere.

### Option B: Postgres
- Solves: Many writers.
- Example: Two workers write orders at once.
- Trade-off: A server to run in dev and CI.
- 1st order: Docker in dev.
- 2nd order: CI needs a service container.
- 3rd order: Ops owns backups.
- Undo cost: low, the toy has no Postgres code yet.

**Would change it:** Two processes that write orders at once.
**Chosen:** A
**Reason:** We have one writer for a year.
```

## Show the card

Show one card at a time. Wait for the answer.

End each card you show with: Reply with a letter, 'explain more about X', or 'not sure, park it'.

## Answers from the human

- An option letter: write it in `Chosen`. Write their reason in `Reason`.
- "Explain more about X": explain X again with a new example. Keep the card the same unless the human gives a new fact.
- "Not sure, park it": write `parked` in `Chosen`. Add an entry to `explore/OPEN.md`.
- "You choose": pick the recommended option. Write `delegated: <their words>` in `Reason`. Ask the human to confirm.

```markdown
## D-E2: <question>
- Owner: <who decides>
- Trigger: <the event that reopens the question>
```

A vague reply is not a choice. Ask again and name the options.

## Statements

When `explore/VERIFY.md` exists, write every statement there; compile does not read the working document then.
