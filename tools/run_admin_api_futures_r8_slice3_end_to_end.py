"""Permanently retired Slice 2R8 end-to-end entrypoint.

R8 is consumed.  This tombstone intentionally imports no project module,
touches no artifact, hydrates no credential, and exposes no execution path.
"""

from __future__ import annotations

import json
import sys
from typing import Sequence


R8_SLICE3_END_TO_END_READY = False


def main(argv: Sequence[str] | None = None) -> int:
    """Reject every invocation without inspecting R8 or any successor path."""

    del argv
    print(
        json.dumps(
            {
                "status": "blocked",
                "blocker": "futures_r8_slice3_permanently_retired",
                "workflow_ready": False,
                "artifact_created": False,
                "coinbase_client_constructed": False,
                "coinbase_read_ran": False,
                "preview_order_attempt_count": 0,
                "slice3_exchange_mutation_attempt_count": 0,
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
