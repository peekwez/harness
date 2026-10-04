# Stage 3 — Converge protocol

Check `harness:design-review` coverage on entry, including `--from-spec` imports
that start here without stage 2. Get the other host's initial critique if
missing; reuse the recorded availability result when nothing has changed.
For imported specs, also perform the stage-2 local premortem before converging:
hunt silent failures and inherited assumptions, and resolve every real risk
into a decision or `[accepted-risk]` block (or rebut it with evidence). The
stage-3 import shortcut skips elicitation, not this risk-resolution obligation.
Imports and resumed designs also need the AC/scenario verification matrix from
`../verification/design.md`. Resolve undefined required checks before declaring
implementation readiness; do not treat planned tests as executed PASS evidence.

For each `[open-question]` in the working document:

1. Write a decision card for the question. Use `../explore/card.md`. Each option gives what it solves with an example, the trade-off, the 1st, 2nd and 3rd order effects, and the undo cost. Use [../explore/calibrate.md](../explore/calibrate.md): calibrate before the first card when explore did not run. End each card you show with: Reply with a letter, 'explain more about X', or 'not sure, park it'.
2. The human answers with an option, "explain more about X", or "not sure, park it". A parked question gets `deferred: <owner>` and a trigger. A vague reply is not a choice. The human can also delegate the pick with "you choose". Delegation is an explicit choice: pick the recommended option, write `delegated: <their words>` in `Reason`, and ask the human to confirm.
3. Write the ADR: Nygard format with machine frontmatter —
   `{id, status, domains[], supersedes[], decision_table_rows[]}` — using the
   adr-authoring skill and `templates/adr.md`. Recurring choices go into
   `decision_table_rows` (lookup, never interpret); one-off architecture
   stays prose. Keep pending ADRs in the nonbinding draft directory of the
   adr-authoring skill. Move an ADR to `adr/` only after acceptance under the
   human's existing choice or delegation, and disclose the review limitation.
   Put the full card in the ADR body.

Some rows need no ADR prose: a convention, a naming rule, or the rows that a `--from-spec` seed waits for. You can write these rows into the fenced tables of the working document instead of an ADR. They compile the same way (ADR-002 D-013):

````
```harness-decisions
| id | domain | question | answer | adr_ref | security |
| --- | --- | --- | --- | --- | --- |
| D-020 | config | Where do defaults live? | In config.yaml, never in code. | | |
```

```harness-abstractions
| id | kind | guidance_ref | source | module_id |
| --- | --- | --- | --- | --- |
| config | config | docs/architecture.md | src/app/config.py | |
```
````

`adr_ref` and `security` may be left empty, and the abstraction table's
three-column form (`id | kind | guidance_ref`) is still accepted.
Module-level abstractions need `source` (or `module_id`), or the id must
equal the dotted module id, else G5 and the resolver cannot see them —
`module_id` is derived from `source` when the cell is blank. One id belongs
to exactly one source: an id in both an ADR and this document is a hard
compile error naming both.

Mark each resolved question `[resolved: adr/NNN]` in the working document.

Before accepting the resulting ADRs, batch material changes into the one
focused design-review follow-up, including the proposed ADRs.
Read its existing round count across sessions. If the budget is spent or the
peer is unavailable, record unreviewed changes and surface them with remaining
choices under the human/delegation contract; do not claim current peer coverage.

Exit criteria: no unresolved `[open-question]` blocks remain (deferred ones
carry `deferred: <owner>`). Mark `<!-- stage: 4 -->`.
