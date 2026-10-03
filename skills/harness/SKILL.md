---
name: harness
description: Inspect, upgrade, plan, build and verify projects that use the Harness development substrate.
---

Use the Harness engine shipped with this plugin. Resolve the plugin root as
two directories above this skill's directory, then invoke
`python3 <plugin-root>/bin/harness --root <project> <command>`.
Use explicit paths; `${CLAUDE_PLUGIN_ROOT}` and the `!` command substitutions
in the shared Claude workflow guides are host syntax, not Codex commands.

Start with `doctor --substrate` and `status --json`. Read the project's
working agreement and `.harness/config.yaml`. The guides under `skills/`
describe the method; use the CLI's `--help` for executable command syntax.

For design, architecture, imported specs and new/superseding ADRs, follow
`architect` and `design-review`: the current host leads and the other provider
independently critiques when available. Persist findings and coverage; retain
local review and human design authority when the peer is unavailable.

For implementation review or "is it done?", use `verification` inside the
existing reviewer. Trace ACs through production behavior and current observed
checks, return explicit per-criterion evidence and actionable gaps. The engine's
`verify` command checks substrate consistency, not application acceptance.

- Use `upgrade --dry-run` to inspect local generated-file and schema updates.
  Use `upgrade --plugin --host codex --dry-run` to inspect a plugin update.
  Apply an upgrade when the user has requested it; report the resulting
  version, substrate warnings, and any new-thread or hook trust step.
- Author slices with the backlog CLI. Oversized slices produce proposals;
  each child needs its own acceptance tests and predicted files.
- Bind work with `start --slice <id>` or `slice --slice <id>`. Dependencies
  must be closed; an explicit forced start requires a written justification.
- Run acceptance and review, commit the source, then use
  `close-slice --slice <id> --commit HEAD`. Closure validates the committed
  bytes and records provenance. Follow the project's configured landing mode.
- Run `verify` before delivery. Telemetry provides diagnostic observations;
  it does not establish correctness or authorize a change.

Installing skills does not activate project hooks. Existing Codex hook
integration uses `adapters/codex/README.md`; preserve other hooks and let the
host request trust when commands change. CI verification remains necessary.

## Gates

Each gate finding names its fix. Apply the fix, then retry.

- G1 manifest-complete: `.harness/` needs `config.yaml`, `schema_version`, `registry.jsonl` and `decisions.jsonl`, and each slice needs its red acceptance tests. Run `/harness:init` or write the missing test.
- G3 spec-bound: a touched file outside the slice's declared files is an advisory finding, and close lists it under `scope_advisory`. A file matching a non-goal boundary blocks only when a `gates.extra` gate cites the boundary id or rule ref in `GATE["cites"]`; otherwise it is advisory, and `compile` lists it under `advisory_only`. Add the file to `predicted_files`. For a cited non-goal, run `harness gates override --target boundary:<id>` with a justification.
- G5 registry-conform: this advisory flags a use outside the slice's declared dependencies, or a reimplemented abstraction. Close reconciles uses against declares and still blocks on a mismatch. Declare the dependency, reuse the entry, or run `harness gates override` with a justification.
- G6 interface-drift: a changed public interface needs an acknowledgement before close. Run `harness gates ack-drift --slice <id> --module <module>`.
- Unshadowed files: `harness doctor --substrate` lists source files that no extractor enforces under `unshadowed_files`. It is advisory.
- Repo-local gates: modules listed under `gates.extra` in `.harness/config.yaml` run beside the builtin gates. A load or run error blocks and names the entry. Fix that module.
