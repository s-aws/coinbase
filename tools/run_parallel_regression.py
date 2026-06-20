"""Run the regression suite with a safe process-parallel split.

The default pytest command stays sequential. This helper is for major milestone
closeout, where the full regression gate is required and wall-clock time
matters. It runs tests marked ``serial`` in a separate sequential lane and runs
the remaining regression files with pytest-xdist process workers.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import uuid4


SUMMARY_PREFIX = "PARALLEL_REGRESSION_RUNNER_SUMMARY "


@dataclass(frozen=True)
class RegressionCommand:
    """A named pytest command in the split regression run."""

    name: str
    command: tuple[str, ...]


def _validate_workers(value: str) -> str:
    if value == "auto":
        return value
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "workers must be a positive integer or 'auto'"
        ) from exc
    if workers < 1:
        raise argparse.ArgumentTypeError(
            "workers must be a positive integer or 'auto'"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run tests/regression with pytest-xdist for the process-safe lane "
            "and a separate serial lane for shared-state tests."
        )
    )
    parser.add_argument(
        "--workers",
        default="4",
        type=_validate_workers,
        help="xdist worker count for the parallel-safe lane; use 'auto' or an integer.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the commands that would run without executing pytest.",
    )
    parser.add_argument(
        "--basetemp-root",
        default=str(Path("genai_tools") / "pytest-tmp" / "parallel-regression"),
        help=(
            "Root directory for per-run pytest temp directories. A unique run "
            "directory is created under this root for each invocation."
        ),
    )
    lane_group = parser.add_mutually_exclusive_group()
    lane_group.add_argument(
        "--parallel-only",
        action="store_true",
        help="Run only tests not marked serial.",
    )
    lane_group.add_argument(
        "--serial-only",
        action="store_true",
        help="Run only tests marked serial.",
    )
    return parser


def _with_basetemp(
    command: tuple[str, ...],
    *,
    basetemp: str | None,
) -> tuple[str, ...]:
    if basetemp is None:
        return command
    return command + ("--basetemp", basetemp)


def build_parallel_command(
    *,
    python: str,
    workers: str,
    basetemp: str | None = None,
) -> RegressionCommand:
    return RegressionCommand(
        name="parallel_safe_regression",
        command=_with_basetemp(
            (
                python,
                "-m",
                "pytest",
                "tests/regression",
                "-m",
                "not serial",
                "-n",
                workers,
                "--dist",
                "loadfile",
                "--max-worker-restart=0",
            ),
            basetemp=basetemp,
        ),
    )


def build_serial_command(
    *,
    python: str,
    basetemp: str | None = None,
) -> RegressionCommand:
    return RegressionCommand(
        name="serial_regression",
        command=_with_basetemp(
            (
                python,
                "-m",
                "pytest",
                "tests/regression",
                "-m",
                "serial",
            ),
            basetemp=basetemp,
        ),
    )


def build_commands(
    args: argparse.Namespace,
    *,
    python: str = sys.executable,
    run_basetemp: Path | None = None,
) -> list[RegressionCommand]:
    commands: list[RegressionCommand] = []
    if not args.serial_only:
        commands.append(
            build_parallel_command(
                python=python,
                workers=args.workers,
                basetemp=(
                    str(run_basetemp / "parallel") if run_basetemp is not None else None
                ),
            )
        )
    if not args.parallel_only:
        commands.append(
            build_serial_command(
                python=python,
                basetemp=(
                    str(run_basetemp / "serial") if run_basetemp is not None else None
                ),
            )
        )
    return commands


def is_xdist_available() -> bool:
    return importlib.util.find_spec("xdist") is not None


def _format_command(command: Iterable[str]) -> str:
    return subprocess.list2cmdline(tuple(command))


def _emit_summary(*, status: str, commands: list[RegressionCommand], failed: str | None) -> None:
    print(
        SUMMARY_PREFIX
        + json.dumps(
            {
                "status": status,
                "commands": [command.name for command in commands],
                "failed_command": failed,
                "live_coinbase_execution": False,
                "live_coinbase_notional_usdc": "0",
            },
            sort_keys=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_basetemp = Path(args.basetemp_root) / uuid4().hex
    commands = build_commands(args, run_basetemp=run_basetemp)

    if args.dry_run:
        for command in commands:
            print(f"{command.name}: {_format_command(command.command)}")
        _emit_summary(status="dry_run", commands=commands, failed=None)
        return 0

    if not args.serial_only and not is_xdist_available():
        print(
            "pytest-xdist is required for the parallel-safe lane. "
            "Install it with: python -m pip install -e \".[test]\"",
            file=sys.stderr,
        )
        _emit_summary(status="missing_xdist", commands=commands, failed="xdist")
        return 2

    for command in commands:
        print(f"==> {command.name}: {_format_command(command.command)}", flush=True)
        completed = subprocess.run(command.command, check=False)
        if completed.returncode != 0:
            _emit_summary(
                status="failed",
                commands=commands,
                failed=command.name,
            )
            return completed.returncode

    _emit_summary(status="passed", commands=commands, failed=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
