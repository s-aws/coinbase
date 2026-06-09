"""Run the focused spot-readiness regression gate."""

from __future__ import annotations

import subprocess
import sys
from typing import Sequence


SPOT_READINESS_TESTS = [
    "tests/regression/test_size_validation.py",
    "tests/regression/test_fee_multiplier_by_product_type.py",
    "tests/regression/test_product_capability_policy.py",
    "tests/regression/test_stealth_action_condition_guard.py",
    "tests/regression/test_spot_planned_budget_guard.py",
    "tests/regression/test_spot_follow_up_policy.py",
    "tests/regression/test_stealth_move_revealed.py",
    "tests/regression/test_spot_inventory_authority.py",
    "tests/regression/test_spot_portfolio_sweep.py",
    "tests/regression/test_spot_paper_mode_replay.py",
    "tests/regression/test_dashboard_action_condition_guard.py",
    "tests/regression/test_dashboard_spot_readiness.py",
    "tests/regression/test_dashboard_spot_sweep_status.py",
    "tests/regression/test_spot_campaign.py",
    "tests/regression/test_live_spot_usdc_smoke_runner.py",
    "tests/regression/test_spot_readiness_gate.py",
]


def main(extra_args: Sequence[str] | None = None) -> int:
    args = [
        sys.executable,
        "-m",
        "pytest",
        *SPOT_READINESS_TESTS,
        "-v",
        "--tb=short",
    ]
    if extra_args:
        args.extend(extra_args)
    return subprocess.call(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
