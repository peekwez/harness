# Adjudicate parked findings

A human resolves parked findings in the main session, through the `harness`
skill. The forked reviewer never adjudicates. List the queue:

    "${CLAUDE_PLUGIN_ROOT}/bin/harness" adjudicate --list

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
- If the resolution reverses a builder override, add `--reverses` (the
  slice metrics count overrides per rule).

The success metric: parks per slice trends down, and the same question never
parks twice. If a finding looks like a previously adjudicated one, cite the
precedent and apply it — do not re-ask the human.
