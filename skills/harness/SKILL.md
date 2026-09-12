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
