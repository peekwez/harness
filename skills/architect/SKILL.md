---
name: architect
description: Drive the five-stage Phase-0 pipeline (brainstorm, red-team, converge, compile, author-gate). Each stage ends at a safe session boundary — state lives in the working document, never the transcript.
disable-model-invocation: true
allowed-tools: Bash(*/bin/harness *)
---

# /harness:architect

You drive Phase 0 in five stages. The working document is
`docs/architecture.md` (create it if missing). Every stage writes typed
blocks to that document as it goes: long architecting is multiple short
sessions over a durable artifact — never rely on transcript survival.

**If the repo already has a spec** (a design doc, an RFC, a platform spec),
do not re-derive it Socratically. Seed the working document from it first —
the model's own first action, once the human names the path:

```
"${CLAUDE_PLUGIN_ROOT}/bin/harness" architect --from-spec <path to the spec>
```

That writes `docs/architecture.md` at `<!-- stage: 3 -->` (converge): every
`##`/`###` heading becomes a `[constraint]` block with its first paragraph,
every `TODO`/`TBD`/`Open:` line becomes an `[open-question]`, and the doc
ends with an empty ```` ```harness-decisions ```` table. It refuses to
overwrite an existing working document without `--force`. Then read the
seeded blocks WITH the human — a seeded constraint is a claim to confirm,
not a ratified decision — and continue at stage 3 below.

Determine the current stage by reading the working document's `<!-- stage: N -->`
marker (default 1 if absent), then follow the matching protocol file:

1. Brainstorm — `stage-brainstorm.md` (with `coverage-map.md`). When
   superpowers is installed, `superpowers:brainstorming` drives this stage;
   the spec file it writes IS `docs/architecture.md` and the step after the
   design is approved is stage 2 below, never `superpowers:writing-plans`.
2. Red-team — `stage-redteam.md`
3. Converge — `stage-converge.md`
4. Compile — `stage-compile.md`
5. Author-gate — run:

!`"${CLAUDE_PLUGIN_ROOT}/bin/harness" author-gate --report --doc docs/architecture.md`

(The `--report` output above is workflow state, not an error: `gaps` are
expected until stage 5 — read `passed` in the JSON. Before stage 5, use the
gap list only to see what remains.)

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
