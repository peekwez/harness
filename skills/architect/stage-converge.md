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

Mark each resolved question `[resolved: adr/NNN]` in the working document.

Exit criteria: no unresolved `[open-question]` blocks remain (deferred ones
carry `deferred: <owner>`). Mark `<!-- stage: 4 -->`.
