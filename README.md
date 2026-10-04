# harness

harness is a Claude Code plugin and a Python engine for building software with coding agents. It records decisions, proves behavior and keeps agent actions safe.

**Documentation: https://peekwez.github.io/harness/**

## What it does

- **Decisions.** Each design decision becomes a decision row. Agents look the answer up instead of guessing.
- **Proof.** Each slice records that its tests failed before the code existed. Close checks that each statement has a test.
- **Safety.** Deterministic gates and a permission layer decide what an agent can do without a human.

Read [Trade-offs and limits](https://peekwez.github.io/harness/trade-offs/) before you adopt harness.

## Install

In Claude Code:

```text
/plugin marketplace add peekwez/harness
/plugin install harness@harness-marketplace
```

The engine needs Python 3.10 or later:

```bash
pip install pyyaml tree-sitter tree-sitter-language-pack
```

Then run `/harness:init` in your repo. Until you run init, the hooks enforce nothing.

The engine also runs without the plugin. CI calls `bin/harness verify` directly.

For Codex, register this repo as a Codex marketplace and install `harness@harness-marketplace`. Then follow [adapters/codex/README.md](adapters/codex/README.md) to install the hooks.

## Quick start

Run these in your repo:

```text
/harness:init                    # create the substrate and wire the hooks
/harness:explore                 # toy, decision cards and statements in explore/
harness explore --freeze         # you sign the cards and the statements
/harness:architect               # cards become decision rows and ADRs; you sign
/harness:backlog                 # slices with red acceptance tests
/harness:build slice-001         # worktree, sandbox and red record; the slice runs to close
/harness:review slice-001        # a forked reviewer reads the substrate and the diff
/harness:close-slice slice-001   # proof checks, commit, git note, then merge or pull request
```

You have a spec already? Start with `harness architect --from-spec docs/spec.md`.

The [Workflow](https://peekwez.github.io/harness/workflow/) pages explain each step.

## Upgrade from 0.9

```bash
harness upgrade --plugin --host claude --dry-run
harness upgrade --plugin --host claude
harness upgrade
```

- The `--dry-run` run prints the plan and changes nothing.
- `--plugin` updates the plugin, then runs the new engine on the project. Use `--host codex` for Codex.
- The plugin run has no terminal, so it skips each step that asks first. Run `harness upgrade` again in a terminal, or add `--yes`.
- Upgrade does not commit. Run `harness doctor --substrate` and `harness verify`, read `git diff`, then commit.

See [Upgrading 0.9 to 0.10](https://peekwez.github.io/harness/upgrading/).

## Repository layout

| Path | Contents |
|---|---|
| `skills/` | the 11 workflow skills |
| `agents/` | the builder, reviewer, architect and red-team agents |
| `engine/` | the engine; `bin/harness` is its CLI |
| `hooks/` | the Claude Code hook wiring and adapter |
| `adapters/` | adapters for other agent hosts |
| `templates/` | the files that `harness init` writes |
| `docs/` | the source of the docs site; `docs/internal/` holds design history and is not published |
| `tests/` | the test suite |

## Contribute

```bash
make test
python3 -m pip install -r docs/requirements.txt
mkdocs serve
```

- `make test` runs the full test suite.
- This repo runs its own ship gate. `.github/workflows/harness-verify.yml` runs `harness verify` on each pull request.
- The Reference pages come from the code. A change to a gate docstring, a CLI help string or a finding catalog entry changes the site in the same pull request.
- The docs follow STE-80. CI runs `harness lint-text` on them.
- Release notes go in [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
