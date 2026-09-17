# Choose checks that prove the claim

Read `.harness/backlog.jsonl` for the slice's `acceptance` paths, and
`.harness/config.yaml` for `acceptance.cmd`, `cwd`, `env`, `gate_cmd` and
`gates.acceptance_runner`. Read the existing tests and their assertions.
Respect the project's test environment and command wrappers; never assume
pytest in a project configured for another runner.

- Per-slice development checks use the configured acceptance command with
  that slice's expanded paths. The default is the project's acceptance Python
  running `-m pytest <paths> -q`. Custom commands substitute `{paths}` or append
  paths when absent; the engine uses argv splitting, not a shell. A red
  feature/bug regression must fail for the intended behavior, not a broken
  environment. Existing correct behavior and static/doc changes need no
  artificial failing test.
- `harness acceptance --closed` runs declared tests for **closed** slices.
  `--list` only inspects selection. Neither selects the active slice; there
  is no `acceptance --slice` command. Inspect `ran`, `disabled`, selected paths
  and actual results as well as process exit status.
- `harness verify` checks substrate/derived-artifact consistency. It does
  **not** execute application acceptance tests or prove user-facing behavior.
- `close-slice` reruns configured acceptance and gates, checks committed bytes
  and records provenance. A standalone verifier does not call it as a test
  shortcut: it mutates lifecycle state. The existing close workflow owns it.

Choose evidence proportional to the claim:

| Claim | Useful evidence |
| --- | --- |
| Validation/calculation | Real input/output assertions, including relevant invalid and boundary input |
| Retry/idempotency | Repeated request against the real state transition; exactly one durable effect |
| Persistence/migration | Disposable representative database; read after reconnect/restart; migration failure/recovery where required |
| App writes across stores | Predeclared sample case, app-only seed/actions, correlated real DB/cache/blob contents and independent read-only Python probes (see [integrity.md](integrity.md)) |
| API/integration | Real boundary in the supported test environment; status, response and resulting state |
| UI behavior/layout | Exercise required flow in browser; state assertions and rendered evidence for visual claims |
| Static docs/config | Parse/lint/reference or generated-output inspection tied to the actual requirement |

Mocks may isolate an external dependency; assertions must still exercise the
changed production behavior. Check that tests are discovered and relevant
assertions ran. A stub `assert False`, a no-op test command, or asserting only
mock behavior is not an acceptance oracle. If evidence seems unable to catch
the defect, demonstrate a counterexample or a reversible local mutation when
safe; restore it before continuing. Do not mutate shared/production state.

Treat verified CI results as evidence only for their exact revision, environment
and check scope; inspect the result itself. Retain check output as a linked
artifact and put a short AC map in the existing review record. No new report
file is required if that record already exists. On resume, recheck revision,
dirty state and relevant fixtures/configuration before reusing evidence.

Feedback example: `AC-2 NOT VERIFIED — duplicate payment requests returned 200,
but no assertion inspects persisted charges. Reproduce by sending the same key
twice against the test store; expect one charge after reconnect. Add that
assertion and inspect the idempotency transaction if it fails.` This identifies
the missing proof without claiming a double-charge defect has already occurred.
