"""Source-revision and changed-file checks shared by the close ceremony."""
from pathlib import Path
import base64
import hashlib
import json
import os
import subprocess
import sys

from engine import HarnessError, IGNORED_DIRS


def journal_path(root, slice_id):
    key = hashlib.sha256(slice_id.encode()).hexdigest()
    return Path(root) / ".harness/memory/session" / f".close-{key}.json"


FINALIZATION_FILES = ("backlog.jsonl", "registry.jsonl", "edges.jsonl",
                      "notes.jsonl", "memory/durable.jsonl")


def _save_journal(path, pending):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        json.dump(pending, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def begin_finalization(root, original, commit):
    """Snapshot ceremony-owned state and the index before ratification."""
    files = {}
    for rel in FINALIZATION_FILES:
        path = Path(root) / ".harness" / rel
        files[rel] = base64.b64encode(path.read_bytes()).decode() if path.exists() else None
    pending = {"original": original, "result": None, "files": files,
               "commit": commit, "index": None, "note": None}
    if (Path(root) / ".git").exists():
        pending["index"] = _git(root, "ls-files", "--stage", "-z", "--", ".harness")
        note = subprocess.run(["git", "-C", str(root), "notes", "--ref=refs/notes/harness",
                               "show", commit], capture_output=True, text=True)
        pending["note"] = note.stdout if note.returncode == 0 else None
    _save_journal(journal_path(root, original["id"]), pending)


def prepare_journal(root, original, result):
    """Keep recovery state outside the commit that it describes."""
    path = journal_path(root, original["id"])
    pending = json.loads(path.read_text())
    pending["result"] = result
    _save_journal(path, pending)


def _restore_finalization(root, pending):
    for rel, encoded in pending.get("files", {}).items():
        path = Path(root) / ".harness" / rel
        if encoded is None:
            path.unlink(missing_ok=True)
        else:
            temp = path.with_name(f".{path.name}.restore")
            temp.write_bytes(base64.b64decode(encoded))
            temp.replace(path)
    if pending.get("index") is not None:
        current = _git(root, "ls-files", "-z", "--", ".harness")
        removed = "".join(f"0 {'0' * 40}\t{p}\0" for p in current.split("\0") if p)
        proc = subprocess.run(["git", "-C", str(root), "update-index", "-z", "--index-info"],
                              input=removed + pending["index"], capture_output=True, text=True)
        if proc.returncode:
            raise HarnessError(f"closure rollback could not restore Git index: {proc.stderr}")
        cmd = ["git", "-C", str(root), "notes", "--ref=refs/notes/harness"]
        current_note = subprocess.run(cmd + ["show", pending["commit"]],
                                      capture_output=True, text=True)
        body = current_note.stdout if current_note.returncode == 0 else None
        if body != pending.get("note"):
            args = (["add", "-f", "-F", "-", pending["commit"]] if pending.get("note")
                    else ["remove", pending["commit"]])
            proc = subprocess.run(cmd + args, input=pending.get("note"),
                                  capture_output=True, text=True)
            if proc.returncode:
                raise HarnessError(f"closure rollback could not restore Git note: {proc.stderr}")


def finish_closure(root, result):
    from engine import memory, telemetry
    from engine.events import Sidecar
    sid = result["slice"]
    sidecar = Sidecar(root)
    try:
        result["bindings_released"] = sidecar.release_slice(sid)
        sidecar.release_snapshots(sid)
    finally:
        sidecar.close()
    telemetry.emit(root, "slice_closed", {
        "slice": sid, "flipped": result["registry_flipped"],
        "flip_skipped": result["flip_skipped"], "memories": result["memory"]["total"]},
        buffered=True, event_id=f"closure:{sid}:{result.get('source_commit')}")
    memory.session_path(root, sid).unlink(missing_ok=True)
    journal_path(root, sid).unlink(missing_ok=True)
    return result


def recover_closure(root, slice_id):
    """Recover a process interruption before or after the substrate commit."""
    from engine import get_slice, save_slice
    path = journal_path(root, slice_id)
    if not path.exists():
        return None
    pending = json.loads(path.read_text())
    result = pending["result"]
    if (Path(root) / ".git").exists():
        rows = [json.loads(line) for line in
                _git(root, "show", "HEAD:.harness/backlog.jsonl").splitlines() if line]
        durable = next((r for r in rows if r["id"] == slice_id), {})
    else:
        durable = get_slice(root, slice_id)
    if result and durable.get("status") == "closed" and durable.get("closed_commit") == result.get("source_commit"):
        result["recovered"] = True
        if (Path(root) / ".git").exists():
            result["substrate_commit"] = _git(root, "rev-parse", "HEAD").strip()
        return finish_closure(root, result)
    _restore_finalization(root, pending)
    path.unlink()
    return None


def scope_findings(root, sl, session, touched, config):
    from engine.events import Sidecar
    from engine.gates import GateContext
    from engine.gates.g3_scope import check
    sidecar = Sidecar(root)
    try:
        return check(GateContext(root, {
            "event": "unit_complete", "session_id": session, "work_unit_id": sl["id"],
            "payload": {"files": [{"path": p} for p in touched]}}, config, sidecar))
    finally:
        sidecar.close()


def _git(root, *args):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    if p.returncode:
        raise HarnessError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def source_matches_commit(root, commit):
    """Acceptance must see the bytes the provenance commit contains."""
    if not (Path(root) / ".git").exists():
        return
    if not commit:
        raise HarnessError("--commit is required to close in a git repo; commit the work first")
    dirty = _git(root, "diff", "--name-only", "-z", commit, "--", ".", ":(exclude).harness")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    paths = sorted({p for p in (dirty + untracked).split("\0")
                    if p and not p.startswith(".harness/")})
    if paths:
        raise HarnessError(f"commit {commit[:12]} does not contain the tested source state: "
                           f"uncommitted or different files {paths}; commit them and close with HEAD")


def prepare_files(root, sl, sidecar, session, commit, config):
    """Discover all changes before any review or conformance check."""
    from engine.events import _regenerate_touched, rel_in_root
    from engine.extractor.engine import shadow_path_for
    from engine.graph import load_edges
    touched = sidecar.touched_paths(slice_id=sl["id"])
    touched |= {e["to"][5:] for e in load_edges(root)
                if e["from"] == f"slice:{sl['id']}" and e["type"] == "touches"
                and e["to"].startswith("file:")}
    if commit and (Path(root) / ".git").exists():
        base = sl.get("started_at_commit")
        if not base:
            print(f"warning: slice {sl['id']} has no started_at_commit; "
                  "reconciling its current commit and recorded touches only", file=sys.stderr)
        args = (["diff", "--name-only", "-z", f"{base}..{commit}"] if base
                else ["diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", commit])
        touched |= {p for p in _git(root, *args).split("\0") if p}
    touched = {p for p in touched if rel_in_root(root, p)
               and not any(part in IGNORED_DIRS for part in Path(p).parts)}
    missing = {p for p in touched if (Path(root) / p).is_file()
               and not shadow_path_for(root, Path(root) / p).exists()}
    sidecar.touch(session, sl["id"], sorted(touched))
    _regenerate_touched(root, sidecar, session, sl["id"], config)
    extracted = sorted(p for p in missing if shadow_path_for(root, Path(root) / p).exists())
    return sorted(touched), extracted
