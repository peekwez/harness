---
name: verification
description: Use when checking implementation against acceptance criteria (ACs), reviewing whether work is complete, investigating failed checks, or preparing a Harness slice for review or close.
---

# Verify the work

Verify **criteria → implementation → observed evidence**. This is a reusable
part of the existing reviewer, not another mandatory agent or engine gate.
Run it for requested work; verification alone does not authorize edits,
closing a slice or deployment. In a build loop, return failures to the builder
for repair and re-verification within the already authorized scope.

1. **Read the contract.** Read the actual ACs, slice/spec, applicable decisions
   and diff. Give each criterion a stable label. Preserve its meaning; do not
   reduce it to what the implementation already does. Missing or ambiguous
   requirements are `INCONCLUSIVE`, with the smallest question needed. Check
   everything else while that question is pending.
2. **Trace the behavior.** Map each AC to production paths and a decisive
   check with an expected observable result. Inspect the implementation and
   assertions: would this check detect the behavior being broken? A retry AC
   needs the resulting charge/state checked, not just a mocked call count.
   Exercise relevant failure/boundary cases, persistence and real integration
   where the criterion crosses a boundary. Do not invent unrelated requirements.
3. **Observe the running system.** Follow [runtime.md](runtime.md) on every
   verification: discover/start or attach to services, confirm current code,
   connect the browser/DevTools and storage/cache clients, and exercise the
   AC flows. Inspect live logs, console/network traffic, persisted data and
   cache behavior; capture screenshots and relevant extracts. A component
   absent from the project is explicitly not applicable, with evidence;
   a component you cannot start/connect to is an outstanding verification gap.
4. **Run decisive checks.** Use the project's runner/configuration in the
   correct worktree. Run the smallest check first, then required regressions
   and integration/browser/visual checks. Testable
   code exposes observable results, controls clock/random/external inputs and
   separates decisions from side effects; recommend a narrow seam if missing.
   Use static inspection for static claims; runtime claims need runtime evidence.
   See [checks.md](checks.md) for Harness command semantics and evidence rules.
5. **Account for evidence.** For every AC record `PASS|FAIL|NOT_RUN|INCONCLUSIVE`,
   implementation location, exact command/check, expected versus observed
   result and evidence location. Record worktree, revision (plus dirty-file
   hashes if applicable) and relevant environment. A builder's statement is
   not proof; independently inspect logs/results or reproduce the check.
   Skips, disabled runners, zero relevant assertions and unavailable services
   never establish a runtime PASS. Relevant later edits invalidate that evidence.
6. **Turn failure into a next action.** Name the AC, smallest reproduction,
   expected/actual behavior, evidence, likely cause and next discriminating
   check. Distinguish implementation defect, defective test, environment failure
   and unclear requirement; mark hypotheses as hypotheses. The builder fixes
   the cause, reruns the failed check, then affected required checks. Never
   weaken an AC, delete a relevant assertion or retry blindly to obtain green.

Output this compact result in the existing review/PR record:

```text
Verdict: VERIFIED | NOT VERIFIED
Scope: slice/requirement source; worktree; revision + dirty state
AC | implementation | check + expected result | observed evidence | status
Gaps: criterion, reproduction, expected/actual, cause confidence, next action
```

`VERIFIED` requires every required AC and applicable required check to have
sufficient, current PASS evidence. Otherwise use `NOT VERIFIED` and name the
gaps; do not average scores or substitute model agreement. Reuse current
evidence for unchanged scope, and rerun when edits, failures or uncertainty
invalidate it. Persist reproducible failed/abandoned approaches through
Harness attempt memory; keep raw logs in artifacts, not the context window.
