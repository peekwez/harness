---
title: Codex Astra — harness enhancement handoff
status: proposed; not implemented
owner: Fable / Claude Code
reviewed_harness_commit: b0befcb5a683ee25c980c431d3385cacdfb01350
reviewed_engine_version: 0.8.5
source: Kente architecture and package review, followed by read-only harness inspection
---

# Harness enhancements: instructions for Fable / Claude Code

## Purpose and limits

Some Kente review recommendations belong upstream in harness. The engine should make accepted rules, outstanding findings, declared scope, and acceptance evidence durable and reliably usable across sessions. Consumer repositories should continue to own their architecture, package graph, runtime infrastructure, release processes, and business policy.

This is a proposed implementation handoff, not an approved architecture decision, bound slice, or finding registered with harness. No implementation, substrate, or existing memory was changed to produce it. Findings below were verified by source inspection at the commit above; I did not run the harness test suite or execute mutating harness commands. Recheck the current branch before implementing: another agent may have moved it forward.

The original Kente review is in the Obsidian vault:
`/Users/kwesi/Documents/obsidian-vaults/decision-quality-enforcement/Technical/Kente/codex-astra-observations/2026-09-06/RECOMMENDATIONS.md`.
The adjacent `HANDOFF.md` and source manifest provide the consumer review context. That document remains authoritative for Kente package findings; this file refines its harness recommendations against the actual upstream implementation.

## Ownership boundary

| Recommendation | Where to implement |
|---|---|
| Reusable closed-slice acceptance selection, strict missing-path handling | Harness engine; consumers configure dependencies and CI invocation |
| Durable finding content, explicit resolution, review freshness | Harness engine and review skills |
| Decision-row lifecycle and structured adjudication | Harness schema, compiler, resolver, CLI; humans author consumer decisions |
| Durable follow-ups with explicit revisit triggers | Harness capability; consumer owns each follow-up and resolution |
| Safe backlog amendments and retirement of unbuilt work | Harness CLI and lifecycle machinery |
| Anchor-aware context estimates that agree with resolver inputs | Harness resolver/compiler integration |
| Constant dynamic-import evidence | Optional generic extractor improvement; consumer gate must adopt it |
| Kente base/optional package dependency rules, unknown-package rejection | Kente `.harness/gates/` and its authored decisions |
| Kente CI path filters, real-backend test lane, release reproducibility | Kente workflows, Makefile, packaging/release configuration |
| DQE evidence and workspace behavior | DQE; possibly a future narrow Kente workspace package after an explicit decision |

Do not move Kente policy into generic engine code. Do not resurrect DBOS or Claude Agent SDK as Kente architecture recommendations. This does not request removing unrelated upstream integrations. Kente plugins are under active implementation; review their completed behavior separately and avoid upgrading that active working tree as part of this handoff.

## What already exists — preserve it

- `engine/cli/acceptance.py` already runs cumulative CLOSED-slice acceptance at close and merge through `run_regression`, using the configured runner. This is not a request to invent cumulative acceptance.
- ADR-level supersession already exists in the compiler and resolver. The missing lifecycle is at decision-row and follow-up level.
- The extractor already prunes obsolete shadows in `extract_all`; do not implement a second pruning system.
- Extra gates, namespace imports, configurable acceptance, provenance, and superpowers composition are covered by ADR-002. Extend these contracts rather than bypassing them.
- Codex already reviews code. Adding another nominal reviewer does not solve missing evidence, stale verdicts, or lost follow-ups.

## Implementation protocol

1. Read current `docs/SPEC.md`, accepted ADRs, actual decision rows, schema, and applicable agent instructions. Check working-tree ownership. Never reset, clean, regenerate, or overwrite another agent’s work just to begin this task.
2. Verify each source observation below on current HEAD. If already fixed, record the commit/test that supersedes it and omit the implementation slice.
3. Author recurring policy choices through the harness architecture/decision process before adding enforcement. Examples needing an explicit contract: decision retirement, stale-review blocking, follow-up escalation, and canceled-slice dependency semantics. This handoff is input to that process, not a replacement backlog. Follow the applicable author gate.
4. Create small declared slices through the existing harness backlog workflow. The labels E1–E7 below are proposal labels, not existing slice IDs. Bind each actual slice, declare dependencies/files, load context, use shadows for neighboring interfaces, and amend scope before extending it. Do not hand-edit derived artifacts.
5. Use test-driven development per unit, investigate failing tests before retrying, record abandoned attempts, and perform the required independent security review when a slice changes trust or enforcement. Honor D-003 through D-006 and ADR-002/D-014. A new blocking finding needs an accepted `rule_ref`; this report’s priority does not supply one.
6. Close and land through the normal harness lifecycle. Preserve independent Codex review, but give it the changed contract, diff, and adversarial cases rather than relying on a severity label.

Any CLI shapes suggested below are design proposals: they are NOT commands available in 0.8.5. Confirm the existing CLI before issuing commands. Candidate file lists identify likely scope, not permission to edit undeclared files.

## E1 — Expose cumulative acceptance and reject missing declared suites

**Priority:** first, narrow correctness improvement.

**Evidence:** `engine/cli/acceptance.py:run_regression` selects closed slices and deduplicates paths, but filters nonexistent literal paths and accepts empty glob results. A deleted historical acceptance file can therefore disappear from regression coverage silently. If all selected paths disappear, the function can report that there are no closed-slice tests to protect. The selection is internal; there is no public acceptance/regression subcommand for consumer CI.

**Required behavior:**

- Extract one shared closed-slice selector returning deterministic paths plus owning slice IDs and actionable diagnostics. Close, merge, and the public CI entry point must use it.
- A declared missing literal or unmatched glob must fail with the declaring slice and pattern. Distinguish an honestly empty acceptance declaration from a declared suite that disappeared. Do not infer retirement from file absence.
- Preserve configured command, cwd, environment, quoting, shell-free invocation, exclusion of the current slice, and default close behavior. Do not hardcode Kente, `uv`, or pytest semantics into the selector.
- Add a documented public entry point with list/JSON and execution modes, for example a proposed `harness acceptance --closed --list` and execution counterpart. Final spelling is an authored API choice. Listing must not execute tests or mutate project state.
- Keep `verify` semantics explicit. Do not silently make every verification invocation install dependencies or execute an expensive application suite. Consumers invoke acceptance after provisioning their environment.
- Explicitly disabled acceptance must be reported as disabled, not executed-and-passed. Existing compatibility behavior should change only under a documented contract.

**Acceptance cases:** closed versus planned/in-progress/parked selection; duplicate paths; paths containing spaces; current-slice exclusion; missing literal; unmatched glob; no closed suites; configured runner failure/spawn failure; custom cwd/env; consistent path list across close, merge, and CI. A missing declaration must not become green because another slice has a valid test.

**Candidate scope:** `engine/cli/acceptance.py`, CLI parser/dispatch, relevant close/merge call sites, `tests/engine/test_acceptance_runner.py`, README/SPEC. Consumer CI-template support should be opt-in and preserve dependency setup ownership.

## E2 — Preserve findings and bind review verdicts to reviewed content

**Priority:** first wave; split storage/resolution from snapshot enforcement if needed.

**Evidence:** `engine/cli/review.py:cmd_review` records ordinary finding edges with identity, code, severity, rule reference, confidence, and session. The full message is printed but is not included in that ordinary persisted edge; parked findings retain fuller content separately. `engine/cli/ceremony.py` reduces recorded findings by code, so two distinct findings sharing a code can affect each other’s effective state. Fork verdict edges do not identify the reviewed source snapshot.

**Required behavior:**

- Persist complete actionable content through an authored finding record or append-only event contract: stable finding ID, full message, rule reference, source/evidence references, originating slice, reviewer/session provenance, and reviewed-content identity. Graph edges may index records, but must not be the only surviving fragment.
- Resolve, rebut, supersede, or park a particular finding ID explicitly. Resolving one finding must not clear another simply because their codes match. Keep historical evidence and resolution rationale.
- Define the review snapshot carefully: reviewed baseline/diff, relevant source content and enforcement inputs, plus engine/rule version where needed. Reuse existing source/provenance hashing conventions if suitable.
- Invalidate a verdict when relevant reviewed content changes. Avoid a naive HEAD-only check that invalidates itself whenever recording the verdict creates bookkeeping commits. A review receipt must not certify unseen edits, and recording the receipt must not require an endless second receipt.
- Preserve the independent reviewer contract. A user-supplied session label is provenance data, not proof of fresh context. Document which host boundary supplies independence and what the engine can actually verify.
- Keep advisory findings advisory unless an accepted rule says otherwise. Do not auto-fix as the reviewer or add an extra reviewer layer.

**Acceptance cases:** full prose survives CLI exit and a fresh session; two findings with the same code remain independently open; resolve one and the other still blocks if rule-backed; rebuttal retains evidence; relevant edit after fork pass makes it stale; receipt-only bookkeeping does not; failed fork cannot be overwritten by unrelated advisory activity; security requirements remain enforced. Include replay and branch/substrate merge tests.

**Compatibility:** existing edges cannot reconstruct lost messages or content hashes. Mark legacy records as incomplete/unverified; never invent evidence or claim historical snapshot assurance. Specify how a legacy open slice obtains a fresh receipt without rewriting closed history.

**Candidate scope:** `engine/cli/review.py`, `engine/cli/ceremony.py`, `engine/graph.py`, schema/merge/replay support, review skills, `test_review_at_close.py`, `test_adr001_fork_review.py`, and existing review regression tests.

## E3 — Add decision-row lifecycle and safe structured adjudication

**Priority:** next; prerequisite for reliable active-rule resolution.

**Evidence:** decision rows currently lack a lifecycle contract. ADR supersession does not express retirement of one row while retaining its ADR. `cmd_adjudicate` builds a decision question from the first 200 characters of the finding and appends the supplied decision ID without a dedicated duplicate-ID guard. Compiler ADR extraction and `engine/docsections.py` copy a fixed set of fields; adding CLI metadata alone would not make it survive all authoring paths.

**Required behavior:**

- Author a minimal lifecycle: active/superseded/retired semantics, replacement reference, rationale, and provenance. Decide whether revisions use new IDs or an explicit revision model; preserve unique identities and never silently overwrite a decision.
- Resolve only rules in force, including the security-rule selector. Keep historical rows available for audit and historical review interpretation. Reject replacement cycles, dangling replacements, conflicting authorship, and ambiguous active versions.
- Accept complete question/answer/domain/security metadata through structured adjudication input. Validate everything before writing; reject duplicate IDs with instructions for the supported revision path.
- Preserve lifecycle and security metadata through both ADR frontmatter and architecture document blocks. Keep the existing adjudication precedence and ADR-level supersession behavior. Compilation must not resurrect an intentionally superseded row.
- Make interrupted adjudication safely retryable. Decision creation, finding resolution, and removal from the parked queue must not leave a false completed state or duplicate records after interruption. Use existing storage conventions; do not add a remote database or hide authoritative state in SQLite.
- Separate deterministic integrity checks from semantic advice. The engine can check references and lifecycle; it cannot automatically decide that a human decision’s rationale is obsolete.

**Acceptance cases:** both authoring paths round-trip metadata; old rows receive documented defaults; one row can be superseded without retiring siblings; replacements cannot cycle; adjudicated rows survive recompilation; duplicate input fails before partial writes; security classification survives; interrupted operation retries safely; resolver and close agree about active rules.

**Candidate scope:** `engine/schema.py`, `engine/compiler.py`, `engine/docsections.py`, `engine/cli/review.py`, `engine/resolver.py`, ceremony security selection, compiler/doc-section/adjudication tests. Follow the schema migration policy when changing required fields or semantics; optional fields alone do not automatically justify a version bump.

## E4 — Make follow-ups durable and queryable without turning all advice into gates

**Priority:** after E2/E3 contracts settle.

Kente’s deferred cursor/fencing work illustrates the need: a revisit condition can become true while the deferred work remains only in prose. Its CAS implementation landing was evidence to revisit an earlier deferral, not automatic proof that the deferred feature must now be built.

**Required behavior:** introduce a small authored follow-up record or an extension of finding records with owner, status, origin, relevant package/slice/decision links, explicit revisit condition, and resolution evidence. Distinguish open work, waiting for a condition, resolved, and consciously declined. Support deterministic references such as “slice X closes” and opaque human conditions that are displayed without pretending to evaluate them.

Provide a current-state view that reports unresolved/triggered follow-ups and relevant active decisions, with links to originals. Generate it from authoritative records rather than maintaining a second hand-written resume narrative. If persisted, designate it derived and make regeneration deterministic. A resolver should surface relevant follow-ups using declared links, not dump all historical memory into every context.

Do not silently migrate all free text into obligations. Import selected Kente items only after their owner validates them. Do not auto-implement triggered work or auto-block unrelated slices. Any mandatory escalation is a separately accepted policy.

**Acceptance cases:** survives session rollover and memory compaction; a slice-close trigger fires deterministically; unknown/manual condition remains unresolved rather than false; closed/declined records retain evidence; stable rendering order; irrelevant follow-ups do not consume slice context; malformed links are diagnosed; advisory default is preserved.

**Candidate scope:** chosen authored storage/schema, CLI/status, `engine/memory.py`, resolver relevance, graph links and tests. Keep SQLite disposable; avoid a parallel issue tracker unless a specific need is demonstrated.

## E5 — Support safe scope amendment and explicit retirement of unbuilt slices

**Priority:** next; keep separate from decision lifecycle implementation.

**Evidence:** `engine/cli/author.py` provides backlog addition and budget-driven splitting, but lacks a dedicated amendment workflow. Its general splitting loop does not restrict itself to planned rows and removing a split parent requires care for other slices that depend on it. Existing slice statuses are planned/in_progress/parked/closed; using closed to mean canceled would misrepresent acceptance and provenance.

**Required behavior:**

- Add a validated amendment operation for allowed mutable fields, with reason, expected revision/digest, and before/after history. Reject stale concurrent amendments. Revalidate dependency references and cycles, declarations, predicted files, acceptance ownership, and context estimates.
- For a bound slice, require context reload and applicable gates after scope changes. An amendment may authorize future work; it must not erase evidence of earlier out-of-scope activity.
- Make automatic splitting safe: never rewrite closed/bound work opportunistically. Require coherent explicit allocation of acceptance, declarations, predicted files, and dependencies when the engine cannot establish a valid split. Dividing a dependency list in half is not a proof of semantic independence.
- Define cancellation/supersession for unbuilt work through an accepted contract. Preserve lineage and require explicit handling of incoming dependencies. Never mark canceled work closed just to get it out of the scheduler.
- Audit every status consumer: campaign selection, dependency readiness, close/merge, regression selection, verify, telemetry, and compiler/author gate. A new terminal status must not accidentally count as accepted implementation or remain forever schedulable.

**Acceptance cases:** stale amendment rejected; cycle rejected; bound context invalidated appropriately; closed rows protected; split with incoming dependencies preserved or refused; canceled dependency requires explicit replacement/waiver policy; canceled acceptance not counted as successful execution; graph and merge/replay retain history.

**Candidate scope:** `engine/cli/author.py`, slice/campaign commands, schema, compiler/author gate, acceptance/status selectors, substrate merge tests and campaign tests. Check actual command names before drafting skill instructions.

## E6 — Unify context candidates and make estimates reflect anchors

**Priority:** narrow reliability improvement; can precede larger lifecycle work.

**Evidence:** `engine/resolver.py:_render_guidance` renders an anchored section when available, while `context_cost_estimate` counts complete referenced guidance files and can count repeated references. Missing anchors currently fall back to the whole file. Independent estimation and rendering logic can cause unnecessary splits and obscure actual context pressure.

**Required behavior:** share a pure candidate-construction layer between estimation and resolution. Apply the same supersession filtering, anchor extraction, shadow identities, and deduplication. Deduplicate by canonical resource plus anchor/content identity; two distinct sections of one file must not collapse into one.

Report unbounded required context cost separately from the budgeted injected context. An estimate that always reports only what fits conceals the need to split. Define missing-anchor handling explicitly: actionable diagnostic or documented fallback with the fallback cost. Do not silently present an anchored estimate when the entire file is loaded.

As a separately authored enforcement choice, decide what happens when binding decision material cannot fit: deterministic prioritization or a clear unsatisfied-context result. Do not certify context loading while silently dropping required rules. Preserve existing quiet/list behavior and record context-loaded evidence only for material actually delivered.

**Acceptance cases:** repeated same anchor counted once; distinct anchors retained; superseded guidance excluded consistently; missing anchor handled consistently; deterministic order; zero/tiny budgets; active decision changes reflected; estimate explains the difference between full demand and injected content. Test behavior rather than mirroring private helper implementation.

**Candidate scope:** `engine/resolver.py`, backlog estimate call sites, resolver/compiler tests, relevant CLI display and documentation. Coordinate E3/E4 integration through shared interfaces rather than repeatedly rewriting the resolver.

## E7 — Optional generic dynamic-import evidence

**Priority:** later, after Kente’s completed plugin design is reviewed.

`engine/extractor/engine.py:_python_imports` extracts syntactic Python import statements. A bounded enhancement can recognize constant-string calls to supported dynamic import forms, and enumerate unresolved dynamic sites as uncertainty. It must not execute imports or claim complete static resolution of arbitrary Python.

Specify alias handling, local rebinding/shadowing, relative imports, literal versus computed values, and deterministic source locations. Unknown cases should remain explicitly unknown. Test those boundaries and regenerate affected shadows through the engine. Review extractor/shadow version compatibility and G7 fixtures.

This alone does not fix Kente K2: its consumer gate must deliberately consume the evidence and distinguish base dependencies from optional adapter edges and package metadata. Keep the Kente layer graph and policy in Kente. Avoid a speculative plugin policy before the current plugin implementation is finished.

## Verification, release, and consumer adoption

Run focused tests for each slice first, followed by the repository’s required checks and acceptance. Existing root commands include `make test`, `make verify`, and `make replay`; inspect their current definitions and the bound-slice acceptance before running them. I have not run them for this handoff. Exercise CLI help/README parity and skill/SPEC references whenever adding commands, fields, or instructions.

Cross-cutting acceptance must cover old substrate loading, compilation without unintended churn, derived byte-identical regeneration, replay, branch/substrate merge conflicts, and upgrading a vendored consumer. Preserve authored consumer configuration and workflow customizations. Never silently rewrite old findings as resolved, old decisions as newly approved, or canceled work as accepted.

Publish through harness’s release process. Test adoption in a disposable fixture or authorized isolated consumer checkout first; use the supported upgrade path instead of hand-editing Kente’s vendored engine. After Kente’s plugin work lands and its owner is ready, adopt separately and add the consumer-specific fixes: CI invocation of closed acceptance, workflow path coverage, explicit dependency edges, and real-backend coverage. Release reproducibility and maintenance sandbox behavior remain separate Kente work.

For every delivered slice, leave a short handoff stating: accepted rule/ADR, changed behavior, tests actually run and outcomes, migration consequences, remaining advisories with stable IDs, and the exact commit. Request Codex to challenge missing evidence, crash/retry boundaries, same-code finding collisions, stale reviews, lifecycle ambiguity, and consumer compatibility. The implementation owner applies any fixes through the gates.

## Completion criteria

This enhancement program is complete only when its approved subset is implemented and verified, its deferred subset has explicit owners/revisit conditions, and consumers can adopt without repairing substrate manually. Do not treat creating this file, adding CLI surface, or obtaining a reviewer pass as evidence that those outcomes have occurred.
