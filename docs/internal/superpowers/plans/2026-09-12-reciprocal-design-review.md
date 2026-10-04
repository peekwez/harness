# Reciprocal design review implementation plan

Scope update: the user also requested a tight verification skill inside the
existing reviewer, including mandatory live services/browser/DevTools, logs,
database/cache inspection and screenshots tied to ACs. Implemented as shared
workflow guidance, with no new engine subcommand or provider dependency.

**Goal:** Claude Code and Codex independently critique design and architecture
when the other provider is available, from either host.

**Design:** Add a shared `design-review` skill, called by architecture and
ADR workflows. The lead owns synthesis and authored artifacts; the peer
provides evidence-backed advice in a fresh, read-only invocation. Availability
is advisory. Existing human decision and author-gate contracts remain.

**Scope:** Shared Markdown skills, agent/template guidance and plugin release
metadata. No provider dependency or new blocking gate in the Python engine.
The user's request authorizes this bounded workflow addition.

## Implementation and validation

- [x] Inspect current architecture, ADR and review routes. Baseline exercise:
  Claude stage 2 uses only a local red-team; Codex `--from-spec` starts at
  stage 3 without peer review; standalone ADR supersession only compiles.
- [x] Confirm clean isolated branch and baseline skill/composition/architect
  tests: 20 passed.
- [x] Obtain an independent Claude critique of the proposed workflow and
  reconcile findings, or record the concrete availability failure.
- [x] Add `skills/design-review/SKILL.md` and its CLI reference. Cover both
  hosts, compact evidence packets, actual execution, durable findings and
  dispositions, bounded follow-up, stale input detection and honest failures.
- [x] Wire `skills/architect` stages 2–5 and imported specs, `agents/architect.md`,
  `skills/adr-authoring`, `skills/harness` and `templates/agents-md.md`.
  Preserve accepted ADRs; avoid duplicate reviews for the same content.
- [x] Document invocation, additional token cost and upgrade behavior in
  README. Bump engine and Claude/Codex manifests together to 0.9.2.
- [x] Forward-test fresh agents on both host routes, seeded/resumed documents,
  missing/failed providers, stale packets, unresolved disagreements and recursion.
  Validate changed skills and plugin packaging; run relevant regression tests
  and Harness verification. Record actual results here.

Publication requires a reviewed PR to origin and the peekwez mirror, passing
CI before merge, and identical remote main commits. Do not contact buzz.

## Evidence

Baseline: the independent workflow exercise explicitly chose no other-host
CLI in all three scenarios. This reproduces the requested behavior gap;
Python tests checking Markdown phrases would not prove its correction.

CLI controls checked against installed `codex exec --help`, `claude --help`
and the official noninteractive/configuration documentation. A filesystem
sandbox does not constrain remote MCP side effects; the invocation reference
must account for enabled tools, hooks and extensions separately.

Validation: the final combined suite passed all 797 tests in 175.45 seconds;
51 focused architecture,
skills, init and upgrade tests passed. After final guidance repairs, seven
skill/composition checks passed again. All changed skills and native Codex
plugin packaging validate. The response schema accepts a valid critique and
rejects invalid assessment, missing assessment and incomplete findings.
`verify` passed (only existing historical provenance advisories), substrate
doctor is healthy, and all 11 golden replay cases passed.

Ten forward scenarios cover both hosts, import, resume, failure envelopes,
insufficient context, concurrent requirement edits, missing CLI, round-two
changes and peer recursion. Follow-up scenarios confirm draft ADR isolation
and separate failed-attempt/completed-round accounting. Final independent
diff review found no remaining material issues after accepted-ADR repair
instructions were corrected.

Claude's initial independent critique led to explicit authored input hashing,
structured assessments, nonbinding ADR drafts, imported-claim handling and
provider identity checks. The proposed deterministic hash command was declined:
this change supplies an advisory skill workflow, with explicit hash comparison
and recorded coverage. A redundant third reviewer was also declined; lead
local analysis plus an independent peer satisfies the requested collaboration.

## Verification workflow addition

- Added `skills/verification/SKILL.md` with command/evidence and runtime
  references. The existing reviewer owns AC-to-implementation-to-observation
  verification, returns VERIFIED/NOT VERIFIED and actionable gaps.
- Wired backlog, build, review, reviewer/builder personas, close, Harness entry
  and generated working agreement. Unavailable required checks prevent a
  completion claim even when no engine gate covers them; no invented rule_ref.
- Runtime startup/attachment checks current code and readiness, connects the
  browser/DevTools, observes console/network/logs, stored data and cache effects,
  and captures evidence. Only genuinely absent components are not applicable.
- Reviewer inherits available host tools to retain browser/data connections;
  implementation editing, production mutation and destructive cleanup remain
  outside verification. Claude's documented omitted-tools behavior was checked.
- Baseline found existing freshness/TDD expectations but no mandatory AC evidence
  map or required runtime observation. Focused 51 regression checks pass after
  integration; seven skill/composition checks pass after final stop-rule repair.
  Native Claude marketplace validation passes with its existing ignored-engine
  metadata warning; native Codex plugin validation passes.

Five additional runtime forward scenarios passed (see
`docs/design-reviews/runtime-verification.md`). Independent review found that
both headless builder prompt templates still bypassed the new prerequisite;
both now include the AC/runtime evidence obligation and stop without closing
when a required check cannot run. Bash syntax and Python compilation passed;
derived shadows were regenerated before rerunning the full suite. Final
independent review confirmed that green CLI results with missing DevTools
evidence stop both headless prompts before close; no material findings remain.
