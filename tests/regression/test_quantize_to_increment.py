"""Regression tests for the canonical quantize_to_increment.

The function had two parallel implementations (calculation/formatter.py
and configuration.py), both built on float modulo, which silently
shaved a full tick off values like 0.123 % 0.001 -> ~0.000999...

These tests pin three things:

1. The implementation uses Decimal arithmetic and is exact at BTC's
   1e-8 scale (no tick shaving).
2. There is exactly ONE source-level definition of the function in
   the codebase. Re-exports via ``from ... import quantize_to_increment``
   are fine; a second ``def quantize_to_increment`` is not (P2 #1: DRY).
3. ``configuration.quantize_to_increment`` and
   ``calculation.formatter.quantize_to_increment`` are the same object.
"""

import inspect
import re
from pathlib import Path

import pytest

from calculation.formatter import quantize_to_increment as canonical
import configuration as configuration_module
from calculation import formatter as formatter_module


def test_re_export_is_same_object():
    """configuration.quantize_to_increment must be the same function
    object as calculation.formatter.quantize_to_increment, not a copy.
    If it's a copy, drift between the two will return."""
    assert configuration_module.quantize_to_increment is canonical
    assert formatter_module.quantize_to_increment is canonical


def test_only_one_def_in_repo():
    """Static-source guard: a single ``def quantize_to_increment(``
    must appear in the repo. Re-exports are imports, not defs."""
    repo_root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"^def\s+quantize_to_increment\s*\(", re.MULTILINE)

    hits = []
    for py in repo_root.rglob("*.py"):
        # Skip venv / build / cache.
        parts = py.parts
        if any(part in {".venv", "venv", "__pycache__", ".git",
                        "build", "dist", "coinbase_engine.egg-info"}
               for part in parts):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if pattern.search(text):
            hits.append(py.relative_to(repo_root).as_posix())

    assert hits == ["calculation/formatter.py"], (
        f"quantize_to_increment must be defined exactly once "
        f"(in calculation/formatter.py). Found definitions in: {hits}"
    )


# ---------------------------------------------------------------------------
# Precision regression tests (the bug that motivated this consolidation).
# ---------------------------------------------------------------------------

def test_down_does_not_shave_a_full_tick():
    """0.123 % 0.001 in float = ~0.000999...; the old impl would
    subtract that and return 0.122. Decimal-based impl returns 0.123."""
    assert canonical(0.123, "0.001", direction="down") == 0.123


def test_btc_eight_decimal_exact():
    """BTC base_increment is 1e-8. An exact tick value must round-trip."""
    assert canonical(0.12345678, "0.00000001", direction="down") == 0.12345678


def test_btc_nine_decimal_snaps_down():
    """A 9-decimal value must snap DOWN to the 8-decimal tick."""
    assert canonical(0.123456789, "0.00000001", direction="down") == 0.12345678


def test_up_rounds_up_one_tick():
    assert canonical(0.1231, "0.001", direction="up") == 0.124


def test_nearest_rounds_half_up():
    assert canonical(0.1235, "0.001", direction="nearest") == 0.124


def test_already_aligned_value_unchanged():
    assert canonical(50.0, "1", direction="down") == 50.0


def test_invalid_increment_rejected():
    with pytest.raises(ValueError):
        canonical(1.0, "0", direction="down")
    with pytest.raises(ValueError):
        canonical(1.0, "-0.01", direction="down")


def test_invalid_direction_rejected():
    with pytest.raises(ValueError):
        canonical(1.0, "0.01", direction="sideways")


def test_signature_is_documented():
    """If someone deletes the docstring or changes the signature, the
    re-export contract still has to mean something. Pin both."""
    sig = inspect.signature(canonical)
    assert list(sig.parameters) == ["value", "increment", "direction"]
    assert canonical.__doc__ is not None and "Quantize" in canonical.__doc__
