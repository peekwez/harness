# Changelog

Newest release first. Each heading is one release.

## 0.10.0 (unreleased)

## 0.9.4 — verification design and live execution coverage

- Design happy-path and relevant edge/failure/recovery verification with features;
  review independent oracles and runtime observation plans before implementation.
- Require scenario-attributed coverage of live production paths and branches,
  including workers, correlated with the action and independently verified result.
- Reject aggregate/probe-only/stale coverage as execution evidence and preserve
  missing instrumentation as a verification gap throughout the build/close workflow.

## 0.9.3 — app-seeded integrity verification

- Require pre-action known-answer cases, app-interface seeding and independent
  read-only Python probes for state-changing acceptance criteria.
- Trace app-produced write fingerprints through real database/cache/blob contents;
  reject fabricated storage outputs, self-derived expectations and mutating probes.
- Carry the evidence requirements through builders, reviewers, close and headless
  templates; missing or contaminated evidence leaves the work NOT VERIFIED.

## 0.9.2 — reciprocal design review and acceptance verification

- Add a shared `design-review` skill for Claude Code/Codex collaboration in
  Phase 0, imported specs, resumed designs and proposed ADRs.
- Persist structured peer findings and input coverage; reconcile decisions,
  preserve accepted ADRs and limit reviews to an initial pass plus one follow-up.
- Report unavailable/failed peers honestly, retain local review and human
  authority, and ship the guidance to both host plugins and generated templates.
- Add `verification` to the existing reviewer: trace ACs to implementation and
  current evidence, distinguish missing proof from defects, and return actionable
  feedback through the build/review/close loop.

## 0.9.1 — preserve legacy G5 approvals during upgrade

- Recognize justified `gate:G5` overrides using historical `deps:<registry-id>`
  targets in graph reconciliation, live gates and closed-slice verification.
  Known manifest names, file paths, unknown IDs and other gates retain their
  existing scope.
- Upgrade appends canonical `registry:` aliases without rewriting old graph
  records or reopening landed slices. The report and dry-run show
  `legacy_overrides`; repeated upgrades add no duplicate aliases. Original
  justifications, finding IDs and commit references remain auditable.
- Canonicalize new legacy-form inputs and count migration aliases as the
  original approvals in telemetry, rather than additional override decisions.

## 0.9.0 — lifecycle integrity and cross-host upgrades

- Validate the committed source at closure, recover interrupted finalization,
  and roll back failed merges without losing pre-existing tracked work.
- Use current dependency snapshots, gate-specific overrides, recoverable
  SQLite baselines, and complete modern graph evidence.
- Resolve Python relative/submodule imports and invalidate shadow caches on
  source, extractor and configuration changes.
- Replace unsafe automatic slice splits with authored-child proposals; enforce
  prerequisites for every binding path and reap timed-out builder processes.
- Make telemetry durable through retries, archive-aware and advisory by default.
- Add Claude/Codex plugin upgrade orchestration, safer project upgrades, native
  Codex metadata, and reciprocal Claude review guidance.


## 0.8.6

Codex Astra handoff, wave 1 — the integrity fixes that need no new rule.

- **`backlog` never rewrites closed, bound or parked slices, nor a parent
  other slices depend on.** The split loop replaced ANY oversized row
  with `-a`/`-b` children, which could erase a closed slice's provenance
  and dangle other slices' `depends_on`. Refusals are reported under
  `split_refused`.
- **`adjudicate --decision-id` refuses an existing id** before any write
  (row, edge, queue). Revision and supersession are lifecycle work
  proposed in ADR-003.
- **Closed-slice acceptance has one selector and a public entry point.**
  `harness acceptance --closed [--list]`; close, merge and the CLI read
  the same selection; a declared suite that disappeared is red naming
  the slice and pattern instead of silently leaving coverage;
  `acceptance_runner: none` is reported as disabled at merge too. The
  scaffolded workflow gains the opt-in `closed-acceptance` /
  `acceptance-setup` inputs.
- **The backlog estimate and the resolver share one guidance layer.**
  Same supersession, anchors and dedup; `backlog` reports an itemised
  breakdown; a missing anchor is a reported whole-file fallback;
  `resolve` reports `demand` and `declared_demand` next to what fit.
- **`compile` warns when a proposed ADR carries binding frontmatter
  rows.** Rows still bind (no silent behaviour change).
- **ADR-003 (proposed)** — finding records, review snapshots,
  decision-row lifecycle, follow-ups and cancellation of unbuilt work:
  the contract the remaining Codex Astra items (E2, E3, E4, E5
  cancellation) wait on. Binds nothing until accepted. Tests in
  `tests/engine/test_codex_astra_wave1.py`.

## 0.8.5

- **Self-contained CI verify.** `init` vendors the engine into
  `.harness/engine/` and the scaffolded `harness-verify.yml` runs that
  copy, so a consumer repo's workflow no longer depends on cloning this
  repo (no `HARNESS_REPO` variable, no `HARNESS_TOKEN`). The clone path
  survives only as a fallback for substrates that have not been upgraded,
  and warns.
- **`harness upgrade`.** One command brings a substrate scaffolded by an
  older plugin up to the installed one: vendors/refreshes the engine,
  refreshes the harness-generated workflow (hand-authored ones are kept,
  with the step to add named), runs the schema migration, reinstalls the
  merge drivers and refreshes a harness-written autonomy profile.
  Idempotent; `init --migrate` is now its alias. `doctor --substrate`
  reports the vendored engine as `current` / `stale` / `missing` and
  names `upgrade` as the fix. Tests in
  `tests/engine/test_vendored_engine.py`.

## 0.8.4

- **`author-gate --report` for skill preambles.** The architect/backlog
  skills run author-gate at every invocation for workflow-state context;
  gaps are the normal state through stages 1–4, but the exit-1 rendered as
  a shell error in the host UI. `--report` always exits 0 once a verdict
  is emitted (the verdict lives in the JSON `passed` field); the bare
  command keeps exit 1 for automation. Both skill preambles now use it and
  explain that gaps before stage 5 are expected.

## 0.8.3

- **Fresh-init UX: no phantom files, no EDIT-ME rows.** `init` no longer
  seeds `.harness/decisions.jsonl` / `.harness/backlog.jsonl` with EDIT-ME
  placeholder rows — both start empty. The author-gate's domain-coverage
  check (every registry domain needs a decision row) already provides the
  same blocks-until-decided guarantee with a clearer message, and the
  seeded backlog row invited exactly the hand-editing the backlog skill
  forbids. `author-gate --doc` on a missing working document now reports a
  gate gap that names the next action (`/harness:architect` or
  `architect --from-spec`) instead of erroring — so the architect/backlog
  skill preambles no longer greet a fresh repo with
  "docs/architecture.md does not exist". Tests in
  `tests/engine/test_init_ux.py`.
- **Version declarations realigned.** 0.8.2 bumped only `plugin.json`;
  `ENGINE_VERSION` and `marketplace.json` now agree again.

## 0.8.1

- **Review Layer 1 honours G5 overrides.** The deterministic `R-uses` rubric
  read `uses_declares.undeclared`, so a use resolved through
  `g5_override: recorded_justification` cleared the close ceremony's own
  uses ⊆ declares check and then blocked the same close at Layer 1 with no
  adjudicable finding (kente slice 001, GOO-45). It now reads the
  override-aware `unresolved` set — the one the ceremony reads — and its
  evidence names the overridden targets. Regression test in
  `tests/engine/test_review_at_close.py`.

## 0.8.0

Makes harness kente-capable and superpowers-composable (ADR-002, Linear
GOO-72). Every 0.7.1 repo keeps its behaviour: each addition below is
opt-in through `.harness/config.yaml`.

- **GOO-73 — repo-local gates (`gates.extra`, D-007).** A consumer repo
  loads its own deterministic gates into `all_gates()` and `harness verify`;
  an entry that fails to import is a blocking `EXTRA_GATE_LOAD_ERROR`, one
  that raises is `EXTRA_GATE_RUN_ERROR`, never a silent skip.
- **GOO-74 — namespace-package awareness (`extractor.src_roots`, D-008).**
  Shadows keep the whole dotted import, `module_id` strips the matching
  source root, and G5/the resolver match registry entries by longest dotted
  prefix — so PEP 420 packages are enforced, not invisible.
- **GOO-75 — pr landing (`landing.mode: pr`, D-009/D-010/D-011).**
  `close-slice` pushes `slice/<id>` and opens the PR, `merge-slice` refuses,
  provenance is keyed twice so a squash merge keeps `verify` green, and the
  permit layer auto-approves exactly the slice's own egress.
- **GOO-76 — `compile --doc` / `architect --from-spec` (D-013).** Decision
  rows and abstractions are authored in `docs/architecture.md`'s fenced
  `harness-decisions` / `harness-abstractions` tables; an existing spec is
  compiled instead of re-derived.
- **GOO-77 — configurable acceptance (`acceptance.cmd`/`gate_cmd`, D-012).**
  The command that decides a slice is green is the repo's, and its
  whole-tree gate runs once per ceremony (`ACCEPTANCE_GATE_FAILED`).
- **GOO-78 — superpowers composition (D-014).** One working agreement says
  which plugin owns the outer loop and which the inner one.
- **GOO-79 — plugin-root-agnostic rules + private-engine CI.**
  `allowed-tools` and generated settings resolve `*/bin/harness` at runtime;
  the CI template clones a private engine with `HARNESS_TOKEN`.

Also in this release: `harness land` (re-note + re-push + re-open a failed
landing, idempotent), the advisory `LANDING_PENDING` finding,
`backlog add --linear`, and abstraction tables that carry `source` /
`module_id`.
