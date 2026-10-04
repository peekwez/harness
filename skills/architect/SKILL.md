---
name: architect
description: Use for Phase-0 architecture, system design, or importing an existing spec. Guides brainstorming, the red-team premortem ("what could go wrong", silent failures, fallback paths), seam decisions such as API contracts, independent Claude/Codex design review, convergence, compilation and the human author-gate.
allowed-tools: Bash(*/bin/harness *) Bash(codex exec *) Bash(claude -p *)
---

Run this workflow for work the user has requested. In Codex, resolve the
plugin root from this skill path and invoke `python3 <plugin-root>/bin/harness`
with an explicit project `--root`; the `!` substitutions and
`${CLAUDE_PLUGIN_ROOT}` examples below use Claude Code syntax.


# /harness:architect

You drive Phase 0 in five stages. The working document is
`docs/architecture.md` (a source command creates it (`--from-explore`, `--from-spec`
or `--skip-explore`)). Every stage writes typed
blocks to that document as it goes: long architecting is multiple short
sessions over a durable artifact — never rely on transcript survival.

Use `harness:design-review` (sibling `../design-review/SKILL.md`) for an
independent critique from the other host when available. Claude Code leads
with Codex as peer; Codex leads with Claude Code as peer. The lead synthesizes
findings into the working document; the peer does not edit or sign it.
Design verification alongside each feature using `../verification/design.md`:
happy-path and relevant edge/failure/recovery scenarios, independent expected
results, real runtime checks and planned code-coverage/trace attribution. Keep
the matrix in the working design and include it in the peer's input packet.

**The working document needs a source.** When `docs/architecture.md`
exists, resume at its stage marker. Otherwise run one of these commands as
your first action:

- `explore/DECISIONS.md` is frozen: `"${CLAUDE_PLUGIN_ROOT}/bin/harness" architect --from-explore`. It writes one ADR and one decision row for each chosen card. It seeds the document at stage 3.
- The repo has a spec (a design doc, an RFC, a platform spec): `"${CLAUDE_PLUGIN_ROOT}/bin/harness" architect --from-spec <path>`. Do not derive the spec again question by question.
- The human chose to skip explore: `"${CLAUDE_PLUGIN_ROOT}/bin/harness" architect --skip-explore "<reason>"`. Write the human's reason in their words. It records the reason in the working document. A new document starts at stage 1.

With none of these, `harness architect` refuses to start. Run
`/harness:explore` first.

After `--from-explore`, do not ask again a question that a card answers.
The decision row cites the ADR that holds the full card.

`--from-spec` writes `docs/architecture.md` at `<!-- stage: 3 -->`
(converge). Each `##` or `###` heading becomes a `[constraint]` block with
its first paragraph. Each `TODO`, `TBD` or `Open:` line becomes an
`[open-question]`. The document ends with an empty
```` ```harness-decisions ```` table. It refuses to overwrite an existing
working document without `--force`. Read the seeded blocks with the human.
A seeded constraint is a claim to confirm, not a ratified decision. Then
continue at stage 3 below. Imported specs still need design review.
Imported approval claims do not count as the review of this repo.

Each new big decision uses the decision card in
[../explore/card.md](../explore/card.md). Use
[../explore/calibrate.md](../explore/calibrate.md): calibrate before the
first card when explore did not run.

Determine the current stage by reading the working document's `<!-- stage: N -->`
marker (default 1 if absent), then follow the matching protocol file:

1. Brainstorm: follow `stage-brainstorm.md` (with `coverage-map.md`). With superpowers installed, `superpowers:brainstorming` drives this stage. The spec file it writes IS `docs/architecture.md`. After design approval, go to stage 2 below, never `superpowers:writing-plans`.
2. Red-team — `stage-redteam.md` (with `premortem.md`)
3. Converge — `stage-converge.md`
4. Compile — `stage-compile.md`
5. Author-gate — run:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" author-gate --report --doc docs/architecture.md`

(The `--report` output above is workflow state, not an error: `gaps` are
expected until stage 5 — read `passed` in the JSON. Before stage 5, use the
gap list only to see what remains.)

Stage-5 rules: if the gate reports gaps, walk the human through each gap and
loop back to the stage that owns it (missing decision rows -> converge;
unresolved open questions -> brainstorm). Progression is blocked until every
sliceable domain has at least one decision row, every open question is
resolved or deferred-with-owner, and the registry covers the
spec's dependency mentions. **The human signs here — this is the one
deliberate checkpoint.** Fully agent-authored Day 0 is out of scope; do not
offer to sign on the human's behalf.

On entry to stages 3–5, check the design-review record against current authored
inputs and check the verification design for gaps, including imported specs.
Undefined required verification methods prevent an implementation-ready claim;
the engine author-gate does not mechanically validate this matrix.
Run missing critique or a material-change follow-up within its two-round
budget, then recompile any changed authored artifacts before author-gate.
Record unavailable/failed peers and continue the local review; do not retry at
every stage or claim peer approval. Surface incomplete/superseded coverage and
remaining decisions to the human at final signoff.

At every stage boundary: update the `<!-- stage: N -->` marker, tell the user
the session can safely end, and name the workflow that resumes: `/harness:architect`
in Claude Code, or the architect skill in Codex. The CLI `architect --from-spec`
seeds a document; it is not the command for resuming the design conversation.
