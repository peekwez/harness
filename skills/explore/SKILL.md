---
name: explore
description: Use before architect for a new design. Calibrate, frame the problem, build a quick toy in explore/, write decision cards with evidence and VERIFY.md statements, then freeze.
allowed-tools: Bash(*/bin/harness *) Bash(codex exec *) Bash(claude -p *)
---

Run this workflow for work the user has requested. In Codex, resolve the
plugin root from this skill path and invoke `python3 <plugin-root>/bin/harness`
with an explicit project `--root`; the `${CLAUDE_PLUGIN_ROOT}` examples below
use Claude Code syntax.

# /harness:explore

Explore tests ideas fast and gives each big decision evidence. Architect
starts from its output.

Explore is required for a new design. To skip it, the human gives a reason,
and you run `harness architect --skip-explore "<reason>"`.

Skill level changes how much you explain. It never changes what you check.

## Start

Run this command as your first action:

```
"${CLAUDE_PLUGIN_ROOT}/bin/harness" explore
```

It creates `explore/` with `DECISIONS.md`, `VERIFY.md` and `OPEN.md`. It
keeps each file that already exists.

## Flow

Do the steps in order. End each step with a short message to the human.

1. **Calibrate.** Ask one question for each area that matters to this app. Use [calibrate.md](calibrate.md).
2. **Frame.** Write back the problem, the users, the constraints and the success criteria. Mark each line `[said]` or `[assumed]`. Ask the human to correct it.
3. **Toy.** Build a quick toy in `explore/`. Speed is the goal, not quality. Keep the commands and the output that the cards will cite.
4. **Cards.** Write a card in `explore/DECISIONS.md` for each big decision. Use [card.md](card.md). Each card cites what the toy showed.
5. **Verify list.** Write statements in `explore/VERIFY.md` for each feature, one per line: `V-<feature>-<n>: <statement>`. When `explore/VERIFY.md` exists, write every statement there; compile does not read the working document then.
6. **Challenge.** Run the red-team pass in `../architect/stage-redteam.md`. Then run `harness:design-review`. Each attack targets the "Would change it" line of a card.
7. **Freeze.** Ask the human to run `harness explore --freeze`. Fix each problem that it prints. The human runs it again until it prints `"frozen": true`. An edit after the freeze needs a new freeze.

After the freeze, run `/harness:architect`. It starts with
`harness architect --from-explore`.

## Rules

- A big decision is a store, a transport, a tier, a seam, a trust boundary, or anything that is hard to undo. Choose a seam (for example an API contract, shared types, or none; see `../architect/coverage-map.md`) with a card.
- Show one card at a time. Wait for the answer.
- Each option gives what it solves with an example, the trade-off, the 1st, 2nd and 3rd order effects, and the undo cost. Use plain words.
- Each card has Evidence from the toy, or `no evidence: <reason>`.
- Recommend one option. The "Would change it" line names the fact that would change the recommendation.
- End each card you show with: Reply with a letter, 'explain more about X', or 'not sure, park it'.
- The human answers with an option letter, "explain more about X", or "not sure, park it".
- For "explain more about X", explain X again with a new example. Then ask again.
- Keep the recommendation unless the human gives a new fact.
- For "not sure, park it", write `parked` in `Chosen`. Add the question to `explore/OPEN.md` with an owner and a trigger.
- A vague reply is not a choice. Ask again and name the options.
- When the human says "you choose", pick the recommended option. Write `delegated: <their words>` in `Reason`, and ask the human to confirm.
- Write the human's reason in their own words in `Reason`.
- Only the human runs `harness explore --freeze`. The freeze is their signature.
- Production code never imports from `explore/`. Gate G9 blocks it.
- Do not turn toy code into production code. Copy what you need into a real module, and test it there.

## Done when

- `harness explore --freeze` prints `"frozen": true`.
- Each card cites toy evidence, or says `no evidence: <reason>`.
- Each parked card has an owner and a trigger in `explore/OPEN.md`.
