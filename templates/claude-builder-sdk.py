#!/usr/bin/env python3
"""Reference builder for `harness run` — Claude Agent SDK edition.

Same contract as templates/claude-builder.sh, driven programmatically:
the dispatcher orchestrates (worktrees, retries, merges, parking); this
process drives ONE slice from red tests to a closed close-slice, then
exits 0 iff the slice row reads status=closed.

Prefer claude-builder.sh unless you need programmatic control (custom
telemetry per message, dynamic prompts, embedding in a larger Python
host): the CLI loads the installed harness plugin — hooks AND skills —
exactly as an interactive session would, while the SDK loads only what
`setting_sources` names. With `setting_sources=["project", "local"]` the
worktree's autonomy profile (.claude/settings.local.json: sandbox,
acceptEdits, pre-approved loop commands, git egress denied) still
applies, which is the layer that matters for unattended safety.

Wire-up in .harness/config.yaml:

    run:
      builder_cmd: "python3 /path/to/plugin/templates/claude-builder-sdk.py"

Requires: pip install claude-agent-sdk  (which needs the claude CLI on
PATH). API reference: https://code.claude.com/docs/en/agent-sdk — verify
option names against the installed SDK version before hardening this.
"""
import asyncio
import json
import os
import sys


def build_prompt(harness_bin: str, slice_id: str) -> str:
    return f"""You are the autonomous harness builder for slice '{slice_id}'
in this worktree. Complete the slice END TO END without asking for
permission — implement -> green -> review -> close. Never git push, never
merge, never touch the main tree.

1. Load context: run
   "{harness_bin}" --root . resolve --slice {slice_id}
   and treat its injections as your Phase-1 context. Read this slice's row
   in .harness/backlog.jsonl (acceptance tests, predicted_files, declares).
   Before implementation, read or complete the feature's verification design:
   concrete happy/edge/failure/recovery inputs, independent expected outcomes,
   planned live paths/coverage and runtime probes. Scope missing test seams,
   instrumentation and environment prerequisites now, not after coding.
2. Red first: run the slice's acceptance tests with the acceptance_python
   that resolve reported; they must fail before you implement. Drive every
   unit inside them with the superpowers:test-driven-development skill when
   it is installed. On ANY red test or gate block, run
   superpowers:systematic-debugging and name the root cause before you
   retry — never re-run a fix you cannot explain.
3. Implement inside predicted_files. If you genuinely need another file,
   amend this slice's row in .harness/backlog.jsonl FIRST. A permission
   denial means you wandered outside the declaration — amend it.
4. After each source change run
   "{harness_bin}" --root . extract <changed files>
   so the interface shadows stay current.
5. When acceptance is green, self-review: git diff > /tmp/slice.diff, then
   "{harness_bin}" --root . review --slice {slice_id} --diff /tmp/slice.diff
   Fix every blocking finding and re-run until clean. Verify each finding
   against the substrate before applying it
   (superpowers:receiving-code-review); rebut the wrong ones with reasoning.
6. Run superpowers:verification-before-completion — a fresh acceptance run
   whose output you read. Apply harness:verification in the existing review:
   map every AC to implementation, decisive checks and current observed evidence.
   Start/attach the documented local test stack, confirm this worktree's code,
   connect browser/DevTools, inspect console/network and service logs, query
   scoped database/cache state and capture screenshots/extracts. Only components
   absent from the project are not applicable. Missing tools, denied connections,
   skipped checks, mock-only assertions or stale results never establish PASS.
   For writes, freeze known inputs/expected outcomes before execution; seed through
   the app's real interfaces, then run separate read-only Python DB/cache/blob
   probes. Require app-produced fingerprints linked to actual content/version.
   Never fabricate expected outputs via SQL, Redis, blob uploads or marker
   backfills; probes must not mutate/repair state or derive expected from actual.
   Inspect probe code/imports and use storage-enforced read-only access. Missing
   provenance or contaminated evidence means NOT VERIFIED, not permission to close.
   Follow a verification design prepared before implementation: happy path plus
   relevant boundaries, races, retries, partial failures and recovery, each with
   independent expected outcomes. Collect scenario-attributed block/branch coverage
   from the live app and workers, joined to traces and independently probed effects.
   Aggregate unit/probe coverage or unrelated hits do not prove that path produced
   this result; missing instrumentation/attribution leaves NOT VERIFIED.
   If the skill is unavailable, these same obligations still apply. Return
   VERIFIED only when every required AC/check has current PASS evidence.
   For gaps, reproduce, diagnose, fix in scope and rerun; when a prerequisite
   remains unavailable, report NOT VERIFIED and stop without closing, even
   if CLI review has no engine block. Never mutate production, wipe shared
   data, weaken permissions or edit an AC to manufacture green.
   Only after verification, commit everything (git add -A; git commit)
   and close:
   "{harness_bin}" --root . close-slice --slice {slice_id} --commit HEAD
   Use the symbolic HEAD — $(...) substitution is never auto-approved.
7. If close-slice blocks, debug it with superpowers:systematic-debugging,
   apply the mechanical fix its reason names, and re-close. Stop and report
   the blocking finding verbatim only when the root cause is one you cannot
   fix inside this slice's declared scope.

Composing with superpowers (ADR-002, D-014): you are already inside the
worktree the dispatcher provisioned — never create another;
superpowers:finishing-a-development-branch is NOT used here (close-slice is
the finish, and the dispatcher owns the merge); and
superpowers:subagent-driven-development's stop-for-side-effects rule does not
apply — the sandbox and the gates are the permission layer.

Done requires VERIFIED evidence and close-slice printing {{"closed": true}}.
Do not invoke close-slice while required verification is missing."""


def slice_closed(worktree: str, slice_id: str) -> bool:
    path = os.path.join(worktree, ".harness", "backlog.jsonl")
    try:
        with open(path) as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("id") == slice_id:
                    return row.get("status") == "closed"
    except OSError:
        pass
    return False


async def main() -> int:
    harness_bin = os.environ["HARNESS_BIN"]
    slice_id = os.environ["HARNESS_SLICE"]
    worktree = os.environ["HARNESS_WORKTREE"]
    # the dispatcher's synthetic session id is for the harness CLI, not
    # the agent — let the SDK mint its own (the sidecar's __default__
    # binding fallback keeps the gates attached to it)
    os.environ.pop("CLAUDE_SESSION_ID", None)

    from claude_agent_sdk import ClaudeAgentOptions, query

    options = ClaudeAgentOptions(
        cwd=worktree,
        permission_mode="acceptEdits",
        # load the worktree's provisioned autonomy profile; without this
        # the SDK ignores filesystem settings entirely
        setting_sources=["project", "local"],
        max_turns=int(os.environ.get("HARNESS_BUILDER_MAX_TURNS", "100")),
    )

    async for message in query(prompt=build_prompt(harness_bin, slice_id),
                               options=options):
        kind = type(message).__name__
        if kind == "ResultMessage":
            print(f"claude-builder-sdk: result subtype="
                  f"{getattr(message, 'subtype', '?')} "
                  f"turns={getattr(message, 'num_turns', '?')}",
                  file=sys.stderr)

    # the dispatcher's own success check, mirrored: only CLOSED counts
    if slice_closed(worktree, slice_id):
        return 0
    print(f"claude-builder-sdk: slice {slice_id} not closed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
