# Harness reciprocal design review

Date: 2026-09-14 (America/Toronto). Task: add reciprocal design/architecture
critique to the shared Harness plugin. Lead: Codex. Peer: Claude Code.
Provenance: native. Completed Claude critiques: 2. Local Codex CLI smoke: 1.
Execution: completed. Assessment: concerns, reconciled below.
Coverage: superseded for final clarified instructions; the peer saw the
pre-clarification inputs below. Those changes received local independent diff
review and behavioral checks; no third Claude critique or peer approval is claimed.

The initial Claude proposal critique used a fresh tool-free print-mode process.
It reported model `claude-fable-5-1`; the structured follow-up reported
`claude-opus-5[1m]`. Actual host-reported models are recorded, not inferred from
the command. The Codex smoke used `codex exec`, reported `gpt-6-astra`, and
validated the opposite-direction CLI recipe. All invocations disabled hooks,
external tools and delegation and operated on supplied packets outside the repo.

Attempts: one sandbox DNS failure (no review); initial Claude critique completed;
structured follow-up timed out at 180 seconds (no review); the same follow-up
completed with an explicit 360-second validation budget. Failed attempts were
not recorded as approvals. Normal guidance retains a task-adjustable deadline.

## Findings and dispositions

Initial critique: accepted the requests for reproducible authored-input coverage,
structured assessments, immutable-ADR handling, fresh review for imported claims,
and documented provider identity. Declined a new engine hash-status command and
a redundant third model pass: this feature is an advisory skill, with a lead local
check and independent peer, and supplies a concrete hash procedure and records.

The [structured Claude response](harness-reciprocal-design-peer.json) raised:

| Finding | Disposition | Resolution |
| --- | --- | --- |
| F1: hashing normalization ambiguous | Accepted | Pin a literal Python byte-hash command; filter only exact stage-marker lines in docs/architecture.md. Five execution cases passed, including CRLF and missing final newline. |
| F2: allowed-tools prevents preparation | Rebutted | Official Claude skills documentation defines this as a preapproval grant, supports space/comma/YAML lists, and distinguishes disallowed-tools. Host-denied prerequisites now explicitly yield unavailable; isolation is never weakened. |
| F3: insufficient context consumes rounds | Rebutted with clarification | Keep the two-response cost bound, including insufficient-context. If neither response assesses the design, coverage stays incomplete and no sufficient peer review is claimed. |
| F4: acceptance changes an immutable ADR | Accepted | Prepare accepted status and final links in staging, then place at an unused adr/ path; immutable from placement onward. Record original/final hashes and metadata delta. |
| F5: imports skip local risk resolution | Accepted | Stage 3 explicitly runs the imported spec through the local premortem and decision/accepted-risk/rebuttal rule; records include provenance and resume fields. |

Permissions source: [Claude skill frontmatter](https://code.claude.com/docs/en/skills#frontmatter-reference).
The [Codex invocation smoke result](harness-reciprocal-design-codex-smoke.json)
also identified the ADR status-only fingerprint transition; coverage.md now
records and carries forward verified path/status/link-only changes.

Independent local forward tests caught proposed ADR supersession taking effect
on compile. Pending drafts now stay under docs/design-reviews/drafts/ until
acceptance; no compiler semantics changed. Final diff review caught old repair
instructions that edited accepted frontmatter; they now require successors.

## Reviewed input evidence

These are raw file hashes for the explicitly supplied workflow excerpt set,
computed from the actual follow-up packet and current files. None is the working
architecture document, so sha256-v1 performs no stage filtering here. The
response schema was supplied through the CLI schema parameter and validated by
the caller. Missing runtime evidence noted by Claude was checked locally using
installed CLI help/features, compiler source, scenario traces and test results.

| Input | Peer-reviewed SHA-256 | Final SHA-256 |
| --- | --- | --- |
| `skills/design-review/SKILL.md` | `4ce0dbcd55328554e51fc04649ef14864c03054454283bb246579fecad62d0eb` | `4ce0dbcd55328554e51fc04649ef14864c03054454283bb246579fecad62d0eb` |
| `skills/design-review/peer-cli.md` | `b80ffe741da823b4ca44639a8ecdbfab1c0cfdf4103865ca77d06ca16703ea29` | `d3d76b0545d8cd722281a82160fcb481021deb7560a107425d802657cf49055c` |
| `skills/design-review/coverage.md` | `6c3e50da69dfbfcaa8c1a347f167db6623518914bcb4879292a9d7bdbb032ac3` | `3430c8e6e20c7d34c03489ba6439727de945802202418932a06f0d10c591920e` |
| `skills/architect/SKILL.md` | `0a0467bc180931d9d636ef89618243a60de167916dea7d41a432613272b453f3` | `0a0467bc180931d9d636ef89618243a60de167916dea7d41a432613272b453f3` |
| `skills/architect/stage-redteam.md` | `b0499c5c194e415fe4fb0d304353412d5bd4c384cba891fcab3209c1d57e242b` | `b0499c5c194e415fe4fb0d304353412d5bd4c384cba891fcab3209c1d57e242b` |
| `skills/architect/stage-converge.md` | `1c6ca33b81284928864d510dc09a42b7f8aa2840fae2887446ab944bb18ec6ec` | `27bc57d9ce73115118e39f257ef49f72bb0b9150aed1e2203c04496e01a4156a` |
| `skills/adr-authoring/SKILL.md` | `c2832037e5df43165693a2d955a117dc83f4836fa5136da585a750f75aabb33e` | `3fbd2d1e0d15ffd315caa52e75575f8286eb1e740e6e6fe7fd3b7bd78e90157f` |

Packet SHA-256: `773bd6303594d696c9b8ee78b6ae3d01490c176683403a158c59315be05460e0`.

Final deltas: coverage clarifies byte hashing, provenance, incomplete coverage
and pre-placement metadata; ADR authoring clarifies the pre-placement transition;
converge makes imported local risk resolution explicit; peer CLI states the
denied-prerequisite outcome. Remaining accepted tradeoffs: peer availability
is advisory, failed sessions can spend time/tokens, and Markdown workflow
instructions are not a deterministic engine gate. No unresolved design choice
requires a new host dependency or additional model round.

Validation: 797 tests passed; Harness verify passed, substrate doctor healthy,
11/11 golden replays passed. Both CLI directions produced validated output.
Changed skills, response schema, native plugin metadata and ten independent
forward scenarios validated. Final guidance deltas received focused checks.
