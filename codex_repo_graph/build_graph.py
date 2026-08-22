#!/usr/bin/env python3
"""Build a deterministic, evidence-addressed graph of the current checkout.

The analyzer is static by design: it never imports repository modules, opens a
database connection, reads credential stores, or invokes network-facing tools.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Sequence


SCHEMA_VERSION = "1.1.0"
ROOT = Path(__file__).resolve().parents[1]
GRAPH_DIR = Path(__file__).resolve().parent
INDEX_DIR = GRAPH_DIR / "index"
SEMANTIC_DIR = GRAPH_DIR / "semantic"
VALIDATION_DIR = GRAPH_DIR / "validation"
GRAPH_PREFIX = f"{GRAPH_DIR.relative_to(ROOT).as_posix()}/"
MAX_INDEXED_TEXT_BYTES = 2_000_000

OPAQUE_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)

SEMANTIC_FILES = (
    "components.jsonl",
    "invariants.jsonl",
    "runtime_flows.jsonl",
    "persistence.jsonl",
    "concurrency.jsonl",
    "interfaces.jsonl",
    "task_routes.jsonl",
    "claims.jsonl",
    "hazards.jsonl",
)

TEXT_EXTENSIONS = {
    ".cfg",
    ".css",
    ".csv",
    ".env.example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

LANGUAGE_BY_EXTENSION = {
    ".cfg": "ini",
    ".css": "css",
    ".csv": "csv",
    ".html": "html",
    ".ini": "ini",
    ".js": "javascript",
    ".json": "json",
    ".jsonl": "jsonl",
    ".md": "markdown",
    ".ps1": "powershell",
    ".py": "python",
    ".sql": "sql",
    ".toml": "toml",
    ".ts": "typescript",
    ".txt": "text",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}

METADATA_ONLY_NAMES = {
    "server_log.txt",
    "server_logs.txt",
    "startup_output.txt",
}

PLAIN_TEXT_NAMES = {
    ".gitattributes",
    ".gitignore",
}

BINARY_EXTENSIONS = {
    ".7z",
    ".bin",
    ".db",
    ".dll",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".webp",
    ".zip",
}

SQL_PATTERNS = (
    ("defines_table", re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"']?([A-Za-z_][\w.]*)", re.I)),
    ("writes_table", re.compile(r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?[\"']?([A-Za-z_][\w.]*)", re.I)),
    ("writes_table", re.compile(r"\bINSERT\s+INTO\s+[\"']?([A-Za-z_][\w.]*)", re.I)),
    ("writes_table", re.compile(r"\bUPDATE\s+[\"']?([A-Za-z_][\w.]*)\s+SET\b", re.I)),
    ("writes_table", re.compile(r"\bDELETE\s+FROM\s+[\"']?([A-Za-z_][\w.]*)", re.I)),
    ("reads_table", re.compile(r"\b(?:FROM|JOIN)\s+[\"']?([A-Za-z_][\w.]*)", re.I)),
)

SQL_STATEMENT_HINT = re.compile(
    r"(?:\bSELECT\b[\s\S]*?\bFROM\b|"
    r"\bINSERT\s+INTO\b|"
    r"\bUPDATE\s+[A-Za-z_][\w.]*\s+SET\b|"
    r"\bDELETE\s+FROM\b|"
    r"\bCREATE\s+TABLE\b|"
    r"\bALTER\s+TABLE\b)",
    re.I,
)

SQL_STATEMENT_START = re.compile(
    r"^\s*(?:WITH\b|SELECT\b|INSERT\b|UPDATE\b|DELETE\b|CREATE\b|ALTER\b)",
    re.I,
)

SQL_RESERVED_RELATIONS = {
    "as",
    "by",
    "from",
    "if",
    "join",
    "not",
    "null",
    "on",
    "select",
    "set",
    "values",
    "where",
}

ENV_PATTERNS_BY_LANGUAGE = {
    "python": (
        re.compile(r"\bos\.getenv\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']"),
        re.compile(r"\bos\.environ(?:\.get\()?\s*\[?\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']"),
    ),
    "javascript": (
        re.compile(r"\bprocess\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"\bprocess\.env\s*\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]"),
        re.compile(r"\bDeno\.env\.get\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']"),
    ),
    "typescript": (
        re.compile(r"\bprocess\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"\bprocess\.env\s*\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]"),
        re.compile(r"\bDeno\.env\.get\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']"),
    ),
    "powershell": (
        re.compile(r"\$env:([A-Za-z_][A-Za-z0-9_]*)", re.I),
    ),
}

HANDLED_EVENT_PATTERNS = (
    re.compile(r"\bmsg_type\s*(?:==|in)\s*[\[(]?\s*[\"']([A-Za-z0-9_.:-]+)[\"']"),
    re.compile(r"\b(?:data|message|msg)\.type\s*={2,3}\s*[\"']([A-Za-z0-9_.:-]+)[\"']"),
    re.compile(r"\bcase\s+[\"']([A-Za-z0-9_.:-]+)[\"']\s*:"),
)

TYPE_DISCRIMINATOR_PATTERNS = (
    re.compile(r"[\"']type[\"']\s*:\s*[\"']([A-Za-z0-9_.:-]+)[\"']"),
    re.compile(r"\btype\s*:\s*[\"']([A-Za-z0-9_.:-]+)[\"']"),
)

RUNTIME_PRIMITIVES = {
    "Condition",
    "Event",
    "Lock",
    "Queue",
    "RLock",
    "Semaphore",
    "Thread",
    "ThreadPoolExecutor",
}


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def render_jsonl(records: Iterable[dict[str, Any]]) -> bytes:
    ordered = sorted(records, key=lambda item: (str(item.get("id", "")), compact_json(item)))
    if not ordered:
        return b""
    return ("\n".join(compact_json(record) for record in ordered) + "\n").encode("utf-8")


def render_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def edge_id(
    source_id: str,
    edge_kind: str,
    target: str,
    path: str,
    line: int,
    confidence: str,
    attributes: dict[str, Any],
) -> str:
    raw = "\0".join(
        (source_id, edge_kind, target, path, str(line), confidence, compact_json(attributes))
    ).encode("utf-8")
    return f"e:{hashlib.sha1(raw).hexdigest()[:24]}"


def run_git(args: Sequence[str], *, allow_failure: bool = False) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode and not allow_failure:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def normalized_path(raw_path: str) -> str:
    return posixpath.normpath(raw_path.replace("\\", "/"))


def redact_opaque_identifiers(value: str) -> str:
    """Remove UUID-shaped operational identifiers from copied descriptive text."""
    return OPAQUE_UUID_PATTERN.sub("<uuid-redacted>", value)


def discover_repository_paths() -> tuple[list[str], list[dict[str, str]]]:
    output = run_git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    raw_paths = output.split("\0")
    included: list[str] = []
    excluded: list[dict[str, str]] = []
    for raw_path in sorted(set(path for path in raw_paths if path)):
        path = normalized_path(raw_path)
        if path == GRAPH_PREFIX.rstrip("/") or path.startswith(GRAPH_PREFIX):
            excluded.append({"path": path, "reason": "graph_self"})
            continue
        absolute = ROOT / path
        if not absolute.exists() and not absolute.is_symlink():
            excluded.append({"path": path, "reason": "missing_worktree_path"})
            continue
        if absolute.is_dir():
            excluded.append({"path": path, "reason": "directory_entry"})
            continue
        included.append(path)
    return included, excluded


def language_for(path: str) -> str:
    name = PurePosixPath(path).name
    if name == "Dockerfile":
        return "dockerfile"
    if name in PLAIN_TEXT_NAMES:
        return "text"
    if name.endswith(".env.example"):
        return "dotenv"
    return LANGUAGE_BY_EXTENSION.get(PurePosixPath(path).suffix.lower(), "binary_or_unknown")


def role_tags_for(path: str, language: str) -> list[str]:
    parts = PurePosixPath(path).parts
    name = PurePosixPath(path).name
    tags: set[str] = set()
    prefix_map = {
        "api_reference": "external_reference",
        "bridges": "bridge",
        "business": "business_logic",
        "calculation": "calculation",
        "core": "core_runtime",
        "data": "data_access",
        "database": "persistence",
        "docs": "documentation",
        "external": "exchange_boundary",
        "genai_data": "agent_context",
        "genai_tools": "non_authoritative_tool",
        "integration": "integration_boundary",
        "market_intel": "market_intelligence",
        "tests": "test",
        "ui_order_span": "ui",
        "websocket": "websocket_dispatch",
        "websocket_reference": "external_reference",
    }
    if parts and parts[0] in prefix_map:
        tags.add(prefix_map[parts[0]])
    if path in {"main.py", "dashboard_server.py", "ui_console.py"}:
        tags.add("runtime_entry_or_surface")
    if name in {"configuration.py", "pyproject.toml", "pytest.ini"}:
        tags.add("configuration")
    if language in {"html", "css", "javascript", "typescript"}:
        tags.add("ui_or_client")
    if language in {"markdown", "text"}:
        tags.add("documentation_or_evidence")
    if path.startswith("tests/"):
        if len(parts) > 1:
            tags.add(f"test_suite:{parts[1]}")
    if path.startswith("genai_tools/"):
        risky_tokens = ("adopt", "backfill", "execute", "fix", "initialize", "reconcile", "sync", "update")
        if any(token in name.lower() for token in risky_tokens):
            tags.add("execution_risk")
    return sorted(tags)


def should_index_content(path: str, size: int) -> tuple[bool, str | None]:
    pure = PurePosixPath(path)
    suffix = pure.suffix.lower()
    lower_name = pure.name.lower()
    if pure.name in METADATA_ONLY_NAMES or lower_name.endswith(".log") or "server_log" in lower_name:
        return False, "log_or_runtime_output"
    if suffix in BINARY_EXTENSIONS:
        return False, "binary_extension"
    if size > MAX_INDEXED_TEXT_BYTES:
        return False, "over_text_size_limit"
    if suffix in TEXT_EXTENSIONS or pure.name in {"Dockerfile", "LICENSE", "Makefile", *PLAIN_TEXT_NAMES}:
        return True, None
    return False, "unknown_or_binary_type"


def decode_text(data: bytes) -> tuple[str | None, str | None]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return None, None


def file_line_count(data: bytes) -> int:
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def build_file_records(paths: Sequence[str]) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, list[str]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    text_by_path: dict[str, str] = {}
    lines_by_path: dict[str, list[str]] = {}
    content_exclusions: list[dict[str, str]] = []
    for path in paths:
        absolute = ROOT / path
        if absolute.is_symlink():
            data = os.readlink(absolute).encode("utf-8", errors="replace")
            link_target = os.readlink(absolute)
        else:
            data = absolute.read_bytes()
            link_target = None
        language = language_for(path)
        content_indexed, exclusion_reason = should_index_content(path, len(data))
        encoding: str | None = None
        text: str | None = None
        if content_indexed:
            text, encoding = decode_text(data)
            if text is None:
                content_indexed = False
                exclusion_reason = "undecodable_text"
        if content_indexed and text is not None:
            text_by_path[path] = text
            lines_by_path[path] = text.splitlines()
        elif exclusion_reason:
            content_exclusions.append({"path": path, "reason": exclusion_reason})
        record: dict[str, Any] = {
            "bytes": len(data),
            "content_exclusion_reason": exclusion_reason,
            "content_indexed": content_indexed,
            "encoding": encoding,
            "id": f"f:{path}",
            "kind": "file",
            "language": language,
            "lines": file_line_count(data),
            "path": path,
            "role_tags": role_tags_for(path, language),
            "sha256": sha256_bytes(data),
            "symlink_target": link_target,
        }
        records.append(record)
    return records, text_by_path, lines_by_path, content_exclusions


def dotted_name(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)
    return None


def safe_unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return None


def first_doc_line(node: ast.AST) -> str | None:
    value = ast.get_docstring(node, clean=True)
    if not value:
        return None
    return redact_opaque_identifiers(value.splitlines()[0][:240])


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render names/types while deliberately omitting every default expression."""

    def render_arg(arg: ast.arg, *, prefix: str = "", has_default: bool = False) -> str:
        rendered = f"{prefix}{arg.arg}"
        annotation = safe_unparse(arg.annotation)
        if annotation:
            rendered += f": {annotation}"
        if has_default:
            rendered += "=<default-redacted>"
        return rendered

    rendered_args: list[str] = []
    positional = [*node.args.posonlyargs, *node.args.args]
    default_start = len(positional) - len(node.args.defaults)
    for index, arg in enumerate(positional):
        rendered_args.append(render_arg(arg, has_default=index >= default_start))
        if node.args.posonlyargs and index + 1 == len(node.args.posonlyargs):
            rendered_args.append("/")
    if node.args.vararg:
        rendered_args.append(render_arg(node.args.vararg, prefix="*"))
    elif node.args.kwonlyargs:
        rendered_args.append("*")
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        rendered_args.append(render_arg(arg, has_default=default is not None))
    if node.args.kwarg:
        rendered_args.append(render_arg(node.args.kwarg, prefix="**"))

    args = ", ".join(rendered_args)
    returns = safe_unparse(node.returns)
    return f"({args})" + (f" -> {returns}" if returns else "")


def expression_kind(node: ast.AST | None) -> str | None:
    """Describe an expression structurally without copying its literal payload."""
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return f"literal:{type(node.value).__name__}"
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return "mapping"
    if isinstance(node, (ast.List, ast.ListComp, ast.Tuple, ast.Set, ast.SetComp)):
        return "collection"
    if isinstance(node, ast.Call):
        return "call"
    if isinstance(node, (ast.Attribute, ast.Name, ast.Subscript)):
        return "reference"
    return type(node).__name__.lower()


def decorator_descriptor(node: ast.AST) -> str:
    """Return decorator identity without serializing argument payloads."""
    if isinstance(node, ast.Call):
        return dotted_name(node.func) or "<dynamic-decorator>"
    return dotted_name(node) or type(node).__name__


def parametrized_test_arguments(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        descriptor = dotted_name(decorator.func) or ""
        if not descriptor.endswith("parametrize") or not decorator.args:
            continue
        raw_names = decorator.args[0]
        if isinstance(raw_names, ast.Constant) and isinstance(raw_names.value, str):
            names.update(part.strip() for part in raw_names.value.split(",") if part.strip())
        elif isinstance(raw_names, (ast.List, ast.Tuple)):
            for item in raw_names.elts:
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    names.add(item.value)
    return names


class PythonCollector(ast.NodeVisitor):
    def __init__(self, path: str, source: str) -> None:
        self.path = path
        self.source = source
        self.file_id = f"f:{path}"
        self.scopes: list[tuple[str, str]] = []
        self.symbols: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.imports: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.tests: list[dict[str, Any]] = []
        self.runtime_refs: list[dict[str, Any]] = []
        self.seen_symbol_ids: Counter[str] = Counter()

    def current_source_id(self) -> str:
        return self.scopes[-1][1] if self.scopes else self.file_id

    def qualname_for(self, name: str) -> str:
        if not self.scopes:
            return name
        return ".".join([scope_name for scope_name, _ in self.scopes] + [name])

    def make_symbol_id(self, qualname: str) -> str:
        base = f"s:{self.path}::{qualname}"
        self.seen_symbol_ids[base] += 1
        occurrence = self.seen_symbol_ids[base]
        return base if occurrence == 1 else f"{base}#{occurrence}"

    def add_symbol(
        self,
        node: ast.AST,
        name: str,
        symbol_kind: str,
        *,
        signature: str | None = None,
        decorators: Sequence[str] = (),
        bases: Sequence[str] = (),
        value_kind: str | None = None,
    ) -> tuple[str, str]:
        qualname = self.qualname_for(name)
        symbol_id = self.make_symbol_id(qualname)
        line_start = int(getattr(node, "lineno", 1))
        line_end = int(getattr(node, "end_lineno", line_start) or line_start)
        record = {
            "async": isinstance(node, ast.AsyncFunctionDef),
            "bases": list(bases),
            "confidence": "exact",
            "decorators": list(decorators),
            "doc": first_doc_line(node) if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) else None,
            "id": symbol_id,
            "kind": "symbol",
            "line_end": line_end,
            "line_start": line_start,
            "name": name,
            "path": self.path,
            "qualname": qualname,
            "role_tags": role_tags_for(self.path, "python"),
            "signature": signature,
            "symbol_kind": symbol_kind,
        }
        if value_kind:
            record["value_kind"] = value_kind
        self.symbols.append(record)
        parent_id = self.current_source_id()
        self.edges.append(make_edge(parent_id, "contains", target_id=symbol_id, path=self.path, line=line_start, confidence="exact"))
        return qualname, symbol_id

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        decorators = [decorator_descriptor(item) for item in node.decorator_list]
        bases = [value for item in node.bases if (value := safe_unparse(item))]
        qualname, symbol_id = self.add_symbol(node, node.name, "class", decorators=decorators, bases=bases)
        self.scopes.append((node.name, symbol_id))
        self.generic_visit(node)
        self.scopes.pop()
        return None

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        decorators = [decorator_descriptor(item) for item in node.decorator_list]
        parent_is_class = bool(self.scopes and self.symbol_by_id(self.scopes[-1][1]).get("symbol_kind") == "class")
        symbol_kind = "method" if parent_is_class else "function"
        qualname, symbol_id = self.add_symbol(
            node,
            node.name,
            symbol_kind,
            signature=function_signature(node),
            decorators=decorators,
        )
        if self.path.startswith("tests/") and node.name.startswith("test"):
            args = [arg.arg for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)]
            parametrized = parametrized_test_arguments(node)
            markers = [item for item in decorators if item.startswith("pytest.mark")]
            parts = PurePosixPath(self.path).parts
            suite = parts[1] if len(parts) > 1 else "root"
            self.tests.append({
                "environment_hints": [],
                "fixtures": sorted(name for name in args if name not in {"self", "cls"} and name not in parametrized),
                "id": f"test:{self.path}::{qualname}",
                "line_start": int(getattr(node, "lineno", 1)),
                "markers": markers,
                "path": self.path,
                "production_targets": [],
                "qualname": qualname,
                "suite": suite,
                "symbol_id": symbol_id,
            })
        self.scopes.append((node.name, symbol_id))
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_function(node)
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_function(node)
        return None

    def symbol_by_id(self, symbol_id: str) -> dict[str, Any]:
        for symbol in reversed(self.symbols):
            if symbol["id"] == symbol_id:
                return symbol
        return {}

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            self.imports.append({
                "alias": alias.asname or alias.name.split(".")[0],
                "imported_name": None,
                "level": 0,
                "line": node.lineno,
                "module": alias.name,
            })
        return None

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        for alias in node.names:
            self.imports.append({
                "alias": alias.asname or alias.name,
                "imported_name": alias.name,
                "level": node.level,
                "line": node.lineno,
                "module": node.module,
            })
        return None

    def visit_Call(self, node: ast.Call) -> Any:
        target_ref = dotted_name(node.func) or safe_unparse(node.func) or "<dynamic>"
        self.calls.append({
            "line": int(getattr(node, "lineno", 1)),
            "source_id": self.current_source_id(),
            "target_ref": target_ref,
        })
        primitive = target_ref.rsplit(".", 1)[-1]
        if primitive in RUNTIME_PRIMITIVES:
            self.runtime_refs.append({
                "line": int(getattr(node, "lineno", 1)),
                "primitive": primitive,
                "source_id": self.current_source_id(),
            })
        self.generic_visit(node)
        return None

    def visit_Assign(self, node: ast.Assign) -> Any:
        if len(self.scopes) <= 1:
            value_ref = dotted_name(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    primitive = (value_ref or "").rsplit(".", 1)[-1]
                    if name.isupper() or primitive in RUNTIME_PRIMITIVES:
                        self.add_symbol(
                            node,
                            name,
                            "runtime_state" if primitive in RUNTIME_PRIMITIVES else "constant",
                            value_kind=expression_kind(node.value),
                        )
        self.generic_visit(node)
        return None

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        if len(self.scopes) <= 1 and isinstance(node.target, ast.Name):
            name = node.target.id
            value_ref = dotted_name(node.value)
            primitive = (value_ref or "").rsplit(".", 1)[-1]
            if name.isupper() or primitive in RUNTIME_PRIMITIVES:
                self.add_symbol(
                    node,
                    name,
                    "runtime_state" if primitive in RUNTIME_PRIMITIVES else "constant",
                    value_kind=expression_kind(node.value),
                )
        self.generic_visit(node)
        return None


def make_edge(
    source_id: str,
    edge_kind: str,
    *,
    path: str,
    line: int,
    confidence: str,
    target_id: str | None = None,
    target_ref: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if bool(target_id) == bool(target_ref):
        raise ValueError("edge requires exactly one of target_id or target_ref")
    target = target_id or target_ref or ""
    normalized_attributes = attributes or {}
    record: dict[str, Any] = {
        "attributes": normalized_attributes,
        "confidence": confidence,
        "edge_kind": edge_kind,
        "id": edge_id(source_id, edge_kind, target, path, line, confidence, normalized_attributes),
        "kind": "edge",
        "line": line,
        "path": path,
        "source_id": source_id,
    }
    if target_id:
        record["target_id"] = target_id
    else:
        record["target_ref"] = target_ref
    return record


def python_module_for_path(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return None
    parts = list(pure.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def resolve_relative_module(path: str, module: str | None, level: int) -> str:
    current = python_module_for_path(path) or ""
    package = current.split(".")[:-1]
    if PurePosixPath(path).name == "__init__.py":
        package = current.split(".") if current else []
    if level:
        keep = max(0, len(package) - (level - 1))
        package = package[:keep]
    else:
        package = []
    if module:
        package.extend(module.split("."))
    return ".".join(part for part in package if part)


def index_python(
    text_by_path: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    symbols: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    collectors: list[PythonCollector] = []
    module_to_path = {
        module: path
        for path in text_by_path
        if (module := python_module_for_path(path)) is not None
    }

    for path in sorted(text_by_path):
        if not path.endswith(".py"):
            continue
        source = text_by_path[path]
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, ValueError) as exc:
            parse_errors.append({
                "error": f"{type(exc).__name__}: {exc}",
                "path": path,
                "stage": "python_ast",
            })
            continue
        collector = PythonCollector(path, source)
        collector.visit(tree)
        collectors.append(collector)
        symbols.extend(collector.symbols)
        edges.extend(collector.edges)
        tests.extend(collector.tests)

    symbols_by_file_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    symbol_by_id = {record["id"]: record for record in symbols}
    for record in symbols:
        symbols_by_file_name[(record["path"], record["name"])].append(record["id"])

    production_targets_by_test_symbol: dict[str, set[str]] = defaultdict(set)
    for collector in collectors:
        alias_map: dict[str, tuple[str | None, str | None]] = {}
        for item in collector.imports:
            module = resolve_relative_module(collector.path, item["module"], item["level"])
            if item["module"] is None and item["imported_name"]:
                candidate_module = f"{module}.{item['imported_name']}" if module else item["imported_name"]
            else:
                candidate_module = module
            target_path = module_to_path.get(candidate_module) or module_to_path.get(module)
            target_ref = candidate_module or item["imported_name"] or "<relative>"
            if target_path:
                edges.append(make_edge(
                    collector.file_id,
                    "imports",
                    target_id=f"f:{target_path}",
                    path=collector.path,
                    line=item["line"],
                    confidence="exact",
                    attributes={"imported_name": item["imported_name"]},
                ))
            else:
                edges.append(make_edge(
                    collector.file_id,
                    "imports",
                    target_ref=target_ref,
                    path=collector.path,
                    line=item["line"],
                    confidence="exact",
                    attributes={"imported_name": item["imported_name"]},
                ))
            alias_map[item["alias"]] = (target_path, item["imported_name"])

        for call in collector.calls:
            target_ref = call["target_ref"]
            target_id: str | None = None
            confidence = "heuristic"
            leaf = target_ref.rsplit(".", 1)[-1]
            root_alias = target_ref.split(".", 1)[0]
            imported_path, imported_name = alias_map.get(root_alias, (None, None))
            if target_ref.startswith(("self.", "cls.")):
                source_symbol = symbol_by_id.get(call["source_id"], {})
                source_qualname = str(source_symbol.get("qualname", ""))
                class_prefix = source_qualname.rsplit(".", 1)[0] if "." in source_qualname else ""
                candidate = f"s:{collector.path}::{class_prefix}.{leaf}" if class_prefix else ""
                if candidate in symbol_by_id:
                    target_id = candidate
            elif imported_path:
                imported_leaf = imported_name if "." not in target_ref and imported_name else leaf
                candidates = symbols_by_file_name.get((imported_path, imported_leaf or leaf), [])
                if len(candidates) == 1:
                    target_id = candidates[0]
            elif "." not in target_ref:
                same_file = symbols_by_file_name.get((collector.path, leaf), [])
                if len(same_file) == 1:
                    target_id = same_file[0]
            if target_id:
                resolved_symbol = symbol_by_id.get(target_id, {})
                resolved_path = str(resolved_symbol.get("path", ""))
                if (
                    collector.path.startswith("tests/")
                    and call["source_id"].startswith(f"s:{collector.path}::")
                    and resolved_path
                    and not resolved_path.startswith("tests/")
                ):
                    production_targets_by_test_symbol[call["source_id"]].add(resolved_path)
                edges.append(make_edge(
                    call["source_id"],
                    "calls",
                    target_id=target_id,
                    path=collector.path,
                    line=call["line"],
                    confidence=confidence,
                    attributes={"syntax": target_ref},
                ))
            else:
                if (
                    collector.path.startswith("tests/")
                    and call["source_id"].startswith(f"s:{collector.path}::")
                    and imported_path
                    and not imported_path.startswith("tests/")
                ):
                    production_targets_by_test_symbol[call["source_id"]].add(imported_path)
                edges.append(make_edge(
                    call["source_id"],
                    "calls",
                    target_ref=target_ref,
                    path=collector.path,
                    line=call["line"],
                    confidence="heuristic",
                ))

        for runtime_ref in collector.runtime_refs:
            primitive_id = f"rt:{runtime_ref['primitive']}"
            edges.append(make_edge(
                runtime_ref["source_id"],
                "constructs",
                target_id=primitive_id,
                path=collector.path,
                line=runtime_ref["line"],
                confidence="exact",
            ))

    for test in tests:
        test["production_targets"] = sorted(production_targets_by_test_symbol[test["symbol_id"]])
        source = text_by_path.get(test["path"], "")
        hints: set[str] = set()
        if "9876" in source or "TEST_DB" in source or "PostgresDB" in source:
            hints.add("postgres_test_database_possible")
        if "COINBASE_API" in source or "pytest.mark.external" in source:
            hints.add("coinbase_credentials_or_external_opt_in_possible")
        if "asyncio" in source or "pytest.mark.asyncio" in source:
            hints.add("async_runtime")
        test["environment_hints"] = sorted(hints)
        for target_path in test["production_targets"]:
            edges.append(make_edge(
                test["symbol_id"],
                "tests",
                target_id=f"f:{target_path}",
                path=test["path"],
                line=test["line_start"],
                confidence="heuristic",
            ))

    runtime_nodes: dict[str, dict[str, Any]] = {}
    for collector in collectors:
        for runtime_ref in collector.runtime_refs:
            primitive = runtime_ref["primitive"]
            runtime_nodes.setdefault(f"rt:{primitive}", {
                "confidence": "exact",
                "id": f"rt:{primitive}",
                "kind": "symbol",
                "line_end": runtime_ref["line"],
                "line_start": runtime_ref["line"],
                "name": primitive,
                "path": collector.path,
                "qualname": primitive,
                "role_tags": ["runtime_primitive"],
                "symbol_kind": "runtime_primitive",
            })
    symbols.extend(runtime_nodes.values())
    return symbols, edges, tests, parse_errors, collectors


def line_number_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def iter_sql_text(path: str, text: str, language: str) -> Iterable[tuple[str, int]]:
    """Yield SQL-bearing text with its approximate repository start line.

    Scanning an entire Python source file makes ``from package import name`` and
    prose such as ``from cancelled order`` look like SQL FROM clauses. Restrict
    Python extraction to string literals containing a complete SQL statement
    hint. SQL files remain whole-file inputs.
    """
    if language == "sql":
        yield text, 1
        return
    if language != "python":
        return
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError):
        return
    docstring_nodes: set[int] = set()
    for owner in (tree, *ast.walk(tree)):
        body = getattr(owner, "body", None)
        if not body or not isinstance(body, list):
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            docstring_nodes.add(id(first.value))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstring_nodes:
            continue
        if SQL_STATEMENT_START.search(node.value) and SQL_STATEMENT_HINT.search(node.value):
            yield node.value, int(getattr(node, "lineno", 1))


def add_global_symbol(
    registry: dict[str, dict[str, Any]],
    *,
    symbol_id: str,
    name: str,
    symbol_kind: str,
    path: str,
    line: int,
    role_tags: Sequence[str],
    confidence: str = "exact",
    source_priority: int = 0,
) -> None:
    existing = registry.get(symbol_id)
    if existing is not None and int(existing.get("_source_priority", 0)) >= source_priority:
        return
    registry[symbol_id] = {
        "_source_priority": source_priority,
        "confidence": confidence,
        "id": symbol_id,
        "kind": "symbol",
        "line_end": line,
        "line_start": line,
        "name": name,
        "path": path,
        "qualname": name,
        "role_tags": list(role_tags),
        "symbol_kind": symbol_kind,
    }


def index_textual_relations(
    text_by_path: dict[str, str],
    file_records: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    symbols: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    global_nodes: dict[str, dict[str, Any]] = {}
    file_ids = {record["path"]: record["id"] for record in file_records}

    for path, text in sorted(text_by_path.items()):
        language = language_for(path)
        file_id = file_ids[path]
        if language in {"python", "sql"}:
            for sql_text, start_line in iter_sql_text(path, text, language):
                cte_names = {
                    match.group(1).lower()
                    for match in re.finditer(
                        r"(?:\bWITH(?:\s+RECURSIVE)?|,)\s*([A-Za-z_][\w]*)\s+AS\s*\(",
                        sql_text,
                        re.I,
                    )
                }
                for edge_kind, pattern in SQL_PATTERNS:
                    for match in pattern.finditer(sql_text):
                        raw_table = match.group(1).strip('"\'')
                        normalized_table = raw_table.lower()
                        if (
                            not raw_table
                            or normalized_table in SQL_RESERVED_RELATIONS
                            or normalized_table in cte_names
                        ):
                            continue
                        if edge_kind == "reads_table":
                            prefix = sql_text[max(0, match.start() - 120):match.start()]
                            if re.search(r"\bEXTRACT\s*\([^)]*$", prefix, re.I):
                                continue
                        if not re.fullmatch(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*", raw_table):
                            continue
                        table_id = f"db:{normalized_table}"
                        line = start_line + line_number_for_offset(sql_text, match.start()) - 1
                        add_global_symbol(
                            global_nodes,
                            symbol_id=table_id,
                            name=normalized_table,
                            symbol_kind="database_table",
                            path=path,
                            line=line,
                            role_tags=("persistence",),
                            confidence="exact" if edge_kind == "defines_table" else "heuristic",
                            source_priority=(
                                1000
                                if edge_kind == "defines_table"
                                else 10
                                if path.startswith(("genai_tools/", "tests/"))
                                else 100
                            ),
                        )
                        confidence = "exact" if language == "sql" else "heuristic"
                        edges.append(make_edge(
                            file_id,
                            edge_kind,
                            target_id=table_id,
                            path=path,
                            line=line,
                            confidence=confidence,
                        ))

        if language in ENV_PATTERNS_BY_LANGUAGE:
            for pattern in ENV_PATTERNS_BY_LANGUAGE[language]:
                for match in pattern.finditer(text):
                    key = match.group(1)
                    config_id = f"cfg:{key}"
                    line = line_number_for_offset(text, match.start())
                    add_global_symbol(
                        global_nodes,
                        symbol_id=config_id,
                        name=key,
                        symbol_kind="configuration_key",
                        path=path,
                        line=line,
                        role_tags=("configuration",),
                    )
                    edges.append(make_edge(
                        file_id,
                        "reads_config",
                        target_id=config_id,
                        path=path,
                        line=line,
                        confidence="exact",
                    ))

        if language in {"python", "javascript", "typescript", "html"}:
            for pattern in HANDLED_EVENT_PATTERNS:
                for match in pattern.finditer(text):
                    event_name = match.group(1)
                    event_id = f"evt:{event_name}"
                    line = line_number_for_offset(text, match.start())
                    add_global_symbol(
                        global_nodes,
                        symbol_id=event_id,
                        name=event_name,
                        symbol_kind="handled_event_candidate",
                        path=path,
                        line=line,
                        role_tags=("interface_event_candidate",),
                        confidence="heuristic",
                    )
                    edges.append(make_edge(
                        file_id,
                        "handles_event",
                        target_id=event_id,
                        path=path,
                        line=line,
                        confidence="heuristic",
                    ))
            for pattern in TYPE_DISCRIMINATOR_PATTERNS:
                for match in pattern.finditer(text):
                    discriminator = match.group(1)
                    discriminator_id = f"disc:{discriminator}"
                    line = line_number_for_offset(text, match.start())
                    add_global_symbol(
                        global_nodes,
                        symbol_id=discriminator_id,
                        name=discriminator,
                        symbol_kind="type_discriminator_candidate",
                        path=path,
                        line=line,
                        role_tags=("type_discriminator_candidate",),
                        confidence="heuristic",
                    )
                    edges.append(make_edge(
                        file_id,
                        "uses_type_discriminator",
                        target_id=discriminator_id,
                        path=path,
                        line=line,
                        confidence="heuristic",
                    ))

        if language in {"javascript", "typescript"}:
            js_patterns = (
                ("js_function", re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(")),
                ("js_class", re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)\b")),
                ("js_arrow_or_callable", re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
            )
            for symbol_kind, pattern in js_patterns:
                occurrence: Counter[str] = Counter()
                for match in pattern.finditer(text):
                    name = match.group(1)
                    occurrence[name] += 1
                    suffix = "" if occurrence[name] == 1 else f"#{occurrence[name]}"
                    line = line_number_for_offset(text, match.start())
                    symbol_id = f"s:{path}::{name}{suffix}"
                    symbols.append({
                        "confidence": "heuristic",
                        "id": symbol_id,
                        "kind": "symbol",
                        "line_end": line,
                        "line_start": line,
                        "name": name,
                        "path": path,
                        "qualname": name,
                        "role_tags": role_tags_for(path, language),
                        "symbol_kind": symbol_kind,
                    })
                    edges.append(make_edge(file_id, "contains", target_id=symbol_id, path=path, line=line, confidence="heuristic"))
            for pattern in (
                re.compile(r"\bimport\s+.*?\s+from\s+[\"']([^\"']+)[\"']"),
                re.compile(r"\brequire\(\s*[\"']([^\"']+)[\"']\s*\)"),
            ):
                for match in pattern.finditer(text):
                    line = line_number_for_offset(text, match.start())
                    edges.append(make_edge(file_id, "imports", target_ref=match.group(1), path=path, line=line, confidence="exact"))

        if language == "html":
            html_id_occurrence: Counter[str] = Counter()
            for match in re.finditer(r"\bid=[\"']([^\"']+)[\"']", text, re.I):
                name = match.group(1)
                html_id_occurrence[name] += 1
                suffix = "" if html_id_occurrence[name] == 1 else f"#{html_id_occurrence[name]}"
                line = line_number_for_offset(text, match.start())
                symbol_id = f"s:{path}::html_id:{name}{suffix}"
                symbols.append({
                    "confidence": "exact",
                    "id": symbol_id,
                    "kind": "symbol",
                    "line_end": line,
                    "line_start": line,
                    "name": name,
                    "path": path,
                    "qualname": f"html_id:{name}{suffix}",
                    "role_tags": role_tags_for(path, language),
                    "symbol_kind": "html_id",
                })
                edges.append(make_edge(file_id, "contains", target_id=symbol_id, path=path, line=line, confidence="exact"))
            for match in re.finditer(r"<script[^>]+src=[\"']([^\"']+)[\"']", text, re.I):
                reference = match.group(1)
                line = line_number_for_offset(text, match.start())
                target_path = normalized_path(str((PurePosixPath(path).parent / reference)))
                if target_path in file_ids:
                    edges.append(make_edge(file_id, "imports", target_id=file_ids[target_path], path=path, line=line, confidence="exact"))
                else:
                    edges.append(make_edge(file_id, "imports", target_ref=reference, path=path, line=line, confidence="exact"))

        if language == "markdown":
            occurrence: Counter[str] = Counter()
            for line_number, line_text in enumerate(text.splitlines(), 1):
                heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line_text)
                if heading_match:
                    heading = redact_opaque_identifiers(heading_match.group(2).strip())
                    slug = re.sub(r"[^a-z0-9]+", "-", heading.casefold()).strip("-") or "heading"
                    occurrence[slug] += 1
                    suffix = "" if occurrence[slug] == 1 else f"#{occurrence[slug]}"
                    symbol_id = f"s:{path}::heading:{slug}{suffix}"
                    symbols.append({
                        "confidence": "exact",
                        "id": symbol_id,
                        "kind": "symbol",
                        "line_end": line_number,
                        "line_start": line_number,
                        "name": heading,
                        "path": path,
                        "qualname": f"heading:{slug}{suffix}",
                        "role_tags": role_tags_for(path, language),
                        "symbol_kind": "document_heading",
                    })
                    edges.append(make_edge(file_id, "contains", target_id=symbol_id, path=path, line=line_number, confidence="exact"))
                for link_match in re.finditer(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)", line_text):
                    reference = link_match.group(1)
                    if "://" in reference or reference.startswith("mailto:"):
                        target_ref = reference
                        edges.append(make_edge(file_id, "references", target_ref=target_ref, path=path, line=line_number, confidence="exact"))
                        continue
                    target_path = normalized_path(str(PurePosixPath(path).parent / reference))
                    if target_path.startswith("./"):
                        target_path = target_path[2:]
                    if target_path in file_ids:
                        edges.append(make_edge(file_id, "references", target_id=file_ids[target_path], path=path, line=line_number, confidence="exact"))
                    else:
                        edges.append(make_edge(file_id, "references", target_ref=reference, path=path, line=line_number, confidence="exact"))

        if language == "json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                parse_errors.append({"error": str(exc), "path": path, "stage": "json"})
            else:
                count = 0
                key_lines: dict[str, deque[int]] = defaultdict(deque)
                for key_match in re.finditer(r'"((?:\\.|[^"\\])*)"\s*:', text):
                    try:
                        parsed_key = json.loads(f'"{key_match.group(1)}"')
                    except json.JSONDecodeError:
                        continue
                    key_lines[str(parsed_key)].append(line_number_for_offset(text, key_match.start()))

                def walk_json(value: Any, pointer: str, depth: int) -> None:
                    nonlocal count
                    if depth > 4 or count >= 5000:
                        return
                    if isinstance(value, dict):
                        for key in value:
                            count += 1
                            child_pointer = f"{pointer}/{str(key).replace('~', '~0').replace('/', '~1')}"
                            line = key_lines[str(key)].popleft() if key_lines[str(key)] else 1
                            symbol_id = f"s:{path}::json:{child_pointer}"
                            symbols.append({
                                "confidence": "exact",
                                "id": symbol_id,
                                "kind": "symbol",
                                "line_end": line,
                                "line_start": line,
                                "name": str(key),
                                "path": path,
                                "qualname": f"json:{child_pointer}",
                                "role_tags": role_tags_for(path, language),
                                "symbol_kind": "json_key",
                            })
                            edges.append(make_edge(file_id, "contains", target_id=symbol_id, path=path, line=line, confidence="exact"))
                            walk_json(value[key], child_pointer, depth + 1)
                    elif isinstance(value, list) and value and depth < 2:
                        walk_json(value[0], f"{pointer}/0", depth + 1)

                walk_json(payload, "", 0)
                if count >= 5000:
                    parse_errors.append({"error": "json key index capped at 5000", "path": path, "stage": "json_index_limit"})

        if language in {"yaml", "toml", "ini", "dotenv"}:
            occurrence: Counter[str] = Counter()
            for line_number, line_text in enumerate(text.splitlines(), 1):
                match = re.match(r"^([A-Za-z_][A-Za-z0-9_.-]*)\s*(?:=|:)\s*", line_text)
                if not match:
                    continue
                key = match.group(1)
                occurrence[key] += 1
                suffix = "" if occurrence[key] == 1 else f"#{occurrence[key]}"
                symbol_id = f"s:{path}::config:{key}{suffix}"
                symbols.append({
                    "confidence": "heuristic",
                    "id": symbol_id,
                    "kind": "symbol",
                    "line_end": line_number,
                    "line_start": line_number,
                    "name": key,
                    "path": path,
                    "qualname": f"config:{key}{suffix}",
                    "role_tags": role_tags_for(path, language),
                    "symbol_kind": "configuration_entry",
                })
                edges.append(make_edge(file_id, "contains", target_id=symbol_id, path=path, line=line_number, confidence="heuristic"))

    for record in global_nodes.values():
        record.pop("_source_priority", None)
    symbols.extend(global_nodes.values())
    return symbols, edges, parse_errors


def deduplicate_records(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    by_id: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []
    for record in records:
        record_id = str(record["id"])
        existing = by_id.get(record_id)
        if existing is None:
            by_id[record_id] = record
        elif existing != record:
            conflicts.append(record_id)
    return list(by_id.values()), sorted(set(conflicts))


def schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def resolve_schema_reference(root_schema: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"unsupported schema reference: {reference}")
    value: Any = root_schema
    for part in reference[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(value, dict):
        raise ValueError(f"schema reference is not an object: {reference}")
    return value


def validate_schema_value(
    value: Any,
    rule: dict[str, Any],
    root_schema: dict[str, Any],
    location: str,
) -> list[str]:
    """Validate the JSON-Schema subset used by schema.json without dependencies."""
    if "$ref" in rule:
        referenced = resolve_schema_reference(root_schema, str(rule["$ref"]))
        return validate_schema_value(value, referenced, root_schema, location)

    errors: list[str] = []
    expected_type = rule.get("type")
    if expected_type and not schema_type_matches(value, str(expected_type)):
        return [f"{location}: expected {expected_type}, got {type(value).__name__}"]
    if "const" in rule and value != rule["const"]:
        errors.append(f"{location}: expected constant {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{location}: value not in enum")
    if isinstance(value, str):
        if len(value) < int(rule.get("minLength", 0)):
            errors.append(f"{location}: string shorter than minLength")
        pattern = rule.get("pattern")
        if pattern and re.search(str(pattern), value) is None:
            errors.append(f"{location}: string does not match {pattern!r}")
    if isinstance(value, int) and not isinstance(value, bool) and "minimum" in rule:
        if value < int(rule["minimum"]):
            errors.append(f"{location}: value below minimum")

    if isinstance(value, dict):
        required = rule.get("required", [])
        for field in required:
            if field not in value:
                errors.append(f"{location}: missing required field {field}")
        properties = rule.get("properties", {})
        for field, field_rule in properties.items():
            if field in value:
                errors.extend(validate_schema_value(value[field], field_rule, root_schema, f"{location}.{field}"))
        if rule.get("additionalProperties") is False:
            for field in sorted(set(value) - set(properties)):
                errors.append(f"{location}: unexpected field {field}")
    if isinstance(value, list) and isinstance(rule.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate_schema_value(item, rule["items"], root_schema, f"{location}[{index}]"))

    if "not" in rule and not validate_schema_value(value, rule["not"], root_schema, location):
        errors.append(f"{location}: matched forbidden schema")
    if "oneOf" in rule:
        branch_results = [
            validate_schema_value(value, branch, root_schema, location)
            for branch in rule["oneOf"]
        ]
        passing = sum(not result for result in branch_results)
        if passing != 1:
            errors.append(f"{location}: expected exactly one schema branch, got {passing}")
            if passing == 0 and branch_results:
                errors.extend(min(branch_results, key=len)[:3])
    return errors


def validate_records_against_schema(
    schema: dict[str, Any],
    record_groups: Sequence[tuple[str, Sequence[dict[str, Any]]]],
) -> tuple[int, list[str]]:
    required_schema_keys = {"$schema", "type", "oneOf", "$defs"}
    missing = sorted(required_schema_keys - set(schema))
    if missing:
        return 0, [f"schema.json missing enforcement keys: {', '.join(missing)}"]
    errors: list[str] = []
    count = 0
    for group_name, records in record_groups:
        for record in records:
            count += 1
            record_id = str(record.get("id", f"record-{count}"))
            errors.extend(validate_schema_value(record, schema, schema, f"{group_name}:{record_id}"))
    return count, errors


def validate_semantic_references(
    semantic_records: Sequence[dict[str, Any]],
    file_records: Sequence[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    semantic_ids = {str(record["id"]) for record in semantic_records}
    files_by_path = {str(record["path"]): record for record in file_records}
    for record in semantic_records:
        record_id = str(record["id"])
        for target_id in record.get("semantic_ids", []):
            if target_id not in semantic_ids:
                errors.append(f"{record_id}: unresolved semantic id: {target_id}")
        for reference in record.get("start_here", []):
            raw_reference = str(reference)
            path = raw_reference
            line: int | None = None
            if ":" in raw_reference:
                possible_path, possible_line = raw_reference.rsplit(":", 1)
                if possible_line.isdigit():
                    path = possible_path
                    line = int(possible_line)
            normalized = normalized_path(path).rstrip("/")
            file_record = files_by_path.get(normalized)
            directory_exists = any(candidate.startswith(f"{normalized}/") for candidate in files_by_path)
            if line is None:
                if not file_record and not directory_exists:
                    errors.append(f"{record_id}: unresolved start_here reference: {raw_reference}")
            elif not file_record or line < 1 or line > max(1, int(file_record["lines"])):
                errors.append(f"{record_id}: unresolved start_here reference: {raw_reference}")
    return errors


SENSITIVE_OUTPUT_PATTERNS = {
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}\b", re.I),
    "credentialed_uri": re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "opaque_uuid": OPAQUE_UUID_PATTERN,
    "private_key_material": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "stripe_live_key": re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b"),
}


def find_sensitive_artifact_patterns(artifacts: dict[Path, bytes]) -> list[str]:
    findings: list[str] = []
    for path, data in sorted(artifacts.items(), key=lambda item: item[0].as_posix()):
        text = data.decode("utf-8", errors="replace")
        for label, pattern in SENSITIVE_OUTPUT_PATTERNS.items():
            count = sum(1 for _ in pattern.finditer(text))
            if count:
                findings.append(f"{path.relative_to(ROOT).as_posix()}: {label} x{count}")
    return findings


def validate_symbol_redaction(symbols: Sequence[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for symbol in symbols:
        symbol_id = str(symbol["id"])
        if "value" in symbol:
            errors.append(f"{symbol_id}: raw value field is forbidden")
        signature = symbol.get("signature")
        if isinstance(signature, str) and re.search(r"=\s*[\"']", signature):
            errors.append(f"{symbol_id}: literal default leaked into signature")
        for decorator in symbol.get("decorators", []):
            if "(" in str(decorator):
                errors.append(f"{symbol_id}: decorator arguments were not redacted")
    return errors


def validate_index_invariants(
    file_records: Sequence[dict[str, Any]],
    symbols: Sequence[dict[str, Any]],
    edges: Sequence[dict[str, Any]],
    tests: Sequence[dict[str, Any]],
    lines_by_path: dict[str, list[str]],
) -> list[str]:
    errors: list[str] = []
    files_by_path = {str(record["path"]): record for record in file_records}
    for record in [*symbols, *tests]:
        record_id = str(record["id"])
        path = str(record.get("path", ""))
        file_record = files_by_path.get(path)
        line_start = int(record.get("line_start", 0))
        line_end = int(record.get("line_end", line_start))
        if not file_record or line_start < 1 or line_end < line_start or line_end > max(1, int(file_record["lines"])):
            errors.append(f"{record_id}: invalid indexed source range")
    for edge in edges:
        path = str(edge.get("path", ""))
        line = int(edge.get("line", 0))
        file_record = files_by_path.get(path)
        if not file_record or line < 1 or line > max(1, int(file_record["lines"])):
            errors.append(f"{edge['id']}: invalid edge source location")

    for symbol in symbols:
        if symbol.get("symbol_kind") != "json_key" or symbol.get("confidence") != "exact":
            continue
        path = str(symbol["path"])
        line = int(symbol["line_start"])
        lines = lines_by_path.get(path, [])
        encoded_key = json.dumps(str(symbol["name"]), ensure_ascii=False)
        if line > len(lines) or encoded_key not in lines[line - 1]:
            errors.append(f"{symbol['id']}: exact JSON key location does not contain key")

    for edge in edges:
        if edge.get("edge_kind") == "calls" and edge.get("confidence") == "exact":
            errors.append(f"{edge['id']}: call edges must remain heuristic")
        if edge.get("edge_kind") == "references" and edge.get("target_ref"):
            reference = str(edge["target_ref"])
            if "://" not in reference and not reference.startswith("mailto:"):
                candidate = normalized_path(str(PurePosixPath(str(edge["path"])).parent / reference))
                if candidate in files_by_path:
                    errors.append(f"{edge['id']}: unresolved local reference has an indexed target")

    defined_tables = {
        str(edge["target_id"])
        for edge in edges
        if edge.get("edge_kind") == "defines_table" and edge.get("target_id")
    }
    for symbol in symbols:
        if (
            symbol.get("symbol_kind") == "database_table"
            and symbol.get("confidence") == "exact"
            and symbol["id"] not in defined_tables
        ):
            errors.append(f"{symbol['id']}: exact database relation lacks a CREATE TABLE edge")
    return errors


def collect_git_commits() -> list[dict[str, Any]]:
    output = run_git([
        "log",
        "--all",
        "--date-order",
        "--format=%H%x1f%P%x1f%ct%x1f%an%x1f%D%x1f%s",
    ])
    records: list[dict[str, Any]] = []
    for line in output.splitlines():
        fields = line.split("\x1f", 5)
        if len(fields) != 6:
            continue
        commit, parents, epoch, author, decorations, subject = fields
        records.append({
            "author_name": author,
            "decorations": decorations,
            "epoch": int(epoch),
            "id": f"commit:{commit}",
            "kind": "git_commit",
            "parents": [f"commit:{parent}" for parent in parents.split() if parent],
            "sha": commit,
            "subject": redact_opaque_identifiers(subject),
        })
    return records


def collect_git_refs() -> tuple[list[dict[str, Any]], int]:
    output = run_git([
        "for-each-ref",
        "--format=%(refname)%09%(objectname)%09%(objecttype)%09%(upstream:short)",
    ])
    records: list[dict[str, Any]] = []
    excluded_count = 0
    for line in output.splitlines():
        fields = line.split("\t", 3)
        if len(fields) != 4:
            continue
        refname, object_name, object_type, upstream = fields
        if refname.startswith("refs/codex/turn-diffs/"):
            excluded_count += 1
            continue
        records.append({
            "id": f"ref:{refname}",
            "kind": "git_ref",
            "object": object_name,
            "object_type": object_type,
            "ref": refname,
            "upstream": upstream or None,
        })
    return records, excluded_count


def collect_path_history() -> list[dict[str, Any]]:
    output = run_git([
        "log",
        "--all",
        "--no-renames",
        "--format=@@%x09%H%x09%ct",
        "--numstat",
    ])
    state: dict[str, dict[str, Any]] = {}
    current_commit: str | None = None
    current_epoch: int | None = None
    for line in output.splitlines():
        if line.startswith("@@\t"):
            parts = line.split("\t")
            if len(parts) >= 3:
                current_commit = parts[1]
                try:
                    current_epoch = int(parts[2])
                except ValueError:
                    current_epoch = None
            continue
        if not current_commit or current_epoch is None or not line or "\t" not in line:
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        additions_raw, deletions_raw, raw_path = parts
        path = normalized_path(raw_path.strip('"'))
        record = state.setdefault(path, {
            "additions": 0,
            "binary_changes": 0,
            "commit_count": 0,
            "deletions": 0,
            "first_epoch": current_epoch,
            "first_sha": current_commit,
            "id": f"history:{path}",
            "kind": "path_history",
            "last_epoch": current_epoch,
            "last_sha": current_commit,
            "path": path,
        })
        record["commit_count"] += 1
        record["first_epoch"] = current_epoch
        record["first_sha"] = current_commit
        if additions_raw == "-" or deletions_raw == "-":
            record["binary_changes"] += 1
        else:
            try:
                record["additions"] += int(additions_raw)
                record["deletions"] += int(deletions_raw)
            except ValueError:
                pass
    return list(state.values())


def load_and_normalize_semantic(
    file_records: Sequence[dict[str, Any]],
    lines_by_path: dict[str, list[str]],
) -> tuple[dict[Path, bytes], list[dict[str, Any]], list[str]]:
    files_by_path = {record["path"]: record for record in file_records}
    expected: dict[Path, bytes] = {}
    all_records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    for filename in SEMANTIC_FILES:
        path = SEMANTIC_DIR / filename
        records: list[dict[str, Any]] = []
        if not path.exists():
            errors.append(f"missing semantic file: {path.relative_to(ROOT).as_posix()}")
            expected[path] = b""
            continue
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path.relative_to(ROOT)}:{line_number}: {exc}")
                continue
            record_id = str(record.get("id", ""))
            if not record_id:
                errors.append(f"{path.relative_to(ROOT)}:{line_number}: missing id")
                continue
            if record_id in seen_ids:
                errors.append(f"duplicate semantic id: {record_id}")
            seen_ids.add(record_id)
            if record.get("state") not in {"verified_current", "intended_only", "historical", "conflicted", "unknown"}:
                errors.append(f"{record_id}: invalid state")
            if record.get("confidence") not in {"exact", "curated", "heuristic"}:
                errors.append(f"{record_id}: invalid confidence")
            evidence_items = record.get("evidence", [])
            if not isinstance(evidence_items, list):
                errors.append(f"{record_id}: evidence must be a list")
                evidence_items = []
                record["evidence"] = evidence_items
            for evidence in evidence_items:
                evidence_path = normalized_path(str(evidence.get("path", "")))
                evidence["path"] = evidence_path
                file_record = files_by_path.get(evidence_path)
                if not file_record:
                    errors.append(f"{record_id}: evidence path not indexed: {evidence_path}")
                    continue
                try:
                    line_start = int(evidence["line_start"])
                    line_end = int(evidence["line_end"])
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{record_id}: invalid evidence range for {evidence_path}")
                    continue
                lines = lines_by_path.get(evidence_path)
                if lines is None:
                    errors.append(f"{record_id}: evidence content excluded: {evidence_path}")
                    continue
                if line_start < 1 or line_end < line_start or line_end > max(1, len(lines)):
                    errors.append(f"{record_id}: evidence range out of bounds: {evidence_path}:{line_start}-{line_end}")
                    continue
                anchor = str(evidence.get("anchor", ""))
                cited = "\n".join(lines[line_start - 1:line_end])
                if not anchor or anchor not in cited:
                    errors.append(f"{record_id}: evidence anchor missing: {evidence_path}:{line_start}-{line_end}: {anchor!r}")
                    continue
                evidence["file_sha256"] = file_record["sha256"]
            records.append(record)
            all_records.append(record)
        expected[path] = render_jsonl(records)
    return expected, all_records, errors


def build_artifacts() -> tuple[dict[Path, bytes], dict[str, Any]]:
    paths, explicit_exclusions = discover_repository_paths()
    file_records, text_by_path, lines_by_path, content_exclusions = build_file_records(paths)
    python_symbols, python_edges, tests, python_errors, _ = index_python(text_by_path)
    text_symbols, text_edges, text_errors = index_textual_relations(text_by_path, file_records)
    symbols, symbol_conflicts = deduplicate_records([*python_symbols, *text_symbols])
    edges, edge_conflicts = deduplicate_records([*python_edges, *text_edges])
    tests, test_conflicts = deduplicate_records(tests)
    commits = collect_git_commits()
    refs, excluded_git_ref_count = collect_git_refs()
    path_history = collect_path_history()

    semantic_artifacts, semantic_records, semantic_errors = load_and_normalize_semantic(file_records, lines_by_path)
    parse_findings = sorted([*python_errors, *text_errors], key=lambda item: (item["path"], item["stage"]))

    all_node_ids = {record["id"] for record in file_records}
    all_node_ids.update(record["id"] for record in symbols)
    dangling_edges = sorted({
        edge["id"]
        for edge in edges
        if edge.get("target_id") and edge["target_id"] not in all_node_ids
    })
    source_ids_missing = sorted({edge["source_id"] for edge in edges if edge["source_id"] not in all_node_ids})

    index_artifacts = {
        INDEX_DIR / "files.jsonl": render_jsonl(file_records),
        INDEX_DIR / "symbols.jsonl": render_jsonl(symbols),
        INDEX_DIR / "edges.jsonl": render_jsonl(edges),
        INDEX_DIR / "tests.jsonl": render_jsonl(tests),
        INDEX_DIR / "git_commits.jsonl": render_jsonl(commits),
        INDEX_DIR / "git_refs.jsonl": render_jsonl(refs),
        INDEX_DIR / "path_history.jsonl": render_jsonl(path_history),
    }

    schema_path = GRAPH_DIR / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise ValueError("schema.json must contain an object")
    schema_record_count, schema_errors = validate_records_against_schema(schema, (
        ("files", file_records),
        ("symbols", symbols),
        ("edges", edges),
        ("tests", tests),
        ("git_commits", commits),
        ("git_refs", refs),
        ("path_history", path_history),
        ("semantic", semantic_records),
    ))
    semantic_reference_errors = validate_semantic_references(semantic_records, file_records)
    index_invariant_errors = validate_index_invariants(file_records, symbols, edges, tests, lines_by_path)
    redaction_errors = validate_symbol_redaction(symbols)
    safety_scan_artifacts = {
        **index_artifacts,
        **semantic_artifacts,
        GRAPH_DIR / "ENTRYPOINT.md": (GRAPH_DIR / "ENTRYPOINT.md").read_bytes(),
        GRAPH_DIR / "build_graph.py": Path(__file__).read_bytes(),
        GRAPH_DIR / "query_graph.py": (GRAPH_DIR / "query_graph.py").read_bytes(),
        schema_path: schema_path.read_bytes(),
    }
    sensitive_output_findings = find_sensitive_artifact_patterns(safety_scan_artifacts)

    source_tree_hash = hashlib.sha256()
    for record in sorted(file_records, key=lambda item: item["path"]):
        source_tree_hash.update(record["path"].encode("utf-8"))
        source_tree_hash.update(b"\0")
        source_tree_hash.update(record["sha256"].encode("ascii"))
        source_tree_hash.update(b"\n")
    source_tree_digest = source_tree_hash.hexdigest()

    branch = run_git(["branch", "--show-current"]).strip() or None
    head = run_git(["rev-parse", "HEAD"]).strip()
    semantic_hashes = {
        path.name: sha256_bytes(data)
        for path, data in sorted(semantic_artifacts.items(), key=lambda item: item[0].name)
    }
    index_hashes = {
        path.name: sha256_bytes(data)
        for path, data in sorted(index_artifacts.items(), key=lambda item: item[0].name)
    }
    tool_hashes = {
        "ENTRYPOINT.md": sha256_bytes((GRAPH_DIR / "ENTRYPOINT.md").read_bytes()),
        "build_graph.py": sha256_bytes(Path(__file__).read_bytes()),
        "query_graph.py": sha256_bytes((GRAPH_DIR / "query_graph.py").read_bytes()),
        "schema.json": sha256_bytes(schema_path.read_bytes()),
    }
    integrity_payload = {
        "branch": branch,
        "head": head,
        "index_hashes": index_hashes,
        "semantic_hashes": semantic_hashes,
        "source_tree_digest": source_tree_digest,
        "tool_hashes": tool_hashes,
    }
    graph_digest = sha256_bytes(compact_json(integrity_payload).encode("utf-8"))

    manifest = {
        "branch": branch,
        "content_exclusion_rules": [
            "logs_and_runtime_output",
            "binary_content",
            "files_over_2000000_bytes",
            "unknown_binary_types",
            "codex_repo_graph_self",
            "gitignored_paths",
            "local_codex_turn_diff_refs",
            "opaque_identifiers_and_literal_payloads",
        ],
        "excluded_git_ref_count": excluded_git_ref_count,
        "graph_digest": graph_digest,
        "graph_schema_version": SCHEMA_VERSION,
        "head": head,
        "index_hashes": index_hashes,
        "indexed_file_count": len(file_records),
        "metadata_only_file_count": sum(not record["content_indexed"] for record in file_records),
        "semantic_hashes": semantic_hashes,
        "source_tree_digest": source_tree_digest,
        "tool_hashes": tool_hashes,
    }

    duplicate_conflicts = {
        "edges": edge_conflicts,
        "symbols": symbol_conflicts,
        "tests": test_conflicts,
    }
    fatal_errors = [
        *semantic_errors,
        *semantic_reference_errors,
        *schema_errors,
        *index_invariant_errors,
        *redaction_errors,
        *[f"parse finding: {item['path']}:{item['stage']}: {item['error']}" for item in parse_findings],
        *[f"sensitive output: {value}" for value in sensitive_output_findings],
        *[f"dangling edge: {value}" for value in dangling_edges],
        *[f"edge source missing: {value}" for value in source_ids_missing],
        *[f"duplicate {kind} id: {value}" for kind, values in duplicate_conflicts.items() for value in values],
    ]
    validation = {
        "content_exclusions": content_exclusions,
        "counts": {
            "commits": len(commits),
            "edges": len(edges),
            "files": len(file_records),
            "git_refs": len(refs),
            "path_history": len(path_history),
            "semantic_records": len(semantic_records),
            "symbols": len(symbols),
            "tests": len(tests),
        },
        "dangling_edge_ids": dangling_edges,
        "duplicate_conflicts": duplicate_conflicts,
        "explicit_exclusions": explicit_exclusions,
        "excluded_git_refs": {
            "count": excluded_git_ref_count,
            "prefix": "refs/codex/turn-diffs/<redacted>",
        },
        "fatal_errors": fatal_errors,
        "index_hashes": index_hashes,
        "index_invariant_errors": index_invariant_errors,
        "parse_findings": parse_findings,
        "redaction_errors": redaction_errors,
        "represented_path_count": len(file_records),
        "schema_validation": {
            "error_count": len(schema_errors),
            "record_count": schema_record_count,
            "validator": "built_in_json_schema_subset",
        },
        "semantic_reference_errors": semantic_reference_errors,
        "sensitive_output_findings": sensitive_output_findings,
        "source_edge_ids_missing": source_ids_missing,
        "source_tree_digest": source_tree_digest,
        "status": "pass" if not fatal_errors else "fail",
        "unresolved_call_edge_count": sum(edge["edge_kind"] == "calls" and "target_ref" in edge for edge in edges),
    }

    artifacts: dict[Path, bytes] = {
        **index_artifacts,
        **semantic_artifacts,
        GRAPH_DIR / "manifest.json": render_json(manifest),
        VALIDATION_DIR / "report.json": render_json(validation),
    }
    return artifacts, validation


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def apply_or_check(artifacts: dict[Path, bytes], *, check: bool) -> list[str]:
    mismatches: list[str] = []
    for path, expected in sorted(artifacts.items(), key=lambda item: item[0].as_posix()):
        current = path.read_bytes() if path.exists() else None
        if current != expected:
            relative = path.relative_to(ROOT).as_posix()
            mismatches.append(relative)
            if not check:
                atomic_write(path, expected)
    expected_index_names = {path.name for path in artifacts if path.parent == INDEX_DIR}
    if INDEX_DIR.exists():
        for extra in sorted(INDEX_DIR.glob("*.jsonl")):
            if extra.name not in expected_index_names:
                mismatches.append(extra.relative_to(ROOT).as_posix())
                if not check:
                    extra.unlink()
    return sorted(set(mismatches))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if generated artifacts are stale")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        artifacts, validation = build_artifacts()
    except Exception as exc:
        print(compact_json({"error": f"{type(exc).__name__}: {exc}", "status": "build_error"}), file=sys.stderr)
        return 2
    mismatches = apply_or_check(artifacts, check=args.check)
    result = {
        "counts": validation["counts"],
        "fatal_error_count": len(validation["fatal_errors"]),
        "mismatches": mismatches,
        "mode": "check" if args.check else "write",
        "parse_finding_count": len(validation["parse_findings"]),
        "status": validation["status"],
    }
    print(compact_json(result))
    if validation["fatal_errors"]:
        for error in validation["fatal_errors"]:
            print(error, file=sys.stderr)
        return 1
    if args.check and mismatches:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
