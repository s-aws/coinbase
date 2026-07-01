"""Write the backend Admin API deployment webhook payload.

The payload is deployment metadata only. It reads the controlled-live smoke
timing artifact, preserves timing evidence for bottleneck analysis, and does
not start services, import trading clients, submit orders, or call Coinbase.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_SMOKE_TIMING_PATH = Path(
    "artifacts/coinbase-backend-controlled-live-mvp-smoke-timing.json"
)
DEFAULT_MANIFEST_PATH = Path("artifacts/coinbase-backend-deployment-manifest.json")
DEFAULT_OUTPUT = Path("artifacts/coinbase-backend-deployment-webhook-payload.json")
ARTIFACT_NAME = "coinbase-backend-deployment.tgz"
MANIFEST_NAME = "coinbase-backend-deployment-manifest.json"
SMOKE_TIMING_ARTIFACT_NAME = (
    "coinbase-backend-controlled-live-mvp-smoke-timing.json"
)
SMOKE_TIMING_SUMMARY_PREFIX = "ADMIN_API_CONTROLLED_LIVE_MVP_SMOKE_SUMMARY"
DEFAULT_ENVIRONMENT = "staging"


def build_deployment_webhook_payload(
    *,
    repository: str,
    commit: str,
    environment: str,
    github_run_id: str,
    smoke_timing: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the deployment webhook payload with smoke timing evidence."""

    timing = normalize_smoke_timing(smoke_timing)
    return {
        "schema_version": "1",
        "artifact_type": "coinbase_admin_api_deployment_webhook_payload",
        "repository": non_empty_string(repository, "local"),
        "commit": non_empty_string(commit, "unknown"),
        "environment": non_empty_string(environment, DEFAULT_ENVIRONMENT),
        "artifact": ARTIFACT_NAME,
        "manifest": MANIFEST_NAME,
        "github_run_id": non_empty_string(github_run_id, "local"),
        "smoke_timing_artifact": SMOKE_TIMING_ARTIFACT_NAME,
        "smoke_timing_summary": SMOKE_TIMING_SUMMARY_PREFIX,
        "smoke_timing": timing,
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0",
    }


def normalize_smoke_timing(smoke_timing: Mapping[str, Any]) -> dict[str, Any]:
    """Return checked smoke timing fields for the deployment webhook."""

    live_execution = non_empty_string(
        smoke_timing.get("live_coinbase_execution"),
        "missing",
    )
    notional_usdc = non_empty_string(smoke_timing.get("notional_usdc"), "missing")
    if live_execution != "not_run" or notional_usdc != "0":
        raise ValueError(
            "Controlled-live smoke timing must prove live Coinbase execution "
            "not_run and notional 0."
        )
    command = smoke_timing.get("command")
    if not isinstance(command, list):
        command = []
    smoke_node_ids = smoke_timing.get("smoke_node_ids")
    if not isinstance(smoke_node_ids, list):
        smoke_node_ids = []
    return {
        "status": non_empty_string(smoke_timing.get("status"), "unknown"),
        "duration_seconds": finite_number(
            smoke_timing.get("duration_seconds"),
            "duration_seconds",
        ),
        "wait_sleep_seconds": finite_number(
            smoke_timing.get("wait_sleep_seconds"),
            "wait_sleep_seconds",
        ),
        "command": command,
        "smoke_node_count": len(smoke_node_ids),
    }


def read_json(path: Path, *, missing_message: str | None = None) -> dict[str, Any]:
    """Read a JSON object from a file."""

    if not path.exists():
        raise FileNotFoundError(
            missing_message
            or f"{path} is missing. Run the required deployment artifact writer first."
        )
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write a stable JSON artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def non_empty_string(value: Any, fallback: str) -> str:
    """Return a trimmed string or a fallback."""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def finite_number(value: Any, label: str) -> float:
    """Return a non-negative finite float."""

    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"Controlled-live smoke timing has invalid {label}.")
    number = float(value)
    if number < 0:
        raise ValueError(f"Controlled-live smoke timing has invalid {label}.")
    return number


def current_utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for artifact metadata."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_git_commit() -> str:
    """Return the local git short SHA for deployment metadata."""

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def resolve_deployment_commit(env: Mapping[str, str | None] = os.environ) -> str:
    """Return CI deployment ref, GitHub SHA, or the local git commit."""

    for key in ("DEPLOYMENT_REF", "GITHUB_SHA"):
        value = env.get(key)
        if value and value.strip():
            return value.strip()
    return read_git_commit()


def assert_manifest_commit(manifest_path: Path, commit: str) -> None:
    """Fail when the deployment manifest commit differs from the webhook commit."""

    manifest = read_json(
        manifest_path,
        missing_message=(
            f"{manifest_path} is missing. Run python "
            "tools/write_admin_api_deployment_manifest.py before the webhook payload writer."
        ),
    )
    manifest_commit = non_empty_string(manifest.get("commit"), "missing")
    payload_commit = non_empty_string(commit, "unknown")
    if manifest_commit != payload_commit:
        raise ValueError(
            "Backend deployment webhook payload commit must match deployment manifest: "
            f"{manifest_path} commit {manifest_commit} != {payload_commit}."
        )


def build_parser() -> argparse.ArgumentParser:
    """Create the deployment webhook payload parser."""

    parser = argparse.ArgumentParser(
        description="Write Admin API deployment webhook payload metadata."
    )
    parser.add_argument(
        "--smoke-timing",
        type=Path,
        default=DEFAULT_SMOKE_TIMING_PATH,
        help=f"Controlled-live smoke timing JSON. Defaults to {DEFAULT_SMOKE_TIMING_PATH}.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help=f"Deployment manifest JSON. Defaults to {DEFAULT_MANIFEST_PATH}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Webhook payload output path. Defaults to {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--repository",
        default=os.getenv("GITHUB_REPOSITORY", "local"),
        help="Repository identifier for deployment metadata.",
    )
    parser.add_argument(
        "--commit",
        default=resolve_deployment_commit(),
        help="Deployment commit ref.",
    )
    parser.add_argument(
        "--environment",
        default=os.getenv("COINBASE_BACKEND_DEPLOYMENT_TIER", DEFAULT_ENVIRONMENT),
        help="Deployment environment.",
    )
    parser.add_argument(
        "--github-run-id",
        default=os.getenv("GITHUB_RUN_ID", "local"),
        help="GitHub Actions run id.",
    )
    parser.add_argument(
        "--generated-at",
        default=current_utc_timestamp(),
        help="Payload generation timestamp.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the payload, and print no-live evidence."""

    args = build_parser().parse_args(argv)
    assert_manifest_commit(args.manifest, args.commit)
    payload = build_deployment_webhook_payload(
        repository=args.repository,
        commit=args.commit,
        environment=args.environment,
        github_run_id=args.github_run_id,
        smoke_timing=read_json(args.smoke_timing),
    )
    payload["generated_at"] = args.generated_at
    write_json(args.output, payload)
    smoke_timing = payload["smoke_timing"]
    print(f"Backend deployment webhook payload written: {args.output.resolve()}")
    print(
        "Controlled-live smoke timing: "
        f"duration {smoke_timing['duration_seconds']}s; "
        f"wait/sleep {smoke_timing['wait_sleep_seconds']}s"
    )
    print("Live Coinbase execution: not run; notional $0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
