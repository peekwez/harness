# Prove the application produced the stored result

Use this for ACs that create, update, delete or propagate state. Define a
known-answer case, perform it through the app, then independently probe the
result. Harness supplies this workflow; the builder writes and the reviewer
inspects/runs project-specific Python scripts with the real schema and clients.
There is no universal database/Redis/blob adapter or new Harness CLI command.
Follow [coverage.md](coverage.md) to record which production blocks/branches
actually execute for the case. Correlate that execution with the app operation
and independently probed effects; fingerprints alone do not prove a code path.

## Define the case before running it

Record the AC, unique run/scenario ID, inputs, initial conditions and expected
effects in the project's test/verification directory. Hash this case before
any action. Derive expected values from the requirement and sample input,
independently of the production calculation. Never generate the oracle by
dumping actual state or accepting an updated snapshot after the run.

For each affected store name the expected values, count, relationship,
version/content digest, permitted timing and expected absence/unchanged state.
Define tolerances and asynchronous deadlines up front. Generated IDs may come
from genuine app receipts; record their mapping without using the response to
invent expected business values. Use unique fixture namespaces and capture a
read-only baseline so leftovers cannot satisfy a fresh case.

## The application owns every scenario write

Seed sample data and dependencies through the real UI, supported API, import
flow or public app CLI that exercises the relevant production path. A UI AC
still requires the browser flow. Save requests/actions, responses, operation
IDs, runtime identity and correlated service logs. Await actual completion;
an accepted/queued response alone is not a committed result.

Never insert/update scenario records with SQL, ORM factories or internal
repository helpers; never SET Redis values or upload blobs with independent
storage credentials to manufacture the expected result. A helper named
`seed.py` is not an app interface if it bypasses application behavior. For an
app's presigned upload flow, use its issued upload authorization and required
finalization; an arbitrary object-store upload does not count. Infrastructure
and schema provisioning are separate setup, never evidence of a business AC.

If the app cannot create the required scenario, report that failure and fix
the app within scope. Do not bypass it to continue toward PASS. Ordinary unit
test fixtures may isolate code, but their directly seeded state cannot serve
as app-write integrity evidence. If a probe writes application storage, or the
verifier writes outside the app's supported flow, invalidate that run, preserve
the failure evidence and rerun via the app in a fresh isolated namespace after
correcting the cause. A driver completing the app-issued upload/finalization
flow is an app action; it does not authorize storage writes by observation probes.

## Fingerprints belong to the real write path

The application must expose a causal identity for its writes: a run/request
or operation ID linked to entity/object IDs, version and content digest as
appropriate. Carry that identity through workers and retries. Use existing
schema fields, object metadata, cache payload versions or a committed audit/
outbox linkage; add missing observability in normal application code within
the slice's declared scope. The verifier must never write/backfill markers.

- **Database:** inspect actual rows, values, counts and relationships; tie the
  fingerprint/audit event to the same committed transaction and entity version.
- **Cache:** inspect the app-produced key/value, version/digest and TTL against
  the case and backing state. Exercise cold/warm reads or invalidation through
  the app. For an expected eviction, observe absence and the app's operation
  evidence; do not require a replacement key or change caching semantics.
- **Blob:** inspect the actual object/version, metadata, byte length and a
  digest computed from retrieved bytes against the input/expected artifact.
  A successful upload response, object listing or marker is insufficient.

Only require effects in stores the operation actually uses. For deletion or
invalidation, use durable operation evidence plus observed absence/unchanged
related state. For partial failure, inspect each boundary; a marker emitted
before a failed write or a success log without correct contents is not proof.
Missing linkage is a verification gap, not permission to invent metadata.
Fingerprints establish traceability; they are not tamper-proof attestations.

## Separate app driver and read-only Python probes

Keep the case, app driver and probe scripts reproducible in the project, using
its existing test layout. The driver holds app credentials; probes receive
only storage-enforced read-only credentials/connections and read scoped state
directly from the relevant database, cache and blob service. Do not give probes
the app's write credentials. Confirm target and permissions before execution;
if read-only access is unavailable, report NOT VERIFIED and the prerequisite.

Review probe code and imports before running: no SQL mutations, mutating stored
procedures, ORM auto-create/migrations, Redis writes/Lua, blob uploads, repair
branches, startup imports with side effects, or app calls that warm caches or
otherwise write. Read-only SQL must use parameterized queries. Poll actual
state within the case's deadline for asynchronous effects; never repair it or
silently extend the deadline. Probe output files are evidence artifacts, not
application writes. Sanitize credentials and unrelated data from those files.

Python probes must compare independently observed contents with the frozen
case and app receipt mapping. Emit machine-readable per-store expected/actual
checks, fingerprint linkage and PASS/FAIL/NOT_RUN/INCONCLUSIVE with errors;
return nonzero unless all required checks pass. Unexpectedly missing required
rows/objects, skipped stores, unreachable clients, malformed output and zero
checks cannot be green. Declared deletion/eviction passes only on proven absence.
Keep failures distinct from missing evidence. No `--update-expected` or
catch-and-PASS fallback in verification mode.

Validate the probe itself: for expected new/changed effects, a pre-action baseline
must reject the not-yet-produced result. No-op/rejected-input cases instead compare
unchanged baseline state and require genuine evidence of the app action/rejection.
A deliberately wrong expected value/digest must fail against the same read-only
observations. Negative controls must fail the intended assertion with
healthy connections; a client/environment error does not validate the oracle.
Do not tamper with live storage to test the probe.
Also exercise the AC's retry/idempotency or rejected-input path where relevant
and confirm forbidden/duplicate effects are absent. Preserve failed results.

Example: a case uploads known bytes through the app and expects one document.
The database probe checks one committed row with the expected size/digest and
object reference; the blob probe hashes downloaded bytes; the cache probe
checks the documented current version or eviction. A correct run ID with
truncated bytes, duplicate rows or stale cache still fails. Replaying the
upload checks the declared duplicate/idempotency behavior through the app.

Link the case hash, script hashes, exact commands, app receipts, target/runtime
identity, baseline and probe results in the AC evidence map. Reviewer and builder
must be able to reproduce it. Existing runtime/browser/log checks still apply;
an all-green Python report cannot replace a required UI observation.
