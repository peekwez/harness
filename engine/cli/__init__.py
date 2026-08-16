"""harness — framework-agnostic enforcement engine CLI.

The portability boundary: CI and other agent frameworks call this with zero
plugin involvement. Exit 0 = verdict/result emitted (semantics live in the
JSON); exit 2 = malformed input; exit 1 = check failed / engine error.
"""
from __future__ import annotations

import argparse
import json
import sys

from engine import HarnessError
from engine.cli.author import (DEFAULT_WORKING_DOC, cmd_architect,
                               cmd_author_gate, cmd_backlog, cmd_compile,
                               cmd_slice)
from engine.cli.close import cmd_close_slice, cmd_merge_slice
from engine.cli.init import cmd_init
from engine.cli.landing import cmd_land
from engine.cli.review import cmd_adjudicate, cmd_review
from engine.cli.run import cmd_run
from engine.cli.slice import cmd_permit, cmd_start
from engine.cli.substrate import (cmd_extract, cmd_gates, cmd_graph,
                                  cmd_memory, cmd_merge_substrate,
                                  cmd_registry, cmd_resolve, cmd_status)
from engine.cli.verify import cmd_doctor, cmd_event, cmd_verify

__all__ = ["COMMANDS", "main"]

# name -> handler. The single dispatch table: the argparse subparsers below,
# the README-coverage test and any host enumerating the CLI all read it.
COMMANDS = {
    "event": cmd_event, "doctor": cmd_doctor, "init": cmd_init,
    "extract": cmd_extract,
    "resolve": cmd_resolve, "gates": cmd_gates, "verify": cmd_verify,
    "architect": cmd_architect,
    "compile": cmd_compile, "author-gate": cmd_author_gate,
    "backlog": cmd_backlog, "slice": cmd_slice,
    "start": cmd_start, "run": cmd_run, "permit": cmd_permit,
    "close-slice": cmd_close_slice, "merge-slice": cmd_merge_slice,
    "land": cmd_land,
    "review": cmd_review,
    "registry": cmd_registry, "merge-substrate": cmd_merge_substrate,
    "graph": cmd_graph, "memory": cmd_memory, "status": cmd_status,
    "adjudicate": cmd_adjudicate,
}


def main(argv=None):
    p = argparse.ArgumentParser(prog="harness", description=__doc__)
    p.add_argument("--root", help="substrate root (default: walk up from cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("event", help="stdin EnforcementEvent -> stdout Verdict")

    sp = sub.add_parser("doctor", help="engine dependency preflight "
                                       "(+ --substrate for repo health)")
    sp.add_argument("--substrate", action="store_true",
                    help="also audit substrate health: schemas, stale "
                         "bindings/worktrees, parks, notes, telemetry")
    sp.add_argument("--fix", action="store_true",
                    help="clear what is safe to clear (stale bindings, "
                         "unflushed telemetry); never removes worktrees")

    sp = sub.add_parser("init", help="scaffold substrate")
    sp.add_argument("--migrate", action="store_true")
    sp.add_argument("--autonomy", action="store_true",
                    help="also write .claude/settings.json pre-approving the "
                         "slice loop's commands (gates stay the guardrail)")

    sp = sub.add_parser("extract", help="tree-sitter -> universal shadows")
    sp.add_argument("paths", nargs="*")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--force", action="store_true",
                    help="bypass the shadow cache (escape hatch for stale/"
                         "corrupted shadows)")

    sp = sub.add_parser("resolve", help="slice -> assembled context")
    sp.add_argument("--slice", required=True)
    sp.add_argument("--session",
                    help="register the resolved context for this session "
                         "(default: $CLAUDE_SESSION_ID, then 'cli')")
    sp.add_argument("--quiet", action="store_true",
                    help="manifest only, no injections — and therefore no "
                         "context registration (G2 certifies what was shown)")

    sp = sub.add_parser("gates", help="run gate pack / record overrides")
    gsub = sp.add_subparsers(dest="gates_cmd")
    sp.add_argument("--event", default="pre_change",
                    choices=["session_start", "pre_context", "pre_change",
                             "post_change", "unit_complete"])
    sp.add_argument("--session")
    sp.add_argument("--slice")
    sp.add_argument("--files", nargs="*")
    sp.add_argument("--context", nargs="*")
    ov = gsub.add_parser("override")
    ov.add_argument("--slice", required=True)
    ov.add_argument("--target", required=True, help="e.g. registry:telemetry")
    ov.add_argument("--justification", required=True)
    ov.add_argument("--finding-id", dest="finding_id")
    ov.add_argument("--rule-ref", dest="rule_ref", default="gate:G5",
                    help="the gate being overridden (e.g. gate:G1); "
                         "recorded in the audit edge")
    ack = gsub.add_parser("ack-drift")
    ack.add_argument("--slice", required=True)
    ack.add_argument("--module", required=True)
    ack.add_argument("--note")

    sp = sub.add_parser("verify", help="full CI check (no plugin required)")
    sp.add_argument("--built-artifact", help="validate manifests against this tree")

    sp = sub.add_parser("architect",
                        help="seed the Phase-0 working document from an "
                             "existing spec (--from-spec)")
    sp.add_argument("--from-spec", dest="from_spec", required=True,
                    help="existing spec/design markdown (root-relative); its "
                         "headings become [constraint] blocks and its "
                         "TODO/TBD/Open lines [open-question]s")
    sp.add_argument("--doc", default=DEFAULT_WORKING_DOC,
                    help="working document to write (default: %(default)s)")
    sp.add_argument("--force", action="store_true",
                    help="overwrite an existing working document")

    sp = sub.add_parser("compile", help="authored artifacts -> substrate")
    sp.add_argument("--doc", help="working document: [non-goal] blocks plus "
                                  "the typed harness-decisions / "
                                  "harness-abstractions tables (D-013)")

    sp = sub.add_parser("author-gate", help="Day-0 completeness check")
    sp.add_argument("--doc")

    sp = sub.add_parser("backlog",
                        help="estimate context costs; split oversized; "
                             "`add` appends a validated slice row")
    sp.add_argument("--split", action="store_true", default=True)
    sp.add_argument("--no-split", dest="split", action="store_false")
    bsub = sp.add_subparsers(dest="backlog_cmd")
    ba = bsub.add_parser("add", help="append a slice row (no hand-edited "
                                     "JSONL — the EDIT-ME defect source)")
    ba.add_argument("--id", required=True)
    ba.add_argument("--title")
    ba.add_argument("--spec")
    ba.add_argument("--declares", nargs="*", default=[],
                    help="registry ids (validated against registry.jsonl)")
    ba.add_argument("--predicts", nargs="*", default=[])
    ba.add_argument("--acceptance", nargs="+", required=True,
                    help="red acceptance test path(s) — required; slices "
                         "start from red tests")
    ba.add_argument("--depends", nargs="*", default=[])
    ba.add_argument("--linear",
                    help="tracker id for this slice (e.g. GOO-73): quoted in "
                         "the PR title and linked in its body under "
                         "landing.mode: pr")

    sp = sub.add_parser("slice", help="bind a slice (repo default + session)")
    sp.add_argument("--slice")
    sp.add_argument("--session")
    sp.add_argument("--release", action="store_true",
                    help="clear bindings (for --slice, or all)")

    sp = sub.add_parser("start",
                        help="begin a slice: worktree + sandboxed autonomy "
                             "profile + binding + Phase-1 context, no prompts")
    sp.add_argument("--slice", required=True)
    sp.add_argument("--session")
    sp.add_argument("--no-worktree", dest="no_worktree", action="store_true",
                    help="bind in the current tree instead of .worktrees/<slice>")
    sp.add_argument("--force", action="store_true",
                    help="start despite unclosed depends_on (records an "
                         "auditable override; requires --justification)")
    sp.add_argument("--justification")

    sp = sub.add_parser("run",
                        help="campaign dispatcher: build every ready slice "
                             "via run.builder_cmd until the backlog is "
                             "empty or a park needs a human")
    sp.add_argument("--lanes", default=1,
                    help="parallel builder lanes (merges always serialize)")
    sp.add_argument("--builder-cmd", dest="builder_cmd",
                    help="override run.builder_cmd for this invocation")
    sp.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="print the dependency waves and exit; mutates nothing")

    sp = sub.add_parser("permit",
                        help="host permission query: would the harness "
                             "approve this tool call in the bound slice?")
    sp.add_argument("--command")
    sp.add_argument("--paths", nargs="*")
    sp.add_argument("--slice")
    sp.add_argument("--session")

    sp = sub.add_parser("close-slice", help="the close ceremony")
    sp.add_argument("--slice", required=True)
    sp.add_argument("--session")
    sp.add_argument("--commit")

    sp = sub.add_parser("merge-slice",
                        help="merge a closed slice's branch into this tree: "
                             "regen+commit shadows, G4 safety net, remove "
                             "worktree+branch")
    sp.add_argument("--slice", required=True)
    sp.add_argument("--session")

    sp = sub.add_parser("land",
                        help="landing.mode: pr — (re)push a closed slice's "
                             "branch and open its PR after a failed landing")
    sp.add_argument("--slice", required=True)
    sp.add_argument("--session")

    sp = sub.add_parser("registry", help="registry maintenance")
    rsub = sp.add_subparsers(dest="registry_cmd", required=True)
    rf = rsub.add_parser("refresh", help="re-derive a built entry's hashes "
                                         "from its fresh shadow")
    rf.add_argument("id")

    sp = sub.add_parser("merge-substrate",
                        help="git merge driver: keyed-by-id 3-way JSONL "
                             "(%%O %%A %%B; result written to ours)")
    sp.add_argument("base")
    sp.add_argument("ours")
    sp.add_argument("theirs")

    sp = sub.add_parser("review", help="C7 stack / golden replay")
    sp.add_argument("--slice")
    sp.add_argument("--diff")
    sp.add_argument("--replay", action="store_true")
    sp.add_argument("--golden")
    sp.add_argument("--layer0-only", action="store_true", dest="layer0_only")
    sp.add_argument("--record-fork", dest="record_fork",
                    choices=["pass", "block"],
                    help="record an independent forked reviewer's verdict "
                         "for --slice (ADR-001; reviewer session only)")
    sp.add_argument("--notes", help="reviewer notes for --record-fork")
    sp.add_argument("--session")
    sp.add_argument("--record-finding", dest="record_finding",
                    action="store_true",
                    help="write a reviewer-agent finding to substrate "
                         "(Layers 1-3 run in the agent; verdicts must land)")
    sp.add_argument("--park", action="store_true",
                    help="record an uncertain finding into the adjudication "
                         "queue instead of blocking on a coin flip")
    sp.add_argument("--code")
    sp.add_argument("--rule-ref", dest="rule_ref",
                    help="gate:GN | decision:D-NNN | adr:NNN")
    sp.add_argument("--message")
    sp.add_argument("--severity", choices=["block", "gate", "advisory"])
    sp.add_argument("--layer")
    sp.add_argument("--confidence", type=float)

    sp = sub.add_parser("graph", help="queries and provenance walks")
    gs = sp.add_subparsers(dest="graph_cmd", required=True)
    n = gs.add_parser("neighbors"); n.add_argument("node")
    pr = gs.add_parser("provenance"); pr.add_argument("module")
    ud = gs.add_parser("uses-declares"); ud.add_argument("slice")
    nt = gs.add_parser("note", help="(re)write a closed slice's provenance "
                                    "note onto a commit")
    nt.add_argument("--slice")
    nt.add_argument("--commit")
    nt.add_argument("--repoint", nargs=2, metavar=("SLICE", "SHA"),
                    help="re-attach a slice's existing note to the commit "
                         "that carries its content after a squash/rebase "
                         "merge (ADR-002 / D-010)")
    ed = gs.add_parser("edge")
    ed.add_argument("type"); ed.add_argument("frm"); ed.add_argument("to")
    ed.add_argument("--commit"); ed.add_argument("--meta")

    sp = sub.add_parser("memory", help="working-memory write/flush/compact")
    ms = sp.add_subparsers(dest="memory_cmd", required=True)
    w = ms.add_parser("write")
    w.add_argument("--slice", required=True)
    w.add_argument("--kind", required=True)
    w.add_argument("--content", required=True)
    w.add_argument("--approach"); w.add_argument("--outcome"); w.add_argument("--why")
    w.add_argument("--edge", nargs="*")
    fl = ms.add_parser("flush")
    fl.add_argument("--slice"); fl.add_argument("--session")
    fl.add_argument("--compaction", action="store_true")
    co = ms.add_parser("compact")
    co.add_argument("--slice", required=True); co.add_argument("--commit")

    sp = sub.add_parser("status", help="telemetry rendering")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--since", help="only events at/after this ISO timestamp "
                                    "(e.g. 2026-07-01)")

    sp = sub.add_parser("adjudicate", help="resolve parked findings")
    sp.add_argument("--list", action="store_true")
    sp.add_argument("--finding-id", dest="finding_id")
    sp.add_argument("--resolution")
    sp.add_argument("--decision-id", dest="decision_id")
    sp.add_argument("--domain")
    sp.add_argument("--reverses", action="store_true")

    args = p.parse_args(argv)
    try:
        return COMMANDS[args.cmd](args)
    except HarnessError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
