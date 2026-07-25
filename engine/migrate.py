"""Substrate schema migrations — plugin upgrades never silently reinterpret
project state. Migration is explicit (`harness init --migrate`)."""
from __future__ import annotations

from pathlib import Path

from . import SCHEMA_VERSION, HarnessError, harness_dir


def current_version(root) -> int:
    sv = harness_dir(root) / "schema_version"
    if not sv.exists():
        raise HarnessError("schema_version missing — not a harness substrate")
    return int(sv.read_text().strip())


# version -> callable(root) upgrading from that version to version+1
MIGRATIONS: dict = {}


def migrate(root) -> dict:
    v = current_version(root)
    applied = []
    while v < SCHEMA_VERSION:
        step = MIGRATIONS.get(v)
        if step is None:
            raise HarnessError(
                f"no migration path from schema {v} to {SCHEMA_VERSION} (fail closed)")
        step(root)
        v += 1
        applied.append(v)
        (harness_dir(root) / "schema_version").write_text(f"{v}\n")
    if v > SCHEMA_VERSION:
        raise HarnessError(
            f"substrate schema {v} is newer than engine {SCHEMA_VERSION}; "
            f"upgrade the plugin")
    return {"from": current_version(root) if not applied else applied[0] - 1,
            "to": v, "applied": applied}
