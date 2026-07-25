# harness × Google Gemini CLI

1. Merge the `hooks` object from `settings-hooks.json` into
   `<repo>/.gemini/settings.json` (or `~/.gemini/settings.json`), replacing
   `${HARNESS_DIR}` with the absolute path of your harness checkout.
2. Bind the active slice: `export HARNESS_SLICE=<slice-id>` or
   `harness slice --slice <id> --session <session>`.
3. Optional: package this adapter as a Gemini extension
   (`gemini-extension.json` + `hooks/hooks.json` + `contextFileName:
   "AGENTS.md"`) so one install ships hooks + context together.
4. Manage at runtime with `/hooks panel`.

**Autonomy (prompt-free slice loop):** install `autonomy-policy.toml` to
`~/.gemini/policies/harness-autonomy.toml` (USER tier — the workspace
policy tier is currently broken upstream, issue #18186): blanket allow at
priority 50, `git push`/`git remote` denied at 900. Optionally add
`"tools": {"allowed": ["run_shell_command(git)", "run_shell_command(pytest)"]}`
to settings.json. Avoid `--yolo`; the policy denies are the point.

Enforcement notes: Gemini hooks are FAIL-OPEN — a crashing hook only warns.
Two mitigations: (a) `harness verify` in CI is the fail-closed backstop;
(b) add deny rules to the Gemini Policy Engine
(`~/.gemini/policies/*.toml`) for paths compiled into
`.harness/boundaries.jsonl` if you need hard, hook-independent bans.
Field names on tool events vary slightly across versions — the adapter
reads `tool_input`/`toolArgs`/`args` defensively; verify against
`gemini --version` ≥ 0.26.
