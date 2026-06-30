"""Write the backend Admin API deployment manifest.

The manifest is intentionally limited to deployment/runtime metadata. It does
not start services, import trading clients, submit orders, or call Coinbase.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from tools import run_admin_api


DEFAULT_OUTPUT = Path("artifacts/coinbase-backend-deployment-manifest.json")
DEFAULT_DEPLOYMENT_TIER = "staging"
DEPLOYMENT_TIERS = ("local", "staging", "production")
PYTHON_VERSION = "3.13"
REQUIRES_PYTHON = ">=3.13"
DEPENDENCY_MANIFEST = "pyproject.toml"
INSTALL_COMMAND = "python -m pip install ."
PRODUCTION_AUTH_MODE = "oidc_jwt"
OIDC_ENV_VARS = (
    "COINBASE_ADMIN_API_AUTH_MODE",
    "COINBASE_ADMIN_API_OIDC_ISSUER",
    "COINBASE_ADMIN_API_OIDC_AUDIENCE",
    "COINBASE_ADMIN_API_OIDC_JWKS_URL",
)
BOOTSTRAP_ENV_VARS = (
    run_admin_api.AUTH_TOKEN_ENV,
    run_admin_api.CORS_ORIGINS_ENV,
    run_admin_api.ENVIRONMENT_ENV,
)


def build_deployment_manifest(
    *,
    generated_at: str,
    commit: str,
    deployment_tier: str,
) -> dict[str, object]:
    """Return deployment metadata for the Admin API runtime artifact."""

    return {
        "schema_version": "1",
        "artifact_type": "coinbase_admin_api_deployment_manifest",
        "generated_at": generated_at,
        "commit": commit,
        "deployment_tier": deployment_tier,
        "runtime": {
            "app": run_admin_api.APP_IMPORT_PATH,
            "python_version": PYTHON_VERSION,
            "requires_python": REQUIRES_PYTHON,
            "dependency_manifest": DEPENDENCY_MANIFEST,
            "install_command": INSTALL_COMMAND,
            "environment_env": run_admin_api.ENVIRONMENT_ENV,
            "deployment_tier_env": run_admin_api.DEPLOYMENT_TIER_ENV,
            "default_environment": deployment_tier,
            "start_command": (
                "python tools/run_admin_api.py "
                f"--host 0.0.0.0 --port {run_admin_api.DEFAULT_PORT}"
            ),
            "default_host": "0.0.0.0",
            "default_port": run_admin_api.DEFAULT_PORT,
            "health_check": "GET /api/v1/admin/health",
            "runner": "tools/run_admin_api.py",
        },
        "auth": {
            "production_mode": PRODUCTION_AUTH_MODE,
            "bootstrap_env": list(BOOTSTRAP_ENV_VARS),
            "oidc_env": list(OIDC_ENV_VARS),
        },
        "frontend_authority": "operator_ui_only",
        "live_action_path": "auditable_backend_admin_interfaces_only",
        "live_coinbase_execution": "not_run",
        "notional_usdc": "0",
    }


def write_manifest(path: Path, manifest: dict[str, object]) -> None:
    """Write a deployment manifest as stable, readable JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_git_commit() -> str:
    """Return the current short git commit or unknown when git is unavailable."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except FileNotFoundError:
        return "unknown"
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def current_utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for artifact metadata."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    """Create the deployment manifest writer parser."""

    parser = argparse.ArgumentParser(description="Write Admin API deployment metadata.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Manifest output path. Defaults to {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--deployment-tier",
        choices=DEPLOYMENT_TIERS,
        default=DEFAULT_DEPLOYMENT_TIER,
        help=f"Deployment tier label. Defaults to {DEFAULT_DEPLOYMENT_TIER}.",
    )
    parser.add_argument("--commit", default=read_git_commit(), help="Commit evidence.")
    parser.add_argument(
        "--generated-at",
        default=current_utc_timestamp(),
        help="Manifest generation timestamp.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the manifest, and print no-live evidence."""

    args = build_parser().parse_args(argv)
    manifest = build_deployment_manifest(
        generated_at=args.generated_at,
        commit=args.commit,
        deployment_tier=args.deployment_tier,
    )
    write_manifest(args.output, manifest)
    print(f"Backend deployment manifest written: {args.output.resolve()}")
    print("Live Coinbase execution: not run; notional $0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
