"""C2 — Extractor: tree-sitter -> universal shadows.

One driver, per-language query packs (symbols.scm / imports.scm / exports.scm).
Content-hash cache: unchanged source -> no work. Unknown language -> degenerate
shadow + G8 finding, never silence. Shadows are deterministic: same source
bytes -> byte-identical shadow.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import (IGNORED_DIRS, IGNORED_EXTS, HarnessError, harness_dir,
                sha256_bytes)
from ..events import make_finding
from .modules import module_id_for_rel
# re-exported: the gates and the event pipeline reach the matcher through
# the extractor's public surface (ADR-002 / D-008)
from .modules import RegistryIndex, match_registry_module  # noqa: F401

# Bump whenever the shadow FORMAT changes (new symbol kinds, new keys…).
# The cache keys on (source_hash, extractor_version): without the version
# half, a format change leaves every committed shadow permanently stale
# while G7's uncached rebuild permanently mismatches — extract --all
# becomes a no-op exactly when it is the named fix (field report W7).
# v2 = class field symbols + this stamp (0.3.5).
# v3 = dotted Python imports + src-root-stripped module ids (0.8, D-008):
# without this bump every committed shadow stays a cache HIT with its
# truncated imports while G7's uncached rebuild mismatches forever.
EXTRACTOR_VERSION = 3

LANG_BY_EXT = {
    ".py": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".yaml": "yaml", ".yml": "yaml",
    ".tf": "hcl", ".hcl": "hcl",
}
QUERY_DIR = Path(__file__).parent / "queries"

DEP_INSTALL_HINT = "pip install pyyaml tree-sitter tree-sitter-language-pack"


def deps_available() -> bool:
    """Whether the tree-sitter extraction stack is importable. When it is
    not, extraction degrades to degenerate shadows with a loud advisory —
    a missing optional dep must never hard-block the session."""
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_language_pack  # noqa: F401
        return True
    except ImportError:
        return False

_PARSERS: dict = {}
_QUERIES: dict = {}


def _get_parser(lang: str):
    if lang not in _PARSERS:
        try:
            from tree_sitter_language_pack import get_language, get_parser
        except ImportError as exc:
            raise HarnessError(
                "tree-sitter-language-pack required: "
                "pip install tree-sitter tree-sitter-language-pack") from exc
        _PARSERS[lang] = (get_parser(lang), get_language(lang))
    return _PARSERS[lang]


def _get_query(lang: str, name: str):
    key = (lang, name)
    if key not in _QUERIES:
        qfile = QUERY_DIR / lang / f"{name}.scm"
        if not qfile.exists():
            raise HarnessError(f"query pack incomplete: {qfile} missing (fail closed)")
        _parser, language = _get_parser(lang)
        try:
            from tree_sitter import Query
            _QUERIES[key] = Query(language, qfile.read_text())
        except Exception:
            _QUERIES[key] = language.query(qfile.read_text())
    return _QUERIES[key]


def _captures(query, node) -> dict:
    """Normalize captures across py-tree-sitter versions -> {name: [nodes]}."""
    try:
        from tree_sitter import QueryCursor
        raw = QueryCursor(query).captures(node)
    except Exception:
        raw = query.captures(node)
    if isinstance(raw, dict):
        return raw
    out: dict = {}
    for n, name in raw:
        out.setdefault(name, []).append(n)
    return out


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


# ------------------------------------------------------------ per-language
def _py_visibility(name: str) -> str:
    return "private" if name.startswith("_") and not name.startswith("__init__") else "public"


def _python_symbols(tree, src):
    symbols = []
    caps = _captures(_get_query("python", "symbols"), tree.root_node)
    for kind_cap, kind in (("function", "function"), ("class", "class")):
        for node in caps.get(kind_cap, []):
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = _text(name_node, src)
            # signature = header line(s) up to the ':' before body
            body = node.child_by_field_name("body")
            sig_end = body.start_byte if body is not None else node.end_byte
            sig = " ".join(src[node.start_byte:sig_end].decode("utf-8", "replace").split())
            sig = sig.rstrip(": ")
            doc = None
            if body is not None and body.child_count:
                first = body.children[0]
                if first.type == "expression_statement" and first.child_count:
                    first = first.children[0]
                if first.type == "string":
                    content = [c for c in first.children if c.type == "string_content"]
                    doc = (_text(content[0], src) if content
                           else _text(first, src).strip("\"'")).strip()
            parent = node.parent
            is_method = False
            while parent is not None:
                if parent.type == "class_definition":
                    is_method = True
                    break
                parent = parent.parent
            # span covers the signature header, not the body: body edits must
            # not perturb the interface shadow (C2 acceptance).
            sig_end_line = (body.start_point[0] + 1) if body is not None \
                else (node.end_point[0] + 1)
            symbols.append({
                "kind": "method" if (kind == "function" and is_method) else kind,
                "name": name, "signature": sig, "doc": doc,
                "visibility": _py_visibility(name),
                "span": [node.start_point[0] + 1, sig_end_line],
            })
            # class-level fields (settings/config objects especially) are
            # interface detail: without them a builder confirms field names
            # from ADR prose instead of the shadow (field report W6)
            if kind == "class" and body is not None:
                for stmt in body.children:
                    # grammar versions differ: assignment may sit directly in
                    # the block or wrapped in an expression_statement
                    expr = stmt
                    if stmt.type == "expression_statement" and stmt.child_count:
                        expr = stmt.children[0]
                    if expr.type != "assignment":
                        continue
                    left = expr.child_by_field_name("left")
                    if left is None or left.type != "identifier":
                        continue
                    fname = _text(left, src)
                    symbols.append({
                        "kind": "field", "name": f"{name}.{fname}",
                        "signature": " ".join(_text(expr, src).split()),
                        "doc": None, "visibility": _py_visibility(fname),
                        "span": [expr.start_point[0] + 1,
                                 expr.end_point[0] + 1],
                    })
    return symbols


def _python_imports(tree, src):
    imports = set()
    caps = _captures(_get_query("python", "imports"), tree.root_node)
    for node in caps.get("import", []):
        if node.type == "import_from_statement":
            mod = node.child_by_field_name("module_name")
            if mod is not None:
                # the WHOLE dotted path (D-008): truncating to the top-level
                # segment makes every namespace package one opaque node
                t = _text(mod, src).lstrip(".")
                if t:
                    imports.add(t)
        else:  # import_statement
            for child in node.named_children:
                if child.type in ("dotted_name", "aliased_import"):
                    t = _text(child, src).split(" as ")[0].strip()
                    if t:
                        imports.add(t)
    return sorted(imports)


def _python_exports(tree, src, symbols):
    caps = _captures(_get_query("python", "exports"), tree.root_node)
    for node in caps.get("all_list", []):
        names = []
        for s in caps.get("all_item", []):
            names.append(_text(s, src).strip("\"'"))
        if names:
            return sorted(set(names))
    # fields are interface detail on their class, not module exports
    return sorted({s["name"] for s in symbols
                   if s["visibility"] == "public" and s["kind"] != "field"})


def _ts_symbols(tree, src):
    symbols = []
    caps = _captures(_get_query("typescript", "symbols"), tree.root_node)
    kind_map = {"function": "function", "class": "class", "interface": "interface",
                "type_alias": "type", "const": "const"}
    exported_spans = {(n.start_byte, n.end_byte)
                      for n in caps.get("exported", [])}

    def is_exported(node):
        p = node.parent
        while p is not None:
            if (p.start_byte, p.end_byte) in exported_spans or p.type == "export_statement":
                return True
            p = p.parent
        return False

    for cap, kind in kind_map.items():
        for node in caps.get(cap, []):
            name_node = node.child_by_field_name("name")
            if name_node is None:
                decl = node.child_by_field_name("declarator")
                name_node = decl.child_by_field_name("name") if decl is not None else None
            if name_node is None and node.named_children:
                for ch in node.named_children:
                    if ch.type in ("identifier", "type_identifier", "variable_declarator"):
                        name_node = ch.child_by_field_name("name") if ch.type == "variable_declarator" else ch
                        break
            if name_node is None:
                continue
            name = _text(name_node, src)
            body = node.child_by_field_name("body")
            sig_end = body.start_byte if body is not None else node.end_byte
            sig = " ".join(src[node.start_byte:sig_end].decode("utf-8", "replace").split())
            symbols.append({
                "kind": kind, "name": name, "signature": sig.rstrip("{ "),
                "doc": None,
                "visibility": "public" if is_exported(node) else "private",
                "span": [node.start_point[0] + 1, node.end_point[0] + 1],
            })
    return symbols


def _ts_imports(tree, src):
    imports = set()
    caps = _captures(_get_query("typescript", "imports"), tree.root_node)
    for node in caps.get("source", []):
        mod = _text(node, src).strip("\"'")
        imports.add(mod.split("/")[0] if not mod.startswith(".") else mod)
    return sorted(imports)


def _rust_doc(node, src) -> str | None:
    """Rust docs are `///` line comments preceding the item (and `//!` inner
    docs, which belong to the module, not to any symbol)."""
    lines, prev = [], node.prev_sibling
    while prev is not None and prev.type == "line_comment":
        text = _text(prev, src).strip()
        if not text.startswith("///"):
            break
        lines.append(text.lstrip("/").strip())
        prev = prev.prev_sibling
    return "\n".join(reversed(lines)) or None


def _rust_visibility(node) -> str:
    return ("public"
            if any(c.type == "visibility_modifier" for c in node.children)
            else "private")


def _rust_header(node, src, body_types) -> tuple:
    """(signature, last_line_of_header) — the header stops at the body, so
    body edits never perturb the interface shadow (C2 acceptance)."""
    body = next((c for c in node.children if c.type in body_types), None)
    end = body.start_byte if body is not None else node.end_byte
    end_line = (body.start_point[0] + 1) if body is not None \
        else (node.end_point[0] + 1)
    sig = " ".join(src[node.start_byte:end].decode("utf-8", "replace").split())
    return sig.rstrip("{ ").rstrip(";"), end_line


RUST_BODIES = ("block", "field_declaration_list", "enum_variant_list",
               "declaration_list")


def _rust_symbols(tree, src):
    symbols = []
    caps = _captures(_get_query("rust", "symbols"), tree.root_node)

    def add(node, kind, name):
        sig, end_line = _rust_header(node, src, RUST_BODIES)
        symbols.append({
            "kind": kind, "name": name, "signature": sig,
            "doc": _rust_doc(node, src),
            "visibility": _rust_visibility(node),
            "span": [node.start_point[0] + 1, end_line],
        })

    def name_of(node):
        for field in ("name",):
            n = node.child_by_field_name(field)
            if n is not None:
                return _text(n, src)
        n = next((c for c in node.children
                  if c.type in ("identifier", "type_identifier")), None)
        return _text(n, src) if n is not None else None

    for cap, kind in (("function", "function"), ("struct", "struct"),
                      ("enum", "enum"), ("trait", "trait"),
                      ("type", "type"), ("const", "const")):
        for node in caps.get(cap, []):
            if node.parent is not None and node.parent.type == "declaration_list":
                continue  # trait/impl members are handled with their owner
            name = name_of(node)
            if name:
                add(node, kind, name)

    # impl blocks contribute methods qualified by their type; the impl
    # header itself is not a symbol
    for impl in caps.get("impl", []):
        type_node = impl.child_by_field_name("type") or next(
            (c for c in impl.children if c.type == "type_identifier"), None)
        owner = _text(type_node, src) if type_node is not None else "impl"
        body = next((c for c in impl.children if c.type == "declaration_list"),
                    None)
        for member in (body.named_children if body is not None else []):
            if member.type != "function_item":
                continue
            name = name_of(member)
            if name:
                add(member, "method", f"{owner}::{name}")

    # trait method requirements are part of the trait's public surface
    for trait in caps.get("trait", []):
        owner = name_of(trait)
        body = next((c for c in trait.children
                     if c.type == "declaration_list"), None)
        for member in (body.named_children if body is not None else []):
            if member.type not in ("function_item", "function_signature_item"):
                continue
            name = name_of(member)
            if name:
                sig, end_line = _rust_header(member, src, RUST_BODIES)
                symbols.append({
                    "kind": "method", "name": f"{owner}::{name}",
                    "signature": sig, "doc": _rust_doc(member, src),
                    "visibility": _rust_visibility(trait),  # trait vis wins
                    "span": [member.start_point[0] + 1, end_line],
                })
    return symbols


def _rust_imports(tree, src):
    """The segment that names a MODULE, because that is what matches a
    registry id: `crate::telemetry::emit_span` -> telemetry, `std::x` -> std.
    """
    imports = set()
    caps = _captures(_get_query("rust", "imports"), tree.root_node)
    for node in caps.get("import", []):
        text = _text(node, src)
        text = text.replace("pub ", "").replace("use ", "")
        text = text.replace("extern crate ", "").strip().rstrip(";")
        path = text.split("{")[0].split(" as ")[0].strip()
        segments = [s for s in path.split("::") if s]
        while segments and segments[0] in ("crate", "self", "super"):
            segments.pop(0)
        if segments:
            imports.add(segments[0].strip())
    return sorted(imports)


def _go_visibility(name: str) -> str:
    """Go's own rule: an identifier is exported iff it starts upper-case."""
    return "public" if name[:1].isupper() else "private"


def _go_doc(node, src) -> str | None:
    lines, prev = [], node.prev_sibling
    while prev is not None and prev.type == "comment":
        text = _text(prev, src).strip()
        if not text.startswith("//"):
            break
        lines.append(text.lstrip("/").strip())
        prev = prev.prev_sibling
    return "\n".join(reversed(lines)) or None


def _go_symbols(tree, src):
    symbols = []
    caps = _captures(_get_query("go", "symbols"), tree.root_node)

    def header(node, doc_node=None):
        body = node.child_by_field_name("body")
        end = body.start_byte if body is not None else node.end_byte
        end_line = (body.start_point[0] + 1) if body is not None \
            else (node.end_point[0] + 1)
        sig = " ".join(src[node.start_byte:end].decode("utf-8", "replace").split())
        return sig.rstrip("{ "), end_line

    for node in caps.get("function", []):
        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        name = _text(name_node, src)
        sig, end_line = header(node)
        symbols.append({"kind": "function", "name": name, "signature": sig,
                        "doc": _go_doc(node, src),
                        "visibility": _go_visibility(name),
                        "span": [node.start_point[0] + 1, end_line]})

    for node in caps.get("method", []):
        name_node = node.child_by_field_name("name")
        recv = node.child_by_field_name("receiver")
        if name_node is None:
            continue
        name = _text(name_node, src)
        owner = ""
        if recv is not None:
            owner = _text(recv, src).strip("()").replace("*", "")
            owner = owner.split()[-1] if owner.split() else owner
        sig, end_line = header(node)
        symbols.append({"kind": "method",
                        "name": f"{owner}.{name}" if owner else name,
                        "signature": sig, "doc": _go_doc(node, src),
                        "visibility": _go_visibility(name),
                        "span": [node.start_point[0] + 1, end_line]})

    for cap, default_kind in (("type_spec", "type"), ("const_spec", "const"),
                              ("var_spec", "const")):
        for node in caps.get(cap, []):
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = _text(name_node, src)
            kind = default_kind
            typ = node.child_by_field_name("type")
            if cap == "type_spec" and typ is not None:
                kind = {"struct_type": "struct",
                        "interface_type": "interface"}.get(typ.type, "type")
            # a spec's own doc may sit on the enclosing declaration
            doc = _go_doc(node, src) or (
                _go_doc(node.parent, src) if node.parent is not None else None)
            if kind in ("struct", "interface"):
                end = typ.start_byte + len(typ.type)  # header only
                sig = " ".join(
                    src[node.start_byte:typ.start_byte].decode(
                        "utf-8", "replace").split())
                sig = f"{sig} {typ.type.replace('_type', '')}".strip()
                end_line = typ.start_point[0] + 1
            else:
                sig = " ".join(_text(node, src).split())
                end_line = node.end_point[0] + 1
            symbols.append({"kind": kind, "name": name, "signature": sig,
                            "doc": doc, "visibility": _go_visibility(name),
                            "span": [node.start_point[0] + 1, end_line]})
    return symbols


def _go_imports(tree, src):
    """The package identifier the code actually calls (`telemetry` from
    "github.com/acme/telemetry") — that is what matches a registry id."""
    imports = set()
    caps = _captures(_get_query("go", "imports"), tree.root_node)
    for node in caps.get("source", []):
        path = _text(node, src).strip('"')
        if path:
            imports.add(path.rstrip("/").split("/")[-1])
    return sorted(imports)


def _yaml_symbols(tree, src):
    symbols = []
    caps = _captures(_get_query("yaml", "symbols"), tree.root_node)
    for node in caps.get("key", []):
        # only top-level keys: depth from root
        depth, p = 0, node.parent
        while p is not None:
            if p.type == "block_mapping_pair":
                depth += 1
            p = p.parent
        if depth <= 1:
            name = _text(node, src).strip("\"'")
            symbols.append({
                "kind": "const", "name": name, "signature": name,
                "doc": None, "visibility": "public",
                "span": [node.start_point[0] + 1, node.end_point[0] + 1],
            })
    return symbols


def _hcl_symbols(tree, src):
    symbols = []
    caps = _captures(_get_query("hcl", "symbols"), tree.root_node)
    for node in caps.get("block", []):
        idents = [c for c in node.children if c.type == "identifier"]
        labels = [c for c in node.children if c.type == "string_lit"]
        if not idents:
            continue
        btype = _text(idents[0], src)
        label = ".".join(_text(l, src).strip("\"") for l in labels)
        name = f"{btype}.{label}" if label else btype
        symbols.append({
            "kind": "const", "name": name, "signature": name, "doc": None,
            "visibility": "public" if btype in ("variable", "output") else "private",
            "span": [node.start_point[0] + 1, node.end_point[0] + 1],
        })
    return symbols


# ------------------------------------------------------------ driver
def rel_to_root(root, path):
    """Root-relative path or a loud, contextual error — never a bare
    ValueError that takes down a Stop hook (field report #19)."""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError as exc:
        raise HarnessError(
            f"path {path!r} is outside the repo root {root!r}; out-of-root "
            f"files are not shadowable — fix the recorded path") from exc


def in_root(root, path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def module_id_for(root, path: Path, config=None) -> str:
    """Dotted module id for a source file (ADR-002 / D-008).

    Args:
        root: Repo root.
        path: Source file, inside the root.
        config: Loaded engine config; None uses the default `src_roots`.

    Returns:
        The source path relative to the first matching `extractor.src_roots`
        glob, dotted, with a trailing `__init__` dropped. A repo with no
        matching source root keeps the dotted relative path it always had.

    Raises:
        HarnessError: If the path is out of root or `src_roots` is malformed.
    """
    rel = rel_to_root(root, path)
    return module_id_for_rel(rel.as_posix(), config)


def shadow_path_for(root, path: Path) -> Path:
    rel = rel_to_root(root, path)
    return harness_dir(root) / "shadows" / rel.parent / (rel.name + ".json")


def _degenerate_shadow(root, path: Path, source: bytes, config=None) -> dict:
    head = source.decode("utf-8", "replace").splitlines()[:40]
    return {
        "module_id": module_id_for(root, path, config),
        "language": "unknown",
        "source_path": str(Path(path).resolve().relative_to(Path(root).resolve())),
        "source_hash": sha256_bytes(source),
        "extractor_version": EXTRACTOR_VERSION,
        "symbols": [],
        "imports": [],
        "exports": "unknown",
        "raw_head": "\n".join(head),
    }


def build_shadow(root, path: Path, source: bytes, lang: str, config=None) -> dict:
    parser, _ = _get_parser(lang)
    tree = parser.parse(source)
    if lang == "python":
        symbols = _python_symbols(tree, source)
        imports = _python_imports(tree, source)
        exports = _python_exports(tree, source, symbols)
    elif lang == "typescript":
        symbols = _ts_symbols(tree, source)
        imports = _ts_imports(tree, source)
        exports = sorted({s["name"] for s in symbols if s["visibility"] == "public"})
    elif lang == "rust":
        symbols = _rust_symbols(tree, source)
        imports = _rust_imports(tree, source)
        # methods are interface detail on their type, not crate exports
        exports = sorted({s["name"] for s in symbols
                          if s["visibility"] == "public" and s["kind"] != "method"})
    elif lang == "go":
        symbols = _go_symbols(tree, source)
        imports = _go_imports(tree, source)
        exports = sorted({s["name"] for s in symbols
                          if s["visibility"] == "public" and s["kind"] != "method"})
    elif lang == "yaml":
        symbols = _yaml_symbols(tree, source)
        imports, exports = [], sorted({s["name"] for s in symbols})
    elif lang == "hcl":
        symbols = _hcl_symbols(tree, source)
        imports, exports = [], sorted({s["name"] for s in symbols
                                       if s["visibility"] == "public"})
    else:  # pragma: no cover — guarded by caller
        raise HarnessError(f"no builder for language {lang}")
    symbols.sort(key=lambda s: (s["span"][0], s["name"]))
    return {
        "module_id": module_id_for(root, path, config),
        "language": lang,
        "source_path": str(Path(path).resolve().relative_to(Path(root).resolve())),
        "source_hash": sha256_bytes(source),
        "extractor_version": EXTRACTOR_VERSION,
        "symbols": symbols,
        "imports": imports,
        "exports": exports,
    }


def write_shadow(root, path: Path, shadow: dict) -> Path:
    sp = shadow_path_for(root, path)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(shadow, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return sp


def load_shadow_file(sp: Path) -> dict:
    return json.loads(Path(sp).read_text(encoding="utf-8"))


def extract_path(root, path, config=None, force=False) -> tuple:
    """Extract one file. Returns (shadow_dict | None, findings).

    Cache: unchanged source AND same extractor version -> no work. A format
    change is a cache miss by construction (W7) — otherwise stale-format
    shadows are served forever while G7's uncached rebuild mismatches
    forever. `force` bypasses the cache entirely (the escape hatch).
    Unknown language -> degenerate shadow + G8 UNKNOWN_LANGUAGE finding.
    Ignored extensions -> (None, []) — docs/substrate are not modules.
    """
    path = Path(path)
    findings = []
    ext = path.suffix.lower()
    if ext in IGNORED_EXTS or not path.is_file():
        return None, []
    if not in_root(root, path):
        # out-of-root files are visible, never shadowable, never a crash
        return None, [make_finding(
            "UNSHADOWED_FILE", "gate:G8",
            f"{path}: outside the repo root — not shadowed, not enforced",
            severity="advisory", key=f"oor|{path}")]
    source = path.read_bytes()
    src_hash = sha256_bytes(source)
    sp = shadow_path_for(root, path)
    lang = LANG_BY_EXT.get(ext)
    enabled = (config or {}).get("languages", {})
    # the language a fresh extraction would produce RIGHT NOW — a language
    # toggle or a deps install changes it, and a cached shadow of the wrong
    # kind is the W7 deadlock again (S3): G7 regenerates one kind while the
    # cache serves the other forever
    expected_lang = (lang if (lang and enabled.get(lang, True)
                              and deps_available()) else "unknown")
    if sp.exists() and not force:
        try:
            existing = load_shadow_file(sp)
            if (existing.get("source_hash") == src_hash
                    and existing.get("extractor_version") == EXTRACTOR_VERSION
                    and existing.get("language") == expected_lang):
                return existing, []   # cache hit: unchanged source + format + kind
        except (json.JSONDecodeError, OSError):
            pass
    if lang is None or not enabled.get(lang, True):
        shadow = _degenerate_shadow(root, path, source, config)
        findings.append(make_finding(
            "UNKNOWN_LANGUAGE", "gate:G8",
            f"{shadow['source_path']}: language for {ext!r} not enforced; "
            f"degenerate shadow written (unenforced surface is enumerated, never invisible)",
            severity="advisory", key=shadow["source_path"]))
    elif not deps_available():
        # Degrade loudly, never crash the session: the exact failure mode the
        # premortem skill hunts is a missing dep turning into a hard block.
        shadow = _degenerate_shadow(root, path, source, config)
        findings.append(make_finding(
            "MISSING_DEPENDENCY", "gate:G8",
            f"{shadow['source_path']}: tree-sitter stack unavailable — "
            f"degenerate shadow written; interface enforcement for {lang} is "
            f"degraded until you run `{DEP_INSTALL_HINT}`",
            severity="advisory", key="deps|" + shadow["source_path"]))
    else:
        shadow = build_shadow(root, path, source, lang, config)
    write_shadow(root, path, shadow)
    return shadow, findings


def extract_all(root, config=None, force=False) -> dict:
    """Walk repo, extract every candidate source file, and refresh every
    EXISTING shadow whose source still exists — including extensionless
    sources (Makefile, LICENSE…) the discovery walk skips. G7 checks all
    stored shadows, so --all must be able to fix all of them."""
    root = Path(root)
    written, cached, findings = [], [], []
    seen = set()

    def one(p):
        sp = shadow_path_for(root, p)
        pre = sp.read_bytes() if sp.exists() else None
        shadow, f = extract_path(root, p, config, force=force)
        findings.extend(f)
        if shadow is None:
            return
        seen.add(shadow["source_path"])
        post = sp.read_bytes() if sp.exists() else None
        (cached if pre == post else written).append(shadow["source_path"])

    for p in sorted(root.rglob("*")):
        # filter on parts RELATIVE to root: a worktree at .worktrees/<slice>
        # (or a repo cloned under ~/venv/…) carries an ignored name in its
        # ABSOLUTE parts, and filtering those extracted nothing (S2)
        if any(part in IGNORED_DIRS for part in p.relative_to(root).parts):
            continue
        if not p.is_file() or p.suffix.lower() in IGNORED_EXTS or not p.suffix:
            continue
        one(p)
    pruned = []
    shadows_dir = harness_dir(root) / "shadows"
    if shadows_dir.exists():
        for sp in sorted(shadows_dir.rglob("*.json")):
            rel_sp = str(sp.relative_to(shadows_dir))
            try:
                stored = load_shadow_file(sp)
            except (json.JSONDecodeError, OSError):
                sp.unlink()          # unparseable derived artifact: garbage
                pruned.append(rel_sp)
                continue
            rel = stored.get("source_path")
            if rel in seen:
                continue
            src = root / rel if rel else None
            if src is None or not in_root(root, src) or not src.is_file():
                # deleted source, traversal path, or no source at all: the
                # shadow is stale derived state a slice can never fix by
                # hand — --all IS the fix (S4/S5), never manual deletion
                sp.unlink()
                pruned.append(rel or rel_sp)
                continue
            one(src)
    return {"written": written, "cached": cached, "pruned": pruned,
            "findings": findings}
