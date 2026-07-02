"""Write local Admin MVP backend deployment metadata.

The manifest describes the local backend artifact and records run outputs. It
does not start services, import trading clients, submit orders, or call
Coinbase.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
import os
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import run_admin_api


DEFAULT_OUTPUT = Path("artifacts/coinbase-backend-deployment-manifest.json")
DEFAULT_DEPLOY_ROOT = Path("..") / "coinbase-local" / "backend"
DEFAULT_TARGET_NAME = "coinbase-local-backend"
ARCHIVE_NAME = "coinbase-backend-deployment.tgz"
MANIFEST_NAME = "coinbase-backend-deployment-manifest.json"
PYTHON_VERSION = "3.13"
REQUIRES_PYTHON = ">=3.13"


class DeploymentTier(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"


class LiveCoinbaseExecution(str, Enum):
    NOT_RUN = "not_run"
    SUBMITTED = "submitted"
    FAILED = "failed"
    UNKNOWN = "unknown"


def build_deployment_manifest(
    *,
    generated_at: str,
    repository: str,
    commit: str,
    branch: str,
    deployment_tier: str,
    deploy_root: Path,
    target_name: str,
    live_coinbase_execution: str,
    notional_usdc: str,
) -> dict[str, object]:
    """Return deployment metadata for the local Admin MVP backend."""

    tier = DeploymentTier(deployment_tier).value
    live_execution = LiveCoinbaseExecution(live_coinbase_execution).value
    notional = decimal_text(notional_usdc)
    start_command = (
        "py -3.13 tools/run_admin_api.py "
        f"--host {run_admin_api.DEFAULT_HOST} "
        f"--port {run_admin_api.DEFAULT_PORT} "
        "--dev-token local-admin-token"
    )
    return {
        "schema_version": "1",
        "artifact_type": "coinbase_admin_api_deployment_manifest",
        "generated_at": generated_at,
        "repository": non_empty(repository, "local"),
        "commit": non_empty(commit, "unknown"),
        "branch": non_empty(branch, "unknown"),
        "deployment_tier": tier,
        "environment": tier,
        "target_name": non_empty(target_name, DEFAULT_TARGET_NAME),
        "deploy_root": str(Path(deploy_root)),
        "artifact": ARCHIVE_NAME,
        "manifest": MANIFEST_NAME,
        "runtime": {
            "api": "Admin MVP HTTP",
            "runner": "tools/run_admin_api.py",
            "python_version": PYTHON_VERSION,
            "requires_python": REQUIRES_PYTHON,
            "dependency_manifest": "pyproject.toml",
            "install_command": "py -3.13 -m pip install -e .",
            "start_command": start_command,
            "default_host": run_admin_api.DEFAULT_HOST,
            "default_port": run_admin_api.DEFAULT_PORT,
            "health_check": "GET /api/v1/admin/health",
            "auth_token_env": run_admin_api.AUTH_TOKEN_ENV,
            "environment_env": run_admin_api.ENVIRONMENT_ENV,
            "deployment_tier_env": run_admin_api.DEPLOYMENT_TIER_ENV,
        },
        "frontend_authority": "operator_ui_only",
        "live_action_path": "auditable_backend_admin_interfaces_only",
        "live_execution_enablement": {
            "default_enabled": False,
            "accepted_env_vars": [
                "COINBASE_ADMIN_LIVE_COINBASE_EXECUTION",
                "COINBASE_ADMIN_API_LIVE_EXECUTION_ENABLED",
            ],
            "requires_backend_proof_chain": True,
        },
        "live_coinbase_execution": live_execution,
        "notional_usdc": notional,
    }


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    """Write a stable JSON object."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def non_empty(value: str | None, fallback: str) -> str:
    """Return trimmed text or a fallback."""

    text = value.strip() if isinstance(value, str) else ""
    return text or fallback


def current_utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_git_value(args: Sequence[str], fallback: str = "unknown") -> str:
    """Return a git value or a fallback."""

    try:
        completed = subprocess.run(
            ["git", *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except FileNotFoundError:
        return fallback
    value = completed.stdout.strip()
    return value if completed.returncode == 0 and value else fallback


def resolve_deployment_commit(env: Mapping[str, str | None] = os.environ) -> str:
    """Return CI deployment ref, GitHub SHA, or the local git commit."""

    for key in ("DEPLOYMENT_REF", "GITHUB_SHA"):
        value = env.get(key)
        if value and value.strip():
            return value.strip()
    return read_git_value(["rev-parse", "--short", "HEAD"])


def resolve_deployment_branch(env: Mapping[str, str | None] = os.environ) -> str:
    """Return CI branch evidence or the local git branch."""

    for key in ("GITHUB_REF_NAME", "BRANCH_NAME"):
        value = env.get(key)
        if value and value.strip():
            return value.strip()
    return read_git_value(["rev-parse", "--abbrev-ref", "HEAD"])


def build_parser() -> argparse.ArgumentParser:
    """Create the deployment manifest writer parser."""

    parser = argparse.ArgumentParser(description="Write backend local deployment metadata.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--deployment-tier",
        choices=[tier.value for tier in DeploymentTier],
        default=os.getenv("COINBASE_BACKEND_DEPLOYMENT_TIER", DeploymentTier.LOCAL.value),
    )
    parser.add_argument("--deploy-root", type=Path, default=DEFAULT_DEPLOY_ROOT)
    parser.add_argument("--target-name", default=DEFAULT_TARGET_NAME)
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", "local"))
    parser.add_argument("--commit")
    parser.add_argument("--branch")
    parser.add_argument("--generated-at", default=current_utc_timestamp())
    parser.add_argument(
        "--live-coinbase-execution",
        choices=[item.value for item in LiveCoinbaseExecution],
        default=os.getenv("COINBASE_ADMIN_LAST_LIVE_COINBASE_EXECUTION", "not_run"),
    )
    parser.add_argument(
        "--notional-usdc",
        default=os.getenv("COINBASE_ADMIN_LAST_NOTIONAL_USDC", "0"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the manifest, and print local deployment evidence."""

    args = build_parser().parse_args(argv)
    manifest = build_deployment_manifest(
        generated_at=args.generated_at,
        repository=args.repository,
        commit=args.commit or resolve_deployment_commit(),
        branch=args.branch or resolve_deployment_branch(),
        deployment_tier=args.deployment_tier,
        deploy_root=args.deploy_root,
        target_name=args.target_name,
        live_coinbase_execution=args.live_coinbase_execution,
        notional_usdc=args.notional_usdc,
    )
    write_json(args.output, manifest)
    print(f"Backend deployment manifest written: {args.output.resolve()}")
    print(
        "Live Coinbase execution: "
        f"{manifest['live_coinbase_execution']}; "
        f"notional {manifest['notional_usdc']} USDC"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
