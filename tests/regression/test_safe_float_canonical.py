"""Regression tests for the canonical safe_float helper."""

from decimal import Decimal
from pathlib import Path
import re

import pytest

from calculation import safe_float as package_export
from calculation.formatter import safe_float as canonical
import configuration as configuration_module


def _production_python_files():
    repo_root = Path(__file__).resolve().parents[2]
    skip_parts = {
        ".git",
        ".venv",
        "__pycache__",
        "build",
        "coinbase_engine.egg-info",
        "dist",
        "genai_tools",
        "tests",
        "venv",
    }
    for py_file in repo_root.rglob("*.py"):
        if any(part in skip_parts for part in py_file.parts):
            continue
        yield repo_root, py_file


def test_safe_float_behavior():
    assert canonical("1.25") == 1.25
    assert canonical(None) == 0.0
    assert canonical("") == 0.0
    assert canonical("", default=2.0) == 2.0
    assert canonical("bad", default=None) is None
    assert canonical(None, default=None) is None
    assert canonical(Decimal("1.2")) == 1.2


def test_safe_float_re_exports_are_same_object():
    assert package_export is canonical
    assert configuration_module.safe_float is canonical


@pytest.mark.serial
def test_only_one_production_definition_in_repo():
    pattern = re.compile(r"^def\s+safe_float\s*\(", re.MULTILINE)

    hits = []
    for repo_root, py_file in _production_python_files():
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(text):
            hits.append(py_file.relative_to(repo_root).as_posix())

    assert hits == ["calculation/formatter.py"], (
        "safe_float must be defined exactly once in production source. "
        f"Found definitions in: {hits}"
    )


@pytest.mark.serial
def test_production_imports_canonical_safe_float():
    pattern = re.compile(r"^\s*from\s+configuration\s+import\s+.*\bsafe_float\b")

    hits = []
    for repo_root, py_file in _production_python_files():
        try:
            lines = py_file.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for line_number, line in enumerate(lines, start=1):
            if line.lstrip().startswith("#"):
                continue
            if pattern.search(line):
                hits.append(f"{py_file.relative_to(repo_root).as_posix()}:{line_number}")

    assert hits == [], (
        "Production modules should import safe_float from calculation.formatter, "
        f"not configuration. Found: {hits}"
    )
