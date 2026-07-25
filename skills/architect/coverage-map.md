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
