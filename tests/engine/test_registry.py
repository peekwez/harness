"""C3 acceptance: manifest deletion blocks session_start with
MANIFEST_INCOMPLETE; status flip rejected unless shadow matches source."""
import pytest

from conftest import make_event
from engine.events import handle_event
from engine.registry import RegistryError, flip_status, load_registry


def test_manifest_deletion_blocks_session_start(toy):
    (toy / "config.py").unlink()  # manifest-listed file for entry 'config'
    v = handle_event(make_event("session_start", session="mdel"), toy)
    assert v["verdict"] == "block"
    hits = [f for f in v["findings"] if f["code"] == "MANIFEST_INCOMPLETE"]
    assert hits, v["findings"]
    assert any("config" in f["message"] for f in hits)
    assert all(f["rule_ref"] == "gate:G1" for f in hits)


def test_flip_rejected_without_shadow(toy):
    # 'orders' has no source file yet -> flip must fail loud
    with pytest.raises(RegistryError):
        flip_status(toy, "orders")


def test_flip_rejected_when_shadow_stale(toy):
    from engine import load_config
    from engine.extractor.engine import extract_path
    (toy / "orders.py").write_text("def create_order(sku):\n    return sku\n")
    extract_path(toy, toy / "orders.py", load_config(toy))
    # source changes after extraction -> stale shadow -> rejected
    (toy / "orders.py").write_text("def create_order(sku, qty):\n    return sku\n")
    with pytest.raises(RegistryError, match="stale"):
        flip_status(toy, "orders")


def test_flip_succeeds_and_derives_fields(toy):
    from engine import load_config
    from engine.extractor.engine import extract_path
    (toy / "orders.py").write_text(
        'def create_order(sku: str) -> dict:\n    return {"sku": sku}\n')
    extract_path(toy, toy / "orders.py", load_config(toy))
    entry = flip_status(toy, "orders")
    assert entry["status"] == "built"
    assert entry["module_id"] == "orders"
    assert entry["shadow"] and entry["source_hash"]
    assert "create_order" in entry["signature_digest"]
    # idempotent
    assert flip_status(toy, "orders")["status"] == "built"


def test_duplicate_registry_id_fails_loud(toy):
    from engine import read_jsonl, write_jsonl
    rows = read_jsonl(toy / ".harness" / "registry.jsonl")
    write_jsonl(toy / ".harness" / "registry.jsonl", rows + [rows[0]])
    with pytest.raises(RegistryError, match="duplicate"):
        load_registry(toy)
