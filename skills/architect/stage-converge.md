# Stage 3 — Converge protocol

For each `[open-question]` in the working document:

1. Present 2–3 options with tradeoffs (a table: option, cost, risk, reach).
2. The human picks, or explicitly delegates the pick ("you choose" is
   recorded as such).
3. Write the ADR: Nygard format with machine frontmatter —
   `{id, status, domains[], supersedes[], decision_table_rows[]}` — using the
   adr-authoring skill and `templates/adr.md`. Recurring choices go into
   `decision_table_rows` (lookup, never interpret); one-off architecture
   stays prose.

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

Exit criteria: no unresolved `[open-question]` blocks remain (deferred ones
carry `deferred: <owner>`). Mark `<!-- stage: 4 -->`.
