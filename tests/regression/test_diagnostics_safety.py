"""Regression guards for tracked operational diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.regression

ROOT = Path(__file__).resolve().parents[2]
MAIN_PLACE_ORDER = ROOT / "tools" / "diagnostics" / "main_place_order.py"


def test_main_place_order_diagnostic_is_fail_closed() -> None:
    text = MAIN_PLACE_ORDER.read_text(encoding="utf-8")

    forbidden_fragments = [
        "REST_CLIENT",
        "create_limit_order_span",
        ".create_order(",
        ".cancel_order(",
        "BIP-20DEC30-CDE",
        "PAU-20DEC30-CDE",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in text

    completed = subprocess.run(
        [sys.executable, str(MAIN_PLACE_ORDER)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["status"] == "disabled"
    assert payload["live_coinbase_execution"] is False
    assert payload["submitted_notional_usdc"] == "0"
    assert payload["executed_notional_usdc"] == "0"
