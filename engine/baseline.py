"""Recoverable interface baselines anchored to the slice's starting commit."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import HarnessError, get_slice, load_config, save_slice


def ensure_baseline(root, sidecar, slice_id, *, starting=False):
    from .extractor.engine import LANG_BY_EXT, build_shadow, _degenerate_shadow
    from .registry import load_registry, public_symbols
    root = Path(root)
    sl = get_slice(root, slice_id)
    if sl.get("status") == "closed":
        return
    marker = f"baseline:{slice_id}"
    if sidecar.state_get("__baselines__", marker):
        return
    base = sl.get("started_at_commit")
    if not base and starting and (root / ".git").exists():
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            base = proc.stdout.strip()
            sl["started_at_commit"] = base
            save_slice(root, sl)
    config = load_config(root)
    if base:
        def blob(path):
            p = subprocess.run(["git", "-C", str(root), "show", f"{base}:{path}"],
                               capture_output=True)
            if p.returncode:
                raise HarnessError(f"cannot recover G6 baseline at {base}: {path}; "
                                   "restore the starting revision before continuing")
            return p.stdout
        try:
            entries = [json.loads(line) for line in blob(".harness/registry.jsonl").splitlines()
                       if line.strip()]
        except (ValueError, TypeError) as exc:
            raise HarnessError(f"invalid registry in starting revision {base}") from exc
        for entry in entries:
            if entry.get("status") != "built" or not entry.get("source"):
                continue
            source = blob(entry["source"])
            path = root / entry["source"]
            lang = LANG_BY_EXT.get(path.suffix.lower())
            shadow = (build_shadow(root, path, source, lang, config)
                      if lang and config.get("languages", {}).get(lang, True)
                      else _degenerate_shadow(root, path, source, config))
            symbols = sorted(f"{s['kind']} {s['signature']}" for s in shadow["symbols"]
                             if s.get("visibility") == "public")
            sidecar.snapshot_set(slice_id, entry["id"],
                                 {"symbols": symbols, "source_hash": shadow["source_hash"]})
    elif starting:
        # Non-Git substrates can retain a session baseline, but its loss
        # cannot be reconstructed from source that has already changed.
        for entry in load_registry(root):
            if entry.get("status") == "built" and entry.get("shadow"):
                symbols = public_symbols(root, entry)
                if symbols is not None:
                    stored = json.loads((root / entry["shadow"]).read_text())
                    sidecar.snapshot_set(slice_id, entry["id"],
                                         {"symbols": symbols, "source_hash": stored.get("source_hash")})
    elif sidecar.snapshot_get(slice_id):
        return  # legacy sidecar already has its original baseline
    elif any(e.get("status") == "built" for e in load_registry(root)):
        raise HarnessError("G6 baseline is missing and this slice has no starting commit; "
                           "restore its baseline or bind it before making changes")
    sidecar.state_set("__baselines__", marker, base or "session")
