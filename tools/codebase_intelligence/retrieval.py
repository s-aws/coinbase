"""Read-only retrieval helpers over a repository index."""

from __future__ import annotations

from collections import deque
from pathlib import Path
import re
from typing import Dict, List, Optional, Set

from tools.codebase_intelligence.models import FileRecord, RepositoryIndex, SymbolRecord


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class CodebaseRetrieval:
    """Constrained navigation API for small-model agents."""

    def __init__(self, index: RepositoryIndex) -> None:
        self.index = index

    def find_relevant_modules(self, query: str, limit: int = 10) -> List[Dict[str, object]]:
        tokens = _tokens(query)
        scored = []
        for file_record in self.index.modules():
            haystack = self._module_haystack(file_record).lower()
            score = sum(haystack.count(token) for token in tokens)
            if score:
                scored.append((score, file_record.path, file_record))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            {
                "path": item.path,
                "module": item.module,
                "domain_tags": item.domain_tags,
                "score": score,
                "symbols": item.symbol_ids[:20],
            }
            for score, _, item in scored[:limit]
        ]

    def summarize_file(self, path_or_module: str) -> Dict[str, object]:
        file_record = self._resolve_file(path_or_module)
        symbols = [self.index.symbols[symbol_id] for symbol_id in file_record.symbol_ids]
        return {
            "path": file_record.path,
            "module": file_record.module,
            "domain_tags": file_record.domain_tags,
            "docstring": file_record.docstring,
            "imports": [item.qualified_name for item in file_record.imports],
            "symbols": [_symbol_summary(symbol) for symbol in symbols],
            "test_symbols": file_record.test_symbol_ids,
        }

    def show_callable_signatures(self, query: str, limit: int = 50) -> List[Dict[str, object]]:
        matches = [
            symbol
            for symbol in self.index.resolve_symbols(query)
            if symbol.is_callable
        ]
        if not matches:
            lowered = query.lower()
            matches = [
                symbol
                for symbol in self.index.symbols.values()
                if symbol.is_callable
                and (lowered in symbol.module.lower() or lowered in symbol.path.lower())
            ]
        return [_symbol_summary(symbol) for symbol in matches[:limit]]

    def find_callsites(self, symbol_query: str, limit: int = 100) -> List[Dict[str, object]]:
        return [
            {
                "caller": call.caller,
                "callee": call.callee,
                "raw": call.raw,
                "path": call.path,
                "line": call.line,
            }
            for call in self.index.callsites_for_symbol(symbol_query)[:limit]
        ]

    def show_tests_for_symbol(self, symbol_query: str, limit: int = 100) -> List[Dict[str, object]]:
        return [
            {
                "test": call.caller,
                "callee": call.callee,
                "path": call.path,
                "line": call.line,
            }
            for call in self.index.tests_for_symbol(symbol_query)[:limit]
        ]

    def explain_dependency_chain(self, source: str, target: str) -> Dict[str, object]:
        source_module = self._resolve_module_name(source)
        target_module = self._resolve_module_name(target)
        if not source_module or not target_module:
            return {"found": False, "chain": [], "reason": "source_or_target_not_found"}
        graph = self._module_graph()
        chain = _shortest_path(graph, source_module, target_module)
        return {"found": bool(chain), "chain": chain}

    def _module_haystack(self, file_record: FileRecord) -> str:
        symbol_text = []
        for symbol_id in file_record.symbol_ids:
            symbol = self.index.symbols[symbol_id]
            symbol_text.extend([symbol.id, symbol.signature, symbol.docstring or ""])
        import_text = [item.qualified_name for item in file_record.imports]
        return " ".join(
            [
                file_record.path,
                file_record.module,
                file_record.docstring or "",
                " ".join(file_record.domain_tags),
                " ".join(import_text),
                " ".join(symbol_text),
            ]
        )

    def _resolve_file(self, path_or_module: str) -> FileRecord:
        normalized = path_or_module.replace("\\", "/").strip()
        if normalized in self.index.files:
            return self.index.files[normalized]
        for file_record in self.index.files.values():
            if file_record.module == normalized or file_record.path.endswith(normalized):
                return file_record
        path_module = Path(normalized).with_suffix("").as_posix().replace("/", ".")
        for file_record in self.index.files.values():
            if file_record.module == path_module:
                return file_record
        raise KeyError(f"unknown file or module: {path_or_module}")

    def _resolve_module_name(self, query: str) -> Optional[str]:
        normalized = query.replace("\\", "/").strip()
        if normalized in self.index.files:
            return self.index.files[normalized].module
        for file_record in self.index.files.values():
            if file_record.module == normalized or file_record.path.endswith(normalized):
                return file_record.module
        symbols = self.index.resolve_symbols(query)
        if symbols:
            return symbols[0].module
        return None

    def _module_graph(self) -> Dict[str, Set[str]]:
        known_modules = {file_record.module for file_record in self.index.files.values()}
        graph: Dict[str, Set[str]] = {module: set() for module in known_modules}

        for file_record in self.index.files.values():
            for item in file_record.imports:
                imported = _nearest_known_module(item.qualified_name, known_modules)
                if imported and imported != file_record.module:
                    graph[file_record.module].add(imported)

        for call in self.index.callsites:
            callee_module = _module_for_symbol_id(call.callee, self.index)
            if callee_module and callee_module != call.module:
                graph.setdefault(call.module, set()).add(callee_module)
        return graph


def _tokens(query: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(query) if token]


def _symbol_summary(symbol: SymbolRecord) -> Dict[str, object]:
    return {
        "id": symbol.id,
        "kind": symbol.kind.value,
        "signature": symbol.signature,
        "path": symbol.path,
        "line": symbol.line,
        "docstring": symbol.docstring,
        "domain_tags": symbol.domain_tags,
        "danger_flags": [flag.value for flag in symbol.danger_flags],
    }


def _nearest_known_module(qualified_name: str, known_modules: Set[str]) -> Optional[str]:
    parts = qualified_name.strip(".").split(".")
    for length in range(len(parts), 0, -1):
        candidate = ".".join(parts[:length])
        if candidate in known_modules:
            return candidate
    return None


def _module_for_symbol_id(symbol_id: str, index: RepositoryIndex) -> Optional[str]:
    symbol = index.symbols.get(symbol_id)
    if symbol:
        return symbol.module
    for candidate in index.symbols.values():
        if symbol_id == candidate.name or symbol_id.endswith(f".{candidate.qualname}"):
            return candidate.module
    return None


def _shortest_path(graph: Dict[str, Set[str]], source: str, target: str) -> List[str]:
    queue = deque([(source, [source])])
    visited = {source}
    while queue:
        node, path = queue.popleft()
        if node == target:
            return path
        for neighbor in sorted(graph.get(node, set())):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((neighbor, [*path, neighbor]))
    return []
