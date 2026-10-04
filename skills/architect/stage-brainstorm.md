# Stage 1 — Brainstorm protocol

Stage 1 runs after `harness architect --skip-explore "<reason>"`. With a
frozen `explore/`, the explore skill already did calibration and framing,
and the document starts at stage 3. Use
[../explore/calibrate.md](../explore/calibrate.md): calibrate before the
first card when explore did not run.

**With superpowers installed, run `superpowers:brainstorming` for this stage.** Bind it to harness artifacts:

1. Its spec file is `docs/architecture.md`, never `docs/superpowers/specs/…`.
2. Its output lands as the typed blocks below.
3. After your human partner approves the design, go to architect **stage 2 (red-team)**. Do NOT invoke `superpowers:writing-plans`; `/harness:backlog` is this repo's plan.

The coverage map below still governs the questions and the exit criteria. Without superpowers, follow this protocol as written.

Socratic elicitation. One question at a time. Ordinary questions are multiple
choice (2–4 options plus "other"). Big decisions use the decision card. Map
the problem space before you choose. When a big decision comes up, write a
decision card with [../explore/card.md](../explore/card.md) and recommend one
option. On the skip or spec path, write each card in the working document under its `[open-question]` block. At stage 3 the full card moves into the ADR body. Do not pick a design without the human. The human
answers with a letter, "explain more about X", or "not sure, park it".

Order of operations:

1. **Scope assessment first.** If the request spans multiple subsystems,
   decompose into subsystem-scoped brainstorms before descending into detail.
2. **Gap-driven elicitation.** Maintain the coverage map (see
   `coverage-map.md`): domains × decision-types. The next question always
   comes from an empty cell, not from whatever the human happens to mention.
   Completeness pressure is visible, not vibes.
3. **Typed blocks.** Every answer lands in the working document as one of:
   `[constraint]`, `[assumption]`, `[open-question]`, `[non-goal]`.
   Non-goals with backticked paths/globs become G3 boundaries at compile time (advisory unless a gate cites them),
   so capture concrete paths when the human names them.
4. **Verification design.** Use `../verification/design.md` as the feature takes shape. Make the happy path and the relevant edge cases concrete: initial state, input, independent oracle, expected and forbidden effects. Add runtime probes and planned production coverage. Record the test seams, environments and observability in the design before implementation.

Exit criteria: coverage map has no empty cells the human considers in scope;
all deferred cells carry `deferred: <owner>`. Mark `<!-- stage: 2 -->`.
