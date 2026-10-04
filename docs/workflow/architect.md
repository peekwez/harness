# Architect

Architect turns a design into decision rows, ADRs and registry entries. It runs in five stages over one working document, `docs/architecture.md`. A human signs the result at the author gate.

## Three ways to start

The working document needs a source. `harness architect` takes one of three:

```bash
harness architect --from-explore
harness architect --from-spec docs/spec.md
harness architect --skip-explore "the team ships this design for a second client"
```

With no flag, `harness architect` acts as `--from-explore` when `explore/` is frozen. Otherwise it refuses to start. `--doc <path>` names another working document.

### From explore

`--from-explore` reads the frozen cards in `explore/DECISIONS.md`. It refuses when the file is not frozen, when a card is not valid, or when the cards changed after the freeze.

For each chosen card, it writes one ADR, `adr/NNN-<slug>.md`, with `status: accepted`:

- The ADR front matter holds one decision row. Its id is the card id, such as `D-E1`.
- The row domain comes from the card's `**Domain:**` line. The default is `architecture`.
- The row answer has 150 words or fewer: the chosen option, what it solves, the trade-off, the undo cost and the ADR path.
- The ADR body holds the full card.

In the working document, each chosen card becomes a `[constraint]` block that ends with "Do not ask this again." The agent does not ask again a question that a card answers. Each parked card becomes an `[open-question]` with its owner and trigger from `explore/OPEN.md`.

A new working document starts at stage 3. An existing working document keeps its content and keeps its stage marker. The command adds blocks only for cards that the document does not hold yet.

Later runs follow these rules:

- A parked card that a human chose since the last run: its seeded `[open-question]` becomes a `[constraint]` block. A hand-edited open question stays, and the command prints a `check:` line.
- An accepted ADR is never rewritten. When a card changes, the command refuses. Write an ADR that supersedes the old one, then run the command again.
- After a superseding ADR, the card gets a new ADR, and its `Decided:` line points to the new ADR.
- An accepted ADR whose card is now parked or gone gives a `check:` line. Write an ADR that supersedes it.
- `--force` reseeds the working document from scratch. It never rewrites an ADR.

### From a spec

`--from-spec <path>` seeds the working document at stage 3 from an existing spec. Each `##` or `###` heading becomes a `[constraint]` block with its first paragraph. Each `TODO`, `TBD` or `Open:` line becomes an `[open-question]`. The document ends with an empty `harness-decisions` table.

It refuses to overwrite an existing working document. `--force` overwrites it. A seeded constraint is a claim to confirm with the human, not a decision.

### Without a toy

`--skip-explore "<reason>"` records the reason as a `<!-- explore-skipped: <reason> -->` line. A new document starts at stage 1. An existing document keeps its content and gets the line. An empty reason is refused.

On the spec and skip paths, the agent calibrates before the first card, with the same questions as explore.

## Stages

The `<!-- stage: N -->` marker in the working document records the stage. Each stage writes typed blocks, such as `[constraint]`, `[open-question]` and `[non-goal]`, so a later session can resume.

1. **Brainstorm.** The agent fills the coverage map with the human. With superpowers installed, `superpowers:brainstorming` drives this stage.
2. **Red-team.** The agent attacks the design with the premortem checklist: silent failures, fallback paths and scale cliffs.
3. **Converge.** The agent writes decision rows and abstractions into the typed tables. Each new big decision uses a [decision card](../decision-cards.md).
4. **Compile.** `harness compile` turns the ADRs and the working document into substrate.
5. **Author gate.** The human signs.

A contract seam, such as an API contract or shared types, is a decision card topic. harness does not check OpenAPI files in core.

## Design review by a second model

`/harness:design-review` gets an independent critique from the other host, when it is available:

- Claude Code leads, and a fresh Codex process critiques.
- Codex leads, and a fresh Claude Code process critiques.

The peer gets a packet: the requirements, the design, the options, the verification matrix and exact excerpts. It returns at most five findings. When the design has decision cards, the peer attacks each card's "Would change it" line and its `Evidence`.

The lead verifies each finding. It records each one as accepted, rebutted or deferred, with a reason. Peer agreement does not sign the author gate.

The effort has a limit: one critique, and at most one focused follow-up for each design task. The lead writes the inputs, the peer response, the dispositions and the coverage under `docs/design-reviews/`.

When the peer is missing, not signed in or fails, the lead records the limit and goes on with local review. A missing peer is never a pass. The second model costs tokens.

## Compile

`harness compile --doc docs/architecture.md` reads the authored files:

- `adr/*.md`: the `decision_table_rows` and abstractions in the front matter, and the `[non-goal]` blocks. It skips superseded ADRs.
- The working document: the fenced `harness-decisions` and `harness-abstractions` tables, and the `[non-goal]` blocks.
- `explore/VERIFY.md`, or the verification matrix in the working document when `VERIFY.md` does not exist.

It writes the derived files:

- `.harness/decisions.jsonl`: one row per decision. A row from adjudication keeps priority over a row with the same id from an ADR.
- `.harness/registry.jsonl`: one `planned` entry per abstraction.
- `.harness/boundaries.jsonl`: one scope boundary per non-goal.
- `.harness/verify.jsonl`: one row per statement. Compile replaces only the rows of the source that it compiled.

Compile also reports:

- a warning for each decision answer over 150 words;
- each non-goal that no gate cites, under `advisory_only`, as "advisory only";
- each test comment that names an unknown statement, as `UNKNOWN_TEST_LINK`.

Without `--doc`, compile warns when `docs/architecture.md` holds typed tables or statements that it did not compile.

## Author gate

`harness author-gate --doc docs/architecture.md` checks that Day 0 is complete:

- Each registry domain, other than `other`, has at least one decision row.
- No decision row, registry entry or slice holds scaffold placeholder text.
- Each module that a slice declares is in the registry.
- Each open question is resolved, or deferred with an owner.
- Each guidance reference of the registry points to a file that exists.

It exits 1 on a gap. `--report` always exits 0 and puts the verdict in the JSON `passed` field. The skills use `--report`, because gaps are normal before stage 5.

The human signs here. This is the one deliberate checkpoint of architect. The agent never signs for the human.
