"""AST-based static repository indexer."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from tools.codebase_intelligence.models import (
    ArgumentRecord,
    CallSiteRecord,
    DangerFlag,
    FileRecord,
    ImportRecord,
    RepositoryIndex,
    SymbolKind,
    SymbolRecord,
)


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coinbase_engine.egg-info",
    "dist",
    "genai_tools",
    "htmlcov",
}

MUTATING_NAME_RE = re.compile(
    r"(write|delete|remove|drop|create|update|insert|save|persist|commit|"
    r"rollback|set|clear|mutate|patch|post|put|send|start|stop|shutdown|"
    r"run|execute|move|cancel|place|reprice|adopt|backfill|initialize|sync)",
    re.IGNORECASE,
)
PAYMENT_TRADING_RE = re.compile(
    r"(payment|charge|trade|trading|order|fill|portfolio|wallet|buy|sell)",
    re.IGNORECASE,
)
NETWORK_WRITE_RE = re.compile(
    r"(connect|subscribe|unsubscribe|request|session|websocket|rest|api|client)",
    re.IGNORECASE,
)
AUTH_CREDENTIAL_RE = re.compile(
    r"(auth|token|secret|credential|key|password|session|sign)",
    re.IGNORECASE,
)
AMBIGUOUS_PARAMETER_NAMES = {
    "body",
    "client",
    "config",
    "conn",
    "cursor",
    "data",
    "db",
    "message",
    "options",
    "params",
    "payload",
    "request",
    "session",
}


def build_repository_index(
    root: str | Path,
    *,
    paths: Optional[Iterable[str | Path]] = None,
    tracked_only: bool = False,
    excluded_dirs: Optional[Set[str]] = None,
) -> RepositoryIndex:
    """Build a static index by parsing Python files without importing them."""

    root_path = Path(root).resolve()
    exclusions = set(DEFAULT_EXCLUDED_DIRS if excluded_dirs is None else excluded_dirs)
    python_files = list(
        _iter_python_files(root_path, paths=paths, tracked_only=tracked_only, excluded_dirs=exclusions)
    )
    ownership = _load_ownership(root_path)

    index = RepositoryIndex(
        root=str(root_path),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    for file_path in sorted(python_files):
        relative_path = _relative_path(root_path, file_path)
        module = _module_name(relative_path)
        domain_tags = _owners_for(relative_path, ownership)
        source = file_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(file_path))
        scanner = _ModuleScanner(
            module=module,
            relative_path=relative_path,
            domain_tags=domain_tags,
            is_test_file=_is_test_path(relative_path),
        )
        file_record = scanner.scan(tree)
        index.files[relative_path] = file_record
        for symbol in scanner.symbols:
            index.symbols[symbol.id] = symbol
        index.callsites.extend(scanner.callsites)

    return index


def _iter_python_files(
    root: Path,
    *,
    paths: Optional[Iterable[str | Path]],
    tracked_only: bool,
    excluded_dirs: Set[str],
) -> Iterable[Path]:
    if paths is not None:
        for item in paths:
            path = Path(item)
            yield path if path.is_absolute() else root / path
        return

    if tracked_only:
        for relative in _git_tracked_python_files(root):
            path = root / relative
            if path.exists() and not _is_excluded(path, root, excluded_dirs):
                yield path
        return

    for path in root.rglob("*.py"):
        if not _is_excluded(path, root, excluded_dirs):
            yield path


def _git_tracked_python_files(root: Path) -> List[Path]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "*.py"],
            cwd=root,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []
    return [Path(line.strip()) for line in proc.stdout.splitlines() if line.strip()]


def _is_excluded(path: Path, root: Path, excluded_dirs: Set[str]) -> bool:
    relative_parts = path.resolve().relative_to(root).parts
    return any(part in excluded_dirs for part in relative_parts)


def _relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _module_name(relative_path: str) -> str:
    path = Path(relative_path)
    without_suffix = path.with_suffix("")
    parts = list(without_suffix.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return normalized.startswith("tests/") or name.startswith("test_")


def _load_ownership(root: Path) -> Optional[Dict[str, object]]:
    manifest = root / ".agents" / "ownership.yaml"
    if not manifest.exists():
        return None
    try:
        from tools.check_ownership import _parse_manifest

        return _parse_manifest(manifest)
    except Exception:
        return None


def _owners_for(relative_path: str, ownership: Optional[Dict[str, object]]) -> List[str]:
    if not ownership:
        return []
    try:
        from tools.check_ownership import owners_for_file

        return owners_for_file(relative_path, ownership)  # type: ignore[arg-type]
    except Exception:
        return []


class _ModuleScanner(ast.NodeVisitor):
    def __init__(
        self,
        *,
        module: str,
        relative_path: str,
        domain_tags: List[str],
        is_test_file: bool,
    ) -> None:
        self.module = module
        self.relative_path = relative_path
        self.domain_tags = domain_tags
        self.is_test_file = is_test_file
        self.imports: List[ImportRecord] = []
        self.import_aliases: Dict[str, str] = {}
        self.symbols: List[SymbolRecord] = []
        self.callsites: List[CallSiteRecord] = []
        self.symbol_ids: List[str] = []
        self.test_symbol_ids: List[str] = []
        self.class_stack: List[str] = []
        self.function_stack: List[str] = []
        self.local_callable_names: Set[str] = set()

    def scan(self, tree: ast.Module) -> FileRecord:
        self._collect_imports(tree)
        self._collect_local_names(tree)
        self.visit(tree)
        return FileRecord(
            path=self.relative_path,
            module=self.module,
            domain_tags=self.domain_tags,
            docstring=ast.get_docstring(tree),
            imports=self.imports,
            symbol_ids=self.symbol_ids,
            test_symbol_ids=self.test_symbol_ids,
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        is_public_top_level = not self.class_stack and not self.function_stack and _is_public(node.name)
        if is_public_top_level:
            symbol = self._class_symbol(node)
            self.symbols.append(symbol)
            self.symbol_ids.append(symbol.id)
            if symbol.is_test:
                self.test_symbol_ids.append(symbol.id)

        self.class_stack.append(node.name)
        for item in node.body:
            self.visit(item)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def visit_Call(self, node: ast.Call) -> None:
        raw = _safe_unparse(node.func)
        callee = self._resolve_callee(node.func, raw)
        self.callsites.append(
            CallSiteRecord(
                caller=self._current_caller(),
                callee=callee,
                raw=raw,
                module=self.module,
                path=self.relative_path,
                line=node.lineno,
            )
        )
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool) -> None:
        is_top_level = not self.class_stack and not self.function_stack
        is_method = bool(self.class_stack) and not self.function_stack
        is_public = _is_public(node.name)
        if (is_top_level or is_method) and is_public:
            symbol = self._function_symbol(node, is_async=is_async, is_method=is_method)
            self.symbols.append(symbol)
            self.symbol_ids.append(symbol.id)
            if symbol.is_test:
                self.test_symbol_ids.append(symbol.id)

        self.function_stack.append(node.name)
        for item in node.body:
            self.visit(item)
        self.function_stack.pop()

    def _collect_imports(self, tree: ast.Module) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".", 1)[0]
                    self.import_aliases[local] = alias.name
                    self.imports.append(
                        ImportRecord(
                            module=alias.name,
                            name=None,
                            alias=alias.asname,
                            level=0,
                            line=node.lineno,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                module = "." * node.level + (node.module or "")
                for alias in node.names:
                    local = alias.asname or alias.name
                    target = f"{module}.{alias.name}" if module else alias.name
                    self.import_aliases[local] = target
                    self.imports.append(
                        ImportRecord(
                            module=module,
                            name=alias.name,
                            alias=alias.asname,
                            level=node.level,
                            line=node.lineno,
                        )
                    )

    def _collect_local_names(self, tree: ast.Module) -> None:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(node.name):
                self.local_callable_names.add(node.name)
            elif isinstance(node, ast.ClassDef) and _is_public(node.name):
                self.local_callable_names.add(node.name)
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_public(item.name):
                        self.local_callable_names.add(f"{node.name}.{item.name}")

    def _class_symbol(self, node: ast.ClassDef) -> SymbolRecord:
        qualname = node.name
        init_node = _find_init(node)
        signature = "()"
        arguments: List[ArgumentRecord] = []
        has_type_hints = False
        has_var_kwargs = False
        if init_node is not None:
            arguments = _argument_records(init_node.args)
            signature = _format_signature(init_node, drop_first=True)
            has_type_hints = _has_complete_type_hints(init_node, drop_first=True)
            has_var_kwargs = init_node.args.kwarg is not None
        symbol = SymbolRecord(
            id=f"{self.module}.{qualname}",
            module=self.module,
            qualname=qualname,
            name=node.name,
            kind=SymbolKind.CLASS,
            path=self.relative_path,
            line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=signature,
            docstring=ast.get_docstring(node),
            decorators=[_safe_unparse(item) for item in node.decorator_list],
            arguments=arguments,
            is_test=self.is_test_file and node.name.startswith("Test"),
            domain_tags=self.domain_tags,
            has_type_hints=has_type_hints,
            has_var_kwargs=has_var_kwargs,
            danger_flags=_danger_flags(node.name, arguments, has_type_hints, has_var_kwargs),
        )
        return symbol

    def _function_symbol(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        is_async: bool,
        is_method: bool,
    ) -> SymbolRecord:
        qualname_parts = [*self.class_stack, node.name]
        qualname = ".".join(qualname_parts)
        arguments = _argument_records(node.args)
        has_type_hints = _has_complete_type_hints(node, drop_first=is_method)
        has_var_kwargs = node.args.kwarg is not None
        return SymbolRecord(
            id=f"{self.module}.{qualname}",
            module=self.module,
            qualname=qualname,
            name=node.name,
            kind=SymbolKind.METHOD if is_method else SymbolKind.FUNCTION,
            path=self.relative_path,
            line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
            signature=_format_signature(node),
            docstring=ast.get_docstring(node),
            decorators=[_safe_unparse(item) for item in node.decorator_list],
            arguments=arguments,
            returns=_safe_unparse(node.returns) if node.returns else None,
            is_async=is_async,
            is_test=self.is_test_file and node.name.startswith("test_"),
            domain_tags=self.domain_tags,
            has_type_hints=has_type_hints,
            has_var_kwargs=has_var_kwargs,
            danger_flags=_danger_flags(node.name, arguments, has_type_hints, has_var_kwargs),
        )

    def _current_caller(self) -> str:
        if self.function_stack:
            qualname = ".".join([*self.class_stack, *self.function_stack])
            return f"{self.module}.{qualname}"
        if self.class_stack:
            return f"{self.module}.{'.'.join(self.class_stack)}"
        return self.module

    def _resolve_callee(self, node: ast.AST, raw: str) -> str:
        if isinstance(node, ast.Name):
            if node.id in self.import_aliases:
                return self.import_aliases[node.id]
            if node.id in self.local_callable_names:
                return f"{self.module}.{node.id}"
            return node.id

        parts = _attribute_parts(node)
        if not parts:
            return raw
        if parts[0] in {"self", "cls"} and self.class_stack:
            local = ".".join([self.class_stack[-1], *parts[1:]])
            return f"{self.module}.{local}"
        if parts[0] in self.import_aliases:
            return ".".join([self.import_aliases[parts[0]], *parts[1:]])
        return ".".join(parts)


def _find_init(node: ast.ClassDef) -> Optional[ast.FunctionDef]:
    for item in node.body:
        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
            return item
    return None


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _safe_unparse(node: Optional[ast.AST]) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _attribute_parts(node: ast.AST) -> List[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [*_attribute_parts(node.value), node.attr]
    return []


def _argument_records(args: ast.arguments) -> List[ArgumentRecord]:
    records: List[ArgumentRecord] = []
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    posonly_names = {id(arg) for arg in args.posonlyargs}
    for arg, default in zip(positional, defaults):
        records.append(
            ArgumentRecord(
                name=arg.arg,
                annotation=_safe_unparse(arg.annotation) if arg.annotation else None,
                default=_safe_unparse(default) if default else None,
                kind="positional_only" if id(arg) in posonly_names else "positional_or_keyword",
            )
        )
    if args.vararg:
        records.append(
            ArgumentRecord(
                name=args.vararg.arg,
                annotation=_safe_unparse(args.vararg.annotation) if args.vararg.annotation else None,
                default=None,
                kind="var_positional",
            )
        )
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        records.append(
            ArgumentRecord(
                name=arg.arg,
                annotation=_safe_unparse(arg.annotation) if arg.annotation else None,
                default=_safe_unparse(default) if default else None,
                kind="keyword_only",
            )
        )
    if args.kwarg:
        records.append(
            ArgumentRecord(
                name=args.kwarg.arg,
                annotation=_safe_unparse(args.kwarg.annotation) if args.kwarg.annotation else None,
                default=None,
                kind="var_keyword",
            )
        )
    return records


def _format_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    drop_first: bool = False,
) -> str:
    records = _argument_records(node.args)
    if drop_first and records:
        records = records[1:]
    parts: List[str] = []
    inserted_kw_marker = False
    for record in records:
        if record.kind == "keyword_only" and not inserted_kw_marker:
            if not any(part.startswith("*") for part in parts):
                parts.append("*")
            inserted_kw_marker = True
        parts.append(_format_argument(record))
    signature = f"({', '.join(parts)})"
    if node.returns:
        signature = f"{signature} -> {_safe_unparse(node.returns)}"
    return signature


def _format_argument(record: ArgumentRecord) -> str:
    prefix = ""
    if record.kind == "var_positional":
        prefix = "*"
    elif record.kind == "var_keyword":
        prefix = "**"
    text = f"{prefix}{record.name}"
    if record.annotation:
        text = f"{text}: {record.annotation}"
    if record.default:
        text = f"{text} = {record.default}"
    return text


def _has_complete_type_hints(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    drop_first: bool = False,
) -> bool:
    records = _argument_records(node.args)
    if drop_first and records:
        records = records[1:]
    normal_args = [
        record
        for record in records
        if record.name not in {"self", "cls"}
        and record.kind not in {"var_positional", "var_keyword"}
    ]
    if any(record.annotation is None for record in normal_args):
        return False
    if node.args.vararg is not None or node.args.kwarg is not None:
        return False
    return node.returns is not None


def _danger_flags(
    name: str,
    arguments: Sequence[ArgumentRecord],
    has_type_hints: bool,
    has_var_kwargs: bool,
) -> List[DangerFlag]:
    flags: List[DangerFlag] = []
    if not _is_public(name):
        flags.append(DangerFlag.PRIVATE)
    if MUTATING_NAME_RE.search(name):
        flags.append(DangerFlag.MUTATING_NAME)
    if PAYMENT_TRADING_RE.search(name):
        flags.append(DangerFlag.PAYMENT_OR_TRADING)
    if NETWORK_WRITE_RE.search(name):
        flags.append(DangerFlag.NETWORK_WRITE)
    if AUTH_CREDENTIAL_RE.search(name):
        flags.append(DangerFlag.AUTH_OR_CREDENTIAL)
    if not has_type_hints:
        flags.append(DangerFlag.MISSING_TYPE_HINTS)
    if has_var_kwargs:
        flags.append(DangerFlag.BROAD_KWARGS)
    if any(_is_ambiguous_argument(argument) for argument in arguments):
        flags.append(DangerFlag.AMBIGUOUS_PARAMETER)
    return flags


def _is_ambiguous_argument(argument: ArgumentRecord) -> bool:
    if argument.name in {"self", "cls"}:
        return False
    lowered = argument.name.lower()
    if lowered in AMBIGUOUS_PARAMETER_NAMES:
        return True
    if argument.annotation in {None, "Any", "object", "dict", "Dict", "Mapping"}:
        return True
    return False
