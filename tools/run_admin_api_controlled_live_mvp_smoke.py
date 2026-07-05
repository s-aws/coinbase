"""Run the backend controlled-live Admin MVP route smoke with timing evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence


SUMMARY_PREFIX = "ADMIN_API_CONTROLLED_LIVE_MVP_SMOKE_SUMMARY "
DEFAULT_SUMMARY_OUTPUT = Path(
    "artifacts/coinbase-backend-controlled-live-mvp-smoke-timing.json"
)
SMOKE_NODE_IDS = (
    "tests/regression/test_admin_api_contract.py::"
    "test_admin_api_order_live_execution_service_dependency_reads_decision_log",
    "tests/regression/test_admin_api_contract.py::"
    "test_read_surfaces_expose_controlled_live_manual_order_from_backend_decision",
    "tests/regression/test_admin_api_contract.py::"
    "test_admin_api_manual_order_route_passes_backend_admission_to_command_service",
    "tests/regression/test_admin_api_contract.py::"
    "test_admin_api_manual_order_route_executes_through_backend_runtime_dependencies",
    "tests/regression/test_admin_api_contract.py::"
    "test_admin_api_manual_order_route_blocks_admitted_quote_above_backend_cap",
)
REQUIRED_BACKEND_CONTROLLED_LIVE_MVP_SMOKE_NODE_IDS = list(SMOKE_NODE_IDS)
LIVE_COINBASE_EXECUTION_VALUES = ("not_run", "submitted", "failed", "unknown")


@dataclass(frozen=True)
class SmokeRunResult:
    return_code: int
    started_at: str
    ended_at: str
    duration_seconds: float


@dataclass(frozen=True)
class BackendGitEvidence:
    commit: str
    branch: str


def resolve_python() -> str:
    """Return the Python executable used for the smoke run."""

    return sys.executable


def build_pytest_command() -> list[str]:
    """Return the controlled-live route smoke pytest command."""

    return [
        resolve_python(),
        "-m",
        "pytest",
        *REQUIRED_BACKEND_CONTROLLED_LIVE_MVP_SMOKE_NODE_IDS,
        "-q",
        "--tb=short",
    ]


def run_smoke(command: Sequence[str]) -> SmokeRunResult:
    """Run the smoke command and return timing metadata."""

    started_at = utc_now_iso()
    started_perf = time.perf_counter()
    completed = subprocess.run(command, check=False)
    duration_seconds = round(time.perf_counter() - started_perf, 3)
    return SmokeRunResult(
        return_code=completed.returncode,
        started_at=started_at,
        ended_at=utc_now_iso(),
        duration_seconds=duration_seconds,
    )


def build_timing_summary(
    *,
    result: SmokeRunResult,
    command: Sequence[str],
    backend_git: BackendGitEvidence,
    backend_contract_ref: str,
    live_coinbase_execution: str = "not_run",
    notional_usdc: str = "0",
) -> dict[str, Any]:
    """Build the machine-readable smoke timing summary."""

    if live_coinbase_execution not in LIVE_COINBASE_EXECUTION_VALUES:
        raise ValueError(f"Invalid live_coinbase_execution: {live_coinbase_execution!r}")
    notional_text = decimal_text(notional_usdc)
    return {
        "schema_version": "1",
        "artifact_type": "coinbase_admin_api_controlled_live_mvp_smoke_timing",
        "status": "passed" if result.return_code == 0 else "failed",
        "return_code": result.return_code,
        "started_at": result.started_at,
        "ended_at": result.ended_at,
        "duration_seconds": result.duration_seconds,
        "wait_sleep_seconds": 0.0,
        "backend_git_commit": backend_git.commit,
        "backend_git_branch": backend_git.branch,
        "backend_contract_ref": backend_contract_ref,
        "command": list(command),
        "smoke_node_ids": list(REQUIRED_BACKEND_CONTROLLED_LIVE_MVP_SMOKE_NODE_IDS),
        "live_coinbase_execution": live_coinbase_execution,
        "notional_usdc": notional_text,
    }


def write_timing_summary(path: Path, summary: dict[str, Any]) -> None:
    """Write the smoke timing summary as stable JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the controlled-live MVP smoke parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the backend controlled-live Admin MVP route smoke and write "
            "machine-readable timing evidence."
        )
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_SUMMARY_OUTPUT,
        help="Path for the JSON smoke timing summary artifact.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Only print the machine-readable summary line after pytest output.",
    )
    parser.add_argument(
        "--live-coinbase-execution",
        choices=LIVE_COINBASE_EXECUTION_VALUES,
        default=os.getenv("COINBASE_ADMIN_LAST_LIVE_COINBASE_EXECUTION", "not_run"),
        help="Recorded live execution state for the run being packaged.",
    )
    parser.add_argument(
        "--notional-usdc",
        default=os.getenv("COINBASE_ADMIN_LAST_NOTIONAL_USDC", "0"),
        help="Recorded notional used by the run being packaged. Defaults to 0.",
    )
    return parser


def decimal_text(value: str | Decimal) -> str:
    """Return a non-negative decimal string without scientific notation."""

    text = str(value).strip()
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid notional_usdc: {value!r}") from exc
    if number < 0:
        raise ValueError("notional_usdc must be non-negative.")
    return format(number, "f")


def utc_now_iso() -> str:
    """Return a compact UTC timestamp for deployment artifacts."""

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def read_git_value(args: Sequence[str], fallback: str = "unknown") -> str:
    """Read a git value for deployment audit evidence."""

    try:
        value = subprocess.check_output(
            ["git", *args],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback
    return value or fallback


def read_backend_git_evidence() -> BackendGitEvidence:
    """Return backend commit and branch evidence for the smoke artifact."""

    return BackendGitEvidence(
        commit=read_git_value(["rev-parse", "--short", "HEAD"]),
        branch=read_git_value(["rev-parse", "--abbrev-ref", "HEAD"]),
    )


def resolve_backend_contract_ref(
    env: Mapping[str, str | None] = os.environ,
    git_evidence: BackendGitEvidence | None = None,
) -> str:
    """Return the backend contract ref associated with this smoke run."""

    for key in (
        "BACKEND_CONTRACT_REF",
        "COINBASE_BACKEND_CONTRACT_REF",
        "DEPLOYMENT_REF",
        "GITHUB_SHA",
    ):
        value = env.get(key)
        if value and value.strip():
            return value.strip()
    evidence = git_evidence or read_backend_git_evidence()
    return evidence.commit


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = build_pytest_command()
    result = run_smoke(command)
    git_evidence = read_backend_git_evidence()
    summary = build_timing_summary(
        result=result,
        command=command,
        backend_git=git_evidence,
        backend_contract_ref=resolve_backend_contract_ref(
            git_evidence=git_evidence,
        ),
        live_coinbase_execution=args.live_coinbase_execution,
        notional_usdc=args.notional_usdc,
    )
    write_timing_summary(args.summary_output, summary)
    if not args.summary_only:
        print(
            "Controlled-live MVP route smoke timing written: "
            f"{args.summary_output.resolve()}"
        )
        print("Live Coinbase execution: not run; notional $0")
    print(SUMMARY_PREFIX + json.dumps(summary, sort_keys=True))
    return result.return_code


if __name__ == "__main__":
    raise SystemExit(main())
