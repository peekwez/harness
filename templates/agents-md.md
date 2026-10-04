# AGENTS.md — this repo is harness-enforced
<!-- harness:agents-md 0.10 -->

Harness records decisions, proves behavior and keeps actions safe.
Read this file before you edit.

## Binding rules

1. Authored files hold human judgment: ADRs, `.harness/config.yaml`, decision rows. The engine writes derived files: `edges.jsonl`, `boundaries.jsonl`, `slice-metrics.jsonl`. Do not edit a derived file.
2. Work only inside a bound slice from `.harness/backlog.jsonl`. Amend its declarations before you touch other files.
3. When a row in `.harness/decisions.jsonl` answers your question, obey it. When no row exists and the question will recur, park it.
4. To read another module's interface, run `harness resolve --module <id>`. Do not paste its source.
5. A blocking finding must cite a `rule_ref`: `gate:GN`, `decision:D-NNN` or `adr:NNN`.
6. STE-80: write for humans in short, active sentences with one action per step. Use one name per concept from `docs/glossary.md`. Rules: skill `harness:harness`, file `ste80.md`. Check: `harness lint-text <paths>`.

## Autonomy: when to stop

A bound slice is yours to finish without a human. Stop only for:

- a parked review finding;
- an author-gate gap;
- a required check that stays unavailable after diagnosis;
- a gate block whose root cause is outside the slice scope.

A gate block names its fix. Apply it. Closing a slice releases its binding.

## Workflow

```
harness doctor                              # dependency preflight
init -> explore -> architect -> author-gate # Phase 0: a human signs
backlog                                     # spec -> slices
start -> build -> review -> close-slice     # one slice
status / adjudicate / verify                # cost, disputes (via harness skill), CI
```

## Pointers

- Superpowers precedence: decision row D-014 (ADR-002); skill `harness:build`.
- Design review and verification: skills `harness:design-review`, `harness:verification`.
- Code review, with Codex as a second reviewer: skill `harness:review`.
- Gates and their fixes: skill `harness:harness`.
