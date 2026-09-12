---
name: status
description: Render advisory harness telemetry — slice progress, gate outcomes, compaction pressure, and parks per slice.
allowed-tools: Bash(*/bin/harness *)
---

Run this workflow for work the user has requested. In Codex, resolve the
plugin root from this skill path and invoke `python3 <plugin-root>/bin/harness`
with an explicit project `--root`; the `!` substitutions and
`${CLAUDE_PLUGIN_ROOT}` examples below use Claude Code syntax.


# /harness:status

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" status --json`

Repo health (schemas, stale bindings/worktrees, unadjudicated parks, missing
provenance notes, unflushed telemetry) is a separate, complementary view:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" doctor --substrate`

Render the JSON as a short diagnostic dashboard. Telemetry is best-effort:
warnings on stderr mean some optional observations may be missing, and the
dashboard does not by itself prove that human withdrawal is safe.

- **Slice progress**: planned / in_progress / parked / closed counts.
- **Observation bounds**: always show `sample_counts` and
  `observed_interval`; when `--since` is used, telemetry events and graph
  edges use that same window.
- **G2-block rate**: treat it as a Phase-1 completeness diagnostic over the
  reported pre-change sample, especially when the sample is small.
- **Rule outcomes**: show firing, override, and reversal counts from
  `rule_samples`. Do not promote a rule automatically from telemetry; review
  the rule and a meaningful observation history first.
- **COMPACTION_REACHED count**: report context pressure. Call it a defect only
  when `compaction_is_defect` is true in the returned configuration view.
- **Parks per slice and outcomes**: include both review parks and automatic
  retry exhaustion (`slice_parked`), alongside dispatched, closed, merged,
  and event-verdict counts.
