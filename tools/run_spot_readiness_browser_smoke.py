"""Run the spot-readiness browser smoke gate."""

from __future__ import annotations

import subprocess
import sys
from typing import Sequence


SPOT_READINESS_BROWSER_TESTS = [
    "tests/e2e/test_spot_readiness_ui_smoke.py",
]


def main(extra_args: Sequence[str] | None = None) -> int:
    args = [
        "pytest",
        *SPOT_READINESS_BROWSER_TESTS,
        "-v",
        "--tb=short",
        "--browser",
        "chromium",
    ]
    if extra_args:
        args.extend(extra_args)
    return subprocess.call(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
