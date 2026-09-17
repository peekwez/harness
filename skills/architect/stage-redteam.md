# Stage 2 — Red-team protocol

First examine the working document locally using `agents/red-team.md` and
the premortem checklist. Then run `harness:design-review` (sibling
`../design-review/SKILL.md`): hand the requirements and design to Codex when
Claude Code leads, or Claude Code when Codex leads. This independent peer
can perform the red-team pass with the checklist below. If unavailable,
use the local red-team persona in a fresh fork where supported and record
the missing peer. Never label a same-host fork as a cross-provider review.

The red-team hunts: unstated assumptions, scale cliffs, security holes,
silent-failure modes (the md-file-bug class: anything that no-ops instead of
erroring when an artifact is missing — see the premortem skill's checklist).
Review the feature's verification matrix using `../verification/design.md`.
Challenge happy-path assumptions with concrete boundary, race, retry, partial
failure and recovery cases. For each applicable risk, demand a reproducible
trigger and independent observable oracle, including live production coverage
and cross-store probes where relevant; a unit-test list is insufficient.

Binding rule: **every risk raised must resolve into either a decision or an
explicit `[accepted-risk]` block** in the working document, or an evidence-backed
rebuttal showing the alleged risk does not apply. Accepted risks
become graph nodes at compile time; silently dropped risks are a defect.

Persist the peer findings, dispositions and input coverage via design-review.
Use at most its one focused follow-up for material design changes; retain
remaining choices for the human instead of looping until models agree.

Exit criteria: red-team pass complete, zero unresolved risks, peer status and
any coverage limits recorded. Provider availability alone is not a gate. Mark
`<!-- stage: 3 -->`.
