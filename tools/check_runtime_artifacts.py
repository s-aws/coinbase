"""Report oversized runtime-state artifacts left by local tests.

The checker is intentionally report-only by default. It is meant to identify
repo-local payload piles that can distort regression memory attribution,
filesystem watchers, and IDE indexers after interrupted or historical runs.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


SUMMARY_PREFIX = "RUNTIME_ARTIFACT_SUMMARY "
DEFAULT_RUNTIME_STATE_DIR = Path(__file__).resolve().parents[1] / "runtime_state"
DEFAULT_MIN_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class RuntimeArtifactFinding:
    """A measured runtime artifact tree that may need operator cleanup."""

    path: Path
    reason: str
    file_count: int
    total_bytes: int
    largest_file_bytes: int

    @property
    def total_gb(self) -> float:
        return round(self.total_bytes / (1024**3), 3)

    @property
    def largest_file_mb(self) -> float:
        return round(self.largest_file_bytes / (1024**2), 1)


def _measure_tree(path: Path) -> tuple[int, int, int]:
    file_count = 0
    total_bytes = 0
    largest_file_bytes = 0
    if path.is_file():
        size = path.stat().st_size
        return 1, size, size
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            size = item.stat().st_size
        except OSError:
            continue
        file_count += 1
        total_bytes += size
        largest_file_bytes = max(largest_file_bytes, size)
    return file_count, total_bytes, largest_file_bytes


def _candidate_reason(path: Path) -> str | None:
    name = path.name.lower()
    if name == "test_admin_api_contract":
        return "admin_api_contract_runtime_state"
    if name.startswith("pytest_") or name.startswith("test_"):
        return "test_runtime_state"
    if name.endswith("_responses") or name == "idempotency_responses":
        return "idempotency_response_blobs"
    return None


def find_runtime_artifacts(
    runtime_state_dir: Path,
    *,
    min_bytes: int = DEFAULT_MIN_BYTES,
) -> list[RuntimeArtifactFinding]:
    """Return measured runtime artifact candidates at or above the byte limit."""

    if min_bytes < 0:
        raise ValueError("min_bytes must be non-negative")
    if not runtime_state_dir.exists():
        return []

    findings: list[RuntimeArtifactFinding] = []
    seen: set[Path] = set()
    candidates = list(runtime_state_dir.iterdir())
    candidates.extend(
        path
        for path in runtime_state_dir.rglob("*_responses")
        if path.is_dir()
    )
    candidates.extend(
        path
        for path in runtime_state_dir.rglob("idempotency_responses")
        if path.is_dir()
    )

    for candidate in sorted(candidates, key=lambda path: len(path.parts)):
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        if any(resolved.is_relative_to(parent) for parent in seen):
            continue
        seen.add(resolved)
        reason = _candidate_reason(candidate)
        if reason is None:
            continue
        file_count, total_bytes, largest_file_bytes = _measure_tree(candidate)
        if total_bytes < min_bytes:
            continue
        findings.append(
            RuntimeArtifactFinding(
                path=candidate,
                reason=reason,
                file_count=file_count,
                total_bytes=total_bytes,
                largest_file_bytes=largest_file_bytes,
            )
        )
    return sorted(findings, key=lambda finding: finding.total_bytes, reverse=True)


def _summary(
    *,
    status: str,
    runtime_state_dir: Path,
    findings: list[RuntimeArtifactFinding],
    fail_above_bytes: int | None,
) -> str:
    return SUMMARY_PREFIX + json.dumps(
        {
            "status": status,
            "runtime_state_dir": str(runtime_state_dir),
            "artifact_count": len(findings),
            "artifact_paths": [str(finding.path) for finding in findings],
            "total_bytes": sum(finding.total_bytes for finding in findings),
            "total_gb": round(
                sum(finding.total_bytes for finding in findings) / (1024**3),
                3,
            ),
            "fail_above_bytes": fail_above_bytes,
            "live_coinbase_execution": False,
            "live_coinbase_notional_usdc": "0",
        },
        sort_keys=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report oversized runtime_state artifacts left by local test runs. "
            "The tool does not delete files."
        )
    )
    parser.add_argument(
        "--runtime-state-dir",
        type=Path,
        default=DEFAULT_RUNTIME_STATE_DIR,
        help="Runtime-state directory to inspect.",
    )
    parser.add_argument(
        "--min-artifact-mb",
        type=float,
        default=100.0,
        help="Minimum artifact tree size to report. Defaults to 100 MB.",
    )
    parser.add_argument(
        "--fail-above-gb",
        type=float,
        default=None,
        help="Exit with status 1 when reported artifacts total above this size.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of largest findings to print in the human report.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit only the machine-readable summary line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_artifact_mb < 0:
        raise SystemExit("--min-artifact-mb must be non-negative")
    if args.fail_above_gb is not None and args.fail_above_gb < 0:
        raise SystemExit("--fail-above-gb must be non-negative")
    if args.top < 0:
        raise SystemExit("--top must be non-negative")

    min_bytes = int(args.min_artifact_mb * 1024 * 1024)
    fail_above_bytes = (
        int(args.fail_above_gb * 1024 * 1024 * 1024)
        if args.fail_above_gb is not None
        else None
    )
    runtime_state_dir = args.runtime_state_dir.resolve()
    findings = find_runtime_artifacts(runtime_state_dir, min_bytes=min_bytes)
    total_bytes = sum(finding.total_bytes for finding in findings)
    status = (
        "artifact_limit_exceeded"
        if fail_above_bytes is not None and total_bytes > fail_above_bytes
        else "artifacts_found"
        if findings
        else "passed"
    )

    if not args.json:
        if findings:
            print("Runtime artifacts found:")
            for finding in findings[: args.top]:
                print(
                    f"- path={finding.path} reason={finding.reason} "
                    f"files={finding.file_count} total_gb={finding.total_gb:.3f} "
                    f"largest_file_mb={finding.largest_file_mb:.1f}"
                )
            print("Report-only: no files were deleted.")
        else:
            print("No oversized runtime artifacts found.")
    print(
        _summary(
            status=status,
            runtime_state_dir=runtime_state_dir,
            findings=findings,
            fail_above_bytes=fail_above_bytes,
        )
    )
    return 1 if status == "artifact_limit_exceeded" else 0


if __name__ == "__main__":
    raise SystemExit(main())
