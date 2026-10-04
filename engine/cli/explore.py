"""`harness explore` and `harness explore --freeze` (spec 5.5)."""
from __future__ import annotations

from engine.cli.common import _print, _root


def cmd_explore(args):
    """Creates explore/ from templates, or freezes it.

    Args:
        args: Parsed CLI args (`freeze`, `root`).

    Returns:
        0 on success. 1 when `--freeze` finds problems.
    """
    root = _root(args)
    if getattr(args, "freeze", False):
        from engine.explore import freeze
        result = freeze(root)
        _print(result)
        return 0 if result["frozen"] else 1
    from engine.explore import scaffold
    _print(scaffold(root))
    return 0
