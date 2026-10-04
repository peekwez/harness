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

- A row's `domain` names the module or domain that IMPLEMENTS the rule: the registry entry's id or its `domain` field. It does not name the feature area that the rule serves. Example: `domain: errors` for a validation rule that the errors slice builds, even if it is "about" the API.
- `kind` is a structural bucket: config, logging, errors, telemetry, util, component or other. The entry's `domain` is the semantic key. It keeps any custom kind, such as `data` or `api`. Decision routing and author-gate coverage both use it. Only a literal domain of `other` is exempt from coverage.
- Safety net: a slice that loads an ADR as guidance gets the rows of that ADR in its decisions block, whatever their domain. Route by domain anyway. The safety net stops when the entry is built and its shadow supersedes the ADR guidance.

Rules:

- Answers are imperative and self-contained — no "see above", no "usually".
- One question per row. Compound answers mean two rows.
- Rows originate from ADR frontmatter (phase0) or adjudication; adjudicated
  rows outrank recompiled phase0 rows with the same id.
- Agents resolving a domain question: query `decisions.jsonl` first. If no
  row answers it and the question will recur, that's an adjudication
  candidate — park it rather than improvising.
