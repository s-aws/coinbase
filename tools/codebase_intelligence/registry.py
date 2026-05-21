"""Safe tool registry for index retrieval and explicit read-only bindings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import inspect
from typing import Dict, Iterable, List, Optional

from tools.codebase_intelligence.models import DangerFlag, RepositoryIndex, SymbolKind, SymbolRecord
from tools.codebase_intelligence.retrieval import CodebaseRetrieval


class UnsafeBindingError(ValueError):
    """Raised when code attempts to expose an unsafe executable binding."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    read_only: bool
    executable: bool
    symbol_id: Optional[str] = None


class ToolRegistry:
    """Default-deny registry for small-model codebase access.

    Retrieval tools are broad and read-only. Executable bindings require both:
    1. a ``@codebase_tool`` or ``@codebase_read_tool`` marker, and
    2. an explicit symbol allowlist entry.
    """

    def __init__(
        self,
        index: RepositoryIndex,
        *,
        executable_allowlist: Optional[Iterable[str]] = None,
    ) -> None:
        self.index = index
        self.retrieval = CodebaseRetrieval(index)
        self.executable_allowlist = set(executable_allowlist or [])
        self._tools: Dict[str, Callable[..., object]] = {}
        self._specs: Dict[str, ToolSpec] = {}
        self._register_retrieval_tools()

    def list_tools(self, *, include_executable: bool = True) -> List[ToolSpec]:
        specs = list(self._specs.values())
        if include_executable:
            return sorted(specs, key=lambda item: item.name)
        return sorted([spec for spec in specs if not spec.executable], key=lambda item: item.name)

    def call_tool(self, tool_name: str, **kwargs: object) -> object:
        try:
            tool = self._tools[tool_name]
        except KeyError as exc:
            raise KeyError(f"unknown codebase tool: {tool_name}") from exc
        return tool(**kwargs)

    def register_callable(
        self,
        func: Callable[..., object],
        *,
        symbol_id: Optional[str] = None,
    ) -> ToolSpec:
        resolved_symbol_id = symbol_id or _callable_symbol_id(func)
        symbol = self.index.symbols.get(resolved_symbol_id)
        if symbol is None:
            raise UnsafeBindingError(f"symbol is not present in static index: {resolved_symbol_id}")

        violations = binding_violations(symbol, allowlist=self.executable_allowlist)
        if not getattr(func, "__codebase_tool__", False):
            violations.append(DangerFlag.NOT_ALLOWLISTED)
        if not getattr(func, "__codebase_tool_read_only__", False):
            violations.append(DangerFlag.NOT_READ_ONLY)
        if resolved_symbol_id not in self.executable_allowlist:
            violations.append(DangerFlag.NOT_ALLOWLISTED)
        if violations:
            details = ", ".join(sorted({flag.value for flag in violations}))
            raise UnsafeBindingError(f"unsafe executable binding {resolved_symbol_id}: {details}")

        tool_name = str(getattr(func, "__codebase_tool_name__", func.__name__))
        description = str(getattr(func, "__codebase_tool_description__", ""))
        spec = ToolSpec(
            name=tool_name,
            description=description,
            read_only=True,
            executable=True,
            symbol_id=resolved_symbol_id,
        )
        self._tools[tool_name] = func
        self._specs[tool_name] = spec
        return spec

    def _register_retrieval_tools(self) -> None:
        self._add_retrieval(
            "find_relevant_modules",
            "Find modules whose paths, symbols, imports, docs, or owner tags match a query.",
            self.retrieval.find_relevant_modules,
        )
        self._add_retrieval(
            "summarize_file",
            "Summarize a file or module from the static index.",
            self.retrieval.summarize_file,
        )
        self._add_retrieval(
            "show_callable_signatures",
            "Show public callable signatures matching a symbol, file, or module query.",
            self.retrieval.show_callable_signatures,
        )
        self._add_retrieval(
            "find_callsites",
            "Find static callsites for a symbol query.",
            self.retrieval.find_callsites,
        )
        self._add_retrieval(
            "show_tests_for_symbol",
            "Find tests that statically call a symbol.",
            self.retrieval.show_tests_for_symbol,
        )
        self._add_retrieval(
            "explain_dependency_chain",
            "Explain a shortest static import/call dependency chain between modules or symbols.",
            self.retrieval.explain_dependency_chain,
        )

    def _add_retrieval(
        self,
        name: str,
        description: str,
        func: Callable[..., object],
    ) -> None:
        self._tools[name] = func
        self._specs[name] = ToolSpec(
            name=name,
            description=description,
            read_only=True,
            executable=False,
        )


def binding_violations(
    symbol: SymbolRecord,
    *,
    allowlist: Iterable[str],
) -> List[DangerFlag]:
    violations: List[DangerFlag] = []
    if symbol.id not in set(allowlist):
        violations.append(DangerFlag.NOT_ALLOWLISTED)
    if symbol.kind != SymbolKind.FUNCTION:
        violations.append(DangerFlag.AMBIGUOUS_PARAMETER)
    if symbol.danger_flags:
        violations.extend(symbol.danger_flags)
    if not _decorator_allows_binding(symbol):
        violations.append(DangerFlag.NOT_ALLOWLISTED)
    return violations


def generate_callable_binding_specs(
    index: RepositoryIndex,
    *,
    allowlist: Iterable[str],
) -> List[ToolSpec]:
    """Generate safe executable binding specs without importing modules."""

    allowed = set(allowlist)
    specs: List[ToolSpec] = []
    for symbol_id in sorted(allowed):
        symbol = index.symbols.get(symbol_id)
        if symbol is None:
            continue
        if binding_violations(symbol, allowlist=allowed):
            continue
        specs.append(
            ToolSpec(
                name=symbol.name,
                description=symbol.docstring or "",
                read_only=True,
                executable=True,
                symbol_id=symbol.id,
            )
        )
    return specs


def _decorator_allows_binding(symbol: SymbolRecord) -> bool:
    for decorator in symbol.decorators:
        name = decorator.split("(", 1)[0]
        if name in {"codebase_tool", "codebase_read_tool"}:
            return True
        if name.endswith(".codebase_tool") or name.endswith(".codebase_read_tool"):
            return True
    return False


def _callable_symbol_id(func: Callable[..., object]) -> str:
    module = inspect.getmodule(func)
    module_name = module.__name__ if module else getattr(func, "__module__", "")
    return f"{module_name}.{func.__qualname__}"
