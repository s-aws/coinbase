"""Apply the Admin MVP backend artifact to the local deployment target."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tarfile
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import write_admin_api_deployment_manifest as deployment_manifest


DEFAULT_MANIFEST_PATH = deployment_manifest.DEFAULT_OUTPUT
DEFAULT_ARCHIVE_PATH = Path("artifacts") / deployment_manifest.ARCHIVE_NAME
LOCAL_MANIFEST_NAME = "coinbase-backend-local-deployment-manifest.json"
LOCAL_ARTIFACT_TYPE = "coinbase_admin_api_local_deployment_manifest"
PAYLOAD_PATHS = (
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
    "tools",
    "websocket",
    "configuration.py",
    "dashboard_server.py",
    "main.py",
    "products.json",
    "pyproject.toml",
    "README.md",
    "README.admin-api.md",
)
REQUIRED_PAYLOAD_PATHS = (
    "application/admin_api/mvp_service.py",
    "tools/run_admin_api.py",
    "pyproject.toml",
)
EXCLUDED_PACKAGE_NAMES = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}
EXCLUDED_PACKAGE_SUFFIXES = {".pyc", ".pyo"}


def apply_local_deployment(
    *,
    source_root: Path,
    manifest_path: Path,
    deploy_root: Path,
    archive_path: Path,
) -> dict[str, Any]:
    """Package and apply the backend release to coinbase-local/backend."""

    source_root = source_root.resolve()
    deploy_root = deploy_root.resolve()
    manifest = read_json_object(manifest_path)
    assert_local_manifest(manifest)
    validate_required_payload(source_root)

    release_name = compact_release_name(str(manifest.get("commit") or "unknown"))
    releases_root = deploy_root / "releases"
    release_path = releases_root / release_name
    current_path = deploy_root / "current"
    ensure_inside(deploy_root, release_path)
    ensure_inside(deploy_root, current_path)

    write_deployment_archive(
        source_root=source_root,
        manifest_path=manifest_path.resolve(),
        archive_path=archive_path.resolve(),
    )
    releases_root.mkdir(parents=True, exist_ok=True)
    remove_tree_inside(deploy_root, release_path)
    extract_archive(archive_path.resolve(), release_path)
    local_manifest = build_local_deployment_manifest(
        manifest=manifest,
        deploy_root=deploy_root,
        current_path=current_path,
        release_path=release_path,
    )
    write_json(release_path / LOCAL_MANIFEST_NAME, local_manifest)
    write_json(release_path / deployment_manifest.MANIFEST_NAME, manifest)

    remove_tree_inside(deploy_root, current_path)
    shutil.copytree(release_path, current_path)
    write_json(current_path / LOCAL_MANIFEST_NAME, local_manifest)
    write_json(current_path / deployment_manifest.MANIFEST_NAME, manifest)
    write_json(deploy_root / "current-release.json", local_manifest)
    return local_manifest


def build_local_deployment_manifest(
    *,
    manifest: Mapping[str, Any],
    deploy_root: Path,
    current_path: Path,
    release_path: Path,
) -> dict[str, Any]:
    """Return frontend-readable local backend release evidence."""

    return {
        "schema_version": "1",
        "artifact_type": LOCAL_ARTIFACT_TYPE,
        "generated_at": current_utc_timestamp(),
        "repository": non_empty(manifest.get("repository"), "local"),
        "commit": non_empty(manifest.get("commit"), "unknown"),
        "branch": non_empty(manifest.get("branch"), "unknown"),
        "environment": "local",
        "deployment_tier": "local",
        "target_name": non_empty(
            manifest.get("target_name"),
            deployment_manifest.DEFAULT_TARGET_NAME,
        ),
        "deploy_root": str(deploy_root),
        "current_path": str(current_path),
        "release_path": str(release_path),
        "artifact": deployment_manifest.ARCHIVE_NAME,
        "manifest": deployment_manifest.MANIFEST_NAME,
        "live_coinbase_execution": non_empty(
            manifest.get("live_coinbase_execution"),
            "unknown",
        ),
        "notional_usdc": non_empty(manifest.get("notional_usdc"), "0"),
    }


def write_deployment_archive(
    *,
    source_root: Path,
    manifest_path: Path,
    archive_path: Path,
) -> None:
    """Write a gzipped deployment archive from known backend payload paths."""

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as archive:
        for path in iter_payload_paths(source_root):
            add_payload_path(archive, source_root, path)
        archive.add(manifest_path, arcname=deployment_manifest.MANIFEST_NAME)


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


def extract_archive(archive_path: Path, release_path: Path) -> None:
    """Extract a deployment archive after verifying paths stay inside release."""

    release_path.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            target = (release_path / member.name).resolve()
            ensure_inside(release_path, target)
        archive.extractall(release_path, members=members, filter="data")


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


def assert_local_manifest(manifest: Mapping[str, Any]) -> None:
    """Fail when a deployment manifest is not for local deployment."""

    artifact_type = non_empty(manifest.get("artifact_type"), "")
    if artifact_type != "coinbase_admin_api_deployment_manifest":
        raise ValueError("Deployment manifest has the wrong artifact_type.")
    tier = non_empty(manifest.get("deployment_tier"), "")
    if tier != "local":
        raise ValueError("Backend local deployment requires deployment_tier=local.")


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object."""

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write a stable JSON object."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def archive_name_for(source_root: Path, path: Path) -> str:
    """Return a POSIX-style archive name for a source path."""

    return path.relative_to(source_root).as_posix()


def compact_release_name(value: str) -> str:
    """Return a filesystem-safe release folder name."""

    compact = "".join(
        char.lower() if char.isalnum() or char in "._-" else "-"
        for char in value.strip()
    ).strip("-")
    return compact[:120] or "unknown"


def ensure_inside(parent: Path, child: Path) -> None:
    """Fail unless child resolves inside parent."""

    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if child_resolved == parent_resolved:
        return
    try:
        child_resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"{child_resolved} must stay inside {parent_resolved}.") from exc


def remove_tree_inside(root: Path, target: Path) -> None:
    """Remove a directory after verifying it stays inside the deployment root."""

    ensure_inside(root, target)
    if target.exists():
        shutil.rmtree(target)


def non_empty(value: Any, fallback: str) -> str:
    """Return trimmed text or a fallback."""

    text = value.strip() if isinstance(value, str) else ""
    return text or fallback


def current_utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    """Create the local deployment apply parser."""

    parser = argparse.ArgumentParser(description="Apply backend local deployment.")
    parser.add_argument("--source-root", type=Path, default=Path("."))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE_PATH)
    parser.add_argument(
        "--deploy-root",
        type=Path,
        default=Path("..") / "coinbase-local" / "backend",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, apply the local deployment, and print release evidence."""

    args = build_parser().parse_args(argv)
    local_manifest = apply_local_deployment(
        source_root=args.source_root,
        manifest_path=args.manifest,
        deploy_root=args.deploy_root,
        archive_path=args.archive,
    )
    print(f"Backend local deployment target: {local_manifest['target_name']}")
    print(f"Backend local deployment current: {local_manifest['current_path']}")
    print(
        "Live Coinbase execution: "
        f"{local_manifest['live_coinbase_execution']}; "
        f"notional {local_manifest['notional_usdc']} USDC"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
