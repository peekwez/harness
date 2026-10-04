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
        from engine.findings import MAX_MESSAGE_WORDS, clip_words
        words = len(args.message.split())
        if words > MAX_MESSAGE_WORDS:
            print(f"error: --message has {words} words; the limit is "
                  f"{MAX_MESSAGE_WORDS}. Put detail in --failure-scenario.",
                  file=sys.stderr)
            return 2
        severity = args.severity or ("gate" if args.park else "advisory")
        if severity == "block" and not args.fix:
            print("error: a blocking finding needs --fix (STE-80). Pass one "
                  "action that resolves it.", file=sys.stderr)
            return 2
        if severity != "advisory" and not args.fix:
            args.fix = "Run: harness adjudicate --list"
        from engine.findings import CATALOG
        if args.code and args.code not in CATALOG:
            print(f"error: --code {args.code} is not a harness code (STE-80). "
                  "Run: harness gates explain", file=sys.stderr)
            return 2
        finding = make_finding(
            args.code or ("REVIEW_UNCERTAIN" if args.park else "REVIEW_FINDING"),
            args.rule_ref, clip_words(args.message), severity=severity,
            layer=int(args.layer or (2 if args.park else 1)),
            key=f"{args.slice}|{args.code}|{args.message[:80]}",
            inject=([f"Failure scenario: {args.failure_scenario}"]
                    if args.failure_scenario else []),
            fix=args.fix)
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
        from engine.review.rubrics import ensemble_enabled
        if not ensemble_enabled(config):
            print("error: golden replay is opt-in. Set review.ensemble: true "
                  "in .harness/config.yaml, then run it again.",
                  file=sys.stderr)
            return 2
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
def _finding_text(finding: dict) -> str:
    """The message plus its inject lines (the failure scenario), so the
    adjudication row keeps the evidence the short message dropped."""
    return " ".join([finding["message"], *finding.get("inject", [])])[:400]


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
    # Every resolution writes an adjudication edge; a --decision-id also
    # writes a decision row. A one-off ruling never writes shared memory:
    # that needs a human, so the output suggests the promote command.
    # The same question never parks twice (the edge suppresses it).
    suggest = None
    if args.decision_id:
        from engine import load_decisions
        rows = load_decisions(root)
        clash = next((r for r in rows if r.get("id") == args.decision_id), None)
        if clash is not None:
            # validated BEFORE any write: no row, no edge, the park stays
            # queued. Revising or superseding an existing row is the
            # decision-lifecycle work proposed in ADR-003, not an adjudication.
            where = clash.get("adr_ref") or f"origin {clash.get('origin')}"
            print(f"error: decision {args.decision_id!r} already exists "
                  f"({where}: {str(clash.get('question', ''))[:80]!r}) — "
                  f"pick a new id for this adjudication; an existing row is "
                  f"never overwritten (revision/supersession: ADR-003)",
                  file=sys.stderr)
            return 2
        rows.append({"id": args.decision_id, "domain": args.domain,
                     "question": _finding_text(target["finding"]),
                     "answer": args.resolution,
                     "adr_ref": None, "origin": "adjudication",
                     "created": now_iso()})
        write_jsonl(harness_dir(root) / "decisions.jsonl", rows)
        back_ref = f"decision:{args.decision_id}"
    else:
        import shlex
        back_ref = f"adjudication:{args.finding_id}"
        fact = (f"{_finding_text(target['finding'])} "
                f"Ruling: {args.resolution}")
        suggest = f"harness memory promote --text {shlex.quote(fact)}"
    append_edge(root, "decided_by", f"finding:{args.finding_id}", back_ref,
                meta={"kind": "adjudication", "resolution": args.resolution,
                      "reverses": args.reverses,
                      "slice": target.get("slice"),
                      "code": target["finding"].get("code"),
                      "rule_ref": target["finding"].get("rule_ref")})
    remaining = [p for p in parked if p["finding"]["finding_id"] != args.finding_id]
    write_jsonl(parked_path, remaining)
    out = {"adjudicated": args.finding_id, "wrote": back_ref,
           "remaining_parked": len(remaining)}
    if suggest:
        out["suggest"] = suggest
    _print(out)
    return 0
