# Decision cards

A decision card puts one big decision in front of a human in a fixed format. The agent recommends one option, and the human chooses. Each chosen card becomes an ADR with one decision row.

## When to write a card

Write a card for each big decision. Big decisions are these:

- stores;
- transports;
- tiers;
- seams, such as an API contract or shared types;
- trust boundaries;
- anything that is hard to undo.

Explore, architect and design review use the same format. Cards from explore live in `explore/DECISIONS.md`, and `harness explore --freeze` checks them. The format is in the explore skill, in [`card.md`](https://github.com/peekwez/harness/blob/main/skills/explore/card.md).

## Card format

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

The 1st order effect is what changes at once. The 2nd order effect is what that change causes, for example in tests, CI or operations. The 3rd order effect is what it means in a year, for example cost, hiring or the next big decision.

## Rules

The freeze checks the format rules:

1. Each card id has the form `D-E<n>` and is unique in the file.
2. Each field is one or two sentences in plain words. No field keeps template text.
3. The card fields are `Why now`, `Evidence`, `Would change it`, `Chosen` and `Reason`. `Domain` is optional, and its default is `architecture`.
4. A card has two or more options. Each option has all seven fields: Solves, Example, Trade-off, 1st order, 2nd order, 3rd order and Undo cost.
5. Exactly one option is marked `(recommended)`.
6. `Undo cost` starts with low, medium or high, then says why.
7. `Evidence` names a file, a command or an observation from the toy. When the toy cannot show it, write `no evidence: <reason>`.
8. `Chosen` is an option letter from the card, or `parked`. Only the human sets it.

The skill sets the conversation rules:

1. The agent shows one card at a time and waits for the answer.
2. The agent ends each card with: "Reply with a letter, 'explain more about X', or 'not sure, park it'."
3. For a letter, the agent writes it in `Chosen` and the human's reason in `Reason`.
4. For "explain more about X", the agent explains X again with a new example. The card stays the same unless the human gives a new fact.
5. For "not sure, park it", the agent writes `parked` in `Chosen`. It moves the question to `explore/OPEN.md`, with an owner and a trigger.
6. For "you choose", the agent picks the recommended option and writes `delegated: <their words>` in `Reason`. Then it asks the human to confirm.
7. A vague reply is not a choice. The agent asks again and names the options.

Skill level changes how much the agent explains around the card: the words, the examples and how far it spells out each effect. It never removes a field. The explore skill's [`calibrate.md`](https://github.com/peekwez/harness/blob/main/skills/explore/calibrate.md) sets the questions and the levels.

## From card to decision row

`harness architect --from-explore` writes one ADR for each chosen card. The ADR front matter holds one decision row, and the ADR body holds the full card. The row takes these values:

- `id`: the card id, such as `D-E1`.
- `domain`: the card's `Domain`, or `architecture`.
- `question`: the card's question.
- `answer`: the chosen option's name, `Solves`, `Trade-off` and `Undo cost`, and the ADR path. The answer has 150 words or fewer.

The freeze already checks the 150-word limit for each chosen card. `harness compile` warns on any decision answer over 150 words.

The example card in `card.md` chooses option A, "SQLite file", for "Where do orders live?". Its row answer is this text:

```text
SQLite file. One file holds all orders. No server runs. Trade-off: One writer at a time. Undo cost: medium, the SQL is portable but the file path is everywhere. Full card: adr/004-where-do-orders-live.md.
```

The [0.10 design spec](https://github.com/peekwez/harness/blob/main/docs/internal/superpowers/specs/2026-10-02-harness-0.10-design.md#3-decision-log) records its own decisions, D-0.10-01 to D-0.10-14, in a compact form of the card. It shows the chosen option in full and lists the other options under `Rejected`. This is D-0.10-03, copied from the spec:

```markdown
### D-0.10-03: How to enforce verification first

- **Chosen:** record red at slice start, check at close. An edit before the red record gives a one-line advisory.
- **Solves:** tests that pass before the code exists. Example: a slice whose suite is green at start cannot close without a recorded reason.
- **Trade-off:** an agent can still edit source before the red record. Close catches it.
- **1st order:** `harness slice start` runs the acceptance suite once.
- **2nd order:** each slice stores evidence that its tests could fail.
- **3rd order:** the "wrong object" defect class from astralabs becomes visible at close.
- **Undo cost:** low.
- **Rejected:** block all edits until red (extra friction on each slice); execute mutants at close (slow; needs a mutation format).
```

## Decision rows and ADRs

A decision row answers a recurring choice in one place. An agent looks it up and obeys it. A row in `.harness/decisions.jsonl` has these fields:

| Field | Meaning |
|---|---|
| `id` | the row id, such as `D-014` or `D-E1` |
| `domain` | the module or domain that implements the rule |
| `question` | the recurring question |
| `answer` | one imperative, self-contained answer |
| `adr_ref` | the ADR that holds the reasons; null for a row from adjudication |
| `origin` | `phase0` from an ADR, or `adjudication` |
| `created` | the time that compile or adjudication wrote the row |

The ADR holds the context, the options and the reasons. The row binds, and the ADR explains. A row from adjudication keeps priority over a row with the same id from an ADR.

`/harness:adr-authoring` writes ADRs. An accepted ADR in `adr/NNN-<title>.md` is immutable. A change is a new ADR with `supersedes: [NNN]`. An ADR that is not accepted stays under `docs/design-reviews/drafts/`, outside the files that `harness compile` reads.
