"""`harness lint-text`: the STE-80 text check (spec 9.3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from engine.lint_text import GLOSSARY_PATH, format_row, lint_paths


def cmd_lint_text(args):
    """Lint markdown text.

    Exit 0: no findings. Exit 1: findings. Exit 2: a path or the explicit
    glossary does not exist. The default glossary is docs/glossary.md under
    --root (or the current directory) when that file exists.
    """
    base = Path(args.root) if args.root else Path.cwd()
    if args.glossary:
        glossary = Path(args.glossary)
        if not glossary.is_file():
            print(f"error: glossary {args.glossary} does not exist",
                  file=sys.stderr)
            return 2
    else:
        default = base / GLOSSARY_PATH
        glossary = default if default.is_file() else None
    try:
        rows = lint_paths([Path(p) for p in args.paths], glossary)
    except FileNotFoundError as exc:
        print(f"error: path {exc} does not exist", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(format_row(row))
    return 1 if rows else 0
