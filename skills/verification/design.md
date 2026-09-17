# Design the verification with the feature

Before calling a feature design implementation-ready, write its verification
design in the existing feature spec or architecture document and link it to
the ACs. Do this during design, not after code exists. A list of unit tests or
"test edge cases" is not a verification design. Scale detail to the behavior
and risk; static-only changes can use decisive static checks.

## Establish the happy path and oracle

Walk a representative user action through every participating component. State
the initial state, concrete sample inputs, expected user-visible response and
durable effects, including values/counts/relationships and what must not change.
Derive these expected answers independently from requirements and inputs. Plan
the app-only seed path, real service/browser environment, read-only Python
probes and operation/fingerprint linkage from [integrity.md](integrity.md).

Plan [live coverage](coverage.md) at the same time: which production blocks and
branches must execute for each scenario, which processes own them, and how the
scenario/trace context will connect execution to the observed result. Before
implementation, use planned component/function responsibilities; refine to
exact source locations and hashes once code exists. Do not invent line numbers.
Name needed test seams, controllable clock/randomness, observability, collector
support, source maps and read-only access so implementation includes them.

## Search for edges from the actual design

Follow data/state transitions and cross each boundary asking: what if the input,
ordering, timing or dependency assumption fails? Deliberately examine these
classes; record concrete applicable scenarios or a reason a class does not apply:

- Empty/missing/malformed input, minimum/maximum/just-outside limits, encoding,
  precision, permissions and tenant/ownership boundaries.
- Duplicate or reordered requests, idempotency, simultaneous writers, races,
  stale reads, version conflicts and cancellation/timeouts.
- Partial completion across database/cache/blob/queue boundaries, unavailable
  dependencies, failed uploads/commits, retry exhaustion and backpressure.
- Cold/warm/stale caches, expiry/invalidation, orphaned blobs, delayed workers,
  restart/recovery, migration/compatibility and rollback where relevant.

For each meaningful failure, specify a reproducible trigger, expected error,
allowed intermediate state, forbidden effects and eventual recovery/invariants.
Inject failures through a controlled disposable test environment or an explicit
test seam in the real path; do not fake the resulting stored state. Include
combined failures where their interaction threatens an invariant. Prioritize
by consequence and likelihood without silently dropping known high-risk cases.
Use boundary tables, state transitions, property-based/generated sequences or
fault injection when they expose cases a few examples would miss; every case
still needs a decisive oracle. Do not require unrelated scenario classes.

## Persist a runnable verification matrix

For each AC, record:

```text
AC / scenario ID / happy, boundary, failure or recovery case / risk addressed
Initial state + app seed action / input or controlled failure trigger
Expected response + durable effects + forbidden effects + timing bound
Production path/branch + process / planned coverage and trace attribution
Checks: unit/component, integration, browser and read-only storage probes as applicable
Environment/setup + commands or planned script responsibilities / required evidence
Owner + unresolved prerequisites / disposition for relevant untested risks
```

Make at least the representative happy path and relevant edge/failure/recovery
paths concrete. Cover outcomes at integration boundaries and in the UI where
the AC requires them; unit tests remain useful but cannot stand in for those
observations. Commands and script responsibilities may be planned before code;
label them planned, never pretend they have run.

The existing design peer and local red-team review this matrix with the feature:
look for missing paths, circular oracles, uncontrollable failures, unobservable
outcomes, false-PASS shortcuts and recovery gaps. Turn missing verification
capability into scoped implementation work or an explicit unresolved prerequisite.
A recorded accepted risk is not PASS evidence and does not waive a required AC.
Do not label the design implementation-ready while its required verification
method is undefined. A future script need not already exist, but its input,
oracle, observations and dependencies must be designed. Keep human acceptance
and the engine author-gate's existing authority; this adds no engine schema/gate.

Backlog carries these cases, instrumentation and probe responsibilities into
slice scope and dependencies. Builders refine and execute them; reviewers
independently inspect the evidence. A changed AC, path or risk updates the
matrix and invalidates affected evidence and design-review coverage. Existing
specs/imports/resumed work receive the same gap check before implementation.
