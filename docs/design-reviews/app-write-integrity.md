# App-write integrity verification

Requirement: seed known sample inputs through the application, independently
probe database/cache/blob results with Python, and correlate actual application
writes through fingerprints. Direct storage seeding must never manufacture
acceptance evidence.

Implementation: `skills/verification/integrity.md`, routed from verification,
runtime/check selection, backlog/build/review/close, both personas, the working
agreement and both headless builder prompts. Consumers implement their real app
driver, known-answer cases, write observability and read-only Python probes in
their existing test layout. Harness adds no generic storage adapter or engine gate.

Baseline inspection at 0.9.2 (`279850289818f2c0b2a61d1f3871d1ac724ec21f`) found
missing explicit rules for fixture/output separation, actual blob contents,
read-only probe/import auditing, pre-action oracles and cross-store attribution.
Existing general rules already rejected several false-PASS scenarios; this was
an omission analysis, not an observed agent accepting fabricated evidence.

Independent forward scenarios:

| Case | Observed instruction outcome |
| --- | --- |
| SQL/Redis/blob seeding with checkout API returning 500 | NOT VERIFIED; preserve failure, repair app, rerun app-only case |
| Upload 202 plus marker, truncated object and stale cache | Await bounded completion; inspect actual bytes/state; wrong final result fails |
| Observer imports startup writes; no read-only credentials | Reject observer, invalidate contaminated evidence, report access prerequisite |
| Expected fixture copied from observed data | Reject circular oracle; freeze independent expected values before rerun |
| Real update deliberately evicts cache; no blob effect | Check committed update and absence; do not create unrelated storage effects |
| App-issued presigned upload and finalization | Valid driver path; require real contents, linkage, probe controls and applicable UI checks |
| Headless green engine review but probe repairs DB/Redis | NOT VERIFIED; both prompts stop before close |

Review corrected three ambiguities: expected absence is valid for deletion/
eviction; baseline controls differ for changed versus no-op/rejected effects;
an app-authorized upload driver is distinct from a mutating observation probe.
Follow-up forward review confirmed these distinctions and the requirement that
negative controls fail the intended assertion with healthy connections. Final
independent diff review found no remaining actionable issues.

Runtime validation of Harness: 797 Python tests passed in 173.40 seconds;
substrate verify and doctor passed, as did all 11 golden replay cases. Skill
validation, native Claude/Codex plugin validation, Bash syntax and Python
template compilation passed. Claude retains its preexisting ignored-engine
metadata warning; verify retains only the historical provenance advisories.

These are instruction-path simulations, not live application or storage runs.
The plugin makes a workflow obligation; each consuming project must supply
the application write path, real clients and enforced read-only probe access.
Fingerprints provide traceability, not tamper-proof attestation. Headless
executables still inspect slice closure rather than validating integrity artifacts.
