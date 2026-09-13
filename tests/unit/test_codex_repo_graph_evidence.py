from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from codex_repo_graph import build_graph
from tests.unit.test_codex_repo_graph_lifecycle import (
    _commit_all,
    _initialize_repository,
    _install_minimal_graph_tool,
    _run,
    _run_builder,
)


def _symbols(source: str, path: str = "application.py") -> list[dict]:
    collector = build_graph.PythonCollector(path, source)
    collector.visit(ast.parse(source))
    return collector.symbols


def _evidence(
    source: str,
    *,
    path: str = "application.py",
    line_start: int = 1,
    line_end: int = 1,
    anchor: str = "def answer(",
    symbol_id: str | None = "s:application.py::answer",
    scope_start: int = 1,
    scope_end: int | None = None,
) -> dict:
    lines = build_graph.source_lines(source)
    excerpt = "\n".join(lines[line_start - 1:line_end])
    scope = "\n".join(lines[scope_start - 1:scope_end]) if symbol_id else excerpt
    result = {
        "path": path,
        "line_start": line_start,
        "line_end": line_end,
        "anchor": anchor,
        "file_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "reviewed_scope_sha256": hashlib.sha256(scope.encode("utf-8")).hexdigest(),
        "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
    }
    if symbol_id:
        result["symbol_id"] = symbol_id
    return result


def _record(evidence: dict) -> dict:
    return {
        "id": "task:answer",
        "kind": "task_route",
        "state": "verified_current",
        "confidence": "curated",
        "evidence": [evidence],
        "start_here": ["s:application.py::answer"],
    }


def _normalize(tmp_path: Path, monkeypatch, evidence: dict, current_source: str):
    semantic_dir = tmp_path / "semantic"
    semantic_dir.mkdir(exist_ok=True)
    for filename in build_graph.SEMANTIC_FILES:
        records = [_record(evidence)] if filename == "task_routes.jsonl" else []
        (semantic_dir / filename).write_bytes(build_graph.render_jsonl(records))
    monkeypatch.setattr(build_graph, "SEMANTIC_DIR", semantic_dir)
    path = evidence["path"]
    file_record = {
        "path": path,
        "sha256": hashlib.sha256(current_source.encode("utf-8")).hexdigest(),
        "lines": len(build_graph.source_lines(current_source)),
    }
    symbols = _symbols(current_source, path) if path.endswith(".py") else []
    artifacts, records, errors = build_graph.load_and_normalize_semantic(
        [file_record], {path: build_graph.source_lines(current_source)}, symbols=symbols
    )
    assert json.loads(artifacts[semantic_dir / "task_routes.jsonl"])["evidence"] == records[0]["evidence"]
    return records[0]["evidence"][0], errors, file_record


def test_symbol_evidence_relocates_after_insertion_without_reapproving_scope(tmp_path: Path, monkeypatch) -> None:
    original = "@tracked\ndef answer():\n    return True\n"
    evidence = _evidence(original, line_start=2, line_end=2)
    before = copy.deepcopy(evidence)
    current = "class Other:\n    def answer(self):\n        return False\n\n" + original

    resolved, errors, file_record = _normalize(tmp_path, monkeypatch, evidence, current)

    assert errors == []
    assert resolved == {**before, "line_start": 6, "line_end": 6, "file_sha256": file_record["sha256"]}
    assert evidence == before


@pytest.mark.parametrize(
    "original,current",
    [
        ("def answer():\n    return True\n", "def answer():\n    return False\n"),
        (
            "@policy(allow=True)\ndef answer():\n    return True\n",
            "@policy(allow=False)\ndef answer():\n    return True\n",
        ),
        (
            "@policy(\n    allow=True,\n)\ndef answer():\n    return True\n",
            "@policy(\n    allow=False,\n)\ndef answer():\n    return True\n",
        ),
    ],
    ids=["body", "decorator", "multiline-decorator"],
)
def test_unchanged_definition_anchor_does_not_reapprove_changed_scope(
    tmp_path: Path, monkeypatch, original: str, current: str
) -> None:
    definition_line = build_graph.source_lines(original).index("def answer():") + 1
    evidence = _evidence(original, line_start=definition_line, line_end=definition_line)

    resolved, errors, _ = _normalize(tmp_path, monkeypatch, evidence, current)

    assert errors and any("review required" in error.lower() for error in errors)
    assert resolved == evidence


@pytest.mark.parametrize("symbol_id", ["s:application.py::answer", "s:application.py::answer#2"])
def test_duplicate_symbol_family_is_ambiguous_even_with_occurrence_suffix(symbol_id: str) -> None:
    symbols = _symbols("def answer():\n    return True\n\ndef answer():\n    return False\n")

    with pytest.raises(ValueError, match="(?i)ambiguous"):
        build_graph.SymbolResolver(symbols).resolve(symbol_id)


@pytest.mark.parametrize("parent_definition", ["class Parent:", "def Parent():"])
def test_unique_member_of_duplicated_parent_is_still_ambiguous(parent_definition: str) -> None:
    source = (
        f"{parent_definition}\n    def answer():\n        return True\n\n"
        f"{parent_definition}\n    pass\n"
    )
    symbols = _symbols(source)
    symbol_id = "s:application.py::Parent.answer"
    assert sum(symbol["id"] == symbol_id for symbol in symbols) == 1

    with pytest.raises(ValueError, match="(?i)ambiguous"):
        build_graph.SymbolResolver(symbols).resolve(symbol_id)


@pytest.mark.parametrize(
    "unsupported",
    [{"symbol_kind": "constant"}, {"confidence": "heuristic"}, {"path": "application.js"}],
    ids=["constant", "heuristic", "non-python"],
)
def test_symbol_resolution_rejects_unsupported_definition(unsupported: dict) -> None:
    symbol = _symbols("def answer():\n    return True\n")[0]
    symbol.update(unsupported)

    with pytest.raises(ValueError, match="(?i)unsupported"):
        build_graph.SymbolResolver([symbol]).resolve(symbol["id"])


def test_symbol_evidence_cannot_use_identical_source_from_another_path() -> None:
    source = "def answer():\n    return True\n"
    evidence = _evidence(source, symbol_id="s:other.py::answer")
    before = copy.deepcopy(evidence)
    resolver = build_graph.SymbolResolver(_symbols(source, "other.py"))

    with pytest.raises(ValueError, match="(?i)path mismatch"):
        build_graph.resolve_evidence(evidence, build_graph.source_lines(source), resolver)

    assert evidence == before


@pytest.mark.parametrize(
    "current",
    [
        "def renamed():\n    return True\n",
        "class Moved:\n    def answer():\n        return True\n",
        "VALUE = True\n",
        "def answer():\n    return True\n\ndef answer():\n    return True\n",
    ],
    ids=["renamed", "moved-to-class", "removed", "duplicate"],
)
def test_missing_or_ambiguous_symbol_cannot_relocate_by_anchor(tmp_path: Path, monkeypatch, current: str) -> None:
    evidence = _evidence("def answer():\n    return True\n")

    resolved, errors, _ = _normalize(tmp_path, monkeypatch, evidence, current)

    assert errors and any("review required" in error.lower() for error in errors)
    assert resolved == evidence


@pytest.mark.parametrize("newline", ["\r\n", "\r"])
def test_reviewed_fingerprints_normalize_line_endings(tmp_path: Path, monkeypatch, newline: str) -> None:
    original = "def answer():\n    return True\n"
    evidence = _evidence(original, line_end=2)

    resolved, errors, file_record = _normalize(tmp_path, monkeypatch, evidence, original.replace("\n", newline))

    assert errors == []
    assert resolved == {**evidence, "file_sha256": file_record["sha256"]}


@pytest.mark.parametrize("separator", ["\u2028", "\u2029", "\f"], ids=["line-separator", "paragraph-separator", "form-feed"])
def test_literal_separator_does_not_hide_changed_source_suffix(tmp_path: Path, monkeypatch, separator: str) -> None:
    original = f"def answer():\n    return 'prefix{separator}before'\n"
    assert build_graph.source_lines(original) == ["def answer():", f"    return 'prefix{separator}before'"]
    evidence = _evidence(original)
    assert evidence["reviewed_scope_sha256"] == hashlib.sha256(original.removesuffix("\n").encode("utf-8")).hexdigest()
    unchanged, initial_errors, _ = _normalize(tmp_path, monkeypatch, evidence, original)
    assert initial_errors == []
    assert unchanged == evidence

    current = original.replace("before", "after")
    resolved, errors, _ = _normalize(tmp_path, monkeypatch, evidence, current)

    assert errors and any("review required" in error.lower() for error in errors)
    assert resolved == evidence


def test_text_evidence_finds_unique_unchanged_excerpt_after_line_movement(tmp_path: Path, monkeypatch) -> None:
    original = "# Behavior\nThe operation returns True.\n"
    evidence = _evidence(
        original, path="behavior.md", line_start=2, line_end=2,
        anchor="operation", symbol_id=None,
    )
    current = "# Behavior\n\nNew introduction.\n\nThe operation returns True.\n"

    resolved, errors, file_record = _normalize(tmp_path, monkeypatch, evidence, current)

    assert errors == []
    assert resolved == {**evidence, "line_start": 5, "line_end": 5, "file_sha256": file_record["sha256"]}


@pytest.mark.parametrize(
    "current",
    [
        "# Behavior\nThe operation returns True.\nThe operation returns True.\n",
        "# Behavior\nThe operation returns False.\n",
    ],
    ids=["ambiguous-excerpt", "changed-excerpt-with-same-anchor"],
)
def test_text_evidence_does_not_guess_or_reapprove(tmp_path: Path, monkeypatch, current: str) -> None:
    evidence = _evidence(
        "# Behavior\nThe operation returns True.\n", path="behavior.md",
        line_start=2, line_end=2, anchor="operation", symbol_id=None,
    )

    resolved, errors, _ = _normalize(tmp_path, monkeypatch, evidence, current)

    assert errors and any("review required" in error.lower() for error in errors)
    assert resolved == evidence


def test_repeated_excerpt_inside_unchanged_symbol_requires_explicit_review(tmp_path: Path, monkeypatch) -> None:
    source = "def answer(flag):\n    if flag:\n        return True\n    if not flag:\n        return True\n"
    evidence = _evidence(source, line_start=3, line_end=3, anchor="return True")

    resolved, errors, _ = _normalize(tmp_path, monkeypatch, evidence, source)

    assert errors and any("review required" in error.lower() for error in errors)
    assert resolved == evidence


@pytest.mark.parametrize("missing_field", ["reviewed_scope_sha256", "excerpt_sha256"])
def test_normalization_never_initializes_an_unreviewed_fingerprint(tmp_path: Path, monkeypatch, missing_field: str) -> None:
    source = "def answer():\n    return True\n"
    evidence = _evidence(source)
    del evidence[missing_field]

    resolved, errors, _ = _normalize(tmp_path, monkeypatch, evidence, source)

    assert errors and any("review required" in error.lower() for error in errors)
    assert resolved == evidence


def test_navigation_follows_changed_symbol_but_rejects_missing_target() -> None:
    source = "# New header\n\ndef answer():\n    return False\n"
    record = _record(_evidence("def answer():\n    return True\n"))
    files = [{"path": "application.py", "lines": 4}]
    symbols = _symbols(source)

    assert build_graph.validate_semantic_references([record], files, symbols=symbols) == []
    record["start_here"] = ["s:application.py::renamed"]
    assert build_graph.validate_semantic_references([record], files, symbols=symbols)


@pytest.mark.parametrize("newline", ["\n", "\r"], ids=["lf", "cr-only"])
def test_build_relocates_navigation_and_failed_review_preserves_all_graph_artifacts(tmp_path: Path, newline: str) -> None:
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    builder = _install_minimal_graph_tool(repository)
    graph_dir = builder.parent
    source = f"def answer():{newline}    return True{newline}"
    application = repository / "application.py"
    application.write_bytes(source.encode("utf-8"))
    task_file = graph_dir / "semantic" / "task_routes.jsonl"
    task_file.write_bytes(build_graph.render_jsonl([_record(_evidence(source))]))
    _commit_all(repository, "reviewed baseline")

    first_build = _run_builder(repository, builder)
    assert first_build.returncode == 0, first_build.stderr
    application.write_bytes((f"# New header{newline}{newline}" + source).encode("utf-8"))
    relocated_build = _run_builder(repository, builder)
    assert relocated_build.returncode == 0, relocated_build.stderr
    checked = _run_builder(repository, builder, check=True)
    assert checked.returncode == 0, checked.stderr

    task = json.loads(task_file.read_text(encoding="utf-8"))
    assert task["evidence"][0]["line_start"] == 3
    assert task["start_here"] == ["s:application.py::answer"]
    queried = _run([sys.executable, str(graph_dir / "query_graph.py"), "task", "answer"], cwd=repository)
    assert json.loads(queried.stdout)["resolved_start_here"] == ["application.py:3"]

    previous_artifacts = {path: path.read_bytes() for path in graph_dir.rglob("*") if path.is_file()}
    application.write_bytes((f"# New header{newline}{newline}" + source.replace("True", "False")).encode("utf-8"))
    rejected = _run_builder(repository, builder)

    assert rejected.returncode == 1
    assert "review required" in rejected.stderr.lower()
    current_artifacts = {path: path.read_bytes() for path in graph_dir.rglob("*") if path.is_file()}
    assert current_artifacts == previous_artifacts
