"""Run the controlled-live Admin MVP backend smoke.

The default smoke proves the backend Admin API route and proof-chain contracts
without executing Coinbase calls. Live execution evidence must come from a
separate explicit backend run that actually submits through the Admin service.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_OUTPUT = (
    Path("artifacts") / "coinbase-backend-controlled-live-mvp-smoke-timing.json"
)
ARTIFACT_TYPE = "coinbase_admin_api_controlled_live_mvp_smoke_timing"
SCHEMA_VERSION = "1"
REQUIRED_BACKEND_CONTROLLED_LIVE_MVP_SMOKE_NODE_IDS = [
    "tests/regression/test_admin_api_contract.py::test_admin_api_order_live_execution_service_dependency_reads_decision_log",
    "tests/regression/test_admin_api_contract.py::test_read_surfaces_expose_controlled_live_manual_order_from_backend_decision",
    "tests/regression/test_admin_api_contract.py::test_admin_api_manual_order_route_passes_backend_admission_to_command_service",
    "tests/regression/test_admin_api_contract.py::test_admin_api_manual_order_route_executes_through_backend_runtime_dependencies",
    "tests/regression/test_admin_api_contract.py::test_admin_api_manual_order_route_blocks_admitted_quote_above_backend_cap",
]


class SmokeStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class LiveCoinbaseExecution(str, Enum):
    NOT_RUN = "not_run"


def resolve_python() -> str:
    """Return the Python executable used for the pytest smoke command."""

    return sys.executable


def build_pytest_command(python: str, node_ids: Sequence[str]) -> list[str]:
    """Return the backend controlled-live route smoke pytest command."""

    return [
        python,
        "-m",
        "pytest",
        *node_ids,
        "-q",
        "--tb=short",
    ]


def run_smoke_command(command: Sequence[str]) -> tuple[int, float]:
    """Run the smoke command and return its exit code and elapsed seconds."""

    started = time.perf_counter()
    completed = subprocess.run(
        list(command),
        cwd=REPO_ROOT,
        check=False,
        text=True,
    )
    return completed.returncode, time.perf_counter() - started


def build_smoke_summary(
    *,
    command: Sequence[str],
    return_code: int,
    duration_seconds: float,
    started_at: str,
    ended_at: str,
    backend_git_commit: str,
    backend_git_branch: str,
    backend_contract_ref: str,
    smoke_node_ids: Sequence[str],
) -> dict[str, object]:
    """Return frontend-consumable backend smoke evidence."""

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": ARTIFACT_TYPE,
        "status": (
            SmokeStatus.PASSED.value
            if return_code == 0
            else SmokeStatus.FAILED.value
        ),
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": round(max(duration_seconds, 0), 3),
        "wait_sleep_seconds": 0,
        "return_code": return_code,
        "command": list(command),
        "backend_git_commit": backend_git_commit,
        "backend_git_branch": backend_git_branch,
        "backend_contract_ref": backend_contract_ref,
        "smoke_node_ids": list(smoke_node_ids),
        "live_coinbase_execution": LiveCoinbaseExecution.NOT_RUN.value,
        "notional_usdc": "0",
    }


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    """Write stable JSON evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_git_value(args: Sequence[str], fallback: str = "unknown") -> str:
    """Return a git value or fallback when git evidence is unavailable."""

    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except FileNotFoundError:
        return fallback
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else fallback


def current_utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    """Create the controlled-live smoke parser."""

    parser = argparse.ArgumentParser(description="Run the Admin API controlled-live MVP smoke.")
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument(
        "--backend-contract-ref",
        default=None,
        help="Backend contract ref to record. Defaults to the current git commit.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run required backend smoke nodes and write timing evidence."""

    args = build_parser().parse_args(argv)
    node_ids = REQUIRED_BACKEND_CONTROLLED_LIVE_MVP_SMOKE_NODE_IDS
    command = build_pytest_command(resolve_python(), node_ids)
    started_at = current_utc_timestamp()
    return_code, duration_seconds = run_smoke_command(command)
    ended_at = current_utc_timestamp()
    backend_git_commit = read_git_value(["rev-parse", "--short", "HEAD"])
    backend_contract_ref = args.backend_contract_ref or backend_git_commit
    summary = build_smoke_summary(
        command=command,
        return_code=return_code,
        duration_seconds=duration_seconds,
        started_at=started_at,
        ended_at=ended_at,
        backend_git_commit=backend_git_commit,
        backend_git_branch=read_git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
        backend_contract_ref=backend_contract_ref,
        smoke_node_ids=node_ids,
    )
    write_json(args.summary_output, summary)
    print(
        "Backend controlled-live MVP smoke: "
        f"{summary['status']}; live {summary['live_coinbase_execution']}; "
        f"notional {summary['notional_usdc']} USDC; "
        f"artifact {args.summary_output.resolve()}"
    )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
