"""Fail-closed placeholder for historical order-placement diagnostics.

This file used to be a quick manual placement helper. Keeping an executable
diagnostic that can enter a futures placement path makes contextless review
unsafe, so the tracked version is now documentation-by-output only.
"""

from __future__ import annotations

import json


EXIT_CODE = 2


def build_disabled_diagnostic() -> dict[str, object]:
    """Return explicit evidence that this diagnostic cannot place orders."""

    return {
        "status": "disabled",
        "reason": "tracked diagnostics must not place, cancel, or modify exchange orders",
        "live_coinbase_execution": False,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "next_step": (
            "Use approved Admin API dry-run/readback surfaces or a quarantined "
            "local-only script outside the repository for operator experiments."
        ),
    }


def main() -> int:
    print(json.dumps(build_disabled_diagnostic(), indent=2, sort_keys=True))
    return EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
