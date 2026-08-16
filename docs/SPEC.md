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
| §5.3 | Universal shadow: `{module_id, language, source_path, source_hash, extractor_version, symbols[], imports[], exports}`. Python imports are recorded whole and dotted (`kente.telemetry.decorators`), never the top-level segment only; `module_id` strips the first matching `extractor.src_roots` glob (default `["src", "packages/*/src"]`), dots the remainder and drops a trailing `__init__`, so `packages/kente-config/src/kente/config/__init__.py` is `kente.config` and a repo matching no source root keeps its dotted relative path. G5 and the resolver map an import to a registry entry by longest dotted prefix over `module_id`/`id` (ADR-002 / D-008). |
| §5.5 | Decision row schema: `{id: D-NNN, domain, question, answer, adr_ref, origin: phase0\|adjudication, created}` (+ optional `security: true`, see ADR-001). Rows are authored in ADR frontmatter `decision_table_rows` **or** in the working document's fenced ` ```harness-decisions ` pipe table (`id \| domain \| question \| answer \| adr_ref \| security`, ADR-002 D-013); abstractions likewise in ` ```harness-abstractions ` (`id \| kind \| guidance_ref`). Both compile to `origin: phase0`; one id belongs to exactly one source. |
| §5.6 | Slice schema: `{id, spec, title, status, declares_dep[], acceptance[], predicted_files[], context_cost_estimate, depends_on[], worktree}` (+ `started_at_commit`, recorded at bind; + optional `linear` — the tracker id a `landing.mode: pr` PR quotes in its title and links in its body — and `landed_via: local\|pr\|pending` / `pr_url` / `landing_error`, recorded and committed by the landing, ADR-002 / D-009). |
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
| `LANDING_MODE_PR` | `engine/cli/close.py` (`merge-slice`) | `landing.mode` is `pr`, where a slice lands by pull request against `landing.base` — a local merge would bypass a protected base branch. The message names the slice's `pr_url` when the row has one. `harness run` refuses for the same reason, as an engine error rather than a finding (it never starts). `rule_ref: adr:002`, `severity: block`. |
| `EXTRA_GATE_RUN_ERROR` | `engine/gates/extra.py` (event dispatch and `harness verify`) | A loaded repo-local gate misbehaved: it raised (the message carries the last traceback frame), returned a non-list, or emitted a finding `engine.events.validate_finding` rejects — notably a `block` with no `rule_ref`, which §5.2 forbids for every gate. |
| `LANDING_PENDING` | `engine/cli/verify.py` | A closed slice's row carries `landed_via: pending`: the ceremony completed but the push, `landing.pr_cmd` or the metadata push did not, so the work is closed and committed yet absent from the forge. `severity: advisory` (never a block — the slice IS closed), `rule_ref: adr:002`; the message carries the recorded `landing_error` and names `harness land --slice <id>`. |
| `ACCEPTANCE_GATE_FAILED` | `engine/cli/acceptance.py` (close ceremony and `merge-slice`) | The repo's configured `acceptance.gate_cmd` (e.g. `make check`) exited non-zero. It runs once per ceremony — after acceptance is green and before the substrate commit at close, and on the merged tree at merge, where the merge is rolled back. The message carries the last 20 lines of combined stdout/stderr (ADR-002 / D-012). |

`LANDING_PENDING` is advisory; the other four carry `severity: block` and `rule_ref: adr:002`: repo-local gates fail
closed and loud, never as a silent skip (ADR-002 / D-007), and the builtin
pack still runs.

## Provenance notes are keyed twice (ADR-002 / D-010)

Every `write_note` writes the note onto the commit AND appends a row to the
derived `.harness/notes.jsonl`:
`{ts, slice_id, commit, tree_hash, source_tree}`. `tree_hash` is
`git rev-parse <commit>^{tree}`; `source_tree` is a digest of that tree's
top-level entries with `.harness` excluded.

`harness verify` uses the second key when the first is gone. A slice whose
noted commit is unreachable, or which has no note at all, is resolved when a
reachable commit (walking `landing.base` and `HEAD`, capped) carries one of
its recorded keys — the whole tree (a rebase-replayed or cherry-picked
commit reproduces it) or the source tree (what a squash merge of a slice
branch reproduces, since the ceremony's substrate commit rides in the same
squash). Resolved slices appear in verify's `resolved_via` map as
`tree_hash` and raise no finding; a slice with neither key is still
`ORPHANED_NOTE` / `MISSING_PROVENANCE_NOTE`. `harness graph note --repoint
<slice-id> <sha>` re-attaches the note itself.

`.harness/notes.jsonl` is derived, append-only and union-merged (like
`edges.jsonl`): it is history, so G7 never regenerates it and hand-editing
it is a bug.
