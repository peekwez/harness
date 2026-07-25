"""Layer 2 — ensemble: N samples on low-confidence blockers.

Splits escalate as `uncertain`, never silently averaged.
"""
from __future__ import annotations


def run_ensemble(model, question: str, context: dict, samples: int,
                 validate=None) -> dict:
    outs = []
    for i in range(samples):
        out = model(question, {**context, "sample": i})
        if validate:
            out = validate(out)
        outs.append(out)
    answers = {o["answer"] for o in outs}
    if len(answers) == 1:
        best = max(outs, key=lambda o: o["confidence"])
        return {"answer": outs[0]["answer"],
                "confidence": best["confidence"],
                "evidence": "; ".join(dict.fromkeys(o["evidence"] for o in outs))}
    # split -> uncertain, park for adjudication (never a majority verdict)
    return {"answer": "uncertain", "confidence": 0.0,
            "evidence": f"ensemble split across {samples} samples: "
                        f"{sorted(answers)}; "
                        + "; ".join(o["evidence"] for o in outs)}
