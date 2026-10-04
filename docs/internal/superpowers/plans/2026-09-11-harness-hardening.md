# Harness behavior hardening implementation plan

> For agentic workers: use systematic debugging, test-driven development, and verification-before-completion. Independent file ownership permits the dispatching-parallel-agents workflow; integrate and review the combined changes before completion.

**Goal:** Repair every confirmed behavior defect in the September 11 review and make enforcement state recoverable, accurate, and auditable.

**Architecture:** Keep authored JSONL, append-only provenance, Git notes, and the disposable SQLite sidecar. Derive current dependency state explicitly from the complete slice file set. Validate and persist the exact source revision at closure. Keep telemetry advisory and robust to diagnostic-storage failures.

**Tech stack:** Python 3.10+, stdlib SQLite/Git subprocesses, PyYAML, tree-sitter, pytest. No new runtime dependency.

**Spec:** The user approved all recommendations in `/tmp/harness-behavior-review-2026-09-11.md` with “fix all and harden.”

## Global constraints

- Preserve old JSONL histories and readable old sidecars; migrations must be additive or regenerable.
- Never erase user source changes, fabricate historical decisions, or silently loosen authoritative gates.
- Optional telemetry storage errors must warn and must not change gate verdicts.
- Every reproduced defect gets a regression test with an observed failure before its fix.
- Implement and validate in this worktree, then apply the verified diff to the original checkout. Preserve the worktree as a backup, leave the original untracked `.DS_Store` untouched, and do not push.

## Task 1: Shadows and derivation inputs

Files: `engine/extractor/engine.py`, `engine/extractor/modules.py`, `engine/gates/g7_derivation.py`, related extractor tests, new `tests/engine/test_hardening_shadows.py`.

- [x] Reproduce package-relative and imported-submodule misses, config cache invalidation, and incremental G7 invalidation.
- [x] Normalize relative imports against the importing package; resolve actual registered/local imported submodules without treating ordinary imported symbols as module dependencies.
- [x] Include config-dependent module identity in shadow cache validation and bump extractor version when output changes.
- [x] Invalidate incremental G7 on source/config/extractor inputs; retain safe optimization only when all relevant inputs match.
- [x] Run new tests and existing extractor, namespace, resolver, and G7 tests; review diff.

## Task 2: Backlog, binding, and campaign

Files: `engine/cli/author.py`, `engine/cli/slice.py`, `engine/cli/run.py`, new `tests/engine/test_hardening_backlog.py`.

- [x] Turn four temporary backlog/campaign reproductions into failing tests.
- [x] Reject generated child-ID collisions before mutation. Replace mechanically invalid acceptance cloning with an explicit split proposal/refusal requiring authored child contracts; preserve safe existing non-splitting behavior and report oversized plans.
- [x] Put dependency checks in the common binding transition. An explicit justified forced start may bypass them, and the override must be recorded in the target worktree.
- [x] Drain builder output while running with bounded memory; terminate and reap the process group on timeout; report the actual exit code.
- [x] Run targeted backlog/start/dispatcher tests and update behavior-specific expectations/docs only where the old contract was defective.

## Task 3: Telemetry

Files: `engine/telemetry.py`, `skills/status/SKILL.md`, telemetry tests, new `tests/engine/test_hardening_telemetry.py`.

- [x] Reproduce rotation discontinuity, inconsistent time filters, omitted retry parks, ignored compaction config, one-event promotion, and flush data loss.
- [x] Flush through durable event IDs with append-before-ack, deduplication, and concurrency-safe acknowledgement of only selected SQLite row IDs. Do not modify `engine/events.py`; use `Sidecar.db` inside the telemetry module if necessary.
- [x] Include archived history, filter edges and events by the same window, report sample counts/observed interval, and expose retry parks and useful outcome counts.
- [x] Honor compaction configuration; default new configs to advisory context pressure. Suppress unsupported automatic rule-promotion claims.
- [x] Make diagnostic emit/flush/rotation failures nonblocking and visible; keep authoritative graph/config errors distinguishable from optional logging errors.
- [x] Update the status skill to explain diagnostic limits and run targeted tests.

## Task 4: Graph, baseline recovery, and provenance

Files: `engine/graph.py`, `engine/events.py`, `engine/gates/g3_scope.py`, `engine/gates/g5_conformance.py`, `engine/gates/g6_drift.py`, `engine/cli/verify.py`, graph/state tests.

- [x] Add failing tests for session contamination, removed imports, wrong-gate overrides, lost baseline, and missing module provenance.
- [x] Add a current dependency projection backed by append-only snapshots, preserving raw `uses` history. Regenerate from files scoped to the current slice, including deletions and every session contributing to that slice.
- [x] Route overrides through a shared rule- and namespace-aware helper.
- [x] Recover missing G6 baselines from `started_at_commit` using Git blobs and current extraction; fail clearly if an active slice's required baseline is unrecoverable.
- [x] Record module touches/production and governing decisions at closure; reconstruct legacy provenance only from explicit note and registry/decision evidence. Verify new closures against an explicit provenance version/completeness marker without inventing old events.
- [x] Run graph, gates, notes, and event tests.

## Task 5: Exact and retryable closure; integration

Files: `engine/cli/ceremony.py`, `engine/cli/close.py`, optional focused helper `engine/cli/closure_state.py`, `engine/memory.py`, new close tests, README/config/spec docs, derived shadows.

- [x] Add failing tests for uncommitted acceptance, hookless imports, and failed substrate commit/retry.
- [x] Resolve the requested revision to a commit; reject source differences before acceptance and again after commands that may mutate files. Discover the Git diff and regenerate dependencies before review/gates; run checks over the complete set.
- [x] Use a recoverable completion journal or rollback of ceremony-owned state so failed final persistence reports `closed:false` and can be retried. Preserve source/index/user changes and do not repeat promoted memory on retry.
- [x] Reconcile graph completeness from the tested revision and make merge gate failures roll back rather than leave invalid merged work.
- [x] Update docs and generated shadows. Run complete pytest, golden replay, self-hosted verify/doctor; review the combined diff and repair findings.

## Execution ledger

Baseline: original checkout `204ceea`; 697 tests passed, verify and doctor green before changes. No production changes existed.

Ruling: the review plus “fix all” supplies implementation authorization; no additional design approval is needed. Worktree creation required sandbox approval because `.git` is read-only in the managed workspace.

Ownership: Tasks 1, 2, and 3 can run in parallel in disjoint files. Root owns Tasks 4 and 5 and integration. Shared interfaces: existing `extract_path`, `Sidecar`, `telemetry.emit/flush/aggregate`, and `_snapshot_slice_baseline` remain callable. Task 2 may add keyword arguments to `_bind_slice` while keeping existing calls valid.

Self-review: all review findings are assigned. The only shared implementation file between sequential tasks is root-owned `events.py`; worker tasks must request changes there rather than edit it. Task 1 changes shadow format and therefore requires final forced regeneration after all source changes. Task 2's safer split behavior intentionally replaces an invalid automatic decomposition and requires documentation/test migration. Task 5 consumes the current dependency and override helpers from Task 4.

## Task 6: Host and project upgrade lifecycle

User steering: `harness upgrade` should update the installed plugin and the
consumer's code/substrate for Claude Code and Codex.

- Keep plain upgrade offline and add explicit host plugin upgrade with dry-run.
- Select only Harness, discover the refreshed installation, and invoke its
  engine for project migration rather than using stale imported modules.
- Refresh generated engine, workflow, integration files and shadows; preserve
  authored decisions, backlog and custom configuration and expose source drift.
- Package native Codex metadata and host-neutral skill instructions; preserve
  hook trust boundaries and report host restart/new-thread requirements.
- Test host commands with doubles and local upgrade using temporary projects.

Progress: Tasks 1 and 2 have passed their focused suites (150 and 80 tests).
Task 3 passed 11 telemetry checks. Root state/closure recovery tests pass;
independent review and complete integration checks are in progress. Task 6
implementation runs in parallel with the final merge hardening and review.

Final review fixes: complete immutable closure-evidence verification;
rollback of authoritative files, Git index and note after failed closure;
post-merge source mutation checks; missing required-shadow detection;
PEP 420 namespace subpackages; telemetry tail/buffer quarantine; safe
vendoring with templates; host selection/version/downgrade checks and
visible host prompts. All have focused regression coverage. Historical
self-hosted notes carry empty file/dependency lists, so migration correctly
reports legacy coverage rather than fabricating edges.

Release candidate: 0.9.0, with Claude and Codex manifests kept in sync.
No host plugin install, remote push, or release publication is part of this
local implementation. Final full-suite and self-hosted verification follow.

Final validation: **779 tests passed in 179.29 seconds**. Self-hosted
`verify` and `doctor --substrate` pass; all 11 golden replay pairs pass.
SQLite reports `integrity_check: ok`; native Codex plugin validation,
Python compilation and `git diff --check` pass. The final schema-error
regression now retains blocking structured findings when required-shadow
discovery cannot read malformed substrate rows.

Integration: apply the verified tracked diff and 26 new files to the
original checkout without committing or changing branch refs. Preserve
the complete development worktree at
`/private/tmp/harness-hardening-2026-09-11` so it is not mistaken for an
application slice by substrate health checks. Host upgrade commands were
validated with command doubles and a read-only Claude installation dry
run; the installed 0.8.6 plugin was not updated or published.

Token/SQLite follow-up: reproduced stable-ID context suppression after
decision, guidance and signature changes. Session deduplication now checks
a fingerprint of the rendered content, with the same stamp recorded by
CLI resolution and slice binding. Five added regression cases pass; 62
focused context/gate/start checks and the final full suite pass. A toy
three-prompt demonstration injected an estimated 122, 0 and 0 tokens.
These are injection estimates, not measured total host/model usage. The
retained main sidecar contained 80 touched records, 302 buffered telemetry
events, no loaded-context rows and no active-slice binding when inspected.
