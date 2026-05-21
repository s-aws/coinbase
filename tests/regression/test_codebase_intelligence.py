import importlib
import shutil
import sys
from uuid import uuid4

import pytest

from tools.codebase_intelligence.indexer import build_repository_index
from tools.codebase_intelligence.registry import (
    ToolRegistry,
    UnsafeBindingError,
    generate_callable_binding_specs,
)


def test_ast_index_extracts_public_symbols_signatures_imports_callsites_and_tests(project_root):
    tmp_path = _workspace_tmp(project_root)
    package = tmp_path / "pkg"
    tests = tmp_path / "tests"
    try:
        package.mkdir()
        tests.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "helpers.py").write_text(
            """
def normalize(value: int) -> int:
    return value
""",
            encoding="utf-8",
        )
        (package / "service.py").write_text(
            '''
import math
from pathlib import Path
from pkg.helpers import normalize as norm


class Widget:
    """Widget docs."""

    def __init__(self, name: str, size: int = 1) -> None:
        self.name = name
        self.size = size

    def measure(self, value: int, *, scale: float = 1.0) -> float:
        return compute(norm(value)) * scale


def compute(value: int) -> float:
    """Compute docs."""
    return math.sqrt(value)


def _private(secret: str) -> str:
    return secret
''',
            encoding="utf-8",
        )
        (tests / "test_service.py").write_text(
            """
from pkg.service import Widget, compute


def test_compute() -> None:
    assert compute(4) == 2.0
    assert Widget("a").measure(9, scale=1.0) == 3.0
""",
            encoding="utf-8",
        )

        index = build_repository_index(tmp_path)

        assert "pkg.service.compute" in index.symbols
        assert "pkg.service.Widget" in index.symbols
        assert "pkg.service.Widget.measure" in index.symbols
        assert "pkg.service._private" not in index.symbols

        compute = index.symbols["pkg.service.compute"]
        assert compute.signature == "(value: int) -> float"
        assert compute.docstring == "Compute docs."
        assert compute.has_type_hints is True

        measure = index.symbols["pkg.service.Widget.measure"]
        assert measure.signature == "(self, value: int, *, scale: float = 1.0) -> float"

        imports = {
            item.qualified_name
            for item in index.files["pkg/service.py"].imports
        }
        assert {"math", "pathlib.Path", "pkg.helpers.normalize"}.issubset(imports)

        calls = {(call.caller, call.callee) for call in index.callsites}
        assert ("pkg.service.Widget.measure", "pkg.service.compute") in calls
        assert ("tests.test_service.test_compute", "pkg.service.compute") in calls

        registry = ToolRegistry(index)
        tests_for_compute = registry.call_tool(
            "show_tests_for_symbol",
            symbol_query="pkg.service.compute",
        )
        assert tests_for_compute[0]["test"] == "tests.test_service.test_compute"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_executable_bindings_are_default_deny_and_static_safety_filtered(project_root):
    tmp_path = _workspace_tmp(project_root)
    try:
        (tmp_path / "sample_tools.py").write_text(
            '''
from tools.codebase_intelligence.decorators import codebase_read_tool


@codebase_read_tool(description="Inspect a named schema.")
def inspect_schema(name: str) -> str:
    """Read-only schema inspection."""
    return name.upper()


@codebase_read_tool()
def write_schema(name: str) -> str:
    return name


@codebase_read_tool()
def loose(payload: dict) -> dict:
    return payload


@codebase_read_tool()
def broad(name: str, **kwargs: str) -> str:
    return name


def undecorated(name: str) -> str:
    return name
''',
            encoding="utf-8",
        )
        index = build_repository_index(tmp_path)
        allowlist = {
            "sample_tools.inspect_schema",
            "sample_tools.write_schema",
            "sample_tools.loose",
            "sample_tools.broad",
            "sample_tools.undecorated",
        }

        specs = generate_callable_binding_specs(index, allowlist=allowlist)
        assert [spec.symbol_id for spec in specs] == ["sample_tools.inspect_schema"]

        sys.path.insert(0, str(tmp_path))
        module = importlib.import_module("sample_tools")

        registry = ToolRegistry(index)
        with pytest.raises(UnsafeBindingError):
            registry.register_callable(module.inspect_schema)

        registry = ToolRegistry(index, executable_allowlist={"sample_tools.inspect_schema"})
        spec = registry.register_callable(module.inspect_schema)
        assert spec.name == "inspect_schema"
        assert registry.call_tool("inspect_schema", name="orders") == "ORDERS"

        with pytest.raises(UnsafeBindingError):
            registry.register_callable(module.undecorated)
        with pytest.raises(UnsafeBindingError):
            registry.register_callable(module.write_schema)
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        sys.modules.pop("sample_tools", None)
        shutil.rmtree(tmp_path, ignore_errors=True)


def _workspace_tmp(project_root):
    root = project_root / "tests" / ".tmp_codebase_intelligence" / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root
