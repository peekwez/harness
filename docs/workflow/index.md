# Workflow

This section explains each step of the harness workflow and the commands behind it. Each step has a page.

## Steps at a glance

| Step | Skill | Engine command | Output |
|---|---|---|---|
| [Explore](explore.md) | `/harness:explore` | `harness explore`, then `harness explore --freeze` | `explore/` files, signed by the freeze |
| [Architect](architect.md) | `/harness:architect` | `harness architect`, `harness compile`, `harness author-gate` | ADRs with decision rows, `.harness/*.jsonl` substrate |
| [Backlog](backlog.md) | `/harness:backlog` | `harness backlog add`, `harness backlog` | slice rows with red acceptance tests |
| [Build](build.md) | `/harness:build` | `harness start` | a worktree, a sandbox profile, a binding and a red record |
| [Review](review.md) | `/harness:review` | `harness review` | findings, a verdict, parks |
| [Close](close.md) | `/harness:close-slice` | `harness close-slice` | a substrate commit, a git note, a metrics row |
| [Land](land.md) | `/harness:close-slice` | `harness merge-slice` or `harness land` | a local merge, or a pull request |

A skill is the agent's instructions for a step. The engine command is what decides. You can run each engine command yourself.

The other skills:

- `init` scaffolds the substrate in a repo.
- `design-review` gets an independent critique of a design from a second model.
- `adr-authoring` writes and supersedes ADRs and decision rows.
- `verification` checks each acceptance criterion against observed evidence.
- `harness` covers status, upgrade and adjudication of parked findings.

## Who signs what

A human does these things. The skills tell the agent never to do them for the human:

1. Chooses each decision card: a letter, or "park it".
2. Freezes `explore/` with `harness explore --freeze`. The freeze writes the human's git identity as `frozen_by`.
3. Gives the reason when a design skips explore.
4. Signs the author gate at the end of architect.
5. Resolves each parked finding with `harness adjudicate`.
6. Approves each `harness memory promote`. On Claude Code, the permit layer asks the human each time.

Overrides and forced starts need a written reason. The engine stores the reason and does not judge it. Read each override in review.

The agent does everything else: the toy, the cards, the slices, the code, the review and the close.
