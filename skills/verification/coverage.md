# Show which live code produced the result

For each runtime AC, connect **app action → executed production path → observed
effect** in the same scenario. Coverage establishes execution; trace/operation
identity links that execution to the action; independent assertions establish
correctness. None of those three replaces the others. Static-only changes use
static checks and do not require a fabricated runtime scenario.

## Plan and instrument the real application

1. From the AC and implementation, identify the relevant production functions,
   blocks and branch outcomes: handler, validation/decision, worker, persistence
   or cache/blob boundary as applicable. State which path each known-input case
   should exercise, including required failure/retry cases. Assess these paths,
   not an arbitrary repository-wide coverage percentage or 100% target.
2. Enable the project's native line/block and branch collector on the actual
   local/test application processes before exercising the case. Include servers,
   workers, child processes and browser code that implement the AC. Coverage of
   the seed driver, Python probe, mock or test helper is not application coverage.
   Keep instrumentation in the verification environment; preserve app semantics
   and normal public entry points. Record process/container, build/revision,
   source hashes and collector configuration/version. Map compiled code through
   matching source maps/debug information where needed.
3. Isolate attribution. Use scenario/request measurement contexts when the
   collector supports the application's concurrency model; propagate the same
   operation/trace ID through requests, queues, workers and retries. Do not assume
   a process-global context switch safely separates simultaneous requests. If
   request attribution is unsupported, run one scenario at a time in an isolated
   app instance with no unrelated traffic/background work, and capture/reset
   scenario counters using supported collector operations after setup/readiness.
   Exclude setup and observation-probe activity. A startup-wide or cumulative
   coverage file cannot attribute a hit to this action, and subtracting aggregate
   sets can miss lines already executed during startup or another request.

Use the existing collector and tracing facilities when available. For Python,
[coverage.py contexts](https://coverage.readthedocs.io/en/latest/contexts.html)
can label measured execution; [branch collection](https://coverage.readthedocs.io/en/latest/commands/cmd_run.html)
requires branch measurement, and [process handling](https://coverage.readthedocs.io/en/latest/subprocess.html)
must include child processes and flushing/export from long-running services.
Check the installed version before choosing its startup/export options. Other
languages use their native collector with equivalent attribution and source
identity; Python is the probe language, not a requirement for the application.
Trace [context propagation](https://opentelemetry.io/docs/concepts/context-propagation/)
can connect services, but a function span alone does not prove each inner branch
ran. When native collection cannot identify a required block, add narrow runtime
instrumentation at that actual block within scope or report INCONCLUSIVE. Never
replace missing block evidence with a generic log statement or inferred path.

## Execute, collect and join the evidence

Drive the frozen sample case through the app while collecting execution data.
Wait for its real asynchronous work within the declared deadline, flush/export
all participating processes and inspect the resulting raw data. Preserve
per-scenario/process records before combining compatible artifacts. Do not mix
different source revisions, unit suites, other cases or stale reports. Confirm
the collector was active and exported the intended process/context; an empty
file, sampled-away trace or missing worker is an evidence gap. Live display is
optional; the data must come from the live execution and remain inspectable.

Record in the existing AC map:

```text
AC / scenario / operation + trace IDs
Expected production path / process + build / covered and missed blocks or branches
Coverage artifact + collector scope / linked trace or block events
App receipt + committed entity/object version / independent expected-versus-actual probe
Execution status / outcome status / gaps and next discriminating check
```

Join the path to the same operation's actual result: use existing trace IDs,
receipts, committed audit linkage, entity versions or content hashes. Extra
marker tables or schema fields are unnecessary when those already establish
the linkage. A hit on a write line or a successful span does not prove the write
committed; retain all checks in [integrity.md](integrity.md). Conversely, correct
stored data without attributable execution cannot prove the claimed block ran.

If a required block/branch is missed, distinguish a wrong scenario, incorrect
implementation and broken instrumentation before repairing and rerunning. Do
not call internal helpers directly, force a branch, seed storage, edit counters
or weaken expected values to paint coverage green. Drive the appropriate real
input through the app. Missing collectors, source mapping, attribution or trace
export leave the AC NOT_RUN/INCONCLUSIVE and the verdict NOT VERIFIED. A known
wrong path or result is FAIL even when other paths are covered.

Example: checkout's duplicate-request case must show the idempotency branch in
the running handler/worker and exactly one durable order through a read-only
probe. A 95% unit-suite report, a hit from an unrelated request, or coverage of
the probe cannot establish that. A covered write followed by rollback still
fails an AC requiring a committed order. Application traces, coverage and
fingerprints are evidence to cross-check, not tamper-proof attestation.
