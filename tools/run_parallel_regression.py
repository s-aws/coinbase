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
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import uuid4


SUMMARY_PREFIX = "PARALLEL_REGRESSION_RUNNER_SUMMARY "
SERIAL_SAFE_COMMENT = "parallel-regression: serial-safe"


@dataclass(frozen=True)
class RegressionCommand:
    """A named pytest command in the split regression run."""

    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class SerialClassificationFinding:
    """A regression file that appears unsafe for the parallel lane."""

    path: Path
    reason: str
    evidence: str


def _has_serial_marker(text: str) -> bool:
    return "pytest.mark.serial" in text


def _has_serial_safe_comment(text: str) -> bool:
    return SERIAL_SAFE_COMMENT in text


def _evidence_line(text: str, pattern: str) -> str:
    compiled = re.compile(pattern)
    for line in text.splitlines():
        if compiled.search(line):
            return line.strip()
    return pattern


def _serial_classification_reasons(text: str) -> list[tuple[str, str]]:
    reasons: list[tuple[str, str]] = []

    if (
        re.search(r"from\s+database\.database\s+import\s+PostgresDB", text)
        and re.search(r"\bPostgresDB\s*\(\s*\)", text)
        and ".get_cursor(" in text
    ):
        reasons.append(
            (
                "uses the default PostgresDB cursor path shared by the test DB",
                _evidence_line(text, r"\bPostgresDB\s*\(\s*\)"),
            )
        )

    service_start_patterns = (
        r"\buvicorn\.run\s*\(",
        r"\bwebsockets\.serve\s*\(",
        r"\bserve_forever\s*\(",
        r"\bHTTPServer\s*\(",
        r"\bsocketserver\.",
        r"\.bind\s*\(",
        r"\.listen\s*\(",
        r"\bsubprocess\.Popen\s*\(",
    )
    for pattern in service_start_patterns:
        if re.search(pattern, text):
            reasons.append(
                (
                    "starts or binds a process-global service resource",
                    _evidence_line(text, pattern),
                )
            )
            break

    global_mutation_patterns = (
        r"\bos\.chdir\s*\(",
        r"\bos\.environ\s*\[",
        r"\bos\.environ\.update\s*\(",
        r"\bos\.putenv\s*\(",
    )
    for pattern in global_mutation_patterns:
        if re.search(pattern, text):
            reasons.append(
                (
                    "mutates process-global state outside pytest fixtures",
                    _evidence_line(text, pattern),
                )
            )
            break

    return reasons


def find_serial_classification_findings(
    regression_dir: Path = Path("tests/regression"),
) -> list[SerialClassificationFinding]:
    """Return regression files that should be marked serial or explicitly safe."""

    findings: list[SerialClassificationFinding] = []
    for path in sorted(regression_dir.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if _has_serial_marker(text) or _has_serial_safe_comment(text):
            continue
        for reason, evidence in _serial_classification_reasons(text):
            findings.append(
                SerialClassificationFinding(
                    path=path,
                    reason=reason,
                    evidence=evidence,
                )
            )
    return findings


def emit_serial_classification_findings(
    findings: list[SerialClassificationFinding],
) -> None:
    print(
        "Regression serial-lane classification failed. Mark each file with "
        "`pytest.mark.serial` or add a `parallel-regression: serial-safe` "
        "comment with a reason.",
        file=sys.stderr,
    )
    for finding in findings:
        print(
            f"- {finding.path}: {finding.reason}; evidence: {finding.evidence}",
            file=sys.stderr,
        )


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
    parser.add_argument(
        "--check-serial-classification-only",
        action="store_true",
        help=(
            "Validate regression files that need the serial lane without "
            "running pytest."
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


def _prepare_basetemp_dirs(commands: Iterable[RegressionCommand]) -> None:
    for command in commands:
        args = command.command
        for index, arg in enumerate(args[:-1]):
            if arg == "--basetemp":
                Path(args[index + 1]).mkdir(parents=True, exist_ok=True)


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

    serial_findings = find_serial_classification_findings()
    if serial_findings:
        emit_serial_classification_findings(serial_findings)
        _emit_summary(
            status="serial_classification_failed",
            commands=commands,
            failed="serial_classification",
        )
        return 2

    if args.check_serial_classification_only:
        _emit_summary(
            status="serial_classification_passed",
            commands=commands,
            failed=None,
        )
        return 0

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

    _prepare_basetemp_dirs(commands)

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
