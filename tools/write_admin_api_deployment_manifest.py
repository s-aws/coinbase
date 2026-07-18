"""Write the backend Admin API deployment manifest.

The manifest is intentionally limited to deployment/runtime metadata. It does
not start services, import trading clients, submit orders, or call Coinbase.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import subprocess

from application.admin_api.spot_portfolio_binding import (
    DEFAULT_SPOT_PORTFOLIO_LABEL,
    SPOT_PORTFOLIO_ID_ENV,
    SPOT_PORTFOLIO_LABEL_ENV,
)
from application.admin_api.live_execution import (
    OPERATOR_READY_MVP_DEPLOYMENT_REF,
    OPERATOR_READY_MVP_GLOBAL_SERVICE_MODULE_ID,
    OPERATOR_READY_MVP_RUNTIME_CONFIGURATION_REF,
)
from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_LEASE_PATH_ENV,
    COINBASE_EXECUTION_LEASE_TOKEN_ENV,
)
from tools import run_admin_api


DEFAULT_OUTPUT = Path("artifacts/coinbase-backend-deployment-manifest.json")
DEFAULT_DEPLOY_ROOT = Path("..") / "coinbase-local" / "backend"
DEFAULT_TARGET_NAME = "coinbase-local-backend"
ARCHIVE_NAME = "coinbase-backend-deployment.tgz"
MANIFEST_NAME = "coinbase-backend-deployment-manifest.json"
CONTROLLED_LIVE_MVP_SMOKE_TIMING_ARTIFACT = (
    "artifacts/coinbase-backend-controlled-live-mvp-smoke-timing.json"
)
CONTROLLED_LIVE_MVP_SMOKE_COMMAND = "python tools/run_admin_api_controlled_live_mvp_smoke.py"
CONTROLLED_LIVE_MVP_SMOKE_SUMMARY_PREFIX = "ADMIN_API_CONTROLLED_LIVE_MVP_SMOKE_SUMMARY"
DEFAULT_DEPLOYMENT_TIER = "local"
DEPLOYMENT_TIERS = ("local", "staging", "production")
LIVE_COINBASE_EXECUTION_VALUES = ("not_run", "submitted", "failed", "unknown")
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
OUTER_EXECUTION_AUTHORITY_ENV = run_admin_api.EXECUTION_AUTHORITY_ENV
OUTER_EXECUTION_AUTHORITY_EXACT_VALUE = "1"
INTERNAL_LIVE_ENABLEMENT_ENV_VARS = (
    run_admin_api.LIVE_RUNTIME_ENABLED_ENV,
    "COINBASE_ADMIN_LIVE_COINBASE_EXECUTION",
    "COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED",
)


def build_deployment_manifest(
    *,
    generated_at: str,
    commit: str,
    deployment_tier: str,
    repository: str = "local",
    branch: str = "unknown",
    deploy_root: Path | None = None,
    target_name: str = DEFAULT_TARGET_NAME,
    live_coinbase_execution: str = "not_run",
    notional_usdc: str = "0",
) -> dict[str, object]:
    """Return deployment metadata for the Admin API runtime artifact."""

    live_execution = normalize_live_coinbase_execution(live_coinbase_execution)
    notional = decimal_text(notional_usdc)
    start_command = (
        "python tools/run_admin_api.py "
        f"--host 0.0.0.0 --port {run_admin_api.DEFAULT_PORT}"
    )
    controlled_live_start_command = (
        f"{OUTER_EXECUTION_AUTHORITY_ENV}=1 "
        "python tools/run_admin_api_operator_runtime.py "
        f"--host 0.0.0.0 --port {run_admin_api.DEFAULT_PORT}"
    )
    default_host = "0.0.0.0"
    install_command = INSTALL_COMMAND
    if deploy_root is not None:
        start_command = (
            "py -3.13 tools/run_admin_api.py "
            f"--host {run_admin_api.DEFAULT_HOST} "
            f"--port {run_admin_api.DEFAULT_PORT} "
            "--dev-token local-admin-token"
        )
        controlled_live_start_command = (
            f"$env:{OUTER_EXECUTION_AUTHORITY_ENV}='1'; "
            "py -3.13 tools/run_admin_api_operator_runtime.py "
            f"--host {run_admin_api.DEFAULT_HOST} "
            f"--port {run_admin_api.DEFAULT_PORT}"
        )
        default_host = run_admin_api.DEFAULT_HOST
        install_command = "py -3.13 -m pip install -e ."
    return {
        "schema_version": "1",
        "artifact_type": "coinbase_admin_api_deployment_manifest",
        "generated_at": generated_at,
        "repository": non_empty(repository, "local"),
        "commit": commit,
        "branch": non_empty(branch, "unknown"),
        "deployment_tier": deployment_tier,
        "environment": deployment_tier,
        "target_name": non_empty(target_name, DEFAULT_TARGET_NAME),
        "deploy_root": str(deploy_root or DEFAULT_DEPLOY_ROOT),
        "artifact": ARCHIVE_NAME,
        "manifest": MANIFEST_NAME,
        "runtime": {
            "app": run_admin_api.APP_IMPORT_PATH,
            "api": "Admin API HTTP",
            "python_version": PYTHON_VERSION,
            "requires_python": REQUIRES_PYTHON,
            "dependency_manifest": DEPENDENCY_MANIFEST,
            "install_command": install_command,
            "environment_env": run_admin_api.ENVIRONMENT_ENV,
            "deployment_tier_env": run_admin_api.DEPLOYMENT_TIER_ENV,
            "default_environment": deployment_tier,
            "start_command": start_command,
            "default_host": default_host,
            "default_port": run_admin_api.DEFAULT_PORT,
            "health_check": "GET /api/v1/admin/health",
            "runner": "tools/run_admin_api.py",
            "controlled_live_runner": (
                "tools/run_admin_api_operator_runtime.py"
            ),
            "controlled_live_start_command": controlled_live_start_command,
            "controlled_live_autonomous_loops_started": False,
            "controlled_live_operator_actions": [
                "manual_spot_order",
                "spot_order_cancel",
            ],
            "auth_token_env": run_admin_api.AUTH_TOKEN_ENV,
        },
        "auth": {
            "production_mode": PRODUCTION_AUTH_MODE,
            "bootstrap_env": list(BOOTSTRAP_ENV_VARS),
            "oidc_env": list(OIDC_ENV_VARS),
        },
        "frontend_authority": "operator_ui_only",
        "live_action_path": "auditable_backend_admin_interfaces_only",
        "live_execution_enablement": {
            "default_enabled": False,
            "accepted_env_vars": [
                OUTER_EXECUTION_AUTHORITY_ENV,
                *INTERNAL_LIVE_ENABLEMENT_ENV_VARS,
            ],
            "outer_authority": {
                "env_var": OUTER_EXECUTION_AUTHORITY_ENV,
                "required_exact_value": OUTER_EXECUTION_AUTHORITY_EXACT_VALUE,
                "alternate_truthy_values_fail_closed": True,
            },
            "internal_enablement": {
                "env_vars": list(INTERNAL_LIVE_ENABLEMENT_ENV_VARS),
                "necessary": True,
                "sufficient_without_outer_authority": False,
            },
            "operator_runtime_prerequisites": {
                "fail_closed_without_all_startup_prerequisites": True,
                "spot_portfolio_binding": {
                    "portfolio_id_env": SPOT_PORTFOLIO_ID_ENV,
                    "portfolio_id_requirement": "nonblank",
                    "portfolio_label_env": SPOT_PORTFOLIO_LABEL_ENV,
                    "default_portfolio_label": DEFAULT_SPOT_PORTFOLIO_LABEL,
                    "credential_scope_must_match": True,
                    "required_for_live_startup": True,
                },
                "runtime_lease": {
                    "path_env": COINBASE_EXECUTION_LEASE_PATH_ENV,
                    "token_env": COINBASE_EXECUTION_LEASE_TOKEN_ENV,
                    "manager_generated": True,
                    "owner_only_regular_file_required": True,
                    "required_for_live_startup": True,
                    "token_format": "lowercase_hex_64",
                },
                "runtime_session_binding": {
                    "live_service_decision_must_not_predate_runtime_lease": True,
                    "operator_ready_integration_goal": (
                        OPERATOR_READY_MVP_DEPLOYMENT_REF
                    ),
                    "global_service_target_module_id": (
                        OPERATOR_READY_MVP_GLOBAL_SERVICE_MODULE_ID
                    ),
                    "global_service_product_scope": [],
                    "deployment_ref": OPERATOR_READY_MVP_DEPLOYMENT_REF,
                    "runtime_configuration_ref": (
                        OPERATOR_READY_MVP_RUNTIME_CONFIGURATION_REF
                    ),
                    "stored_route_specific_adapter_decision_required": False,
                    "canonical_route_runtime_capability_required": True,
                    "request_bound_command_evidence_required": True,
                    "required_before_exchange_mutation": True,
                },
            },
            "requires_backend_proof_chain": True,
        },
        "verification": {
            "controlled_live_mvp_smoke": {
                "command": CONTROLLED_LIVE_MVP_SMOKE_COMMAND,
                "timing_artifact": CONTROLLED_LIVE_MVP_SMOKE_TIMING_ARTIFACT,
                "summary_prefix": CONTROLLED_LIVE_MVP_SMOKE_SUMMARY_PREFIX,
                "required_status": "passed",
                "wait_sleep_seconds_field": "wait_sleep_seconds",
                "live_coinbase_execution": "not_run",
                "notional_usdc": "0",
            },
        },
        "live_coinbase_execution": live_execution,
        "notional_usdc": notional,
    }


def write_manifest(path: Path, manifest: dict[str, object]) -> None:
    """Write a deployment manifest as stable, readable JSON."""

    write_json(path, manifest)


def write_json(path: Path, manifest: Mapping[str, object]) -> None:
    """Write a deployment manifest as stable, readable JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


def normalize_live_coinbase_execution(value: str) -> str:
    """Return a checked live execution label."""

    text = str(value).strip() or "not_run"
    if text not in LIVE_COINBASE_EXECUTION_VALUES:
        raise ValueError(f"Invalid live_coinbase_execution: {value!r}")
    return text


def non_empty(value: str | None, fallback: str) -> str:
    """Return trimmed text or a fallback."""

    text = value.strip() if isinstance(value, str) else ""
    return text or fallback


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
    return read_git_commit()


def resolve_deployment_branch(env: Mapping[str, str | None] = os.environ) -> str:
    """Return CI branch evidence or the local git branch."""

    for key in ("GITHUB_REF_NAME", "BRANCH_NAME"):
        value = env.get(key)
        if value and value.strip():
            return value.strip()
    return read_git_value(["rev-parse", "--abbrev-ref", "HEAD"])


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
        default=os.getenv("COINBASE_BACKEND_DEPLOYMENT_TIER", DEFAULT_DEPLOYMENT_TIER),
        help=f"Deployment tier label. Defaults to {DEFAULT_DEPLOYMENT_TIER}.",
    )
    parser.add_argument("--deploy-root", type=Path, default=None)
    parser.add_argument("--target-name", default=DEFAULT_TARGET_NAME)
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", "local"))
    parser.add_argument("--commit", default=resolve_deployment_commit(), help="Commit evidence.")
    parser.add_argument("--branch", default=resolve_deployment_branch(), help="Branch evidence.")
    parser.add_argument(
        "--generated-at",
        default=current_utc_timestamp(),
        help="Manifest generation timestamp.",
    )
    parser.add_argument(
        "--live-coinbase-execution",
        choices=LIVE_COINBASE_EXECUTION_VALUES,
        default=os.getenv("COINBASE_ADMIN_LAST_LIVE_COINBASE_EXECUTION", "not_run"),
    )
    parser.add_argument(
        "--notional-usdc",
        default=os.getenv("COINBASE_ADMIN_LAST_NOTIONAL_USDC", "0"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the manifest, and print no-live evidence."""

    args = build_parser().parse_args(argv)
    manifest = build_deployment_manifest(
        generated_at=args.generated_at,
        repository=args.repository,
        commit=args.commit,
        branch=args.branch,
        deployment_tier=args.deployment_tier,
        deploy_root=args.deploy_root,
        target_name=args.target_name,
        live_coinbase_execution=args.live_coinbase_execution,
        notional_usdc=args.notional_usdc,
    )
    write_manifest(args.output, manifest)
    print(f"Backend deployment manifest written: {args.output.resolve()}")
    print(
        "Live Coinbase execution: "
        f"{manifest['live_coinbase_execution']}; "
        f"notional {manifest['notional_usdc']} USDC"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
