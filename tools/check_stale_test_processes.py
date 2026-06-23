"""Report or clean stale test worker processes for this workspace.

The normal test runners should exit cleanly. This tool covers the failure mode
where an interrupted shell leaves pytest, Vitest, Playwright, npm, or local
Next.js test-server children running after the parent command has stopped.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SUMMARY_PREFIX = "STALE_TEST_PROCESS_SUMMARY "

TEST_PROCESS_NAMES = {
    "cmd.exe",
    "node.exe",
    "npm.cmd",
    "npx.cmd",
    "powershell.exe",
    "python.exe",
}

TEST_COMMAND_TOKENS = (
    "pytest",
    "vitest",
    "playwright",
    "npm run test",
    "npm run release:gate",
    "npm run quality",
    "next start",
    "node_modules\\vitest",
    "node_modules/vitest",
    "node_modules\\@playwright",
    "node_modules/@playwright",
)


@dataclass(frozen=True)
class ProcessInfo:
    """A process snapshot row relevant to stale test-process checks."""

    name: str
    process_id: int
    parent_process_id: int | None
    age_seconds: int | None
    working_set_mb: float
    command_line: str


def _normalize_path_variants(path: Path) -> tuple[str, ...]:
    resolved = path.resolve()
    return (
        str(resolved).lower(),
        resolved.as_posix().lower(),
    )


def _matches_any_token(command_line: str, tokens: Iterable[str]) -> bool:
    normalized = command_line.lower()
    return any(token.lower() in normalized for token in tokens)


def _matches_any_root(command_line: str, roots: Iterable[Path]) -> bool:
    normalized = command_line.lower()
    for root in roots:
        if any(variant in normalized for variant in _normalize_path_variants(root)):
            return True
    return False


def is_test_process(process: ProcessInfo, roots: Iterable[Path]) -> bool:
    """Return whether a process looks like a repo-owned test worker."""

    if process.name.lower() not in TEST_PROCESS_NAMES:
        return False
    if not process.command_line:
        return False
    return _matches_any_root(process.command_line, roots) and _matches_any_token(
        process.command_line,
        TEST_COMMAND_TOKENS,
    )


def find_stale_test_processes(
    processes: Iterable[ProcessInfo],
    *,
    roots: Iterable[Path],
    min_age_seconds: int,
) -> list[ProcessInfo]:
    """Filter process rows down to stale test workers for the configured roots."""

    stale: list[ProcessInfo] = []
    for process in processes:
        if not is_test_process(process, roots):
            continue
        if process.age_seconds is None or process.age_seconds >= min_age_seconds:
            stale.append(process)
    return stale


def _coerce_process_row(row: dict[str, Any]) -> ProcessInfo:
    return ProcessInfo(
        name=str(row.get("Name") or ""),
        process_id=int(row.get("ProcessId") or 0),
        parent_process_id=(
            int(row["ParentProcessId"]) if row.get("ParentProcessId") is not None else None
        ),
        age_seconds=(int(row["AgeSeconds"]) if row.get("AgeSeconds") is not None else None),
        working_set_mb=float(row.get("WorkingSetMB") or 0.0),
        command_line=str(row.get("CommandLine") or ""),
    )


def parse_process_json(payload: str) -> list[ProcessInfo]:
    """Parse PowerShell JSON process output into stable process rows."""

    stripped = payload.strip()
    if not stripped:
        return []
    parsed = json.loads(stripped)
    rows = parsed if isinstance(parsed, list) else [parsed]
    return [_coerce_process_row(row) for row in rows if isinstance(row, dict)]


def query_windows_processes() -> list[ProcessInfo]:
    """Read process rows from Windows CIM through PowerShell."""

    command = r"""
$now = Get-Date
Get-CimInstance Win32_Process |
  Select-Object Name,ProcessId,ParentProcessId,
    @{n='AgeSeconds';e={if ($_.CreationDate) {[int]($now - $_.CreationDate).TotalSeconds} else {$null}}},
    @{n='WorkingSetMB';e={[math]::Round(($_.WorkingSetSize / 1MB), 1)}},
    CommandLine |
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
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "PowerShell process query failed")
    return parse_process_json(completed.stdout)


def kill_process_tree(process: ProcessInfo) -> bool:
    """Terminate a stale process tree by PID."""

    completed = subprocess.run(
        ["taskkill.exe", "/PID", str(process.process_id), "/T", "/F"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.returncode == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report stale pytest/Vitest/Playwright workers associated with this "
            "repo, and optionally terminate them explicitly."
        )
    )
    parser.add_argument(
        "--repo-root",
        action="append",
        type=Path,
        help="Repository root whose test processes should be considered. Repeatable.",
    )
    parser.add_argument(
        "--include-sibling-frontend",
        action="store_true",
        help="Also inspect ../coinbase-frontend when it exists.",
    )
    parser.add_argument(
        "--min-age-seconds",
        type=int,
        default=900,
        help="Minimum process age to report as stale. Defaults to 900 seconds.",
    )
    parser.add_argument(
        "--kill",
        action="store_true",
        help="Terminate matching stale process trees. Default is report-only.",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Exit with status 1 when stale test processes are found.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit only the machine-readable summary line.",
    )
    return parser


def resolve_roots(args: argparse.Namespace) -> list[Path]:
    roots = [root.resolve() for root in args.repo_root] if args.repo_root else [
        Path(__file__).resolve().parents[1]
    ]
    sibling_frontend = roots[0].parent / "coinbase-frontend"
    if args.include_sibling_frontend and sibling_frontend.exists():
        roots.append(sibling_frontend.resolve())
    return roots


def _summary(
    *,
    status: str,
    roots: list[Path],
    stale: list[ProcessInfo],
    killed: list[int],
    kill_failed: list[int],
) -> str:
    return SUMMARY_PREFIX + json.dumps(
        {
            "status": status,
            "repo_roots": [str(root) for root in roots],
            "stale_process_count": len(stale),
            "stale_process_ids": [process.process_id for process in stale],
            "killed_process_ids": killed,
            "kill_failed_process_ids": kill_failed,
            "live_coinbase_execution": False,
            "live_coinbase_notional_usdc": "0",
        },
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_age_seconds < 0:
        raise SystemExit("--min-age-seconds must be non-negative")

    roots = resolve_roots(args)
    stale = find_stale_test_processes(
        query_windows_processes(),
        roots=roots,
        min_age_seconds=args.min_age_seconds,
    )

    killed: list[int] = []
    kill_failed: list[int] = []
    if args.kill:
        for process in stale:
            if kill_process_tree(process):
                killed.append(process.process_id)
            else:
                kill_failed.append(process.process_id)

    status = "failed_to_kill" if kill_failed else "stale_found" if stale else "passed"
    if not args.json:
        if stale:
            print("Stale test processes:")
            for process in stale:
                print(
                    f"- pid={process.process_id} ppid={process.parent_process_id} "
                    f"age_seconds={process.age_seconds} "
                    f"working_set_mb={process.working_set_mb:.1f} "
                    f"name={process.name} command={process.command_line}"
                )
        else:
            print("No stale test processes found.")
    print(
        _summary(
            status=status,
            roots=roots,
            stale=stale,
            killed=killed,
            kill_failed=kill_failed,
        )
    )
    if kill_failed:
        return 2
    if stale and args.fail_on_stale:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
