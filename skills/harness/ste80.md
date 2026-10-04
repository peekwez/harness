# STE-80: text for humans

Harness writes text for humans in STE-80. Check a file with
`harness lint-text <paths>`. The check covers rules 1, 5 and 6.

## Rules

1. Write 25 words or fewer in each sentence of a step, a list item or a message. Prose sentences have 35 words or fewer.
2. Put one action in each step.
3. Use the active voice. Name the subject that acts.
4. Use one name for each concept. Take the name from `docs/glossary.md`.
5. Do not use a banned word. Use the plain word in the table below.
6. Do not use a glossary synonym. Use the glossary term.
7. Write rules, not history. Say what to do now.

## Finding messages

1. Put the rule in `rule_ref`. Put what is wrong and the file in the message.
2. Keep the message to 25 words or fewer.
3. Put the command or action that fixes it in `fix`.
4. Put long detail, such as an exception or a symbol list, in `inject`.

Good: `orders.py is outside the declared files of slice slice-042.`
Fix: `Add orders.py to predicted_files of slice slice-042.`

## Review findings

1. `summary`: one sentence of 25 words or fewer. Name the rule, the problem and the file.
2. `failure_scenario`: one or two sentences. Give a concrete input and the wrong result.
3. `fix`: one action.

## Decision rows

A decision row answer has 150 words or fewer. Put the reasons in the ADR that the row cites. `harness compile` warns about a longer answer.

## Banned words

| Banned | Write |
|---|---|
| utilize, utilise, make use of, leverage | use |
| in order to | to |
| prior to | before |
| in the event that | if |
| due to the fact that | because |
| is able to | can |
| a number of | some, or the number |
| facilitate | help, or name the action |
| simply, basically, essentially, obviously | delete the word |
| robust, seamless, best-in-class, cutting-edge, world-class | say what it does |
| at this point in time, going forward | now, later |
| it should be noted that, needless to say | delete the phrase |
| synergy | name the shared gain |
