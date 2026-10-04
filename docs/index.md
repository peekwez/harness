# harness

harness helps a team build software with coding agents and keep control of three things: the decisions, the proof and the actions.

It is a Claude Code plugin with a Python engine. The engine also runs in CI and, through adapters, in other agent hosts.

## What harness does

harness does three jobs.

1. **It records decisions.** Each design decision becomes a decision row that an agent looks up instead of guessing.
2. **It proves behavior.** Each slice shows that its tests failed before the code existed and pass after it.
3. **It keeps actions safe.** Deterministic gates and a permission layer decide what an agent can do without a human.

harness does not control what the agent reads. Current agents find code with search and file reads. harness gives them the decisions, the boundaries and the proof rules. Then it checks the result.

## Who it is for

- A technical lead who lets agents write production code and needs a record of each choice and its reason.
- A team that wants each change tied to a statement and to a test that could fail.
- An engineer who wants to change harness itself. The engine is plain Python, and each gate is one small module.

harness is a poor fit for some work. [Trade-offs and limits](trade-offs.md) lists what it does not catch and when not to use it.

## Two-minute tour

A feature moves through seven steps. Most steps have a skill in Claude Code and a command in the engine. Freeze is part of the explore skill.

1. **Explore.** The agent builds a quick toy in `explore/`. It writes a decision card for each big decision and cites what the toy showed.
2. **Freeze.** The agent writes statements in `explore/VERIFY.md`, such as `V-orders-3: a failed payment leaves no order row`. A human runs `harness explore --freeze`.
3. **Architect.** `harness architect --from-explore` turns each chosen card into an ADR that holds one decision row. A second model reviews the design. A human signs.
4. **Backlog.** The work becomes slices. Each slice has a title, the statements it verifies, red acceptance tests, declared modules and predicted files.
5. **Build.** `/harness:build <slice>` creates a worktree and a sandbox profile, then binds the slice. The bind runs the acceptance suite and writes a red record.
6. **Review.** A forked reviewer reads only the substrate and the diff. A blocking finding must cite a gate, a decision row or an ADR.
7. **Close and land.** Close checks the proof, then writes a substrate commit, a git note and one metrics row. The slice merges locally or opens a pull request.

These are the main checks at close. Close blocks when one of them is false:

- The acceptance suite and the regression suite are green.
- A red record shows that the acceptance suite failed at slice start. A suite that was green at start needs an override with a reason.
- Each statement of the slice has a test with a `verifies:` comment and a `kills:` text.
- Each change to a public interface has a drift acknowledgement.
- Each module that the slice uses is in its declared modules.
- The review has no blocking finding, and no parked finding of the slice is open.

## What you get

| Part | What it is |
|---|---|
| Skills | 11 workflow skills, such as `explore`, `architect`, `build`, `review` and `close-slice` |
| Agents | builder, reviewer, architect and red-team personas |
| Engine | `bin/harness`: one Python CLI that decides each verdict, in hooks and in CI |
| Gates | G1, G3, G5, G6, G9 and G10, plus the gates that your repo adds |
| Substrate | committed files in your repo: `.harness/`, `adr/`, `explore/`, `AGENTS.md` and a CI workflow |
| Adapters | hook adapters for Codex CLI, Cursor, Gemini CLI, OpenCode and pi |

## What it costs

- One more step before design: a toy, or a one-line reason to skip it.
- One run of the acceptance suite at slice start, and more runs at close.
- Always-on context. `harness status` prints its size for each source, in characters and estimated tokens.
- Model tokens for the forked reviewer and the design review.
- A breaking upgrade from 0.9. `harness upgrade` moves a repo to 0.10 in one run.

## Install

```text
/plugin marketplace add peekwez/harness
/plugin install harness@harness-marketplace
```

The engine needs Python 3.10 or later and three packages:

```bash
pip install pyyaml tree-sitter tree-sitter-language-pack
```

Then run `/harness:init` in your repo. Until you run init, the hooks enforce nothing, and the host's own permissions still decide.

## Where to go next

- [Slice lifecycle](concepts/lifecycle.md) shows the full flow as a diagram.
- [Workflow](workflow/index.md) explains each step and its commands.
- [CLI reference](reference/cli.md) lists each command. The build generates it from the code.
- [Trade-offs and limits](trade-offs.md) tells you what harness does not do.
- [Internals](internals.md) is for contributors.
