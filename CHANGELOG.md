# Changelog

Newest release first. Each heading is one release.

## 0.10.0 (2026-10-04)

0.10 breaks 0.9. Read this entry before you upgrade. [Upgrading 0.9 to 0.10](https://peekwez.github.io/harness/upgrading/) gives the full steps.

### Highlights

- Explore first. A design starts with a toy in `explore/`, decision cards and statements. A human freezes it.
- Verify first. Each statement has a linked test. A red record proves that the suite failed at slice start.
- Leaner context. The injection is capped at 9,000 characters. Later prompts get only the blocks that changed.
- Shared memory. Only a human-approved `harness memory promote` writes to `.claude/memory/shared/`.
- One upgrade command moves a 0.8 or 0.9 repo to 0.10 and proposes one commit.
- Fewer parts. Four gates, `harness run` and the contract checks are gone. The 18 skills became 11.

### What changes in your repo on upgrade

How to upgrade from 0.9.x:

1. Update the plugin with your host, for example `claude plugin update harness@harness-marketplace --scope user`.
2. Start a new session, so that the host loads the 0.10 engine.
3. Preview the plan: `harness upgrade --dry-run`.
4. Run the new engine: `harness upgrade --yes`.

Do not use `harness upgrade --plugin` from 0.9. The 0.9 CLI has no `--yes`, so the 0.10 run skips each step that asks first. From 0.10 on, `harness upgrade --plugin --host claude --yes` does both steps.

The upgrade migrates `.harness/schema_version` from 1 to 2 and repairs old overrides. Then it runs these 19 steps:

- `w1.gitignore-cache`: adds `.harness/cache/` to `.gitignore`.
- `w1.untrack-shadows`: untracks and deletes `.harness/shadows/`. Shadows now live in the gitignored cache. This step asks first.
- `w1.drop-registry-shadow`: removes the `shadow` field from registry rows.
- `w1.drop-resolver-config`: removes `resolver.budget_tokens`, `ranking` and `degrade` from `config.yaml`.
- `w2.slice-metrics`: adds `.harness/slice-metrics.jsonl` and its merge rule.
- `w2.telemetry`: converts old telemetry into slice-metrics rows. This step asks first.
- `w2.config`: removes retired config keys. It adds `review.ensemble` and `gates.exempt_paths`.
- `w2.skill-names`: renames removed skills in a harness-marked `AGENTS.md`, `CLAUDE.md` and CI workflow.
- `w2.contracts`: reports that harness no longer checks `contracts/`.
- `w3.retire-durable-memory`: exports the kept memory rows for review. This step asks first.
- `w3.memory-git-lines`: removes the `.harness/memory/` lines from `.gitattributes` and `.gitignore`.
- `w3.shared-memory-index`: creates the index `.claude/memory/shared/MEMORY.md`.
- `w3.claude-md-import`: adds the shared memory import to a harness-marked `CLAUDE.md`.
- `w4.glossary`: creates `docs/glossary.md` when it does not exist.
- `w4.agents-md-ste80`: adds the STE-80 rule to a harness-marked `AGENTS.md`.
- `w5.legacy-verification`: marks each slice that is not closed `legacy_verification: true`.
- `w6.agents-md-explore`: adds explore to the `AGENTS.md` workflow line.
- `w8.agents-md`: replaces a harness-written `AGENTS.md` with the 0.10 template. It keeps the old file in `.harness/cache/`. This step asks first.
- `w8.stale-merge-rules`: removes merge and ignore rules for files that 0.10 removed.

Upgrade moves old files. It does not delete them:

- `.harness/memory/` moves to `.harness/cache/legacy-memory/<stamp>/`. The kept rows go to `.harness/cache/durable-memory-export.md`. Promote the facts that the team needs.
- An untracked telemetry file moves to `.harness/cache/legacy-telemetry/`. Git history keeps a tracked `.harness/telemetry.jsonl`.

After the steps, upgrade refreshes the vendored engine, the CI workflow and the host settings. Then it runs `harness doctor --substrate` and `harness verify`.

Upgrade never commits. The report proposes one commit with the message `harness: upgrade to 0.10`. Read `git status` and `human_checks`, then run that command.

Exit codes:

- 0: `upgraded`, `already on 0.10` or `--dry-run`.
- 1: `incomplete`, `checks failed` or `failed`. The JSON report prints in each case.

Without a terminal, upgrade skips each step that asks first and reports `incomplete`. Run `harness upgrade --yes` to finish.

A slice that is open during the upgrade gets `legacy_verification: true`. Close skips its red-record and statement checks. Acceptance and regression still run.

### New

- Shadows are a gitignored cache in `.harness/cache/shadows/`. CI rebuilds them when G5 or G6 needs them.
- The resolver injects context in blocks, once per binding. Later prompts get only the changed blocks. The cap is 9,000 characters.
- Telemetry stays local in `.harness/cache/events.jsonl`. Close commits one row per slice to `.harness/slice-metrics.jsonl`.
- Shared memory lives in `.claude/memory/shared/`. Use `harness memory promote`, `harness memory accept` and `harness memory changed`.
- G10 blocks each edit-tool write to shared memory. At close, G10 also checks the slice diff for that folder.
- STE-80 text rules: `harness lint-text`, the glossary in `docs/glossary.md` and a finding catalog.
- `harness gates explain <CODE>` prints the catalog entry of a finding code.
- Verification first: statements in `.harness/verify.jsonl`, `verifies:` and `kills:` links in tests, a red record at bind, and close checks.
- The explore stage: `harness explore`, then `harness explore --freeze`. Each big decision is a decision card.
- `harness architect` starts from one source: `--from-explore`, `--from-spec <path>` or `--skip-explore "<reason>"`.
- G9 blocks production code that imports from `explore/`.
- The docs site: <https://peekwez.github.io/harness/>.

### Removed

- `harness run`.
- The contract checks. harness no longer checks `contracts/`. Use a repo-local gate or a CI linter.
- Gates G2, G4, G7 and G8. Their ids stay reserved.
- `harness memory write`, `flush` and `compact`, and the `.harness/memory/` store.
- The committed `.harness/telemetry.jsonl`.
- Skills went from 18 to 11. Eight skills were removed, and `explore` is new. Each removed skill moved into a kept skill:

| Old skill | Its content is now in |
|---|---|
| `premortem` | `architect` |
| `contract-first` | `architect`, as a decision card |
| `decision-tables` | `adr-authoring` |
| `slice-decomposition` | `backlog` |
| `shadow-context` | `build` |
| `review-rubrics` | `review` |
| `adjudicate` | `harness` |
| `status` | `harness` |

- Kept skills: `adr-authoring`, `architect`, `backlog`, `build`, `close-slice`, `design-review`, `explore`, `harness`, `init`, `review`, `verification`.

### Known limits

[Trade-offs and limits](https://peekwez.github.io/harness/trade-offs/) has the full list.

- The permit layer reads shell command text. Some spellings pass without a prompt. Add `.claude/memory/shared` to `sandbox.filesystem.denyWrite`.
- Only the Claude Code hook runs the permit layer on shell commands. The other hosts' profiles approve shell commands.
- G9 reads static imports only. It can block a module that is named `explore` by mistake.
- A shell command can append a row to `.harness/promotions.jsonl`. The G10 close check trusts that ledger.
- Two slices that each promote a fact conflict in `MEMORY.md`. Resolve the conflict, then run `harness memory accept .claude/memory/shared/MEMORY.md`.
- A stub test such as `assert False` records red. A JUnit check for each test is not built.
- On the `--skip-explore` and `--from-spec` paths, only the skill text asks for decision cards.
- `harness gates explain` has no entry for a code from a `gates.extra` gate.
- Upgrade merges `.claude/settings.local.json` and keeps old entries. Compare the backup and remove stale entries.
- An acceptance timeout stops only the direct child process.
- A harness root in a subfolder of a larger git repo is not supported.
- `.harness/cache/events.jsonl` grows without a limit.

### Testing

- Chained end-to-end upgrades of 0.8 and 0.9.4 fixtures, in five variants, reach 0.10. A second run changes no file.
- This repo upgraded itself with `harness upgrade`.
- We skipped the field test on a real consumer repo for this release.

Closes peekwez/harness#2, #3, #4, #5, #6, #7, #8 and #9.

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
