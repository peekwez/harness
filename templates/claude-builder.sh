#!/usr/bin/env bash
# Reference builder for `harness run` — headless Claude Code edition.
#
# The dispatcher owns orchestration (worktrees, retries, merges, parking);
# this script owns exactly one thing: drive ONE slice from red tests to a
# closed close-slice inside the worktree the dispatcher provisioned. That
# boundary is the portability contract — swap this file for any agent CLI
# and `harness run` does not change.
#
# Wire it up in .harness/config.yaml:
#
#   run:
#     builder_cmd: "bash /path/to/plugin/templates/claude-builder.sh"
#     max_slice_attempts: 3
#     builder_timeout: 3600
#
# Environment (exported by the dispatcher for every lane):
#   HARNESS_BIN       absolute path to the harness CLI
#   HARNESS_SLICE     the slice id this lane must close
#   HARNESS_WORKTREE  the provisioned worktree (also this script's cwd)
#   HARNESS_ROOT      the main repo root (do not build here)
#
# Optional knobs:
#   CLAUDE_BIN                 claude executable (default: claude)
#   HARNESS_BUILDER_MAX_TURNS  agent turn budget per attempt (default: 100)
#   HARNESS_BUILDER_MODEL      --model override (default: host default)
#
# Why no --dangerously-skip-permissions: the worktree already carries the
# harness autonomy profile (.claude/settings.local.json — sandbox on,
# acceptEdits, the loop's command surface pre-approved, git egress denied),
# and when the harness plugin is installed its PreToolUse hook answers the
# permission question from the gates themselves. Declared work never
# prompts; undeclared work SHOULD fail in headless mode — that is G3
# telling the builder to amend its declaration, not an inconvenience.

set -euo pipefail

: "${HARNESS_BIN:?claude-builder.sh must be launched by 'harness run'}"
: "${HARNESS_SLICE:?missing HARNESS_SLICE}"
: "${HARNESS_WORKTREE:?missing HARNESS_WORKTREE}"

CLAUDE_BIN="${CLAUDE_BIN:-claude}"
MAX_TURNS="${HARNESS_BUILDER_MAX_TURNS:-100}"

cd "$HARNESS_WORKTREE"

# The dispatcher exports CLAUDE_SESSION_ID=run:<slice> for the harness CLI;
# claude mints its own real session id and the sidecar's __default__ binding
# fallback keeps the gates attached to it. Don't leak the synthetic one in.
unset CLAUDE_SESSION_ID || true

PROMPT=$(cat <<EOF
You are the autonomous harness builder for slice '${HARNESS_SLICE}' in this
worktree. Complete the slice END TO END without asking for permission —
implement -> green -> review -> close. Never git push, never merge, never
touch the main tree.

If the harness plugin's build skill is available, follow it. Either way the
loop is:

1. Load context: run
   "${HARNESS_BIN}" --root . resolve --slice ${HARNESS_SLICE}
   and treat its injections as your Phase-1 context. Read this slice's row
   in .harness/backlog.jsonl (acceptance tests, predicted_files, declares).
2. Red first: run the slice's acceptance tests with the acceptance_python
   that resolve reported; they must fail before you implement.
3. Implement inside predicted_files. If you genuinely need another file,
   amend this slice's row in .harness/backlog.jsonl FIRST (G3 findings must
   be reconciled before close). A permission prompt/denial means you
   wandered outside the declaration — amend it, don't fight it.
4. After each source change run
   "${HARNESS_BIN}" --root . extract <changed .py/.ts/... files>
   so the interface shadows stay current.
5. When acceptance is green, self-review: git diff > /tmp/slice.diff, then
   "${HARNESS_BIN}" --root . review --slice ${HARNESS_SLICE} --diff /tmp/slice.diff
   Fix every blocking finding (each names its rule and fix) and re-run
   until clean.
6. Commit everything (git add -A; git commit), then close:
   "${HARNESS_BIN}" --root . close-slice --slice ${HARNESS_SLICE} --commit HEAD
   Use the symbolic HEAD — \$(...) substitution is never auto-approved.
7. If close-slice blocks, its reason names the mechanical fix (amend
   declaration, ack-drift, extract, override --justification). Apply it and
   re-close; budget 3 fix-and-retry iterations, then stop and report the
   blocking finding verbatim.

Done means close-slice printed {"closed": true}. Nothing else counts.
EOF
)

# -p is print (non-interactive) mode: the run ends when the agent stops.
# Permission asks cannot be answered headlessly, so an "ask" is a denial —
# by design (see the note above). Stdout flows through so the dispatcher
# can capture a diagnostic tail on failure.
set +e
"$CLAUDE_BIN" -p "$PROMPT" \
  --permission-mode acceptEdits \
  --max-turns "$MAX_TURNS" \
  ${HARNESS_BUILDER_MODEL:+--model "$HARNESS_BUILDER_MODEL"}
CLAUDE_RC=$?
set -e

# The only success signal the dispatcher trusts is the slice being CLOSED
# on its branch — mirror that check here so retries trigger correctly even
# when the agent exits 0 after merely narrating.
set +e
python3 - "$HARNESS_SLICE" <<'PY'
import json, sys
sid = sys.argv[1]
for line in open(".harness/backlog.jsonl"):
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("id") == sid:
        sys.exit(0 if row.get("status") == "closed" else 1)
sys.exit(1)
PY
CLOSED_RC=$?
set -e

if [ "$CLOSED_RC" -ne 0 ]; then
    echo "claude-builder: slice ${HARNESS_SLICE} not closed" \
         "(claude rc=${CLAUDE_RC})" >&2
fi
exit "$CLOSED_RC"
