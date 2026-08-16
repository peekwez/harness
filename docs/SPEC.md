# harness spec glossary

The skills and engine cite section and component markers (`§5.6`, `C7`,
`T1`, `M4`). Those come from the original design document, which is not
vendored here — so this file defines every marker they use. **Lookup, never
interpret** applies to the harness's own docs too: an agent told to obey
`§5.6` must be able to resolve it.

Adding a marker to a skill means adding its definition here; the test
`tests/engine/test_review_fixes.py::test_spec_glossary_resolves_every_referenced_marker`
fails otherwise.

## Components (C-markers)

| Marker | Component | Lives in |
|---|---|---|
| C1 | Event contract & engine shell — the five events, EnforcementEvent → EnforcementVerdict, sidecar state | `engine/events.py` |
| C2 | Extractor — tree-sitter → universal shadows, content-hash + extractor-version cache | `engine/extractor/` |
| C3 | Resolver — slice → assembled context under a token budget, with ranked degradation | `engine/resolver.py` |
| C4 | Compiler — authored ADRs → substrate (decision rows, registry skeletons, G3 boundaries) | `engine/compiler.py` |
| C5 | Registry & provenance graph — abstractions, manifests, edges, git notes | `engine/registry.py`, `engine/graph.py` |
| C6 | Gates — G1–G8, each declaring preferred/fallback events | `engine/gates/` |
| C7 | Review stack — Layer 0 facts, Layer 1 rubrics, Layer 2 ensemble, Layer 3 advisory | `engine/review/` |
| C8 | Acceptance harness — the toy repo end-to-end suite | `tests/engine/test_e2e.py` |
| C9 | CI verifier — `harness verify`, runs with no plugin installed | `bin/harness` |

## Transitions / design tenets (T-markers)

| Marker | Tenet |
|---|---|
| T1 | Portability: gates declare preferred **and** fallback events, so hosts without pre-change interception run degraded (revert-and-retry) rather than unenforced. |
| T2 | Reconciliation: a unit cannot close until every touched file is declared, predicted, or overridden. |
| T3 | Escape hatches are auditable: an override is an edge with a written justification, never a silent bypass. |

## Milestones (M-markers)

| Marker | Milestone |
|---|---|
| M1 | Substrate scaffolding + provenance rule (`init`) |
| M2 | Extraction + resolution under budget |
| M3 | Gate pack enforcing on real events |
| M4 | Toy-repo acceptance: block → inject → pass, full close ceremony |
| M5 | Review stack + golden replay |
| M6 | Adjudication: parks resolve into substrate; the same question never parks twice |
| M7 | Autonomy: a bound slice runs start-to-close with no human intervention |

## Sections (§-markers)

| Marker | Section |
|---|---|
| §1.4 | Gates live in the CLI, not in prompts — enforcement is engine-side or it does not exist. |
| §1.5 | Compaction is a defect signal, not a feature: session cycling is the strategy. |
| §5.2 | Findings contract: `{finding_id, layer, severity, code, rule_ref, message, inject[], precedents[]}`. Every blocking finding cites a `rule_ref`; the engine rejects those without one. |
| §5.5 | Decision row schema: `{id: D-NNN, domain, question, answer, adr_ref, origin: phase0\|adjudication, created}` (+ optional `security: true`, see ADR-001). |
| §5.6 | Slice schema: `{id, spec, title, status, declares_dep[], acceptance[], predicted_files[], context_cost_estimate, depends_on[], worktree}` (+ `started_at_commit`, recorded at bind). |
| §5.7 | Node IDs in the graph are stable logical ids (`slice:`, `module:`, `file:`, `finding:`, `decision:`), never machine-specific absolute paths. |
| §7.5 | Close preconditions, engine-enforced: acceptance green, gates pass, uses ⊆ declares reconciled. |
| §7.7 | Park-once: a question already adjudicated surfaces its precedent instead of re-parking. |
| §8 | Memory model: session memory (working, compacted at close) vs durable memory (survives, edged to modules). |

## Finding codes raised outside the gate pack

Most finding codes are named by the gate that raises them (`gate:G1` …
`gate:G8`). These are raised by the engine itself and carry a non-gate
`rule_ref`:

| Code | Raised by | Meaning |
|---|---|---|
| `EXTRA_GATE_LOAD_ERROR` | `engine/gates/extra.py` (event dispatch and `harness verify`) | A `gates.extra` entry could not be loaded: it does not exist, is an absolute path or resolves outside the repo (path entries are repo-relative and contained — they name code the engine executes), fails to import, declares no valid `GATE` (`id` + `preferred`, known event names, an id unique across the pack), or exposes no callable `run(ctx)`. |
| `EXTRA_GATE_RUN_ERROR` | `engine/gates/extra.py` (event dispatch and `harness verify`) | A loaded repo-local gate misbehaved: it raised (the message carries the last traceback frame), returned a non-list, or emitted a finding `engine.events.validate_finding` rejects — notably a `block` with no `rule_ref`, which §5.2 forbids for every gate. |

Both carry `severity: block` and `rule_ref: adr:002`: repo-local gates fail
closed and loud, never as a silent skip (ADR-002 / D-007), and the builtin
pack still runs.
