"""Run the regression suite with a safe process-parallel split.

The default pytest command stays sequential. This helper is for major milestone
closeout, where the full regression gate is required and wall-clock time
matters. It runs tests marked ``serial`` in a separate sequential lane and runs
the remaining regression files with pytest-xdist process workers.
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from uuid import uuid4


SUMMARY_PREFIX = "PARALLEL_REGRESSION_RUNNER_SUMMARY "
SERIAL_SAFE_COMMENT = "parallel-regression: serial-safe"
MAX_PARALLEL_WORKERS = 4
PYTEST_TRACEBACK_STYLE = "short"
DEFAULT_MEMORY_SAMPLE_SECONDS = 5
DEFAULT_MAX_COMMIT_GB = 96.0
DEFAULT_MAX_COMMIT_PERCENT = 85.0
DEFAULT_MAX_PHYSICAL_PERCENT = 75.0
DEFAULT_MIN_AVAILABLE_PHYSICAL_GB = 24.0
MEMORY_ABORT_EXIT_CODE = 87


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


@dataclass(frozen=True)
class MemorySnapshot:
    """Bounded system-memory sample used to stop unsafe regression runs."""

    commit_used_gb: float
    commit_limit_gb: float
    commit_percent: float
    total_physical_gb: float
    used_physical_gb: float
    physical_percent: float
    available_physical_gb: float


@dataclass(frozen=True)
class ProcessMemorySnapshot:
    """Top process row captured when the memory guard aborts a lane."""

    process_id: int
    parent_process_id: int | None
    name: str
    private_mb: float
    working_set_mb: float
    command_line: str


@dataclass(frozen=True)
class RegressionRunResult:
    """Pytest lane result plus bounded memory telemetry."""

    returncode: int
    peak_memory_snapshot: MemorySnapshot | None = None
    process_memory_snapshots: tuple[ProcessMemorySnapshot, ...] | None = None


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

    if re.search(r"from\s+api\.v1\.app\s+import\s+create_app", text):
        reasons.append(
            (
                "imports the full FastAPI app/route graph and must stay out "
                "of the parallel lane to keep regression memory bounded",
                _evidence_line(text, r"from\s+api\.v1\.app\s+import\s+create_app"),
            )
        )

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
        raise argparse.ArgumentTypeError(
            f"workers must be a positive integer no greater than {MAX_PARALLEL_WORKERS}; "
            "'auto' is disabled to keep regression memory bounded"
        )
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"workers must be a positive integer no greater than {MAX_PARALLEL_WORKERS}"
        ) from exc
    if workers < 1:
        raise argparse.ArgumentTypeError(
            f"workers must be a positive integer no greater than {MAX_PARALLEL_WORKERS}"
        )
    if workers > MAX_PARALLEL_WORKERS:
        raise argparse.ArgumentTypeError(
            f"workers must be no greater than {MAX_PARALLEL_WORKERS}; "
            "raise this cap only after measuring peak memory on the target host"
        )
    return value


def _validate_positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def _validate_positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive number")
    return parsed


def _validate_percent(value: str) -> float:
    parsed = _validate_positive_float(value)
    if parsed > 100:
        raise argparse.ArgumentTypeError("percent must be between 0 and 100")
    return parsed


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
        help=(
            "xdist worker count for the parallel-safe lane; capped at 4 to "
            "keep regression memory bounded."
        ),
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
    parser.add_argument(
        "--memory-sample-seconds",
        default=DEFAULT_MEMORY_SAMPLE_SECONDS,
        type=_validate_positive_int,
        help=(
            "Seconds between Windows memory guard samples. Defaults to "
            f"{DEFAULT_MEMORY_SAMPLE_SECONDS}."
        ),
    )
    parser.add_argument(
        "--max-commit-percent",
        default=DEFAULT_MAX_COMMIT_PERCENT,
        type=_validate_percent,
        help=(
            "Abort the active pytest lane when Windows committed memory reaches "
            f"this percent. Defaults to {DEFAULT_MAX_COMMIT_PERCENT}."
        ),
    )
    parser.add_argument(
        "--max-commit-gb",
        default=DEFAULT_MAX_COMMIT_GB,
        type=_validate_positive_float,
        help=(
            "Abort the active pytest lane when Windows committed memory reaches "
            f"this absolute GiB value. Defaults to {DEFAULT_MAX_COMMIT_GB}."
        ),
    )
    parser.add_argument(
        "--max-physical-percent",
        default=DEFAULT_MAX_PHYSICAL_PERCENT,
        type=_validate_percent,
        help=(
            "Abort the active pytest lane when Windows physical memory use "
            f"reaches this percent. Defaults to {DEFAULT_MAX_PHYSICAL_PERCENT}."
        ),
    )
    parser.add_argument(
        "--min-available-physical-gb",
        default=DEFAULT_MIN_AVAILABLE_PHYSICAL_GB,
        type=_validate_positive_float,
        help=(
            "Abort the active pytest lane when available physical memory drops "
            f"below this many GiB. Defaults to {DEFAULT_MIN_AVAILABLE_PHYSICAL_GB}."
        ),
    )
    parser.add_argument(
        "--disable-memory-watch",
        action="store_true",
        help=(
            "Disable the Windows memory pressure guard. Use only for a scoped "
            "diagnostic run."
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
                f"--tb={PYTEST_TRACEBACK_STYLE}",
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
                f"--tb={PYTEST_TRACEBACK_STYLE}",
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


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def read_system_memory_snapshot() -> MemorySnapshot | None:
    """Return a Windows memory-pressure sample, or None when unavailable."""

    if not sys.platform.startswith("win"):
        return None

    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None

    commit_limit = status.ullTotalPageFile
    commit_used = max(0, status.ullTotalPageFile - status.ullAvailPageFile)
    commit_percent = (commit_used / commit_limit * 100) if commit_limit else 0.0
    total_physical = status.ullTotalPhys
    available_physical = status.ullAvailPhys
    used_physical = max(0, total_physical - available_physical)
    physical_percent = (
        (used_physical / total_physical * 100) if total_physical else 0.0
    )
    return MemorySnapshot(
        commit_used_gb=round(commit_used / (1024**3), 2),
        commit_limit_gb=round(commit_limit / (1024**3), 2),
        commit_percent=round(commit_percent, 2),
        total_physical_gb=round(total_physical / (1024**3), 2),
        used_physical_gb=round(used_physical / (1024**3), 2),
        physical_percent=round(physical_percent, 2),
        available_physical_gb=round(available_physical / (1024**3), 2),
    )


def _coerce_process_memory_snapshot(row: object) -> ProcessMemorySnapshot | None:
    if not isinstance(row, dict):
        return None
    try:
        process_id = int(row.get("ProcessId") or 0)
        private_mb = float(row.get("PrivateMB") or 0.0)
        working_set_mb = float(row.get("WorkingSetMB") or 0.0)
    except (TypeError, ValueError):
        return None

    parent_process_id = row.get("ParentProcessId")
    try:
        coerced_parent = (
            int(parent_process_id) if parent_process_id is not None else None
        )
    except (TypeError, ValueError):
        coerced_parent = None

    return ProcessMemorySnapshot(
        process_id=process_id,
        parent_process_id=coerced_parent,
        name=str(row.get("Name") or ""),
        private_mb=round(private_mb, 1),
        working_set_mb=round(working_set_mb, 1),
        command_line=str(row.get("CommandLine") or ""),
    )


def read_top_process_memory_snapshots(
    *,
    limit: int = 12,
    command_line_limit: int = 220,
) -> tuple[ProcessMemorySnapshot, ...]:
    """Return top Windows process private-memory rows for abort attribution."""

    if not sys.platform.startswith("win"):
        return ()

    command = rf"""
Get-CimInstance Win32_Process |
  Select-Object Name,ProcessId,ParentProcessId,
    @{{n='PrivateMB';e={{[math]::Round(($_.PrivatePageCount / 1MB), 1)}}}},
    @{{n='WorkingSetMB';e={{[math]::Round(($_.WorkingSetSize / 1MB), 1)}}}},
    @{{n='CommandLine';e={{if ($_.CommandLine -and $_.CommandLine.Length -gt {command_line_limit}) {{$_.CommandLine.Substring(0, {command_line_limit}) + '...'}} else {{$_.CommandLine}}}}}} |
  Sort-Object -Property PrivateMB -Descending |
  Select-Object -First {limit} |
  ConvertTo-Json -Depth 3
"""
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return ()

    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ()

    rows = parsed if isinstance(parsed, list) else [parsed]
    snapshots = [
        snapshot
        for row in rows
        if (snapshot := _coerce_process_memory_snapshot(row)) is not None
    ]
    return tuple(snapshots)


def _memory_guard_triggered(
    snapshot: MemorySnapshot,
    *,
    max_commit_gb: float,
    max_commit_percent: float,
    max_physical_percent: float,
    min_available_physical_gb: float,
) -> bool:
    return (
        snapshot.commit_used_gb >= max_commit_gb
        or snapshot.commit_percent >= max_commit_percent
        or snapshot.physical_percent >= max_physical_percent
        or snapshot.available_physical_gb <= min_available_physical_gb
    )


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return

    process.terminate()


def run_regression_command(
    command: RegressionCommand,
    *,
    memory_watch_enabled: bool,
    memory_sample_seconds: int,
    max_commit_gb: float,
    max_commit_percent: float,
    max_physical_percent: float,
    min_available_physical_gb: float,
) -> RegressionRunResult:
    """Run one pytest lane and abort if system memory pressure is unsafe."""

    if not memory_watch_enabled:
        return RegressionRunResult(
            returncode=subprocess.run(command.command, check=False).returncode,
        )

    process = subprocess.Popen(command.command)
    next_sample_at = time.monotonic()
    peak_snapshot: MemorySnapshot | None = None
    while True:
        returncode = process.poll()
        if returncode is not None:
            return RegressionRunResult(
                returncode=returncode,
                peak_memory_snapshot=peak_snapshot,
            )

        now = time.monotonic()
        if now >= next_sample_at:
            snapshot = read_system_memory_snapshot()
            if (
                snapshot is not None
                and (
                    peak_snapshot is None
                    or snapshot.commit_used_gb > peak_snapshot.commit_used_gb
                )
            ):
                peak_snapshot = snapshot
            if snapshot is not None and _memory_guard_triggered(
                snapshot,
                max_commit_gb=max_commit_gb,
                max_commit_percent=max_commit_percent,
                max_physical_percent=max_physical_percent,
                min_available_physical_gb=min_available_physical_gb,
            ):
                process_snapshots = read_top_process_memory_snapshots()
                print(
                    (
                        f"Memory guard aborting {command.name}: "
                        f"commit={snapshot.commit_used_gb:.2f}GiB/"
                        f"{snapshot.commit_limit_gb:.2f}GiB "
                        f"({snapshot.commit_percent:.2f}%), "
                        f"physical={snapshot.used_physical_gb:.2f}GiB/"
                        f"{snapshot.total_physical_gb:.2f}GiB "
                        f"({snapshot.physical_percent:.2f}%), "
                        f"available_physical={snapshot.available_physical_gb:.2f}GiB, "
                        f"limits=max_commit_gb={max_commit_gb:.2f}, "
                        f"max_commit_percent={max_commit_percent:.2f}, "
                        f"max_physical_percent={max_physical_percent:.2f}, "
                        f"min_available_physical_gb={min_available_physical_gb:.2f}"
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                _terminate_process_tree(process)
                return RegressionRunResult(
                    returncode=MEMORY_ABORT_EXIT_CODE,
                    peak_memory_snapshot=peak_snapshot,
                    process_memory_snapshots=process_snapshots,
                )
            next_sample_at = now + memory_sample_seconds

        time.sleep(min(1.0, max(0.1, next_sample_at - time.monotonic())))


def _format_memory_peak_snapshots(
    peaks: dict[str, MemorySnapshot | None],
) -> list[dict[str, float | str]] | None:
    formatted: list[dict[str, float | str]] = []
    for command_name, snapshot in peaks.items():
        if snapshot is None:
            continue
        formatted.append(
            {
                "command": command_name,
                "commit_used_gb": snapshot.commit_used_gb,
                "commit_limit_gb": snapshot.commit_limit_gb,
                "commit_percent": snapshot.commit_percent,
                "used_physical_gb": snapshot.used_physical_gb,
                "total_physical_gb": snapshot.total_physical_gb,
                "physical_percent": snapshot.physical_percent,
                "available_physical_gb": snapshot.available_physical_gb,
            }
        )
    return formatted or None


def _format_process_memory_snapshots(
    snapshots: dict[str, tuple[ProcessMemorySnapshot, ...] | None],
) -> list[dict[str, object]] | None:
    formatted: list[dict[str, object]] = []
    for command_name, rows in snapshots.items():
        if not rows:
            continue
        formatted.append(
            {
                "command": command_name,
                "top_processes": [
                    {
                        "process_id": row.process_id,
                        "parent_process_id": row.parent_process_id,
                        "name": row.name,
                        "private_mb": row.private_mb,
                        "working_set_mb": row.working_set_mb,
                        "command_line": row.command_line,
                    }
                    for row in rows
                ],
            }
        )
    return formatted or None


def _emit_summary(
    *,
    status: str,
    commands: list[RegressionCommand],
    failed: str | None,
    memory_watch_enabled: bool,
    max_commit_gb: float,
    max_commit_percent: float,
    max_physical_percent: float,
    min_available_physical_gb: float,
    memory_peak_snapshots: dict[str, MemorySnapshot | None] | None = None,
    process_memory_snapshots: dict[str, tuple[ProcessMemorySnapshot, ...] | None]
    | None = None,
) -> None:
    print(
        SUMMARY_PREFIX
        + json.dumps(
            {
                "status": status,
                "commands": [command.name for command in commands],
                "failed_command": failed,
                "memory_watch_enabled": memory_watch_enabled,
                "max_commit_gb": max_commit_gb,
                "max_commit_percent": max_commit_percent,
                "max_physical_percent": max_physical_percent,
                "min_available_physical_gb": min_available_physical_gb,
                "memory_peak_snapshots": _format_memory_peak_snapshots(
                    memory_peak_snapshots or {}
                ),
                "process_memory_snapshots": _format_process_memory_snapshots(
                    process_memory_snapshots or {}
                ),
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
    memory_watch_enabled = (
        not args.disable_memory_watch
        and not args.dry_run
        and not args.check_serial_classification_only
        and sys.platform.startswith("win")
    )

    serial_findings = find_serial_classification_findings()
    if serial_findings:
        emit_serial_classification_findings(serial_findings)
        _emit_summary(
            status="serial_classification_failed",
            commands=commands,
            failed="serial_classification",
            memory_watch_enabled=memory_watch_enabled,
            max_commit_gb=args.max_commit_gb,
            max_commit_percent=args.max_commit_percent,
            max_physical_percent=args.max_physical_percent,
            min_available_physical_gb=args.min_available_physical_gb,
        )
        return 2

    if args.check_serial_classification_only:
        _emit_summary(
            status="serial_classification_passed",
            commands=commands,
            failed=None,
            memory_watch_enabled=memory_watch_enabled,
            max_commit_gb=args.max_commit_gb,
            max_commit_percent=args.max_commit_percent,
            max_physical_percent=args.max_physical_percent,
            min_available_physical_gb=args.min_available_physical_gb,
        )
        return 0

    if args.dry_run:
        for command in commands:
            print(f"{command.name}: {_format_command(command.command)}")
        _emit_summary(
            status="dry_run",
            commands=commands,
            failed=None,
            memory_watch_enabled=memory_watch_enabled,
            max_commit_gb=args.max_commit_gb,
            max_commit_percent=args.max_commit_percent,
            max_physical_percent=args.max_physical_percent,
            min_available_physical_gb=args.min_available_physical_gb,
        )
        return 0

    if not args.serial_only and not is_xdist_available():
        print(
            "pytest-xdist is required for the parallel-safe lane. "
            "Install it with: python -m pip install -e \".[test]\"",
            file=sys.stderr,
        )
        _emit_summary(
            status="missing_xdist",
            commands=commands,
            failed="xdist",
            memory_watch_enabled=memory_watch_enabled,
            max_commit_gb=args.max_commit_gb,
            max_commit_percent=args.max_commit_percent,
            max_physical_percent=args.max_physical_percent,
            min_available_physical_gb=args.min_available_physical_gb,
        )
        return 2

    _prepare_basetemp_dirs(commands)
    memory_peak_snapshots: dict[str, MemorySnapshot | None] = {}
    process_memory_snapshots: dict[
        str, tuple[ProcessMemorySnapshot, ...] | None
    ] = {}

    for command in commands:
        print(f"==> {command.name}: {_format_command(command.command)}", flush=True)
        result = run_regression_command(
            command,
            memory_watch_enabled=memory_watch_enabled,
            memory_sample_seconds=args.memory_sample_seconds,
            max_commit_gb=args.max_commit_gb,
            max_commit_percent=args.max_commit_percent,
            max_physical_percent=args.max_physical_percent,
            min_available_physical_gb=args.min_available_physical_gb,
        )
        memory_peak_snapshots[command.name] = result.peak_memory_snapshot
        process_memory_snapshots[command.name] = result.process_memory_snapshots
        if result.returncode != 0:
            _emit_summary(
                status=(
                    "memory_guard_aborted"
                    if result.returncode == MEMORY_ABORT_EXIT_CODE
                    else "failed"
                ),
                commands=commands,
                failed=command.name,
                memory_watch_enabled=memory_watch_enabled,
                max_commit_gb=args.max_commit_gb,
                max_commit_percent=args.max_commit_percent,
                max_physical_percent=args.max_physical_percent,
                min_available_physical_gb=args.min_available_physical_gb,
                memory_peak_snapshots=memory_peak_snapshots,
                process_memory_snapshots=process_memory_snapshots,
            )
            return result.returncode

    _emit_summary(
        status="passed",
        commands=commands,
        failed=None,
        memory_watch_enabled=memory_watch_enabled,
        max_commit_gb=args.max_commit_gb,
        max_commit_percent=args.max_commit_percent,
        max_physical_percent=args.max_physical_percent,
        min_available_physical_gb=args.min_available_physical_gb,
        memory_peak_snapshots=memory_peak_snapshots,
        process_memory_snapshots=process_memory_snapshots,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
