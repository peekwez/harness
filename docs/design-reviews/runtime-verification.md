# Runtime verification workflow validation

User requirement: the existing reviewer checks acceptance criteria against
implementation and observed runtime behavior. It starts/attaches services,
connects browser/DevTools, inspects logs, SQL/stored data and caches, captures
screenshots, and gives builders actionable feedback. No extra mandatory agent.

The shared `verification` skill supplies that workflow in both hosts; build,
backlog, review, close and the headless builder prompts call it. The engine's
existing gates retain their scope: a successful substrate `verify` command
does not certify application behavior. Missing required evidence stops the
workflow with NOT VERIFIED even if no engine gate encodes that requirement.

## Acceptance evidence

| AC | Implementation | Check/evidence | Result |
| --- | --- | --- | --- |
| Trace requirements through production behavior and real checks | verification/SKILL.md and checks.md; reviewer integration | Baseline/forward exercise with a mock-call-only payment test; returned missing durable-effect proof and a concrete repeated-request/query check | PASS |
| Start/attach and inspect current runtime | verification/runtime.md | Stopped Docker/Postgres/Redis/UI scenario requires startup, health, current-build identity, browser/DevTools and scoped storage observations before verification | PASS (workflow exercise) |
| Reject stale running code | runtime identity and evidence rules | Healthy app from main while worktree changes idempotency/cache invalidation; scenario rejected main's evidence and required isolated/current stack and rerun | PASS (workflow exercise) |
| Observe browser/logs/data/cache, not just screenshots | runtime.md effect-through-stack checklist | Screenshot-only tool without required console/network access remained NOT VERIFIED; correlated logs/data may prove a defect but do not erase a missing required check | PASS (workflow exercise) |
| Preserve environment and data boundaries | runtime.md target identification/scoped fixtures | Production-only DB credentials did not authorize mutations; missing disposable database remained NOT_RUN, not not-applicable | PASS (workflow exercise) |
| Handle projects without web components honestly | runtime discovery rules | CLI-only plugin scenario used actual CLI/tests and required repository evidence for absent Docker/UI/data services | PASS (workflow exercise) |
| Apply the same rule to headless builders | both claude-builder templates | Independent review found the old CLI-review-to-close bypass; both prompts now include mandatory runtime/AC evidence and stop-before-close instructions | Repaired and independently reviewed |
| Keep browser/data tools available to reviewer | reviewer persona inherits host tools | Official Claude subagent docs confirm omitted tools inherits available subagent tools; native plugin metadata validation passes | PASS |

These exercises validate the instructions and routing. They do not claim that
a payment application, Docker stack or browser was operated in this repository.
Harness is a CLI/plugin; application-specific runtime targets were simulated
for the forward tests. Its actual runtime validation uses the Python tests,
CLI commands and native plugin validators recorded in the implementation plan.

Remaining limit: this is an explicit reviewer/build obligation, not a new
machine-enforced gate. Tool inheritance does not grant missing credentials,
Docker privileges or browser capabilities. Such gaps stay visible and cannot
be labeled as successful verification. A read-only cross-provider code critique
is advisory and does not replace the primary reviewer's runtime observations.
