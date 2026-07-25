# Stage 1 — Brainstorm protocol

Socratic elicitation. One question at a time; multiple-choice preferred (2–4
options plus "other"). No solutioning until the problem space is mapped —
if you catch yourself proposing architecture, stop and ask instead.

Order of operations:

1. **Scope assessment first.** If the request spans multiple subsystems,
   decompose into subsystem-scoped brainstorms before descending into detail.
2. **Gap-driven elicitation.** Maintain the coverage map (see
   `coverage-map.md`): domains × decision-types. The next question always
   comes from an empty cell, not from whatever the human happens to mention.
   Completeness pressure is visible, not vibes.
3. **Typed blocks.** Every answer lands in the working document as one of:
   `[constraint]`, `[assumption]`, `[open-question]`, `[non-goal]`.
   Non-goals with backticked paths/globs become G3 boundaries at compile time,
   so capture concrete paths when the human names them.

Exit criteria: coverage map has no empty cells the human considers in scope;
all deferred cells carry `deferred: <owner>`. Mark `<!-- stage: 2 -->`.
