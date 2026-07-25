---
name: decision-tables
description: When a choice belongs in a decision table row versus a full ADR; the row schema; lookup-never-interpret. Use when handling recurring choices, conventions, style questions, "which pattern should I use", "what's our convention for", error handling style, naming, propagation rules, or any question an agent might answer differently per-file.
---

# Decision tables

The principle: **lookup, never interpret.** Principles get reinterpreted
per-file — every agent, every session, slightly differently. Table rows
don't. If a question can recur, it must be a row.

Row vs ADR:

- **Row** (`decision_table_rows` in ADR frontmatter -> `decisions.jsonl`):
  a recurring choice with one atomic answer. "Error propagation style?" ->
  "Raise domain exceptions; never return None for failure." An agent reads
  it and obeys; there is nothing to weigh.
- **Full ADR prose**: one-off architecture with tradeoffs that need
  extrapolation in novel situations. The prose *justifies*; rows *bind*.

Row schema (§5.5): `{id: D-NNN, domain, question, answer, adr_ref,
origin: phase0|adjudication, created}`.

Domain routing (how a row reaches a builder):

- A row's `domain` should name the module/domain that IMPLEMENTS the rule
  (the registry entry's id or its `domain` field), not the feature area it
  serves — `domain: errors` for a validation rule the errors slice builds,
  even if it's "about" the API. `kind` is a structural bucket
  (config/logging/errors/telemetry/util/component/other); the entry's
  `domain` (preserved from any custom kind, e.g. `data`, `api`) is the
  semantic key that both decision routing and author-gate coverage use.
  Only a literal domain of `other` is exempt from coverage.
- Safety net: rows authored in an ADR that a slice loads as guidance are
  injected into that slice's decisions block regardless of domain — but
  route by domain anyway; the safety net stops working once the entry is
  built and the ADR's guidance is superseded by its shadow.

Rules:

- Answers are imperative and self-contained — no "see above", no "usually".
- One question per row. Compound answers mean two rows.
- Rows originate from ADR frontmatter (phase0) or adjudication; adjudicated
  rows outrank recompiled phase0 rows with the same id.
- Agents resolving a domain question: query `decisions.jsonl` first. If no
  row answers it and the question will recur, that's an adjudication
  candidate — park it rather than improvising.
