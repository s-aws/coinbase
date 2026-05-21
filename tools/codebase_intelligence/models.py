"""Data models for the static repository index."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class SymbolKind(str, Enum):
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"


class DangerFlag(str, Enum):
    PRIVATE = "private"
    MUTATING_NAME = "mutating_name"
    PAYMENT_OR_TRADING = "payment_or_trading"
    NETWORK_WRITE = "network_write"
    AUTH_OR_CREDENTIAL = "auth_or_credential"
    MISSING_TYPE_HINTS = "missing_type_hints"
    BROAD_KWARGS = "broad_kwargs"
    AMBIGUOUS_PARAMETER = "ambiguous_parameter"
    NOT_ALLOWLISTED = "not_allowlisted"
    NOT_READ_ONLY = "not_read_only"


@dataclass(frozen=True)
class ImportRecord:
    module: str
    name: Optional[str]
    alias: Optional[str]
    level: int
    line: int

    @property
    def qualified_name(self) -> str:
        if self.name:
            return f"{self.module}.{self.name}" if self.module else self.name
        return self.module


@dataclass(frozen=True)
class ArgumentRecord:
    name: str
    annotation: Optional[str]
    default: Optional[str]
    kind: str


@dataclass(frozen=True)
class SymbolRecord:
    id: str
    module: str
    qualname: str
    name: str
    kind: SymbolKind
    path: str
    line: int
    end_line: int
    signature: str
    docstring: Optional[str]
    decorators: List[str] = field(default_factory=list)
    arguments: List[ArgumentRecord] = field(default_factory=list)
    returns: Optional[str] = None
    is_async: bool = False
    is_test: bool = False
    domain_tags: List[str] = field(default_factory=list)
    has_type_hints: bool = False
    has_var_kwargs: bool = False
    danger_flags: List[DangerFlag] = field(default_factory=list)

    @property
    def is_callable(self) -> bool:
        return self.kind in {SymbolKind.FUNCTION, SymbolKind.METHOD}


@dataclass(frozen=True)
class CallSiteRecord:
    caller: str
    callee: str
    raw: str
    module: str
    path: str
    line: int


@dataclass(frozen=True)
class FileRecord:
    path: str
    module: str
    domain_tags: List[str]
    docstring: Optional[str]
    imports: List[ImportRecord] = field(default_factory=list)
    symbol_ids: List[str] = field(default_factory=list)
    test_symbol_ids: List[str] = field(default_factory=list)


@dataclass
class RepositoryIndex:
    root: str
    generated_at: str
    files: Dict[str, FileRecord] = field(default_factory=dict)
    symbols: Dict[str, SymbolRecord] = field(default_factory=dict)
    callsites: List[CallSiteRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for symbol in data["symbols"].values():
            symbol["kind"] = _enum_value(symbol["kind"])
            symbol["danger_flags"] = [_enum_value(flag) for flag in symbol["danger_flags"]]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryIndex":
        files = {
            path: FileRecord(
                path=record["path"],
                module=record["module"],
                domain_tags=list(record.get("domain_tags", [])),
                docstring=record.get("docstring"),
                imports=[ImportRecord(**item) for item in record.get("imports", [])],
                symbol_ids=list(record.get("symbol_ids", [])),
                test_symbol_ids=list(record.get("test_symbol_ids", [])),
            )
            for path, record in data.get("files", {}).items()
        }
        symbols = {
            symbol_id: SymbolRecord(
                id=record["id"],
                module=record["module"],
                qualname=record["qualname"],
                name=record["name"],
                kind=SymbolKind(record["kind"]),
                path=record["path"],
                line=int(record["line"]),
                end_line=int(record["end_line"]),
                signature=record["signature"],
                docstring=record.get("docstring"),
                decorators=list(record.get("decorators", [])),
                arguments=[ArgumentRecord(**item) for item in record.get("arguments", [])],
                returns=record.get("returns"),
                is_async=bool(record.get("is_async", False)),
                is_test=bool(record.get("is_test", False)),
                domain_tags=list(record.get("domain_tags", [])),
                has_type_hints=bool(record.get("has_type_hints", False)),
                has_var_kwargs=bool(record.get("has_var_kwargs", False)),
                danger_flags=[
                    DangerFlag(flag) for flag in record.get("danger_flags", [])
                ],
            )
            for symbol_id, record in data.get("symbols", {}).items()
        }
        callsites = [CallSiteRecord(**record) for record in data.get("callsites", [])]
        return cls(
            root=data["root"],
            generated_at=data["generated_at"],
            files=files,
            symbols=symbols,
            callsites=callsites,
        )

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "RepositoryIndex":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def resolve_symbols(self, query: str) -> List[SymbolRecord]:
        normalized = query.strip()
        if not normalized:
            return []
        lowered = normalized.lower()
        exact = self.symbols.get(normalized)
        if exact:
            return [exact]
        matches = [
            symbol
            for symbol in self.symbols.values()
            if lowered in symbol.id.lower()
            or lowered == symbol.name.lower()
            or lowered == symbol.qualname.lower()
        ]
        return sorted(matches, key=lambda item: (len(item.id), item.id))

    def callsites_for_symbol(self, query: str) -> List[CallSiteRecord]:
        symbols = self.resolve_symbols(query)
        targets = {symbol.id for symbol in symbols}
        targets.update(symbol.name for symbol in symbols)
        if not targets and query:
            targets.add(query)
        return [
            call
            for call in self.callsites
            if _call_matches_any_target(call.callee, targets)
        ]

    def tests_for_symbol(self, query: str) -> List[CallSiteRecord]:
        return [
            call
            for call in self.callsites_for_symbol(query)
            if _is_test_path(call.path)
        ]

    def modules(self) -> Iterable[FileRecord]:
        return self.files.values()


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _call_matches_any_target(callee: str, targets: Iterable[str]) -> bool:
    for target in targets:
        if callee == target or callee.endswith(f".{target}"):
            return True
    return False


def _is_test_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    return normalized.startswith("tests/") or name.startswith("test_")
