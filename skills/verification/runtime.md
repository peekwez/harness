# Inspect the running implementation

Do this on every verification pass. Unit tests and source inspection accompany
live verification; they do not replace it. Discover the runtime from the
project's README, working agreement, Compose files, scripts and configuration.
Record which services, UI, database and caches exist and which ACs use them.
Only a component actually absent from the project is `not applicable`, with
the discovery evidence. Missing credentials/tools or a failed connection is
`NOT_RUN`/`INCONCLUSIVE`, not `not applicable` or PASS.

## Start and connect

1. Start the documented local/test stack, including Docker services where used.
   If already running, attach and prove it uses this worktree/revision: inspect
   mounts/image/build identity and rebuild/restart the owned service when stale.
   Check health/readiness and dependent service connectivity; a listening port
   or an `up` container alone is insufficient. Record commands, endpoints and
   environment identity. Keep logs accessible while exercising behavior.
2. Open the actual UI through the host's browser automation or browser/DevTools
   connection. Confirm the URL and current application build. Connect tools to
   inspect DOM/rendered state, console errors, network requests/responses and
   relevant browser storage. Screenshots alone do not prove API or state changes.
   If tooling lacks a needed capability, report that specific evidence gap;
   do not describe an imagined browser run.
3. Connect to the disposable/local test database and cache using the project's
   client, CLI or connector. Confirm the target database/schema/cache namespace
   before queries. Scope fixtures and actions to the AC. Use existing test
   accounts/data; no production mutation, blanket cache flush, volume deletion
   or unrelated service shutdown to make a check green.

## Follow the effect through the stack

For each affected AC, perform the real action and inspect its consequences:

- **UI:** exercise the flow, including relevant error/loading/empty states;
  capture screenshots at decisive states and check interactions, not just page load.
- **API/logs:** inspect request inputs, response/body/status, browser console and
  correlated application/container logs. Check the failing path too; an HTTP 200
  cannot prove the intended effect when logs or response contents show failure.
- **Database:** inspect scoped SQL/query extracts before and after the action;
  assert values, row counts, relationships and transaction effects. Reconnect or
  restart the relevant test component when persistence/recovery is part of the AC.
- **Cache:** inspect relevant keys, values, TTLs and behavior on cold/warm reads,
  mutation/invalidation or expiry when relevant. Compare with backing storage;
  a cached response can hide a failed write or stale data. Avoid sleeps when
  a controlled clock or polling on an explicit condition is available.

Store screenshots, scoped/sanitized query extracts, console/network evidence
and log excerpts as artifacts linked to the AC map, with time and runtime
identity. Exclude credentials/session tokens and unrelated user data. Compare
expected and observed results; merely collecting screenshots or SQL output
does not establish PASS.

Record which services this run started. Follow project policy for leaving dev
services running or stopping owned temporary ones; preserve shared/preexisting
services and useful debug evidence. Never close/deploy the slice as a substitute
for connecting to and observing it.
