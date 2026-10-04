# Explore

Explore tests ideas fast and gives each big decision evidence. The agent builds a quick toy, writes a decision card for each big decision, and lists the statements that tests must prove. A human freezes the result.

## When explore is required

Explore is required for a new design. The [0.10 design spec](https://github.com/peekwez/harness/blob/main/docs/internal/superpowers/specs/2026-10-02-harness-0.10-design.md#d-010-12-is-explore-required) gives the reasons. `harness architect` refuses to start unless one of these is true:

- `explore/DECISIONS.md` is frozen.
- You pass `--from-spec <path>` for an existing spec.
- You pass `--skip-explore "<reason>"`.

When `explore/` exists but is not frozen, architect refuses and tells you to run `harness explore --freeze`.

The skip reason goes into the working document as a `<!-- explore-skipped: <reason> -->` line. Close copies it into each slice metrics row as `explore_skipped`.

Existing projects are not affected. A repo that never runs `harness explore` sees no G9 finding. It can add `explore/VERIFY.md` at any time, and `harness compile` reads it.

## The seven steps

`/harness:explore` runs these steps in order:

1. **Calibrate.** The agent asks one question for each area that matters to this app: new to it, used it, or designed it.
2. **Frame.** The agent writes back the problem, users, constraints and success criteria. It marks each line `[said]` or `[assumed]`, and the human corrects it.
3. **Toy.** The agent builds a quick toy in `explore/`. Speed is the goal, not quality.
4. **Cards.** The agent writes a [decision card](../decision-cards.md) for each big decision. Each card cites what the toy showed.
5. **Verify list.** The agent writes statements in `explore/VERIFY.md`, one per line: `V-<feature>-<n>: <statement>`.
6. **Challenge.** The red-team pass and the second-model design review attack the "Would change it" line of each card.
7. **Freeze.** The human runs `harness explore --freeze`.

The agent keeps the calibration levels in its own personal memory. harness does not store them. The level changes how much the agent explains. It never removes a card field.

## Files

| File | Owner | Content |
|---|---|---|
| `explore/` code | agent | the toy, in any structure |
| `explore/DECISIONS.md` | the human signs | decision cards |
| `explore/VERIFY.md` | the human signs | statements: `V-<feature>-<n>: <statement>` |
| `explore/OPEN.md` | agent | parked questions: the question, an owner and a trigger |

`harness explore` creates the folder and the three files from templates. It never overwrites a file that exists. It warns when `explore/` already held other files, because G9 then blocks production imports from them.

## Freeze

`harness explore --freeze` checks the explore files. It writes nothing when it finds a problem. It prints each problem and exits 1. It checks these things:

1. The three files exist, and the front matter of `DECISIONS.md` is valid YAML.
2. Each card follows the card format. Each field has one or two sentences and no template text.
3. Each card has an id `D-E<n>`, two or more options and exactly one `(recommended)` option.
4. Each `Chosen` is an option letter from that card, or `parked`.
5. Each parked card has an owner and a trigger in `explore/OPEN.md`.
6. The decision row of each chosen card has 150 words or fewer.
7. Each statement id in `VERIFY.md` is unique and matches `V-[a-z0-9-]+-[0-9]+`.
8. Git has a `user.name`, and the repo has at least one commit.

Then it writes three keys into the `DECISIONS.md` front matter:

- `frozen_by`: your git identity.
- `frozen_at_commit`: the commit at `HEAD`.
- `frozen_digest`: a SHA-256 of the `DECISIONS.md` body.

An edit to `DECISIONS.md` after the freeze changes the body. `harness architect --from-explore` then refuses until you re-freeze. The digest does not cover `VERIFY.md`. `harness compile` reads `VERIFY.md` each time it runs.

Only the human runs the freeze. The freeze is the human's signature.

## Isolation from production code

The toy is never production code. Copy what you need into a real module, and test it there.

G9 blocks a file outside `explore/` that imports from `explore/`. G9 is active only when `explore/DECISIONS.md` exists. It runs at `post_change`, at `unit_complete` and in `harness verify`.

G9 resolves imports this way:

- **Python:** a module id from the shadow that is `explore` or starts with `explore.`.
- **TypeScript and JavaScript:** an import path that resolves under `explore/`. A relative path is joined to the file's folder, and a bare path is read from the repo root.
- **Go:** an import path that starts with `<module>/explore`, where `<module>` comes from the nearest `go.mod`.
- **Rust:** a `use` path whose first module segment is `explore`.

`explore/` is in the default `gates.exempt_paths`. An edit there gives no G3 undeclared-file finding, no G5 finding and no red-record advisory. G3 still checks the non-goals.

[Trade-offs and limits](../trade-offs.md#imports-from-the-toy) lists the imports that G9 cannot see.
