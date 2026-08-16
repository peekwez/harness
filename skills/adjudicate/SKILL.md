---
name: adjudicate
description: Present parked findings with evidence and nearest precedents; every resolution writes back a decision row or durable memory plus an adjudication edge.
disable-model-invocation: true
allowed-tools: Bash(*/bin/harness *)
---

# /harness:adjudicate

List the queue:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" adjudicate --list`

For each parked finding, present to the human: the finding (code, rule_ref,
message, evidence), and its nearest precedents (the `precedents` ids —
fetch their content from `.harness/memory/durable.jsonl`).

Ask the human for a resolution. Then write it back — every resolution MUST
write substrate; a resolution that only lives in conversation will recur:

- Recurring question -> decision row:
  `"${CLAUDE_PLUGIN_ROOT}/bin/harness" adjudicate --finding-id <id> --resolution "<answer>"
  --decision-id D-NNN --domain <domain>`
- One-off judgment -> durable memory:
  `"${CLAUDE_PLUGIN_ROOT}/bin/harness" adjudicate --finding-id <id> --resolution "<judgment>"`
- If the resolution reverses a builder override, add `--reverses` (feeds the
  reversal-rate telemetry that ranks rule quality).

The success metric: parks per slice trends down, and the same question never
parks twice. If a finding looks like a previously adjudicated one, cite the
precedent and apply it — do not re-ask the human.
