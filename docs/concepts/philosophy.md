# Philosophy

harness 0.10 rests on a few ideas. This page states each idea and the reason for it.

## Three jobs

harness does three jobs:

1. It records decisions.
2. It proves behavior.
3. It keeps actions safe.

harness does not control what the agent reads. Agents find code with search and file reads. harness gives them the decisions, the boundaries and the proof rules. Then it checks the result.

## Why 0.10 changed course

harness 0.9 made three assumptions about agents:

- Agents cannot find context.
- Agents wander out of scope.
- Agents edit derived files by hand.

Current models read code with search and file reads at low cost. Claude Code requires a file read before an edit. One consumer repo on 0.9.4 showed what the old assumptions cost:

- Path-only G3 non-goals: 46 overrides against 45 firings.
- G5: 12 overrides against 1 firing.
- Campaign mode: 0 dispatches.
- Shadows: 3.0 MB, and 90% of that text was not interfaces. One false G7 block came after a docs build.
- Slice context injection: about 2.4k tokens on each prompt. The 9,500-character clip cut the decision rows.
- After 13 closed slices, a whole-repo review found 11 defects. Tests often checked the wrong object.

The risks that remain are these:

- decisions without evidence;
- tests that prove nothing;
- unsafe actions;
- text that humans cannot read fast.

Each part of 0.10 targets one of these four risks.

## Lookup, never interpret

A recurring choice has one decision row. The agent looks up the row and does not decide again. An ADR holds the reasons and the options that the team did not choose.

Each agent reads a principle in a slightly different way, in each file and each session. A row gives one answer each time. The [Decision cards](../decision-cards.md) page shows how a row starts.

## Deterministic gates, advisory judgement

A gate is code. It gives the same answer for the same input each time.

A blocking finding must cite a `rule_ref`, such as a gate, a decision row or an ADR. The engine rejects a blocking finding that has no `rule_ref`.

Model review gives advice. A model finding blocks only when it cites a rule. A model finding with low confidence parks for a human. The holistic review layer never blocks.

## Skill level changes explanation, not checks

Before the first decision card, the agent asks how well you know each area, such as data stores or auth. It explains more to a person who is new to an area. It never checks less. Each card keeps every field at every level.

## Writing for humans

harness writes text for humans in STE-80. STE-80 has four rules:

1. Short sentences: 25 words or fewer in steps and messages.
2. One action per step.
3. Active voice with a named subject.
4. One name per concept, from the glossary.

`harness lint-text` checks sentence length, banned words and glossary synonyms. Its limit is 25 words in list items and numbered steps, and 35 words in prose. It does not detect passive voice or meaning.

The [Glossary](../glossary.md) gives one name for each concept. A finding message follows the same rules. It states the rule, what is wrong and the file. The fix comes after the message.

## Architecture in one table

| Layer | Contents |
|---|---|
| Decide | explore, architect, design review, ADRs, decision rows, `compile` |
| Prove | `verify.jsonl` statements, red record, acceptance and regression, statement coverage, G6, forked reviewer |
| Safe | permits, autonomy profile, egress fail-closed, G1, G9 |
| Context | one injection per binding, deltas after, pointers instead of shadows |
| Interfaces | lazy shadow cache for G5, G6 and review |
| Memory | `.claude/memory/shared/` only, guarded by G10 |
| Words | STE-80, `lint-text`, glossary, finding catalog |
| Docs | mkdocs site, generated reference |
