"""Apply the backend Admin API deployment artifact to a local filesystem target.

The local deployment target is a versioned directory. This script does not
start services, import trading clients, submit orders, call Coinbase, or call
external deployment webhooks.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
from typing import Any

from tools.run_admin_api_controlled_live_mvp_smoke import SMOKE_NODE_IDS


DEFAULT_TARGET_NAME = "coinbase-local-backend"
DEFAULT_LOCAL_ROOT_NAME = "coinbase-local"
DEFAULT_LOCAL_COMPONENT_NAME = "backend"
LOCAL_DEPLOY_ROOT_ENV = "COINBASE_BACKEND_LOCAL_DEPLOY_ROOT"
DEFAULT_ARCHIVE_PATH = Path("artifacts/coinbase-backend-deployment.tgz")
DEFAULT_MANIFEST_PATH = Path("artifacts/coinbase-backend-deployment-manifest.json")
DEFAULT_SMOKE_TIMING_PATH = Path(
    "artifacts/coinbase-backend-controlled-live-mvp-smoke-timing.json"
)
DEFAULT_OUTPUT = Path("artifacts/coinbase-backend-local-deployment-manifest.json")
ARTIFACT_NAME = "coinbase-backend-deployment.tgz"
MANIFEST_NAME = "coinbase-backend-deployment-manifest.json"
LOCAL_DEPLOYMENT_MANIFEST_NAME = "coinbase-backend-local-deployment-manifest.json"
SMOKE_TIMING_ARTIFACT_NAME = "coinbase-backend-controlled-live-mvp-smoke-timing.json"
SMOKE_TIMING_SUMMARY_PREFIX = "ADMIN_API_CONTROLLED_LIVE_MVP_SMOKE_SUMMARY"
DEFAULT_ENVIRONMENT = "local"
DEPLOYMENT_TIERS = ("local",)
PAYLOAD_PATHS = (
    "api",
    "application",
    "bridges",
    "business",
    "calculation",
    "core",
    "data",
    "database",
    "external",
    "integration",
    "market_intel",
    "openapi",
    "tools",
    "tests/__init__.py",
    "tests/pytest.ini",
    "tests/conftest.py",
    "tests/regression/__init__.py",
    "tests/regression/test_admin_api_contract.py",
    "tests/regression/test_admin_mvp_api.py",
    "websocket",
    "configuration.py",
    "dashboard_server.py",
    "logging_service.py",
    "main.py",
    "products.json",
    "pyproject.toml",
    "README.md",
    "README.admin-api.md",
)
REQUIRED_PAYLOAD_PATHS = (
    "api/v1/app.py",
    "application/admin_api/mvp_service.py",
    "tools/run_admin_api.py",
    "logging_service.py",
    "tests/regression/test_admin_api_contract.py",
    "tests/regression/test_admin_mvp_api.py",
    "pyproject.toml",
)
EXCLUDED_PACKAGE_NAMES = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
EXCLUDED_PACKAGE_SUFFIXES = {".pyc", ".pyo"}


def build_local_deployment_manifest(
    *,
    repository: str,
    commit: str,
    deployment_tier: str,
    target_name: str,
    deploy_root: Path,
    current_path: Path,
    release_path: Path,
    generated_at: str,
    smoke_timing: Mapping[str, Any] | None = None,
    source_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return metadata for the applied local backend Admin API release."""

    source_manifest = source_manifest or {}
    payload: dict[str, Any] = {
        "schema_version": "1",
        "artifact_type": "coinbase_admin_api_local_deployment_manifest",
        "generated_at": generated_at,
        "repository": non_empty_string(repository, "local"),
        "commit": non_empty_string(commit, "unknown"),
        "environment": deployment_tier,
        "deployment_tier": deployment_tier,
        "target_name": non_empty_string(target_name, DEFAULT_TARGET_NAME),
        "deploy_root": str(deploy_root),
        "current_path": str(current_path),
        "release_path": str(release_path),
        "artifact": ARTIFACT_NAME,
        "manifest": MANIFEST_NAME,
        "live_coinbase_execution": non_empty_string(
            source_manifest.get("live_coinbase_execution"),
            "not_run",
        ),
        "notional_usdc": non_empty_string(source_manifest.get("notional_usdc"), "0"),
    }
    if smoke_timing is not None:
        timing = normalize_smoke_timing(smoke_timing)
        payload["smoke_timing_artifact"] = SMOKE_TIMING_ARTIFACT_NAME
        payload["smoke_timing_summary"] = SMOKE_TIMING_SUMMARY_PREFIX
        payload["smoke_timing"] = timing
        payload["live_coinbase_execution"] = "not_run"
        payload["notional_usdc"] = "0"
    return payload


def apply_local_deployment(
    *,
    deploy_root: Path,
    archive_path: Path = DEFAULT_ARCHIVE_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    smoke_timing_path: Path | None = None,
    output_path: Path | None = None,
    target_name: str = DEFAULT_TARGET_NAME,
    repository: str = "local",
    commit: str | None = None,
    deployment_tier: str = DEFAULT_ENVIRONMENT,
    generated_at: str | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    """Extract the checked deployment artifact into the local release target."""

    manifest = read_json(manifest_path)
    payload_commit = non_empty_string(commit, non_empty_string(manifest.get("commit"), "unknown"))
    payload_tier = non_empty_string(
        deployment_tier,
        non_empty_string(manifest.get("deployment_tier"), DEFAULT_ENVIRONMENT),
    )
    if source_root is not None:
        write_deployment_archive(
            source_root=source_root.resolve(),
            manifest_path=manifest_path.resolve(),
            archive_path=archive_path.resolve(),
        )
    assert_archive_exists(archive_path)
    assert_deployment_manifest(manifest_path, payload_commit, payload_tier)
    smoke_timing = read_json(smoke_timing_path) if smoke_timing_path is not None else None

    root = deploy_root.resolve()
    release_path = root / "releases" / release_label(payload_commit)
    current_path = root / "current"
    assert_child_path(root, release_path, "release path")
    assert_child_path(root, current_path, "current path")

    local_manifest = build_local_deployment_manifest(
        repository=repository,
        commit=payload_commit,
        deployment_tier=payload_tier,
        target_name=target_name,
        deploy_root=root,
        current_path=current_path,
        release_path=release_path,
        smoke_timing=smoke_timing,
        generated_at=generated_at or current_utc_timestamp(),
        source_manifest=manifest,
    )

    root.mkdir(parents=True, exist_ok=True)
    remove_path(release_path, root)
    release_path.mkdir(parents=True)
    extract_archive_safely(archive_path, release_path)
    write_json(release_path / LOCAL_DEPLOYMENT_MANIFEST_NAME, local_manifest)

    remove_path(current_path, root)
    shutil.copytree(release_path, current_path)
    write_json(root / "current-release.json", local_manifest)
    if output_path is not None:
        write_json(output_path, local_manifest)
    return local_manifest


def normalize_smoke_timing(smoke_timing: Mapping[str, Any]) -> dict[str, Any]:
    """Return checked smoke timing fields for local deployment evidence."""

    status = non_empty_string(smoke_timing.get("status"), "unknown")
    if status != "passed":
        raise ValueError("Controlled-live smoke timing must prove status passed.")
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
    smoke_node_ids = required_smoke_string_list(smoke_timing, "smoke_node_ids")
    assert_required_smoke_node_ids(smoke_node_ids)
    return {
        "status": status,
        "duration_seconds": finite_number(
            smoke_timing.get("duration_seconds"),
            "duration_seconds",
        ),
        "wait_sleep_seconds": finite_number(
            smoke_timing.get("wait_sleep_seconds"),
            "wait_sleep_seconds",
        ),
        "backend_git_commit": required_smoke_string(
            smoke_timing,
            "backend_git_commit",
        ),
        "backend_git_branch": required_smoke_string(
            smoke_timing,
            "backend_git_branch",
        ),
        "backend_contract_ref": required_smoke_string(
            smoke_timing,
            "backend_contract_ref",
        ),
        "command": command,
        "smoke_node_count": len(smoke_node_ids),
        "smoke_node_ids": smoke_node_ids,
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


def required_smoke_string(smoke_timing: Mapping[str, Any], field_name: str) -> str:
    """Return a required non-empty smoke timing string."""

    value = non_empty_string(smoke_timing.get(field_name), "")
    if not value:
        raise ValueError(f"Controlled-live smoke timing is missing {field_name}.")
    return value


def required_smoke_string_list(
    smoke_timing: Mapping[str, Any],
    field_name: str,
) -> list[str]:
    """Return a required non-empty list of smoke timing strings."""

    value = smoke_timing.get(field_name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"Controlled-live smoke timing is missing {field_name}.")
    string_values = [item for item in value if isinstance(item, str) and item.strip()]
    if len(string_values) != len(value):
        raise ValueError(f"Controlled-live smoke timing has invalid {field_name}.")
    return string_values


def assert_required_smoke_node_ids(smoke_node_ids: Sequence[str]) -> None:
    """Fail when controlled-live smoke evidence omits required test nodes."""

    missing_node_ids = [
        node_id for node_id in SMOKE_NODE_IDS if node_id not in smoke_node_ids
    ]
    if missing_node_ids:
        raise ValueError(
            "Controlled-live smoke timing is missing required smoke nodes: "
            + ", ".join(missing_node_ids)
        )


def finite_number(value: Any, label: str) -> float:
    """Return a non-negative finite float."""

    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"Controlled-live smoke timing has invalid {label}.")
    number = float(value)
    if number < 0:
        raise ValueError(f"Controlled-live smoke timing has invalid {label}.")
    return number


def assert_archive_exists(archive_path: Path) -> None:
    """Fail when the packaged backend deployment artifact is missing."""

    if not archive_path.exists():
        raise FileNotFoundError(
            f"{archive_path} is missing. Run the deployment packaging step first."
        )
    if not archive_path.is_file():
        raise ValueError(f"{archive_path} must be a file.")


def assert_deployment_manifest(
    manifest_path: Path,
    commit: str,
    deployment_tier: str,
) -> None:
    """Fail unless the deployment manifest matches local deployment metadata."""

    manifest = read_json(
        manifest_path,
        missing_message=(
            f"{manifest_path} is missing. Run python "
            "tools/write_admin_api_deployment_manifest.py before local deployment."
        ),
    )
    assert_manifest_commit(manifest, manifest_path, commit)
    assert_manifest_local(manifest, manifest_path, deployment_tier)
    assert_manifest_no_live(manifest, manifest_path)


def assert_manifest_commit(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    commit: str,
) -> None:
    """Fail when the deployment manifest commit differs from the release commit."""

    manifest_commit = non_empty_string(manifest.get("commit"), "missing")
    payload_commit = non_empty_string(commit, "unknown")
    if manifest_commit != payload_commit:
        raise ValueError(
            "Backend local deployment commit must match deployment manifest: "
            f"{manifest_path} commit {manifest_commit} != {payload_commit}."
        )


def assert_manifest_local(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    deployment_tier: str,
) -> None:
    """Fail unless the backend deployment manifest is local-only."""

    manifest_tier = non_empty_string(manifest.get("deployment_tier"), "missing")
    if manifest_tier != deployment_tier or deployment_tier != DEFAULT_ENVIRONMENT:
        raise ValueError(
            "Backend deployment manifest must target local deployment only: "
            f"{manifest_path} has deployment_tier={manifest_tier}."
        )


def assert_manifest_no_live(manifest: Mapping[str, Any], manifest_path: Path) -> None:
    """Fail unless the deployment manifest proves no live Coinbase execution."""

    live_execution = non_empty_string(manifest.get("live_coinbase_execution"), "missing")
    notional_usdc = non_empty_string(manifest.get("notional_usdc"), "missing")
    if live_execution != "not_run" or notional_usdc != "0":
        raise ValueError(
            "Backend deployment manifest must prove live Coinbase execution "
            f"not_run and notional 0: {manifest_path} has "
            f"live_coinbase_execution={live_execution}, notional_usdc={notional_usdc}."
        )


def release_label(commit: str) -> str:
    """Return a filesystem-safe release directory name for a commit ref."""

    label = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in commit.strip()
    ).strip(".")
    return label[:80] or "unknown"


def assert_child_path(root: Path, child: Path, label: str) -> None:
    """Fail when a path would escape the local deployment root."""

    root_resolved = root.resolve()
    child_resolved = child.resolve()
    try:
        child_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} must stay inside local deploy root.") from exc


def remove_path(path: Path, root: Path) -> None:
    """Remove an existing deployment path after checking root containment."""

    if not path.exists():
        return
    assert_child_path(root, path, str(path))
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def extract_archive_safely(archive_path: Path, destination: Path) -> None:
    """Extract a tar archive without allowing paths to escape destination."""

    destination_resolved = destination.resolve()
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            if member.issym() or member.islnk():
                raise ValueError("Backend deployment archive must not contain links.")
            target = (destination / member.name).resolve()
            try:
                target.relative_to(destination_resolved)
            except ValueError as exc:
                raise ValueError(
                    "Backend deployment archive contains a path outside the "
                    f"local release directory: {member.name}"
                ) from exc
        archive.extractall(destination, filter="data")


def write_deployment_archive(
    *,
    source_root: Path,
    manifest_path: Path,
    archive_path: Path,
) -> None:
    """Write a gzipped deployment archive from known backend payload paths."""

    validate_required_payload(source_root)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in iter_payload_paths(source_root):
            add_payload_path(archive, source_root, path)
        archive.add(manifest_path, arcname=MANIFEST_NAME)


def add_payload_path(tar: tarfile.TarFile, source_root: Path, path: Path) -> None:
    """Add a file or filtered directory tree to the deployment archive."""

    if path.is_file():
        if should_package_path(path):
            tar.add(path, arcname=archive_name_for(source_root, path))
        return
    for child in path.rglob("*"):
        if child.is_file() and should_package_path(child):
            tar.add(child, arcname=archive_name_for(source_root, child))


def should_package_path(path: Path) -> bool:
    """Return True when a local file should be copied into the release."""

    if any(part in EXCLUDED_PACKAGE_NAMES for part in path.parts):
        return False
    return path.suffix not in EXCLUDED_PACKAGE_SUFFIXES


def iter_payload_paths(source_root: Path) -> list[Path]:
    """Return existing files and directories included in the backend artifact."""

    paths = []
    for relative_path in PAYLOAD_PATHS:
        path = source_root / relative_path
        if path.exists():
            paths.append(path)
    return paths


def validate_required_payload(source_root: Path) -> None:
    """Fail when the minimal local backend runtime files are absent."""

    missing = [
        relative_path
        for relative_path in REQUIRED_PAYLOAD_PATHS
        if not (source_root / relative_path).exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Backend local deployment payload is missing: " + ", ".join(missing)
        )


def archive_name_for(source_root: Path, path: Path) -> str:
    """Return a POSIX-style archive name for a source path."""

    return path.relative_to(source_root).as_posix()


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


def default_deploy_root(env: Mapping[str, str | None] = os.environ) -> Path:
    """Return the configured local deploy root or the repo-adjacent default."""

    value = env.get(LOCAL_DEPLOY_ROOT_ENV)
    if value and value.strip():
        return Path(value.strip())
    return Path.cwd().parent / DEFAULT_LOCAL_ROOT_NAME / DEFAULT_LOCAL_COMPONENT_NAME


def current_utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp for artifact metadata."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    """Create the local deployment parser."""

    parser = argparse.ArgumentParser(
        description="Apply the Admin API deployment artifact to a local target."
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        help="Optional backend source root to package before applying.",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_ARCHIVE_PATH,
        help=f"Packaged backend artifact. Defaults to {DEFAULT_ARCHIVE_PATH}.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help=f"Deployment manifest JSON. Defaults to {DEFAULT_MANIFEST_PATH}.",
    )
    parser.add_argument(
        "--smoke-timing",
        type=Path,
        default=DEFAULT_SMOKE_TIMING_PATH,
        help=f"Controlled-live smoke timing JSON. Defaults to {DEFAULT_SMOKE_TIMING_PATH}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Local deployment manifest output path. Defaults to {DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--deploy-root",
        type=Path,
        default=default_deploy_root(),
        help=(
            "Local deployment root. Defaults to "
            f"${LOCAL_DEPLOY_ROOT_ENV} or "
            f"../{DEFAULT_LOCAL_ROOT_NAME}/{DEFAULT_LOCAL_COMPONENT_NAME}."
        ),
    )
    parser.add_argument(
        "--target-name",
        default=DEFAULT_TARGET_NAME,
        help=f"Local deployment target name. Defaults to {DEFAULT_TARGET_NAME}.",
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
        "--deployment-tier",
        choices=DEPLOYMENT_TIERS,
        default=os.getenv("COINBASE_BACKEND_DEPLOYMENT_TIER", DEFAULT_ENVIRONMENT),
        help=f"Deployment tier label. Defaults to {DEFAULT_ENVIRONMENT}.",
    )
    parser.add_argument(
        "--generated-at",
        default=current_utc_timestamp(),
        help="Deployment generation timestamp.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, apply the release, and print no-live evidence."""

    args = build_parser().parse_args(argv)
    manifest = apply_local_deployment(
        archive_path=args.archive,
        manifest_path=args.manifest,
        smoke_timing_path=args.smoke_timing,
        output_path=args.output,
        deploy_root=args.deploy_root,
        target_name=args.target_name,
        repository=args.repository,
        commit=args.commit,
        deployment_tier=args.deployment_tier,
        generated_at=args.generated_at,
        source_root=args.source_root,
    )
    print(f"Backend local deployment manifest written: {args.output.resolve()}")
    print(f"Backend local deployment applied: {manifest['current_path']}")
    print("Live Coinbase execution: not run; notional $0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
