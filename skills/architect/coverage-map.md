# Coverage map — domains × decision-types

Maintain this matrix in the working document. Rows are the project's domains
(errors, logging, config, telemetry, data, auth, api, ui, infra — prune or
extend per project). Columns are decision-types:

| domain | naming/structure | error handling | persistence | interfaces | testing | non-goals |
|---|---|---|---|---|---|---|

Cell states: `?` (empty — generates the next question), `D-NNN` (decided),
`deferred: <owner>`, `n/a` (human explicitly ruled out of scope).

The elicitation loop: pick the highest-risk empty cell, ask one question
about it, record the typed block, update the cell. Never ask about a filled
cell; never skip to detail while a whole row is empty.

## Seams

When the design has a frontend/backend or service-to-service boundary,
write a decision card for the seam: an OpenAPI contract, shared types, or
no formal contract. Harness does not check contracts. A team that wants
contract checks adds a `gates.extra` gate or a linter in CI, and records
that choice in the card.
