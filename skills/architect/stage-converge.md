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

1. Present 2–3 options with tradeoffs (a table: option, cost, risk, reach).
2. The human picks, or explicitly delegates the pick ("you choose" is
   recorded as such).
3. Write the ADR: Nygard format with machine frontmatter —
   `{id, status, domains[], supersedes[], decision_table_rows[]}` — using the
   adr-authoring skill and `templates/adr.md`. Recurring choices go into
   `decision_table_rows` (lookup, never interpret); one-off architecture
   stays prose. Keep pending ADRs in the adr-authoring skill's nonbinding
   draft directory; put them in `adr/` only after acceptance under the human's
   existing choice/delegation, with the review limitation disclosed.

A row whose decision needs no ADR prose (a convention, a naming rule, the
rows a `--from-spec` seed is waiting for) may instead be written straight
into the working document's fenced tables, which compile identically
(ADR-002 D-013):

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
focused design-review follow-up, including the proposed ADRs and contracts.
Read its existing round count across sessions. If the budget is spent or the
peer is unavailable, record unreviewed changes and surface them with remaining
choices under the human/delegation contract; do not claim current peer coverage.

Exit criteria: no unresolved `[open-question]` blocks remain (deferred ones
carry `deferred: <owner>`). Mark `<!-- stage: 4 -->`.
