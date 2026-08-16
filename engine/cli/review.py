"""`harness review` and `adjudicate` — the review stack's CLI surface.

review runs Layer 0 + the deterministic rubrics and records the reviewer
agent's findings; adjudicate drains the park queue back into substrate.
"""
from __future__ import annotations

import sys
from pathlib import Path

from engine import harness_dir, load_config, write_jsonl
from engine.cli.common import PLUGIN_ROOT, _print, _root, _session


# ------------------------------------------------------------------ review
def cmd_review(args):
    from engine.review import assemble, replay, run_review
    root = _root(args)
    config = load_config(root)
    if args.record_finding or args.park:
        # Layers 1-3 run in the reviewer AGENT (fixed schema, precedents,
        # ensemble). Its conclusions only count once they are substrate:
        # a recorded finding is an auditable edge, a parked one enters the
        # adjudication queue. Without this the queue had no producer at all
        # and every intervention stayed in a transcript (review R1/R2).
        from engine import append_jsonl, read_jsonl, telemetry
        from engine.events import make_finding
        from engine.graph import append_edge
        if not args.slice:
            print("error: --slice required", file=sys.stderr)
            return 2
        if not args.message or not args.rule_ref:
            print("error: --message and --rule-ref are required (a finding "
                  "without a rule reference cannot block or adjudicate)",
                  file=sys.stderr)
            return 2
        severity = args.severity or ("gate" if args.park else "advisory")
        finding = make_finding(
            args.code or ("REVIEW_UNCERTAIN" if args.park else "REVIEW_FINDING"),
            args.rule_ref, args.message, severity=severity,
            layer=int(args.layer or (2 if args.park else 1)),
            key=f"{args.slice}|{args.code}|{args.message[:80]}")
        append_edge(root, "reviewed_by", f"slice:{args.slice}",
                    f"finding:{finding['finding_id']}",
                    meta={"kind": "park" if args.park else "finding",
                          "severity": severity, "code": finding["code"],
                          "rule_ref": args.rule_ref,
                          "confidence": args.confidence,
                          "session": _session(args, root)})
        parked = False
        if args.park:
            path = harness_dir(root) / "parked.jsonl"
            existing = {row["finding"]["finding_id"] for row in read_jsonl(path)}
            if finding["finding_id"] not in existing:
                append_jsonl(path, {"slice": args.slice, "finding": finding})
                telemetry.emit(root, "park", {"slice": args.slice,
                                              "finding_id": finding["finding_id"]})
                parked = True
        _print({"recorded": True, "parked": parked, "finding": finding})
        return 0

    if args.record_fork:
        # ADR-001: an INDEPENDENT (forked) reviewer records its verdict as
        # an auditable edge; close-slice honors the latest verdict for
        # security-relevant slices. Recorded by the reviewer session, never
        # the builder that produced the diff.
        if not args.slice:
            print("error: --slice required with --record-fork", file=sys.stderr)
            return 2
        from engine.graph import append_edge
        edge = append_edge(root, "reviewed_by", f"slice:{args.slice}",
                           "review:fork",
                           meta={"kind": "fork", "verdict": args.record_fork,
                                 "notes": args.notes or "",
                                 "session": _session(args, root)})
        _print({"recorded": args.record_fork, "slice": args.slice,
                "edge": edge})
        return 0
    if args.replay:
        golden = Path(args.golden or (PLUGIN_ROOT / "tests" / "fixtures" / "golden-set"))
        result = replay(root, golden, config)
        _print(result)
        return 0 if result["passed"] else 1
    if not args.slice:
        print("error: --slice required for review", file=sys.stderr)
        return 2
    if args.diff and args.diff != "-":
        dp = Path(args.diff)
        try:
            is_file = dp.is_file()
        except OSError:
            # inline diff text passed as the arg is too long to be a path
            # (Errno 63) — is_file() itself raised; treat as not-a-file (Z2)
            is_file = False
        if not is_file:
            # a raw traceback here tripped every autonomous self-review (X1/Z2)
            print(f"error: --diff {args.diff!r} is not a readable file — "
                  f"pass a unified-diff file path, or use '-' (or omit --diff) "
                  f"and pipe the diff on stdin", file=sys.stderr)
            return 2
        diff_text = dp.read_text()
    else:
        diff_text = sys.stdin.read()
    facts = assemble(root, diff_text, args.slice, config)
    if args.layer0_only:
        _print(facts)
        return 0
    result = run_review(root, facts, config, model=None)
    _print(result)
    return 0 if result["verdict"] != "block" else 1


# ------------------------------------------------------------------ adjudicate
def cmd_adjudicate(args):
    from engine import append_jsonl, now_iso, read_jsonl
    from engine.graph import append_edge
    root = _root(args)
    parked_path = harness_dir(root) / "parked.jsonl"
    parked = read_jsonl(parked_path)
    if args.list:
        _print({"parked": parked})
        return 0
    if not args.finding_id or not args.resolution:
        print("error: --finding-id and --resolution are required", file=sys.stderr)
        return 2
    if args.decision_id and not args.domain:
        print("error: --domain is required with --decision-id (a decision row "
              "in an out-of-scope domain never reaches any slice)", file=sys.stderr)
        return 2
    target = next((p for p in parked
                   if p["finding"]["finding_id"] == args.finding_id), None)
    if target is None:
        print(f"error: parked finding {args.finding_id!r} not found",
              file=sys.stderr)
        return 1
    # Every resolution writes back substrate: a decision row or durable memory,
    # plus an adjudication edge. The same question never parks twice.
    if args.decision_id:
        from engine import load_decisions
        rows = load_decisions(root)
        rows.append({"id": args.decision_id, "domain": args.domain,
                     "question": target["finding"]["message"][:200],
                     "answer": args.resolution,
                     "adr_ref": None, "origin": "adjudication",
                     "created": now_iso()})
        write_jsonl(harness_dir(root) / "decisions.jsonl", rows)
        back_ref = f"decision:{args.decision_id}"
    else:
        from engine import memory
        entry = memory.make_entry(target["slice"], "adjudication",
                                  f"{args.finding_id}: {args.resolution}")
        memory.write_entry(root, entry)
        back_ref = f"memory:{entry['id']}"
    append_edge(root, "decided_by", f"finding:{args.finding_id}", back_ref,
                meta={"kind": "adjudication", "resolution": args.resolution,
                      "reverses": args.reverses})
    remaining = [p for p in parked if p["finding"]["finding_id"] != args.finding_id]
    write_jsonl(parked_path, remaining)
    _print({"adjudicated": args.finding_id, "wrote": back_ref,
            "remaining_parked": len(remaining)})
    return 0
