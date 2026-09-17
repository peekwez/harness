# Verification design and live execution coverage

Requirements: design verification with each feature before implementation,
including happy paths and a deliberate search for applicable boundaries,
concurrency, partial failure and recovery cases. Show which live production
blocks/branches execute for a scenario and correlate them with its independently
verified result.

Implemented in `skills/verification/design.md` and `coverage.md`, routed through
architecture, imports/resume, cross-provider design review, backlog, build,
review, close, personas and both headless builders. The feature's existing spec
holds the matrix; no new engine gate/schema or generic application adapter.

The 0.9.3 baseline already rejected fabricated storage results and rolled-back
writes and had a premortem/risk process. It did not require a complete verification
matrix before design readiness or scenario-attributed coverage of live app code.
The baseline exercise established those omissions, not unsafe agent compliance.

## Independent instruction scenarios

Seven forward scenarios exercised happy-path-only feature designs, imported
stage-3 specs without a matrix, aggregate/probe-only coverage, covered writes
followed by rollback, concurrent context contamination with a missing worker,
a correctly attributed case and headless completion with missing coverage.
The incomplete designs remained not implementation-ready; missing/contaminated
execution evidence remained NOT VERIFIED; a known failed required write remained
FAIL. A properly evidenced scenario can pass without a blanket 100% target.
Final independent review found no actionable issues. These scenarios were
instruction simulations, not live web/distributed-system runs.

## Live Harness CLI smoke

An isolated Python environment used coverage.py 7.16.1 with `--branch`, separate
`--context=init-fresh` and `--context=init-repeat`, separate data files and
`--source=engine`. Both cases invoked the real `bin/harness --root <temporary
project> init` entry point; no internal helpers seeded application state.
The CLI process itself is the application. These are isolated CLI scenarios;
their startup-wide contexts are not presented as request-level attribution for
a shared long-running server.

The known-answer case was frozen before execution (SHA-256
`1f187ccc4c64b1e58186ef66483fba600f59ee961a07e3fb14287d1d2cdbab50`).
The independent read-only Python probe (SHA-256
`cbb90e444fff9c98f88dbf1472f8f211199e0985ae179adf27ed1b995fd32b75`)
asserted schema version 1, vendored engine version 0.9.4, empty backlog and empty
decisions. Before init those assertions failed on missing files; after init all
passed. A deliberately wrong version failed the intended value assertion.

Fresh init exited 0, executed `engine/cli/init.py` branch `57 → 65` and the schema
write at line 92, and did not execute the refusal at line 62. Repeated init exited
1, executed branch `57 → 58` and refusal line 62, and did not execute the schema
write. All 98 generated file hashes remained identical after refusal.
[The extracted smoke result](runtime-coverage-smoke.json) records the contexts,
covered/missed blocks, branches and source hash. The two raw JSON report hashes
were `97423714ffc8ad254a3bc12af09b891ec93f8c2c055fe3350d5ce57ae75c0290`
and `2589e382282eb5c7af97e61afa0296941b85e31b9e2b6e3eade43c01d2e43af8`.
This validates execution/outcome correlation for these CLI cases, not a universal
tracing adapter, browser coverage or distributed-worker instrumentation.

## Regression and packaging checks

40 focused architecture/import, skill composition/lint, init and upgrade tests
passed. Changed skills and native Claude/Codex plugin metadata validate. Both
headless templates pass syntax checks, shadows were regenerated and Harness
verify passes with only the existing historical provenance advisories. Claude
retains its preexisting ignored-engine metadata warning. Verification remains
a workflow obligation with project-specific instrumentation and probes.
