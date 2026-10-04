# Calibrate

Ask one question for each area that matters to this app. Skip each area
that does not apply. Ask one question per turn.

> For <area>, which fits you best? (1) new to it, (2) used it, (3) designed it.

## Areas

| Area | Ask when the app has |
|---|---|
| Data stores | data that must survive a restart |
| Transports and APIs | two or more processes that talk |
| Tiers and deployment | more than one runtime or host |
| Auth and trust boundaries | users, tenants or secrets |
| Concurrency and jobs | background work or parallel writers |
| User interface | screens or pages |
| Testing and verification | always |
| Operations | a production deploy |

## How to adapt

The level changes three things: the vocabulary, the examples, and how much
of each effect you spell out.

- New to it: use plain vocabulary, and define each term once. Explain each option with an example before you show the card. Spell out the 1st, 2nd and 3rd order effects in full.
- Used it: use the usual terms. Give one example for each trade-off. Skip the basics.
- Designed it: show the card. Keep the effects short. Explain only when the human asks.
- Change the level from what you observe. A precise question shows more experience. A wrong term shows less.
- When the human asks to "explain more", use a new example at a lower level for that area.
- Keep the levels in your own personal memory. Harness does not store them.

## When explore did not run

On the `--skip-explore` and `--from-spec` paths, calibrate before the first
card. Use the same question and the same areas.

The level changes how much you explain. It never changes what you check.
Each card keeps every field at every level, and each card needs evidence or
a reason.
