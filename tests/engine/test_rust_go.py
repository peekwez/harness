"""Rust and Go shadow extraction: same universal schema, same G7 guarantee.

Visibility follows each language's own rule — `pub` in Rust, initial-capital
in Go — because that is what "public interface" means to their compilers.
"""
import json

from conftest import run_cli
from engine import load_config

RUST_SOURCE = '''//! Order service.
use std::collections::HashMap;
use crate::telemetry::emit_span;

/// A customer order.
pub struct Order {
    pub sku: String,
    qty: u32,
}

pub enum Status {
    Open,
    Closed,
}

pub trait Repo {
    fn save(&self, o: &Order) -> Result<(), String>;
}

impl Order {
    /// Build a new order.
    pub fn new(sku: String) -> Self {
        Order { sku, qty: 1 }
    }

    fn internal(&self) -> u32 {
        self.qty
    }
}

pub fn create_order(sku: &str) -> Order {
    emit_span("create_order");
    Order::new(sku.to_string())
}

fn helper(map: &HashMap<String, u32>) {}

pub type OrderId = u64;
pub const MAX_COUNT: u32 = 100;
'''

GO_SOURCE = '''// Package orders creates orders.
package orders

import (
	"fmt"
	"github.com/acme/telemetry"
)

// Order is a customer order.
type Order struct {
	SKU string
	qty int
}

type Repo interface {
	Save(o *Order) error
}

const MaxCount = 100

// CreateOrder builds an order and emits a span.
func CreateOrder(sku string) (*Order, error) {
	telemetry.EmitSpan("create_order")
	return &Order{SKU: sku}, nil
}

func (o *Order) Total() int {
	return o.qty
}

func helper() string {
	return fmt.Sprintf("x")
}
'''


def _extract(toy, name, source):
    from engine.extractor.engine import extract_path
    path = toy / name
    path.write_text(source)
    shadow, findings = extract_path(toy, path, load_config(toy))
    return shadow, findings, path


# ---------------------------------------------------------------- Rust
def test_rust_symbols_cover_the_item_kinds(toy):
    shadow, findings, _ = _extract(toy, "orders.rs", RUST_SOURCE)
    assert shadow["language"] == "rust", findings
    by_name = {s["name"]: s for s in shadow["symbols"]}
    assert by_name["Order"]["kind"] == "struct"
    assert by_name["Status"]["kind"] == "enum"
    assert by_name["Repo"]["kind"] == "trait"
    assert by_name["create_order"]["kind"] == "function"
    assert by_name["OrderId"]["kind"] == "type"
    assert by_name["MAX_COUNT"]["kind"] == "const"
    # impl methods are qualified by their type
    assert by_name["Order::new"]["kind"] == "method"
    assert "sku: String" in by_name["Order::new"]["signature"]
    assert "-> Order" in by_name["create_order"]["signature"]


def test_rust_visibility_follows_pub(toy):
    shadow, _, _ = _extract(toy, "orders.rs", RUST_SOURCE)
    by_name = {s["name"]: s for s in shadow["symbols"]}
    assert by_name["create_order"]["visibility"] == "public"
    assert by_name["helper"]["visibility"] == "private"
    assert by_name["Order::new"]["visibility"] == "public"
    assert by_name["Order::internal"]["visibility"] == "private"
    assert "create_order" in shadow["exports"]
    assert "helper" not in shadow["exports"]


def test_rust_docs_and_imports(toy):
    shadow, _, _ = _extract(toy, "orders.rs", RUST_SOURCE)
    by_name = {s["name"]: s for s in shadow["symbols"]}
    assert "customer order" in (by_name["Order"]["doc"] or "")
    assert "Build a new order" in (by_name["Order::new"]["doc"] or "")
    # `crate::telemetry::…` resolves to the module, not the crate root —
    # that is what matches a registry id
    assert "telemetry" in shadow["imports"]
    assert "std" in shadow["imports"]


# ---------------------------------------------------------------- Go
def test_go_symbols_cover_the_declaration_kinds(toy):
    shadow, findings, _ = _extract(toy, "orders.go", GO_SOURCE)
    assert shadow["language"] == "go", findings
    by_name = {s["name"]: s for s in shadow["symbols"]}
    assert by_name["Order"]["kind"] == "struct"
    assert by_name["Repo"]["kind"] == "interface"
    assert by_name["MaxCount"]["kind"] == "const"
    assert by_name["CreateOrder"]["kind"] == "function"
    assert by_name["Order.Total"]["kind"] == "method"
    assert "sku string" in by_name["CreateOrder"]["signature"]


def test_go_visibility_follows_capitalization(toy):
    shadow, _, _ = _extract(toy, "orders.go", GO_SOURCE)
    by_name = {s["name"]: s for s in shadow["symbols"]}
    assert by_name["CreateOrder"]["visibility"] == "public"
    assert by_name["helper"]["visibility"] == "private"
    assert by_name["Order.Total"]["visibility"] == "public"
    assert "CreateOrder" in shadow["exports"]
    assert "helper" not in shadow["exports"]


def test_go_docs_and_imports(toy):
    shadow, _, _ = _extract(toy, "orders.go", GO_SOURCE)
    by_name = {s["name"]: s for s in shadow["symbols"]}
    assert "builds an order" in (by_name["CreateOrder"]["doc"] or "")
    # the package identifier the code actually calls, not the full URL
    assert "telemetry" in shadow["imports"] and "fmt" in shadow["imports"]


# ---------------------------------------------------------------- shared
def test_rust_and_go_shadows_regenerate_identically(toy):
    """G7's guarantee must hold for every enabled language."""
    from engine.gates.g7_derivation import derivation_findings
    _extract(toy, "orders.rs", RUST_SOURCE)
    _extract(toy, "orders.go", GO_SOURCE)
    blocking = [f for f in derivation_findings(toy, load_config(toy))
                if f["severity"] == "block"]
    assert not blocking, blocking


def test_body_edits_do_not_perturb_the_interface_shadow(toy):
    """The C2 acceptance property: a shadow tracks the interface, so bodies
    can churn without producing interface drift. (Spans are line numbers and
    do move; G6 compares kind+signature, which must not.)"""
    from engine.extractor.engine import extract_path

    def interface(shadow):
        return sorted((s["kind"], s["name"], s["signature"], s["visibility"])
                      for s in shadow["symbols"])

    for name, source, body_change in (
        ("orders.rs", RUST_SOURCE, ("Order::new(sku.to_string())",
                                    "Order::new(String::from(sku))")),
        ("orders.go", GO_SOURCE, ("return &Order{SKU: sku}, nil",
                                  "o := &Order{SKU: sku}\n\treturn o, nil")),
    ):
        shadow, _, path = _extract(toy, name, source)
        before = interface(shadow)
        path.write_text(source.replace(*body_change))
        after_shadow, _ = extract_path(toy, path, load_config(toy))
        assert interface(after_shadow) == before, name


def test_init_detects_rust_and_go_and_enables_the_packs(tmp_path):
    root = tmp_path / "polyglot"
    root.mkdir()
    (root / "main.rs").write_text("pub fn main() {}\n")
    (root / "main.go").write_text("package main\n\nfunc main() {}\n")
    proc = run_cli("init", root=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    import yaml
    langs = yaml.safe_load((root / ".harness" / "config.yaml").read_text())["languages"]
    assert langs["rust"] is True and langs["go"] is True
    assert "rust" in proc.stdout and "go" in proc.stdout


def test_disabled_language_degrades_loudly_not_silently(toy):
    """Turning a pack off must enumerate the surface, never hide it."""
    import yaml
    cfg_path = toy / ".harness" / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["languages"]["rust"] = False
    cfg_path.write_text(yaml.safe_dump(cfg))
    shadow, findings, _ = _extract(toy, "orders.rs", RUST_SOURCE)
    assert shadow["language"] == "unknown"
    assert any(f["code"] == "UNKNOWN_LANGUAGE" for f in findings), findings
