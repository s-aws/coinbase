"""Executable dependency and capability-debt contract.

The contract intentionally works from source syntax and never imports runtime
modules.  Importing ``configuration`` currently constructs authenticated REST
state and an OrderBook, so an import-based architecture test would itself have
production-like side effects.

This freezes what static inspection can prove: internal imports, cycles,
broad/untyped constructor dependencies, their directly visible capability
surface, and reflection mechanisms that can obscure that surface.  It cannot
prove arbitrary aliasing or runtime object dispatch; the human-readable
limitations live beside the machine contract in ``genai_data``.
"""

from __future__ import annotations

import ast
from collections import Counter
from functools import lru_cache
from pathlib import Path
import tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = PROJECT_ROOT / "module_boundaries.toml"


@lru_cache(maxsize=1)
def _contract() -> dict:
    with CONTRACT_PATH.open("rb") as contract_file:
        contract = tomllib.load(contract_file)
    assert contract["version"] == 1
    return contract


def _module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@lru_cache(maxsize=1)
def _runtime_modules() -> dict[str, Path]:
    contract = _contract()
    modules: dict[str, Path] = {}

    for package_name in contract["runtime_packages"]:
        package_path = PROJECT_ROOT / package_name
        for source_path in sorted(package_path.rglob("*.py")):
            modules[_module_name(source_path)] = source_path

    for module_name in contract["runtime_root_modules"]:
        source_path = PROJECT_ROOT / f"{module_name}.py"
        assert source_path.is_file(), f"missing runtime root module: {source_path}"
        modules[module_name] = source_path

    return modules


@lru_cache(maxsize=None)
def _tree(module_name: str) -> ast.Module:
    source_path = _runtime_modules()[module_name]
    return ast.parse(
        source_path.read_text(encoding="utf-8-sig"),
        filename=str(source_path),
    )


def _absolute_import_name(
    source_module: str,
    source_path: Path,
    imported_module: str,
    level: int,
) -> str:
    if level == 0:
        return imported_module

    package_name = (
        source_module
        if source_path.name == "__init__.py"
        else source_module.rpartition(".")[0]
    )
    package_parts = package_name.split(".") if package_name else []
    keep = len(package_parts) - (level - 1)
    if keep < 0:
        return imported_module
    prefix = package_parts[:keep]
    suffix = imported_module.split(".") if imported_module else []
    return ".".join(prefix + suffix)


def _resolve_internal_module(
    imported_name: str,
    internal_modules: set[str],
) -> str | None:
    candidates = [
        module_name
        for module_name in internal_modules
        if imported_name == module_name
        or imported_name.startswith(f"{module_name}.")
    ]
    return max(candidates, key=len) if candidates else None


@lru_cache(maxsize=1)
def _import_graph() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    modules = _runtime_modules()
    internal_modules = set(modules)
    internal_edges: set[tuple[str, str]] = set()
    excluded_local_edges: set[tuple[str, str]] = set()

    excluded_roots = {"codex_repo_graph", "genai_tools", "scripts", "tests"}
    excluded_roots.update(
        source_path.stem
        for source_path in PROJECT_ROOT.glob("*.py")
        if source_path.stem not in _contract()["runtime_root_modules"]
    )

    for source_module, source_path in modules.items():
        for node in ast.walk(_tree(source_module)):
            imported_names: list[str] = []
            if isinstance(node, ast.Import):
                imported_names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_names.append(
                    _absolute_import_name(
                        source_module,
                        source_path,
                        node.module,
                        node.level,
                    )
                )

            for imported_name in imported_names:
                target_module = _resolve_internal_module(
                    imported_name,
                    internal_modules,
                )
                if target_module is not None:
                    internal_edges.add((source_module, target_module))
                    continue
                if imported_name.split(".", maxsplit=1)[0] in excluded_roots:
                    excluded_local_edges.add((source_module, imported_name))

    return internal_edges, excluded_local_edges


def _zone_for(module_name: str) -> str:
    zone_rules = _contract()["module_zones"]
    if module_name in zone_rules:
        return zone_rules[module_name]

    matches = [
        (rule_name[:-2], zone_name)
        for rule_name, zone_name in zone_rules.items()
        if rule_name.endswith(".*")
        and module_name.startswith(f"{rule_name[:-2]}.")
    ]
    assert matches, f"runtime module has no declared zone: {module_name}"
    return max(matches, key=lambda match: len(match[0]))[1]


def _format_set_difference(
    *,
    actual: set[str],
    expected: set[str],
    label: str,
) -> str:
    additions = sorted(actual - expected)
    removals = sorted(expected - actual)
    return (
        f"{label} changed\n"
        f"new/unapproved: {additions}\n"
        f"removed/stale contract entries: {removals}"
    )


def _strongly_connected_components(
    nodes: set[str],
    edges: set[tuple[str, str]],
) -> set[tuple[str, ...]]:
    adjacency = {node: set() for node in nodes}
    reverse = {node: set() for node in nodes}
    for source, target in edges:
        adjacency[source].add(target)
        reverse[target].add(source)

    visited: set[str] = set()
    finish_order: list[str] = []

    def visit(node: str) -> None:
        if node in visited:
            return
        visited.add(node)
        for target in adjacency[node]:
            visit(target)
        finish_order.append(node)

    for node in sorted(nodes):
        visit(node)

    visited.clear()
    components: set[tuple[str, ...]] = set()

    def collect(node: str, component: set[str]) -> None:
        if node in visited:
            return
        visited.add(node)
        component.add(node)
        for source in reverse[node]:
            collect(source, component)

    for node in reversed(finish_order):
        if node in visited:
            continue
        component: set[str] = set()
        collect(node, component)
        if len(component) > 1:
            components.add(tuple(sorted(component)))

    return components


def _annotation_is_broad(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return True
    return any(
        (
            isinstance(node, ast.Name)
            and node.id in {"Any", "ModuleType", "object"}
        )
        or (
            isinstance(node, ast.Attribute)
            and node.attr in {"Any", "ModuleType"}
        )
        for node in ast.walk(annotation)
    )


def _call_name(node: ast.expr) -> str:
    return ast.unparse(node)


def _broad_capability_debt() -> set[str]:
    records: set[str] = set()

    for module_name in sorted(_runtime_modules()):
        tree = _tree(module_name)
        for class_node in (
            node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        ):
            initializer = next(
                (
                    node
                    for node in class_node.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "__init__"
                ),
                None,
            )
            if initializer is None:
                continue

            initializer_node_ids = {id(node) for node in ast.walk(initializer)}
            parameters = initializer.args.args + initializer.args.kwonlyargs
            broad_parameters = {
                argument.arg
                for argument in parameters
                if argument.arg != "self"
                and _annotation_is_broad(argument.annotation)
            }
            fields: dict[str, set[str]] = {}
            establishing_parameter_node_ids: set[int] = set()

            for node in ast.walk(initializer):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                if node.value is None or any(
                    isinstance(child, ast.Call) for child in ast.walk(node.value)
                ):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                used_parameters = {
                    child.id
                    for child in ast.walk(node.value)
                    if isinstance(child, ast.Name)
                    and child.id in broad_parameters
                }
                for target in targets:
                    if not (
                        used_parameters
                        and isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        continue
                    fields.setdefault(target.attr, set()).update(used_parameters)
                    establishing_parameter_node_ids.update(
                        id(child)
                        for child in ast.walk(node.value)
                        if isinstance(child, ast.Name)
                        and child.id in used_parameters
                    )

            parent = {
                child: node
                for node in ast.walk(class_node)
                for child in ast.iter_child_nodes(node)
            }
            class_nodes = list(ast.walk(class_node))

            for field_name, providers in sorted(fields.items()):
                members: set[str] = set()
                callable_field = False
                passes: set[str] = set()
                dynamic_member = False

                for provider_name in providers:
                    for node in class_nodes:
                        is_field = (
                            isinstance(node, ast.Attribute)
                            and isinstance(node.value, ast.Name)
                            and node.value.id == "self"
                            and node.attr == field_name
                        )
                        is_initializer_parameter = (
                            id(node) in initializer_node_ids
                            and isinstance(node, ast.Name)
                            and node.id == provider_name
                        )
                        if not (is_field or is_initializer_parameter):
                            continue
                        if id(node) in establishing_parameter_node_ids:
                            continue

                        parent_node = parent.get(node)
                        if (
                            isinstance(parent_node, ast.Attribute)
                            and parent_node.value is node
                        ):
                            members.add(parent_node.attr)
                            continue
                        if (
                            isinstance(parent_node, ast.Subscript)
                            and parent_node.value is node
                        ):
                            members.add("__getitem__")
                            continue
                        if isinstance(parent_node, ast.Call):
                            if parent_node.func is node:
                                callable_field = True
                                continue
                            if node in parent_node.args:
                                target_name = _call_name(parent_node.func)
                                if target_name in {"getattr", "hasattr", "setattr"}:
                                    attribute = (
                                        parent_node.args[1]
                                        if len(parent_node.args) > 1
                                        else None
                                    )
                                    if (
                                        isinstance(attribute, ast.Constant)
                                        and isinstance(attribute.value, str)
                                    ):
                                        members.add(attribute.value)
                                    else:
                                        dynamic_member = True
                                elif target_name not in {
                                    "bool",
                                    "isinstance",
                                    "repr",
                                    "str",
                                    "type",
                                }:
                                    passes.add(target_name)
                                continue
                        if (
                            isinstance(parent_node, ast.keyword)
                            and parent_node.value is node
                        ):
                            call_node = parent.get(parent_node)
                            if isinstance(call_node, ast.Call):
                                passes.add(_call_name(call_node.func))
                        elif (
                            isinstance(parent_node, ast.Return)
                            and parent_node.value is node
                        ):
                            passes.add("<return>")
                        elif (
                            isinstance(parent_node, (ast.Assign, ast.AnnAssign))
                            and parent_node.value is node
                        ):
                            passes.add("<assign>")

                records.add(
                    "|".join(
                        (
                            f"{module_name}:{class_node.name}.{field_name}"
                            f"<-{','.join(sorted(providers))}",
                            f"members={','.join(sorted(members)) or '-'}",
                            f"call={str(callable_field).lower()}",
                            f"dynamic={str(dynamic_member).lower()}",
                            f"passes={','.join(sorted(passes)) or '-'}",
                        )
                    )
                )

    return records


class _ReflectionVisitor(ast.NodeVisitor):
    def __init__(self, module_name: str):
        self.module_name = module_name
        self.scope: list[str] = []
        self.records: Counter[str] = Counter()

    def _scope_name(self) -> str:
        return ".".join(self.scope) or "<module>"

    def _record(self, kind: str, detail: str) -> None:
        key = f"{self.module_name}:{self._scope_name()}|{kind}|{detail}"
        self.records[key] += 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        function_name = _call_name(node.func)
        if function_name in {"getattr", "hasattr", "setattr"} and len(node.args) > 1:
            attribute = node.args[1]
            if not (
                isinstance(attribute, ast.Constant)
                and isinstance(attribute.value, str)
            ):
                self._record(
                    "dynamic-attribute",
                    f"{function_name}({ast.unparse(node.args[0])}, "
                    f"{ast.unparse(attribute)})",
                )
        if function_name in {
            "__import__",
            "eval",
            "exec",
            "globals",
            "importlib.import_module",
            "locals",
            "vars",
        }:
            self._record("reflection-call", function_name)
        if function_name == "operator.attrgetter" and any(
            not (
                isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
            )
            for argument in node.args
        ):
            self._record("dynamic-attribute", ast.unparse(node))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "__dict__":
            self._record("direct-reflection", ast.unparse(node))
        if (
            isinstance(node.value, ast.Name)
            and node.value.id == "sys"
            and node.attr == "modules"
        ):
            self._record("direct-reflection", "sys.modules")
        self.generic_visit(node)


def _reflection_debt() -> set[str]:
    records: Counter[str] = Counter()
    for module_name in sorted(_runtime_modules()):
        visitor = _ReflectionVisitor(module_name)
        visitor.visit(_tree(module_name))
        records.update(visitor.records)
    return {f"{record}|count={count}" for record, count in records.items()}


def test_runtime_module_zones_and_import_debt_are_frozen() -> None:
    modules = set(_runtime_modules())
    assert modules
    for module_name in modules:
        _zone_for(module_name)

    edges, excluded_local_edges = _import_graph()
    assert not excluded_local_edges, (
        "runtime modules may not import tests, tools, scripts, or unsupported "
        f"root modules: {sorted(excluded_local_edges)}"
    )

    allowed = {
        zone_name: set(target_zones)
        for zone_name, target_zones in _contract()[
            "allowed_zone_dependencies"
        ].items()
    }
    actual_debt = {
        f"{source} -> {target}"
        for source, target in edges
        if _zone_for(target) not in allowed[_zone_for(source)]
    }
    expected_debt = {
        edge
        for debt_group in _contract()["import_debt"].values()
        for edge in debt_group
    }
    assert actual_debt == expected_debt, _format_set_difference(
        actual=actual_debt,
        expected=expected_debt,
        label="forbidden import debt",
    )


def test_runtime_import_cycles_are_frozen() -> None:
    edges, _ = _import_graph()
    actual_cycles = _strongly_connected_components(
        set(_runtime_modules()),
        edges,
    )
    expected_cycles = {
        tuple(sorted(component))
        for component in _contract()["expected_import_cycles"]
    }
    assert actual_cycles == expected_cycles, _format_set_difference(
        actual={" <-> ".join(component) for component in actual_cycles},
        expected={" <-> ".join(component) for component in expected_cycles},
        label="runtime import cycles",
    )


def test_broad_constructor_capability_debt_is_frozen() -> None:
    actual = _broad_capability_debt()
    expected = set(_contract()["broad_capability_debt"])
    assert actual == expected, _format_set_difference(
        actual=actual,
        expected=expected,
        label="broad constructor capability debt",
    )


def test_reflection_debt_is_frozen() -> None:
    actual = _reflection_debt()
    expected = set(_contract()["reflection_debt"])
    assert actual == expected, _format_set_difference(
        actual=actual,
        expected=expected,
        label="reflection debt",
    )
