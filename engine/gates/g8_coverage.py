"""G8 coverage-boundary: files outside shadow enforcement are enumerated.

Advisory, always emitted. Unenforced surface area is always visible,
never invisible.
"""
from __future__ import annotations

from pathlib import Path

from .. import IGNORED_EXTS
from ..events import make_finding
from ..extractor.engine import LANG_BY_EXT

GATE = {"id": "G8", "rule_ref": "gate:G8",
        "preferred": ("post_change",), "fallback": ()}


def check(ctx) -> list:
    findings = []
    enabled = ctx.config.get("languages", {})
    for rel in sorted(ctx.rel(p) for p in ctx.touched_files()):
        ext = Path(rel).suffix.lower()
        if ext in IGNORED_EXTS:
            continue
        # extensionless files (Makefile, Dockerfile, scripts) are unenforced
        # surface too — enumerated, never invisible
        lang = LANG_BY_EXT.get(ext) if ext else None
        if lang is None or not enabled.get(lang, True):
            findings.append(make_finding(
                "UNSHADOWED_FILE", GATE["rule_ref"],
                f"{rel}: outside shadow enforcement (language "
                f"{lang or 'unknown'}); coverage boundary enumerated",
                severity="advisory", key=rel))
    return findings
