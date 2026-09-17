---
name: review
description: Run the four-layer review stack over the slice diff in a forked reviewer session — substrate + diff only, never builder memory.
allowed-tools: Bash(*/bin/harness *) Bash(git diff *) Bash(make review-codex *) Bash(codex *) Bash(claude -p *)
context: fork
agent: reviewer
argument-hint: "<slice-id>"
---

Run this workflow for work the user has requested. In Codex, resolve the
plugin root from this skill path and invoke `python3 <plugin-root>/bin/harness`
with an explicit project `--root`; the `!` substitutions and
`${CLAUDE_PLUGIN_ROOT}` examples below use Claude Code syntax.


# /harness:review $1

You are the reviewer. Your context is **substrate + diff only** — you never
read `.harness/memory/session/` (the builder's working memory). Independent
derivation from the same ground truth is the point; where you and the
builder disagree, the substrate underdetermined the answer, and that
disagreement is signal.

Layer 0 — deterministic facts (gates, uses/declares diff, duplicate
candidates, decision rows in scope, shadows of everything the diff imports).
**Run this now, before anything else** (a preflight cannot carry the slice
argument, so this is your first command):

```
git diff <landing.base>...HEAD > /tmp/harness-review-$1.diff && "${CLAUDE_PLUGIN_ROOT}/bin/harness" review --slice $1 --diff /tmp/harness-review-$1.diff --layer0-only
```

`<landing.base>` is `landing.base` from `.harness/config.yaml` (default
`main`) — a repo that ships from `develop` must not be reviewed against a
branch its slices never leave.

After Layer 0, run `harness:verification` (sibling
`../verification/SKILL.md`) as part of this review. Independently trace the
actual acceptance criteria through the implementation and observed check
results. Report the AC evidence matrix and `VERIFIED|NOT VERIFIED` alongside
the existing review verdict; do not claim done from green tests that miss an
AC, skipped checks or stale results. The builder supplies checkable artifacts,
never session memory as proof. Feed each gap back with a reproduction and
next action. This is the reviewer's responsibility, not another agent layer.
It includes starting/attaching to the local stack, a real browser/DevTools
connection, and observing logs, persisted database state and cache effects
where those components exist. Attach the resulting screenshots/extracts to
the AC evidence map. Report an unavailable runtime connection as missing proof.
For writes, follow `../verification/integrity.md`: a frozen known-answer case,
app-only setup/actions, real DB/cache/blob fingerprints and content checks,
and independently reviewed read-only Python probes. Verifier-created outputs
or a probe that repairs state invalidate that run; they cannot establish PASS.
Engine-blocking findings still require the existing `rule_ref` contract below;
missing proof never licenses an invented rule or a fabricated passing result.

Layers 1–3 — rubric-bound checks over those facts:

- One narrow question per check; answer in the fixed schema
  `{answer: pass|fail|uncertain, confidence: 0..1, evidence: string}`.
- Retrieve 2–3 precedent exemplars from adjudicated findings before
  answering (they are listed in the Layer-0 output).
- Every blocking finding MUST cite a `rule_ref` (gate:GN, decision:D-NNN, or
  adr:NNN). No blocking on taste — taste becomes a Layer-3 advisory plus a
  proposed rule. The engine rejects rule-ref-less blocks; do not fight it.
- If your confidence on a would-block finding is below the ensemble
  threshold, say so explicitly and mark the finding `uncertain` — it parks
  for adjudication rather than blocking on a coin flip.
- Layer 3 only: run `superpowers:requesting-code-review` when it is
  installed and treat everything it returns as ADVISORY input. Its
  Critical/Important/Minor severities carry no blocking power here. Promote
  one of its findings to a blocking finding ONLY when you can cite a
  `rule_ref` for it; otherwise record it as a Layer-3 advisory plus a
  proposed rule.
- Layer 3, second opinion: when Codex is available (an MCP tool named
  `codex`, or the `codex` CLI on PATH), run it over the same slice diff —
  `make review-codex` if the repo's Makefile defines that target, else
  `codex review` (or `codex exec` with the diff). Two independent reviewers
  disagreeing is signal. Verify every Codex finding against the substrate
  yourself, then record the real ones with
  `harness review --record-finding …`; blocking still requires a `rule_ref`,
  so the rest are Layer-3 advisories. Codex never auto-fixes inside the
  slice — the slice owner applies fixes so the gates see the edits. If Codex
  is absent, skip this silently.
- When Codex owns the slice, use Claude Code as the independent second
  opinion if available. Start a fresh `claude -p` process with the diff and
  requirements; request structured findings with file, line, evidence and
  severity. Use `--tools Read,Grep,Glob --strict-mcp-config --mcp-config
  '{"mcpServers":{}}' --output-format json --no-session-persistence` so the
  reviewer has file-reading tools and no editing or shell tools. Do not
  resume the builder's session. Check process success and JSON `is_error`,
  then verify and record findings through the same Harness contract above.
  An unavailable or failed reviewer is reported as skipped/failed, never pass.
  `claude mcp serve` exposes Claude Code's tools; it is not itself an
  independent Claude reasoning service. A separate MCP wrapper around
  `claude -p` is optional and is not required for this workflow.

Output: AC verification matrix/verdict, findings list (§5.2 schema), review
verdict, and any Layer-3 proposals.
Blocking findings gate the merge; disputes park via `/harness:adjudicate`.
