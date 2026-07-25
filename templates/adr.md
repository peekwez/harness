---
id: "000"
status: proposed        # proposed | accepted | superseded
domains: []             # e.g. [telemetry, errors]
supersedes: []
decision_table_rows: []
#  - id: D-001
#    domain: errors
#    question: "Error propagation style?"
#    answer: "Raise domain exceptions; never return None for failure."
abstractions: []
#  - id: telemetry
#    kind: telemetry     # enum: logging|telemetry|config|errors|util|component|other
#    source: services/api/telemetry.py
#    section: s2
#    replaces: []        # planned scaffold entries this abstraction merges away
# kinds outside the enum coerce to 'other' with a compile warning; decision
# rows still reach slices by matching the abstraction id as a domain.
api_surface: []
#  - "GET /orders"
---

# ADR-000: Title

## Status

Proposed.

## Context

What forces are at play? Prose here is for agent extrapolation in novel
situations; the frontmatter above is what the resolver queries.

## Decision

What we decided, stated as an imperative.

## Consequences

What becomes easier, what becomes harder.

## Considered Alternatives

2–3 options with tradeoffs; why the losers lost.

## Implementation

Pointers, not plans. [non-goal] blocks here compile into G3 scope boundaries.
