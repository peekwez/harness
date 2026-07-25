---
id: "001"
status: accepted
domains: [review]
supersedes: []
decision_table_rows:
  - id: D-004
    domain: review
    question: "When is an independent (forked) LLM review mandatory before close-slice?"
    answer: "When any decision row resolving for the slice carries security: true. The close ceremony blocks (rule_ref adr:001) until a forked reviewer records a pass verdict: `harness review --record-fork pass --slice <id>`. All other slices close on the deterministic engine review stack alone."
  - id: D-005
    domain: review
    question: "Who records the fork verdict?"
    answer: "Only a reviewer session with fresh context (the harness:reviewer agent) that saw substrate + diff and no builder session memory. The builder that produced the diff never records its own verdict."
  - id: D-006
    domain: review
    question: "Which decision rows get security: true?"
    answer: "Rows whose violation leaks secrets, weakens auth/crypto, or widens attack surface (seed handling, token redaction, permission boundaries). Mark them in ADR frontmatter (`security: true` on the row); the compiler carries the flag into decisions.jsonl."
abstractions: []
api_surface: []
---

# ADR-001: Independent forked review is mandatory for security-relevant slices

## Status

Accepted.

## Context

The autonomous slice loop closes on the deterministic engine review stack
(layer-0 facts, rubric checks, gates G1–G8). That stack catches rule
violations it can enumerate. The most serious catch of the rt-pilot
campaign — slice-003's seed value leaking into telemetry span attributes —
came from neither: it was found by a **forked LLM reviewer**, a fresh
session holding only substrate and diff, with none of the builder's
rationalizations in context.

That reviewer only ran when a human or orchestrator happened to invoke it.
Full autonomy that skips it silently trades away exactly that class of
catch, on exactly the slices where the cost of a miss is highest. The
opposite extreme — a mandatory fork for every slice — doubles the cost of
every close for a class of defect most slices cannot exhibit.

## Decision

Fork review is mandated **by data classification, not by blanket policy**:

1. Decision rows may carry `security: true` (authored in ADR frontmatter;
   the compiler preserves the flag into `decisions.jsonl`).
2. A slice is **security-relevant** iff any security-marked row resolves
   for it — the row's domain matches the slice's declared deps' ids or
   kinds, or the slice declares no deps (all rows join, mirroring the
   resolver's routing; when in doubt the gate errs toward review).
3. `close-slice` blocks a security-relevant slice (`rule_ref: adr:001`)
   until the **latest** recorded fork verdict for the slice is `pass`.
   Verdicts are auditable `reviewed_by` edges written by
   `harness review --record-fork pass|block --slice <id> [--notes …]`.
4. The verdict is recorded by a fresh-context reviewer session (the
   `harness:reviewer` agent) — never by the builder session that produced
   the diff. A `block` verdict does not unlock the close; a later `pass`
   (after fixes and re-review) does.
5. All other slices close engine-only, unchanged. The mechanism is
   config-gated (`review.fork_for_security_rows`, default `true`).

## Consequences

- The autonomous loop stays autonomous: builders hitting the block dispatch
  the reviewer agent themselves; a human only enters on a parked finding,
  as today.
- The cost of the fork (a second model pass) is paid only where the
  campaign showed it earns its keep; the marginal slice is untouched.
- Security relevance becomes an *authored* property of the decision table,
  reviewable in ADR diffs, rather than an orchestrator's judgment call at
  close time.
- A mis-scoped domain on a security row silently narrows enforcement —
  authors must give security rows the domains of the abstractions they
  guard (D-006), and review of ADR frontmatter should treat a security
  row's domain as load-bearing.

## Considered Alternatives

- **Fork review for every slice**: maximally safe, but doubles close cost
  for defect classes the engine stack already covers; rejected as the
  default (a repo may still opt in by marking broad rows).
- **Orchestrator-invoked review only** (status quo): the seed-leak class of
  catch depends on someone remembering; rejected — enforcement intent must
  be explicit and deterministic.
- **A severity heuristic over diffs** (path patterns, entropy scans):
  guesses at security relevance instead of reading the substrate's own
  classification; rejected as interpretation where a lookup exists.

## Implementation

`bin/harness` close-slice precondition 1.5 + `review --record-fork`;
`engine/compiler.py` carries `security: true` through row compilation;
`reviewed_by` in `engine/graph.py` EDGE_TYPES; default config
`review.fork_for_security_rows: true`. The build and close-slice skills
name the block's remedy; `agents/reviewer.md` owns verdict recording.
