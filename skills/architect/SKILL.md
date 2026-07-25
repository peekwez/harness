---
name: architect
description: Drive the five-stage Phase-0 pipeline (brainstorm, red-team, converge, compile, author-gate). Each stage ends at a safe session boundary — state lives in the working document, never the transcript.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/harness *)
---

# /harness:architect

You drive Phase 0 in five stages. The working document is
`docs/architecture.md` (create it if missing). Every stage writes typed
blocks to that document as it goes: long architecting is multiple short
sessions over a durable artifact — never rely on transcript survival.

Determine the current stage by reading the working document's `<!-- stage: N -->`
marker (default 1 if absent), then follow the matching protocol file:

1. Brainstorm — `stage-brainstorm.md` (with `coverage-map.md`)
2. Red-team — `stage-redteam.md`
3. Converge — `stage-converge.md`
4. Compile — `stage-compile.md`
5. Author-gate — run:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" author-gate --doc docs/architecture.md`

Stage-5 rules: if the gate reports gaps, walk the human through each gap and
loop back to the stage that owns it (missing decision rows -> converge;
unresolved open questions -> brainstorm). Progression is blocked until every
sliceable domain has at least one decision row, every open question is
resolved or deferred-with-owner, contracts lint, and the registry covers the
spec's dependency mentions. **The human signs here — this is the one
deliberate checkpoint.** Fully agent-authored Day 0 is out of scope; do not
offer to sign on the human's behalf.

At every stage boundary: update the `<!-- stage: N -->` marker, tell the user
the session can safely end, and name the command that resumes.
