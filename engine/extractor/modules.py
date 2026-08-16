"""Module ids and dotted-import matching for namespace packages (D-008).

A shadow keeps the whole dotted Python import (`kente.telemetry.decorators`),
never the top-level segment only, so a repo of PEP 420 namespace packages is
not one opaque `kente` node. Module ids are derived by stripping the first
matching `extractor.src_roots` glob from the source path, dotting what is
left and dropping a trailing `__init__`; registry lookups then match those
ids by longest dotted prefix (ADR-002, decision row D-008).
"""
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from .. import DEFAULT_SRC_ROOTS, HarnessError

_SRC_ROOTS_KEY = "extractor.src_roots"


def src_roots(config: dict | None = None) -> list:
    """Configured source roots, validated.

    Args:
        config: Loaded engine config, or None for the defaults.

    Returns:
        The glob patterns to strip, in the order they are tried.

    Raises:
        HarnessError: If `extractor.src_roots` is not a list of strings — a
            malformed key silently falling back to the defaults would move
            every module id in the repo without saying so.
    """
    extractor = (config or {}).get("extractor")
    if extractor is None:
        return list(DEFAULT_SRC_ROOTS)
    if not isinstance(extractor, dict):
        # only a missing key defaults; `extractor: []` is a malformed block,
        # and defaulting it silently would move every module id in the repo
        raise HarnessError(
            f"{_SRC_ROOTS_KEY}: `extractor` must be a mapping, got "
            f"{extractor!r}")
    if "src_roots" not in extractor:
        return list(DEFAULT_SRC_ROOTS)
    raw = extractor["src_roots"]
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise HarnessError(
            f"{_SRC_ROOTS_KEY}: expected a list of glob strings (e.g. "
            f'["src", "packages/*/src"]), got {raw!r}')
    return list(raw)


def strip_src_root(rel_posix: str, roots: list) -> list:
    """Path segments left after removing the first matching source root.

    A pattern only matches ANCHORED at the repo root: `docs/src/conf.py` keeps
    the id `docs.src.conf` rather than colliding with the real `src/conf.py`.

    Args:
        rel_posix: Repo-relative POSIX path, extension already dropped.
        roots: Glob patterns from `src_roots`.

    Returns:
        The remaining segments; the input segments when nothing matches (and
        always at least one segment — a source root never eats the module).
    """
    parts = [p for p in rel_posix.split("/") if p and p != "."]
    for pattern in roots:
        pat = [p for p in pattern.split("/") if p and p != "."]
        if not pat or len(parts) <= len(pat):
            continue
        if all(fnmatchcase(parts[j], pat[j]) for j in range(len(pat))):
            return parts[len(pat):]
    return parts


def module_id_for_rel(rel_posix: str, config: dict | None = None) -> str:
    """Module id for a repo-relative source path.

    `packages/kente-config/src/kente/config/__init__.py` -> `kente.config`;
    `src/app/orders.py` -> `app.orders`; `telemetry.py` -> `telemetry`.

    Args:
        rel_posix: Repo-relative POSIX path of the source file.
        config: Loaded engine config, or None for the default source roots.

    Returns:
        The dotted module id.

    Raises:
        HarnessError: If `extractor.src_roots` is malformed.
    """
    stem = PurePosixPath(rel_posix).with_suffix("").as_posix()
    parts = strip_src_root(stem, src_roots(config))
    if len(parts) > 1 and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class RegistryIndex:
    """Longest-dotted-prefix lookup over registry entries (D-008).

    Built once per gate run / resolve / review pass and reused across the
    imports of every shadow: the maps are O(registry) to build and the
    callers loop over O(files x imports).
    """

    def __init__(self, entries):
        """Index registry entries by `id` and by `module_id`.

        Args:
            entries: Registry entries (dicts with `id` and optional
                `module_id`). First entry wins on a duplicate key.
        """
        self.by_id: dict = {}
        self.by_module: dict = {}
        for entry in entries:
            eid = entry.get("id")
            if eid and eid not in self.by_id:
                self.by_id[eid] = entry
            mid = entry.get("module_id")
            if mid and mid not in self.by_module:
                self.by_module[mid] = entry

    def match(self, import_name: str) -> dict | None:
        """Entry an import refers to, by longest dotted prefix.

        `kente.config.secrets` matches the entry whose `module_id` (or `id`,
        for entries still `planned`) is `kente.config` before the one that is
        bare `kente`. An exact match on the whole import name is just the
        longest prefix, so flat repos resolve exactly as before D-008.

        Args:
            import_name: Import as recorded in a shadow (`kente.config`).

        Returns:
            The matching entry, or None when the import is not a registry
            abstraction (third-party and stdlib imports land here).
        """
        if not import_name:
            return None
        parts = import_name.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            hit = self.by_id.get(candidate) or self.by_module.get(candidate)
            if hit is not None:
                return hit
        return None


def match_registry_module(import_name: str, entries) -> dict | None:
    """One-shot longest-dotted-prefix lookup (see `RegistryIndex.match`).

    Args:
        import_name: Import as recorded in a shadow.
        entries: Registry entries.

    Returns:
        The matching entry, or None.
    """
    return RegistryIndex(entries).match(import_name)
