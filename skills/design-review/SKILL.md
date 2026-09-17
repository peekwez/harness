---
name: design-review
description: Use when designing architecture, comparing system designs, reviewing an RFC, or making a new or superseding ADR for requested work in a Harness project.
---

# Independent design review

The current host leads the design. When available, the other provider
independently critiques it: **Claude Code leads → Codex reviews; Codex leads
→ Claude Code reviews.** Read [peer-cli.md](peer-cli.md) for actual invocation,
isolation and result checks. A local persona or tools-only MCP is not a peer.

If you were invoked **as the peer**, return your critique to the lead and
stop: do not invoke this workflow, delegate, edit artifacts or call another peer.

1. **Scope.** Review once a concrete draft/options exist, before final design
   approval or accepting any new/superseding ADR, including during Phase 0.
   Include the stage-2 red-team checklist; retain the lead's local check.
   Also cover imported specs and resumed stages 3–5. Already-reviewed drafts
   with only editorial changes need a recorded delta, not another critique.
2. **Packet.** Provide the original requirements, constraints/non-goals,
   proposed design, alternatives/tradeoffs, relevant decisions/contracts and
   open questions. Include exact current excerpts with source paths and
   content hashes; paths alone do not supply context. Use
   [coverage.md](coverage.md) for fingerprints and durable records. Prefer
   interfaces and
   focused excerpts to whole repositories. Exclude builder transcripts and
   `.harness/memory/session/`. The peer identifies missing evidence explicitly.
3. **Critique.** Ask for at most five highest-impact findings: severity,
   evidence (path/section), affected requirement, consequence, proposed fix
   and uncertainty. Check assumptions, failure/recovery, security, migrations,
   concurrency, operability and unnecessary complexity; request a simpler
   alternative if one meets the requirements. Require
   [response.schema.json](response.schema.json), no edits or delegation.
4. **Reconcile.** Verify each finding against the packet. Record accepted,
   rebutted or deferred, with rationale and an owner for deferrals. Apply
   accepted changes to authored design/ADRs; real risks become a decision or
   explicit `[accepted-risk]` block. Unresolved choices follow the existing
   human/delegation contract. Peer agreement does not sign the author-gate or
   create a blocking rule; disagreements are evidence to resolve, not votes.
5. **Persist.** Write the coverage record and validated peer response under
   `docs/design-reviews/`. Execution status and design assessment are separate:
   a completed response with `insufficient-context` leaves coverage incomplete.
   Missing inputs can use the one focused follow-up; otherwise retain the
   limitation and complete local review without claiming peer coverage.
6. **Bound effort.** One initial critique, at most one focused follow-up for
   material changes or unresolved high risk for this design task, across
   sessions. Reuse coverage only when inputs match. After two rounds, record
   later material changes as `superseded` coverage and surface remaining
   choices; do not reset the budget by renaming the revision.

If the peer is missing, unauthenticated, denied, times out or returns invalid
output, record the specific limitation and continue local red-team review.
Absence/failure is never a pass. Do not retry an unchanged availability failure
at each stage, install tools or change authentication. Retry after a concrete
availability change or user request. Honor a user opt-out; if the user expressly
requires both approvals, require sufficient peer coverage and resolution of
its concerns before finalization, or an explicit human waiver.
