"""Layer 1 — rubric-bound checks: one narrow question per check, fixed JSON
output schema {answer, confidence, evidence}, 2–3 precedent exemplars pulled
from adjudicated findings in the graph.

The model is injected (callable(question, context) -> dict). Without a model,
only deterministic rubrics run — the engine stays standalone.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import HarnessError, harness_dir, read_jsonl
from ..events import make_finding, validate_finding
from .ensemble import run_ensemble

RUBRIC_SCHEMA_FIELDS = ("answer", "confidence", "evidence")


def _deterministic_rubrics():
    """Rubrics answerable from Layer-0 facts alone. Each returns
    {answer: pass|fail, confidence: 1.0, evidence: str}."""

    def uses_reconciled(facts):
        und = facts["uses_declares"]["undeclared"]
        return {"answer": "pass" if not und else "fail", "confidence": 1.0,
                "evidence": f"undeclared uses: {und}"}

    def no_blocking_gate_findings(facts):
        blocks = [f["code"] for f in facts["gate_findings"]
                  if f["severity"] == "block"]
        return {"answer": "pass" if not blocks else "fail", "confidence": 1.0,
                "evidence": f"blocking gate findings: {blocks}"}

    def duplicates_resolved(facts):
        dups = [f["finding_id"] for f in facts["duplicate_candidates"]]
        return {"answer": "pass" if not dups else "fail", "confidence": 1.0,
                "evidence": f"duplicate candidates: {dups}"}

    return [
        {"id": "R-uses", "question": "Are all used registry abstractions declared?",
         "check": uses_reconciled, "severity_if_fail": "block",
         "rule_ref": "gate:G5"},
        {"id": "R-gates", "question": "Are all Layer-0 gates green?",
         "check": no_blocking_gate_findings, "severity_if_fail": "block",
         "rule_ref": "gate:G7"},
        {"id": "R-dup", "question": "Are duplicate candidates resolved or overridden?",
         "check": duplicates_resolved, "severity_if_fail": "block",
         "rule_ref": "gate:G5"},
    ]


def _model_rubrics(root):
    """Model-backed rubrics loaded from substrate decision rows: every
    decision row in scope becomes one narrow conformance question."""
    return [
        {"id": "R-decisions",
         "question": "Does the diff conform to every decision row in scope? "
                     "Answer pass/fail with the violated row id as evidence.",
         "severity_if_fail": "block", "rule_ref": "decision:in-scope"},
        {"id": "R-holistic",
         "question": "Holistic pass: anything worth a new decision row, ADR, "
                     "or gate? Proposals only.",
         "severity_if_fail": "advisory", "rule_ref": "review:layer3",
         "layer": 3},
    ]


def _precedents(root, rubric_id: str, limit: int = 3) -> list:
    """Nearest adjudicated exemplars from durable memory."""
    rows = read_jsonl(harness_dir(root) / "memory" / "durable.jsonl")
    hits = [r for r in rows if r.get("kind") == "adjudication"
            and rubric_id in (r.get("content") or "")]
    hits = hits or [r for r in rows if r.get("kind") == "adjudication"]
    return [r["id"] for r in hits[:limit]]


def _validate_model_output(out: dict, rubric_id: str) -> dict:
    if not isinstance(out, dict):
        raise HarnessError(f"rubric {rubric_id}: model output must be an object")
    for f in RUBRIC_SCHEMA_FIELDS:
        if f not in out:
            raise HarnessError(
                f"rubric {rubric_id}: model output missing {f!r} "
                f"(fixed schema: answer/confidence/evidence)")
    if out["answer"] not in ("pass", "fail", "uncertain"):
        raise HarnessError(f"rubric {rubric_id}: answer must be pass|fail|uncertain")
    return out


def _already_adjudicated(root) -> set:
    """Finding IDs with a decided_by edge: the same question never parks
    twice — prior adjudications suppress the repeat park (§7.7, M6)."""
    from ..graph import load_edges
    return {e["from"].split(":", 1)[1] for e in load_edges(root)
            if e["type"] == "decided_by" and e["from"].startswith("finding:")}


def _already_parked(root) -> set:
    return {row["finding"]["finding_id"]
            for row in read_jsonl(harness_dir(root) / "parked.jsonl")}


def run_review(root, facts: dict, config: dict, model=None,
               record_parks: bool = True) -> dict:
    """Full stack over assembled facts. Returns a verdict-shaped dict with
    findings; parked findings are appended to .harness/parked.jsonl.
    record_parks=False makes the run side-effect-free (golden replay)."""
    from .. import telemetry
    findings = list(facts.get("gate_findings", []))
    parked = []
    adjudicated = _already_adjudicated(root)

    for rubric in _deterministic_rubrics():
        out = rubric["check"](facts)
        if out["answer"] == "fail":
            findings.append(make_finding(
                rubric["id"], rubric["rule_ref"],
                f"{rubric['question']} -> fail. {out['evidence']}",
                severity=rubric["severity_if_fail"], layer=1,
                precedents=_precedents(root, rubric["id"]),
                key=facts["slice"] + "|" + rubric["id"]))

    if model is not None:
        threshold = float(config["ensemble"]["trigger_confidence_below"])
        samples = int(config["ensemble"]["samples"])
        for rubric in _model_rubrics(root):
            ctx = {"facts": {k: facts[k] for k in
                             ("diff_files", "uses_declares", "decisions_in_scope",
                              "imported_shadows")},
                   "precedents": _precedents(root, rubric["id"])}
            out = _validate_model_output(model(rubric["question"], ctx), rubric["id"])
            layer = rubric.get("layer", 1)
            would_block = rubric["severity_if_fail"] == "block" and out["answer"] == "fail"
            # Layer 2: ensemble only when confidence < threshold AND severity
            # would block. Splits escalate as uncertain — never averaged.
            if would_block and out["confidence"] < threshold:
                out = run_ensemble(model, rubric["question"], ctx, samples,
                                   validate=lambda o: _validate_model_output(o, rubric["id"]))
            if layer >= 3:
                # Layer 3 is advisory-only: findings can only spawn proposals.
                if out["answer"] != "pass":
                    findings.append(make_finding(
                        rubric["id"], rubric["rule_ref"],
                        f"proposal: {out['evidence']}",
                        severity="advisory", layer=3,
                        key=facts["slice"] + "|" + rubric["id"]))
                continue
            if out["answer"] == "fail":
                findings.append(make_finding(
                    rubric["id"], rubric["rule_ref"],
                    f"{rubric['question']} -> fail. {out['evidence']}",
                    severity=rubric["severity_if_fail"], layer=layer,
                    precedents=ctx["precedents"],
                    key=facts["slice"] + "|" + rubric["id"]))
            elif out["answer"] == "uncertain":
                f = make_finding(
                    "REVIEW_UNCERTAIN", rubric["rule_ref"],
                    f"{rubric['question']} -> ensemble split; parked for "
                    f"adjudication. {out['evidence']}",
                    severity="gate", layer=2,
                    precedents=ctx["precedents"],
                    key=facts["slice"] + "|" + rubric["id"] + "|park")
                if f["finding_id"] in adjudicated:
                    # Adjudication already answered this exact question:
                    # surface the precedent, do not re-park (park-once).
                    f["severity"] = "advisory"
                    f["message"] += " [previously adjudicated: applying precedent]"
                    findings.append(f)
                else:
                    findings.append(f)
                    parked.append(f)

    for f in findings:
        validate_finding(f)  # a blocking finding without rule_ref is rejected here

    if record_parks:
        queued = _already_parked(root)
        for f in parked:
            if f["finding_id"] in queued:
                continue  # already in the queue: no duplicate rows
            from .. import append_jsonl
            append_jsonl(harness_dir(root) / "parked.jsonl",
                         {"slice": facts["slice"], "finding": f})
            telemetry.emit(root, "park", {"slice": facts["slice"],
                                          "finding_id": f["finding_id"]})

    verdict = "allow"
    if any(f["severity"] == "block" for f in findings):
        verdict = "block"
    elif findings:
        verdict = "allow_with_findings"
    return {"verdict": verdict, "findings": findings, "injections": [],
            "parked": [f["finding_id"] for f in parked]}
