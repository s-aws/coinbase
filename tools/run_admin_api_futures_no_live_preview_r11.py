"""Prepare and consume the single audited Slice 2R11 Preview claim.

Preflight is fully offline: it validates the immutable R10 predecessor, the
installed SDK pin, and a disposable R11 claim without creating the production
artifact or hydrating credentials.  Confirmation remains fail-closed until a
separate constants-only audit activation binds the exact prepared revisions.
The live-capable surface exposes six fixed read categories and one Preview;
it has no Create, Cancel, Close, Reduce, retry, fallback, redirect, or accepted
session handoff path.
"""

from __future__ import annotations

import sys


_R11_PYCACHE_PREFIX = "/dev/null/r11"
if __name__ == "__main__" and (
    not sys.flags.isolated
    or not sys.flags.no_site
    or not sys.flags.dont_write_bytecode
    or sys.pycache_prefix != _R11_PYCACHE_PREFIX
):
    sys.stderr.write(
        '{"blocker":"futures_preview_r11_isolated_runtime_required",'
        '"status":"blocked"}\n'
    )
    raise SystemExit(2)


import argparse
import ast
import base64
from collections.abc import Callable, Mapping, Sequence
import csv
from datetime import datetime, timezone
from functools import partial
import hashlib
import importlib
import importlib.machinery
from importlib.metadata import distribution, version
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tomllib
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = REPO_ROOT.parent / "coinbase-frontend"

_AUDIT_BINDING_START = "# BEGIN R11 AUDIT BINDINGS\n"
_AUDIT_BINDING_END = "# END R11 AUDIT BINDINGS\n"
_AUDIT_BINDING_PLACEHOLDER = (
    "# BEGIN R11 AUDIT BINDINGS\n"
    "if False:\n"
    "    pass  # normalized audited activation bindings\n"
    "# END R11 AUDIT BINDINGS\n"
)
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_AUDIT_BINDING_SCALAR_NAMES = (
    "R11_PREVIEW_CALL_AUTHORITY_ACTIVE",
    "R11_FINAL_AUDIT_BINDING_READY",
    "R11_PREPARATION_REVISION",
    "R11_FRONTEND_REVISION",
    "R11_NORMALIZED_RUNNER_SHA256",
    "R11_AUTHORIZATION_SHA256",
    "R11_SAFETY_AUDIT_RECEIPT_SHA256",
    "R11_BLIND_AUDIT_RECEIPT_SHA256",
    "R11_ACTIVATION_NOT_AFTER",
)
_AUDIT_BINDING_HASH_NAMES = _AUDIT_BINDING_SCALAR_NAMES[2:-1]
_R11_RUNNER_RELATIVE_PATH = "tools/run_admin_api_futures_no_live_preview_r11.py"
_FIXED_R11_PRODUCTION_ARTIFACT_PATH = (
    REPO_ROOT / "artifacts" / "futures_exact_no_live_preview_slice_2r11.jsonl"
)
_R11_EXPECTED_COMPONENTS = frozenset(
    {
        "backend:.agents/ownership.yaml",
        "backend:api/v1/routes/futures.py",
        "backend:application/admin_api/futures_order_preview.py",
        "backend:application/admin_api/models.py",
        "backend:docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
        "backend:docs/FUTURES_SLICE_2R11_PREPARATION.md",
        "backend:docs/MAINTAINER_HANDOFF.md",
        "backend:docs/README.md",
        "backend:external/coinbase_client.py",
        "backend:genai_data/AGENT_MVP_REBUILD_GOAL.md",
        "backend:openapi/coinbase-admin-api.yaml",
        "backend:pyproject.toml",
        "backend:README.admin-api.md",
        "backend:tests/unit/test_admin_api_futures_order_preview.py",
        "backend:tests/unit/test_run_admin_api_futures_no_live_preview_r11.py",
        "backend:tests/regression/test_spot_readiness_gate.py",
        "backend:tools/coinbase_live_credentials.py",
        "backend:tools/run_admin_api_futures_no_live_preview.py",
        "backend:tools/run_autonomous_work_queue_check.py",
        "frontend:AGENTS.md",
        "frontend:README.admin-frontend.md",
        "frontend:docs/ADMIN_MODULE_CAPABILITY_MATRIX.md",
        "frontend:docs/API_CONTRACT.md",
        "frontend:docs/CURRENT_MVP_GOAL.md",
        "frontend:docs/FUTURES_PERPETUALS_READS.md",
        "frontend:docs/HUMAN_OPERATOR_RUNBOOK.md",
        "frontend:docs/MAINTAINER_HANDOFF.md",
        "frontend:docs/ORIGIN_PROD_FEATURE_MVP_MAP.md",
        "frontend:docs/TESTING.md",
        "frontend:docs/plans/AUTONOMOUS_WORK_QUEUE.md",
        "frontend:docs/plans/MVP_BLOCKER_LEDGER.md",
        "frontend:scripts/check-autonomous-work-queue.mjs",
        "frontend:scripts/check-deployment-readiness.mjs",
        "frontend:scripts/check-mvp-goal-alignment.mjs",
        "frontend:scripts/run-vitest.mjs",
        "frontend:src/features/futures-perpetuals/FuturesPerpetualsReadModel.tsx",
        "frontend:src/features/futures-perpetuals/futuresPerpetualsBackendAdapters.ts",
        "frontend:src/shared/api/generated/schema.ts",
        "frontend:src/shared/quality/artifactContract.json",
        "frontend:src/shared/quality/deploymentReadiness.ts",
        "frontend:tests/unit/FuturesOrderPreviewReadback.test.tsx",
        "frontend:tests/unit/qualityGates.test.tsx",
        "frontend:vitest.config.ts",
    }
)
_R11_SDK_SOURCE_SHA256 = {
    "coinbase/rest/orders.py": (
        "c3d34a3583dea07d69f9f06c5691be02f77b08d3a37b102b40666090e40cea06"
    ),
    "coinbase/rest/rest_base.py": (
        "05708e76001707ea56c45ec680ac5305b2a51061ed0122840f446930845d1cec"
    ),
    "coinbase/rest/types/base_response.py": (
        "89e40f2f95020a5ea1a4323200a2473c30681b9de4ce8a0de561ec4c739e5989"
    ),
    "coinbase/rest/types/orders_types.py": (
        "19552322d672d194aad8cf91b7a07038360c6d9504ac4fce1e7524b7728317b2"
    ),
}
_R11_DEPENDENCY_SITE = Path(
    "/home/developer/.local/lib/python3.13/site-packages"
)
_R11_SYSTEM_DEPENDENCY_SITE = Path("/usr/local/lib/python3.13/site-packages")
_R11_SDK_DIST_INFO_NAME = "coinbase_advanced_py-1.8.4.dist-info"
_R11_SDK_RECORD_SHA256 = (
    "40430123aeb0b6b38b333b676c0b5775b86188e5082ee2bbb54f337d48edeba1"
)
_R11_SDK_REQUIRED_MODULES = (
    "coinbase",
    "coinbase.rest",
    "coinbase.rest.orders",
    "coinbase.rest.rest_base",
    "coinbase.rest.types.base_response",
    "coinbase.rest.types.orders_types",
)
_R11_RUNTIME_DEPENDENCIES: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "coinbase-advanced-py",
        "1.8.4",
        "/home/developer/.local/lib/python3.13/site-packages",
        "coinbase_advanced_py-1.8.4.dist-info",
        "coinbase",
        "40430123aeb0b6b38b333b676c0b5775b86188e5082ee2bbb54f337d48edeba1",
    ),
    (
        "requests",
        "2.34.2",
        "/home/developer/.local/lib/python3.13/site-packages",
        "requests-2.34.2.dist-info",
        "requests",
        "2e48b2db823e566cd0e9c99df87dfa6117fe020e6519f3f9909f4470291fab4b",
    ),
    (
        "urllib3",
        "2.7.0",
        "/usr/local/lib/python3.13/site-packages",
        "urllib3-2.7.0.dist-info",
        "urllib3",
        "bab9edcf76ec02bac68329df0e7de530efcbd3dc131551f5f86a83ff4d087106",
    ),
    (
        "PyJWT",
        "2.13.0",
        "/home/developer/.local/lib/python3.13/site-packages",
        "pyjwt-2.13.0.dist-info",
        "jwt",
        "e66ede74c7a4eaef0332c82e25c313c183114ecb993cae8c2d9a72efe89cdf27",
    ),
    (
        "cryptography",
        "49.0.0",
        "/home/developer/.local/lib/python3.13/site-packages",
        "cryptography-49.0.0.dist-info",
        "cryptography",
        "8aef53314efc7136ef9aafcaf3da40e9b2b2d71086e969f354e9f744f14b5be5",
    ),
    (
        "cffi",
        "2.1.0",
        "/home/developer/.local/lib/python3.13/site-packages",
        "cffi-2.1.0.dist-info",
        "cffi",
        "b4126874ee638ae57d4b6291a819e92c0ba4e4cf538ca4cec3ee360fc28d243a",
    ),
    (
        "certifi",
        "2026.6.17",
        "/usr/local/lib/python3.13/site-packages",
        "certifi-2026.6.17.dist-info",
        "certifi",
        "99d26202d832e6cde4539b481e5956858b5e051bdc7f407f101e03b4319e4c4c",
    ),
    (
        "charset-normalizer",
        "3.4.9",
        "/home/developer/.local/lib/python3.13/site-packages",
        "charset_normalizer-3.4.9.dist-info",
        "charset_normalizer",
        "ce77d38b745a896acd0f012d1300fa4afea386d991835c943dec27d74fb9e963",
    ),
    (
        "idna",
        "3.18",
        "/usr/local/lib/python3.13/site-packages",
        "idna-3.18.dist-info",
        "idna",
        "0d15c3a9678cec4de0ae64abb7f85a636e44dea89d15f73c94d58e24ffaae78f",
    ),
    (
        "backoff",
        "2.2.1",
        "/home/developer/.local/lib/python3.13/site-packages",
        "backoff-2.2.1.dist-info",
        "backoff",
        "ac9598ad7ca72d341773345bce960fd6b392f38d33ef1766a4d752a23f794b6e",
    ),
    (
        "websockets",
        "13.1",
        "/home/developer/.local/lib/python3.13/site-packages",
        "websockets-13.1.dist-info",
        "websockets",
        "9ce8a817feeced95d3a864c5c14bf964a21fc572b8f7649d58f377140032e802",
    ),
    (
        "pydantic",
        "2.13.4",
        "/home/developer/.local/lib/python3.13/site-packages",
        "pydantic-2.13.4.dist-info",
        "pydantic",
        "774c7cbfbb195bcfebdd1b6b3f0ea3ce47fad225b8b1e8e172c5864dec34a358",
    ),
    (
        "pydantic_core",
        "2.46.4",
        "/home/developer/.local/lib/python3.13/site-packages",
        "pydantic_core-2.46.4.dist-info",
        "pydantic_core",
        "cf9ba47e87c106a9c3a90175556a5e62b66bc0747e754f5d31441314910e7318",
    ),
    (
        "annotated-types",
        "0.7.0",
        "/home/developer/.local/lib/python3.13/site-packages",
        "annotated_types-0.7.0.dist-info",
        "annotated_types",
        "f7c0160ccf09bebdec2eb160bb86d1a170670af060991dd2b16299da91a43b84",
    ),
    (
        "typing-inspection",
        "0.4.2",
        "/home/developer/.local/lib/python3.13/site-packages",
        "typing_inspection-0.4.2.dist-info",
        "typing_inspection",
        "0f03ce122a0ee9bbadaf2877040b7b14ca553bdead97797be3333171f7ab153c",
    ),
    (
        "typing_extensions",
        "4.16.0",
        "/usr/local/lib/python3.13/site-packages",
        "typing_extensions-4.16.0.dist-info",
        "typing_extensions.py",
        "87c5132ed922c2e300fd3c36b828e1b3694f2e2ac38f26f556064c4bf3d9af81",
    ),
    (
        "PySocks",
        "1.7.1",
        "/usr/local/lib/python3.13/site-packages",
        "PySocks-1.7.1.dist-info",
        "socks.py",
        "c82333a9b7743d58eb07ca1721d35803bbcdc42a048c8154133d142151c5be91",
    ),
)
_R11_RUNTIME_DEPENDENCY_BINDING_SHA256 = (
    "2119cad7e5d47201a637511c61944ff01be7b5708cb642be8da8634edb8f1541"
)
_R11_RUNTIME_SITE_ROOTS = tuple(
    dict.fromkeys(specification[2] for specification in _R11_RUNTIME_DEPENDENCIES)
)
_R11_VERIFIED_DEPENDENCY_FILES: set[str] = set()
_R11_VERIFIED_DEPENDENCY_BINDINGS: dict[str, tuple[object, ...]] = {}
_R11_VERIFIED_IMPORT_TOP_LEVELS: set[str] = set()
_R11_TRACKED_BACKEND_IMPORT_FILES: set[str] = set()
_R11_MAX_DEPENDENCY_FILE_BYTES = 64 * 1024 * 1024
_R11_AWS_CLI_VERSION_ROOT = Path(
    "/home/developer/.local/aws-cli/v2/2.35.24"
)
_R11_AWS_CLI_CANONICAL_PATH = _R11_AWS_CLI_VERSION_ROOT / "dist" / "aws"
_R11_AWS_CLI_CA_BUNDLE = (
    _R11_AWS_CLI_VERSION_ROOT / "dist" / "awscli" / "botocore" / "cacert.pem"
)
_R11_AWS_CLI_SHA256 = (
    "cf06831bd626c1132effdff0c403cc115ae15fe83aaf455f43e504c148d344e5"
)
_R11_AWS_CLI_VERSION_OUTPUT = (
    "aws-cli/2.35.24 Python/3.14.6 "
    "Linux/6.18.33.2-microsoft-standard-WSL2 exe/x86_64.debian.12"
)
_R11_AWS_CLI_TREE_ENTRY_COUNT = 8649
_R11_AWS_CLI_TREE_FILE_BYTES = 254415287
_R11_AWS_CLI_TREE_SHA256 = (
    "ec5b4574cc2fd9ee0f91afe7cef682a52ded5ac98faeae9bbc23b0b6f04ff7c1"
)
_R11_MAX_AWS_SECRET_RESPONSE_BYTES = 128 * 1024
_FRONTEND_INERT_UNTRACKED_SHA256 = {
    "coinbase-admin-live-root-child-chain-2026-07-11.png": (
        "a38b6a6bdca3073cca7245cfece2783b82e9414267bff421fcd97ad7d5e79cec"
    ),
    "coinbase-admin-live-root-child-chain-complete-2026-07-12.png": (
        "5b0057de8d4e9e0757341cdb95dcaace979cef72f12f3da2cda9f1b72c5697b6"
    ),
    "coinbase-admin-spot-operations-2026-07-11.png": (
        "4c65c473dd7cd3ffb155a6623545578f08cd6caf72db43c387b5bcc7da131244"
    ),
    "selected-order-execution-closeout-v14.png": (
        "020fa080228ab52ab3d318fda112e48efb1f27532418e999abfdb4bd54cbbb1d"
    ),
}
_R11_DEFERRED_CALLS = (
    "api_key_permissions",
    "portfolio_catalog",
    "product",
    "best_bid_ask",
    "futures_positions",
    "futures_margin_collateral",
    "preview_order",
)


def _literal_audit_binding_values(block: str) -> dict[str, object]:
    """Parse the inert activation suite without evaluating any expression."""

    parsed = ast.parse(block, mode="exec")
    if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.If):
        raise ValueError("wrapper")
    wrapper = parsed.body[0]
    if (
        not isinstance(wrapper.test, ast.Constant)
        or wrapper.test.value is not False
        or wrapper.orelse
        or len(wrapper.body) != len(_AUDIT_BINDING_SCALAR_NAMES) + 1
    ):
        raise ValueError("wrapper")
    values: dict[str, object] = {}
    for expected_name, statement in zip(
        _AUDIT_BINDING_SCALAR_NAMES,
        wrapper.body[:-1],
        strict=True,
    ):
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not isinstance(statement.targets[0], ast.Name)
            or statement.targets[0].id != expected_name
            or statement.type_comment is not None
        ):
            raise ValueError("scalar_assignment")
        values[expected_name] = ast.literal_eval(statement.value)
    component_statement = wrapper.body[-1]
    if (
        not isinstance(component_statement, ast.AnnAssign)
        or not isinstance(component_statement.target, ast.Name)
        or component_statement.target.id != "R11_AUDITED_COMPONENT_SHA256"
        or ast.unparse(component_statement.annotation) != "dict[str, str]"
        or component_statement.value is None
        or component_statement.simple != 1
        or not isinstance(component_statement.value, ast.Dict)
    ):
        raise ValueError("component_assignment")
    component_keys = [
        ast.literal_eval(key) for key in component_statement.value.keys
    ]
    if (
        any(not isinstance(key, str) for key in component_keys)
        or len(component_keys) != len(set(component_keys))
        or any(
            not isinstance(value, ast.Constant)
            or not isinstance(value.value, str)
            for value in component_statement.value.values
        )
    ):
        raise ValueError("component_literals")
    components = ast.literal_eval(component_statement.value)
    values["R11_AUDITED_COMPONENT_SHA256"] = components
    active = (
        values["R11_PREVIEW_CALL_AUTHORITY_ACTIVE"] is True
        and values["R11_FINAL_AUDIT_BINDING_READY"] is True
        and all(
            isinstance(values[name], str)
            and _HEX_SHA256.fullmatch(values[name]) is not None
            for name in _AUDIT_BINDING_HASH_NAMES
        )
        and isinstance(values["R11_ACTIVATION_NOT_AFTER"], str)
        and bool(values["R11_ACTIVATION_NOT_AFTER"])
        and isinstance(components, dict)
        and set(components) == _R11_EXPECTED_COMPONENTS
        and all(
            isinstance(key, str)
            and isinstance(value, str)
            and _HEX_SHA256.fullmatch(value) is not None
            for key, value in components.items()
        )
    )
    inactive = (
        values["R11_PREVIEW_CALL_AUTHORITY_ACTIVE"] is False
        and values["R11_FINAL_AUDIT_BINDING_READY"] is False
        and all(values[name] == "" for name in _AUDIT_BINDING_HASH_NAMES)
        and values["R11_ACTIVATION_NOT_AFTER"] == ""
        and components == {}
    )
    if not active and not inactive:
        raise ValueError("binding_state")
    if active:
        if component_keys != sorted(_R11_EXPECTED_COMPONENTS):
            raise ValueError("component_order")
        activation = datetime.fromisoformat(
            str(values["R11_ACTIVATION_NOT_AFTER"]).replace("Z", "+00:00")
        )
        if activation.tzinfo is None:
            raise ValueError("activation_timezone")
    return values


def _audit_binding_block(text: str) -> tuple[str, int, int]:
    if text.count(_AUDIT_BINDING_START) != 1 or text.count(
        _AUDIT_BINDING_END
    ) != 1:
        raise ValueError("markers")
    start = text.index(_AUDIT_BINDING_START)
    end = text.index(_AUDIT_BINDING_END, start) + len(_AUDIT_BINDING_END)
    return text[start:end], start, end


def _bootstrap_file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _recorded_sdk_paths() -> set[str]:
    metadata_root = _R11_DEPENDENCY_SITE / _R11_SDK_DIST_INFO_NAME
    record_path = metadata_root / "RECORD"
    if _bootstrap_file_sha256(record_path) != _R11_SDK_RECORD_SHA256:
        raise ValueError("record_hash")
    rows = list(csv.reader(record_path.read_text(encoding="utf-8").splitlines()))
    record_relative = f"{_R11_SDK_DIST_INFO_NAME}/RECORD"
    recorded: set[str] = set()
    for row in rows:
        if len(row) != 3:
            raise ValueError("record_row")
        raw_relative, encoded_hash, encoded_size = row
        relative = PurePosixPath(raw_relative)
        if (
            not raw_relative
            or relative.is_absolute()
            or relative.as_posix() != raw_relative
            or any(part in {"", ".", ".."} for part in relative.parts)
            or raw_relative in recorded
        ):
            raise ValueError("record_path")
        recorded.add(raw_relative)
        target = _R11_DEPENDENCY_SITE.joinpath(*relative.parts)
        current = _R11_DEPENDENCY_SITE
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("record_symlink")
        if raw_relative == record_relative:
            if encoded_hash or encoded_size:
                raise ValueError("record_self_row")
            continue
        if not encoded_hash and not encoded_size:
            if "__pycache__" not in relative.parts:
                raise ValueError("record_unhashed")
            continue
        algorithm, separator, expected_digest = encoded_hash.partition("=")
        if (
            algorithm != "sha256"
            or not separator
            or not encoded_size.isascii()
            or not encoded_size.isdigit()
            or not stat.S_ISREG(target.lstat().st_mode)
            or target.stat().st_size != int(encoded_size)
        ):
            raise ValueError("record_metadata")
        observed_digest = base64.urlsafe_b64encode(
            hashlib.sha256(target.read_bytes()).digest()
        ).rstrip(b"=").decode("ascii")
        if observed_digest != expected_digest:
            raise ValueError("record_digest")
    if record_relative not in recorded:
        raise ValueError("record_self_missing")
    return recorded


def _bootstrap_read_regular(
    path: Path,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> bytes:
    """Read one stable, non-linked, non-writable provenance-bound file."""

    before = path.lstat()
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or (before.st_size == 0 and not allow_empty)
        or before.st_size > maximum_bytes
        or stat.S_IMODE(before.st_mode) & 0o022
    ):
        raise ValueError("regular_file")
    identity = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_uid,
        before.st_gid,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    with path.open("rb") as handle:
        payload = handle.read(maximum_bytes + 1)
        opened = os.fstat(handle.fileno())
    after = path.lstat()
    opened_identity = (
        opened.st_dev,
        opened.st_ino,
        opened.st_mode,
        opened.st_uid,
        opened.st_gid,
        opened.st_nlink,
        opened.st_size,
        opened.st_mtime_ns,
        opened.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_uid,
        after.st_gid,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if (
        identity != opened_identity
        or identity != after_identity
        or len(payload) != before.st_size
        or len(payload) > maximum_bytes
    ):
        raise ValueError("unstable_file")
    return payload


def _runtime_file_binding(path: Path) -> tuple[object, ...]:
    """Bind content plus file identity for immediate import-time rechecks."""

    payload = _bootstrap_read_regular(
        path,
        maximum_bytes=_R11_MAX_DEPENDENCY_FILE_BYTES,
        allow_empty=True,
    )
    metadata = path.lstat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        hashlib.sha256(payload).hexdigest(),
    )


def _runtime_distribution_target(site_root: Path, relative: str) -> Path:
    """Resolve a RECORD row within its fixed installation prefix."""

    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or "\\" in relative
        or "\x00" in relative
        or any(part in {"", "."} for part in pure.parts)
        or pure.as_posix() != relative
    ):
        raise ValueError("record_path")
    lexical = Path(os.path.abspath(site_root.joinpath(*pure.parts)))
    installation_root = (
        Path("/home/developer/.local")
        if str(site_root).startswith("/home/developer/.local/")
        else Path("/usr/local")
    )
    if (
        os.path.commonpath((str(lexical), str(installation_root)))
        != str(installation_root)
        or os.path.realpath(lexical) != str(lexical)
    ):
        raise ValueError("record_path")
    return lexical


def _runtime_import_file(path: Path) -> bool:
    name = path.name
    return name.endswith((".py", ".pyd", ".so")) or (
        bool(importlib.machinery.EXTENSION_SUFFIXES)
        and name.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES))
    )


def _verify_runtime_distribution(
    specification: tuple[str, str, str, str, str, str],
) -> dict[str, str]:
    """Verify every hashed RECORD row and every importable package file."""

    (
        name,
        expected_version,
        site_root_text,
        dist_info_name,
        package_name,
        record_sha256,
    ) = specification
    site_root = Path(site_root_text)
    if (
        site_root.is_symlink()
        or not stat.S_ISDIR(site_root.lstat().st_mode)
        or stat.S_IMODE(site_root.lstat().st_mode) & 0o022
    ):
        raise ValueError("site_root")

    dist_prefix = dist_info_name.partition("-")[0] + "-"
    observed_metadata = {
        str(candidate)
        for root_text in _R11_RUNTIME_SITE_ROOTS
        for candidate in Path(root_text).glob(f"{dist_prefix}*.dist-info")
    }
    expected_metadata = str(site_root / dist_info_name)
    if observed_metadata != {expected_metadata}:
        raise ValueError("duplicate_distribution")
    for root_text in _R11_RUNTIME_SITE_ROOTS:
        alternate = Path(root_text) / package_name
        if Path(root_text) != site_root and (
            alternate.exists() or alternate.is_symlink()
        ):
            raise ValueError("duplicate_package")

    metadata_root = site_root / dist_info_name
    if metadata_root.is_symlink() or not stat.S_ISDIR(
        metadata_root.lstat().st_mode
    ):
        raise ValueError("dist_info")
    record_relative = f"{dist_info_name}/RECORD"
    record_path = metadata_root / "RECORD"
    record_payload = _bootstrap_read_regular(
        record_path,
        maximum_bytes=512 * 1024,
    )
    if hashlib.sha256(record_payload).hexdigest() != record_sha256:
        raise ValueError("record_hash")
    try:
        rows = list(csv.reader(record_payload.decode("utf-8").splitlines()))
    except (csv.Error, UnicodeDecodeError):
        raise ValueError("record_encoding") from None

    seen: set[str] = set()
    hashed_relative_paths: set[str] = set()
    for row in rows:
        if len(row) != 3 or not row[0] or row[0] in seen:
            raise ValueError("record_row")
        relative, encoded_hash, size_text = row
        seen.add(relative)
        target = _runtime_distribution_target(site_root, relative)
        if not encoded_hash:
            if relative == record_relative:
                if size_text:
                    raise ValueError("record_self")
                continue
            if (
                "__pycache__" not in PurePosixPath(relative).parts
                or not relative.endswith((".pyc", ".pyo"))
                or size_text
            ):
                raise ValueError("record_unhashed")
            continue
        algorithm, separator, expected_encoded = encoded_hash.partition("=")
        if algorithm != "sha256" or not separator or not size_text.isdigit():
            raise ValueError("record_metadata")
        payload = _bootstrap_read_regular(
            target,
            maximum_bytes=_R11_MAX_DEPENDENCY_FILE_BYTES,
            allow_empty=True,
        )
        observed_encoded = base64.urlsafe_b64encode(
            hashlib.sha256(payload).digest()
        ).rstrip(b"=").decode("ascii")
        if observed_encoded != expected_encoded or len(payload) != int(size_text):
            raise ValueError("record_digest")
        hashed_relative_paths.add(relative)
        absolute_target = str(target)
        _R11_VERIFIED_DEPENDENCY_FILES.add(absolute_target)
        _R11_VERIFIED_DEPENDENCY_BINDINGS[absolute_target] = (
            _runtime_file_binding(target)
        )

    metadata_relative = f"{dist_info_name}/METADATA"
    if record_relative not in seen or metadata_relative not in hashed_relative_paths:
        raise ValueError("record_required_rows")
    metadata_payload = _bootstrap_read_regular(
        metadata_root / "METADATA",
        maximum_bytes=2 * 1024 * 1024,
    )
    try:
        metadata_lines = metadata_payload.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        raise ValueError("metadata_encoding") from None
    if (
        metadata_lines.count(f"Name: {name}") != 1
        or metadata_lines.count(f"Version: {expected_version}") != 1
    ):
        raise ValueError("metadata_version")

    package_root = site_root / package_name
    if package_root.is_symlink() or not (
        package_root.is_dir() or stat.S_ISREG(package_root.lstat().st_mode)
    ):
        raise ValueError("package_root")
    candidates: list[Path] = []
    if package_root.is_dir():
        for directory, directories, filenames in os.walk(
            package_root,
            followlinks=False,
        ):
            directory_path = Path(directory)
            if any((directory_path / child).is_symlink() for child in directories):
                raise ValueError("package_symlink")
            candidates.extend(directory_path / filename for filename in filenames)
    else:
        candidates.append(package_root)
    for candidate in candidates:
        if candidate.is_symlink():
            raise ValueError("package_symlink")
        if _runtime_import_file(candidate):
            relative = candidate.relative_to(site_root).as_posix()
            if (
                relative not in hashed_relative_paths
                or str(candidate.resolve()) not in _R11_VERIFIED_DEPENDENCY_FILES
            ):
                raise ValueError("unrecorded_import")

    top_level = package_name.removesuffix(".py")
    _R11_VERIFIED_IMPORT_TOP_LEVELS.add(top_level)
    return {
        "name": name,
        "version": expected_version,
        "site_root": site_root_text,
        "record_sha256": record_sha256,
    }


def _verify_runtime_dependencies() -> bool:
    """Verify the complete imported dependency closure and canonical binding."""

    try:
        _R11_VERIFIED_DEPENDENCY_FILES.clear()
        _R11_VERIFIED_DEPENDENCY_BINDINGS.clear()
        _R11_VERIFIED_IMPORT_TOP_LEVELS.clear()
        packages = [
            _verify_runtime_distribution(specification)
            for specification in _R11_RUNTIME_DEPENDENCIES
        ]
        binding = {
            "schema_version": "r11-runtime-dependency-binding-v1",
            "packages": packages,
        }
        digest = hashlib.sha256(
            json.dumps(
                binding,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return digest == _R11_RUNTIME_DEPENDENCY_BINDING_SHA256
    except (OSError, UnicodeError, ValueError):
        _R11_VERIFIED_DEPENDENCY_FILES.clear()
        _R11_VERIFIED_DEPENDENCY_BINDINGS.clear()
        _R11_VERIFIED_IMPORT_TOP_LEVELS.clear()
        return False


def _runtime_dependency_spec_is_verified(specification: object) -> bool:
    """Return whether an import spec is outside site roots or RECORD-bound."""

    origin = getattr(specification, "origin", None)
    locations = getattr(specification, "submodule_search_locations", None) or ()
    if origin in {None, "built-in", "frozen"}:
        for location in locations:
            absolute_location = os.path.abspath(str(location))
            for root in _R11_RUNTIME_SITE_ROOTS:
                try:
                    if os.path.commonpath((absolute_location, root)) == root:
                        return False
                except ValueError:
                    return False
            try:
                repository_location = (
                    os.path.commonpath(
                        (absolute_location, str(REPO_ROOT))
                    )
                    == str(REPO_ROOT)
                    and any(
                        candidate.startswith(absolute_location + os.sep)
                        for candidate in _R11_TRACKED_BACKEND_IMPORT_FILES
                    )
                )
                stdlib_location = (
                    os.path.commonpath(
                        (absolute_location, "/usr/local/lib/python3.13")
                    )
                    == "/usr/local/lib/python3.13"
                )
            except ValueError:
                return False
            if not repository_location and not stdlib_location:
                return False
        return True
    absolute_origin = os.path.abspath(str(origin))
    for root in _R11_RUNTIME_SITE_ROOTS:
        try:
            inside = os.path.commonpath((absolute_origin, root)) == root
        except ValueError:
            return False
        if inside:
            expected_binding = _R11_VERIFIED_DEPENDENCY_BINDINGS.get(
                absolute_origin
            )
            if (
                os.path.realpath(absolute_origin) != absolute_origin
                or absolute_origin not in _R11_VERIFIED_DEPENDENCY_FILES
                or expected_binding is None
            ):
                return False
            try:
                return _runtime_file_binding(Path(absolute_origin)) == (
                    expected_binding
                )
            except (OSError, ValueError):
                return False
    try:
        if (
            os.path.commonpath((absolute_origin, str(REPO_ROOT)))
            == str(REPO_ROOT)
        ):
            return (
                os.path.realpath(absolute_origin) == absolute_origin
                and absolute_origin in _R11_TRACKED_BACKEND_IMPORT_FILES
            )
        stdlib_root = "/usr/local/lib/python3.13"
        return (
            os.path.commonpath((absolute_origin, stdlib_root)) == stdlib_root
            and os.path.realpath(absolute_origin) == absolute_origin
        ) or absolute_origin.startswith("/usr/local/lib/python313.zip/")
    except ValueError:
        return False


class _R11VerifiedDependencyFinder:
    """Reject site-root imports unless their exact origin was RECORD-verified."""

    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        specification = importlib.machinery.PathFinder.find_spec(
            fullname,
            path,
            target,
        )
        if specification is not None and not _runtime_dependency_spec_is_verified(
            specification
        ):
            raise ImportError("futures_preview_r11_unverified_dependency_import")
        return specification


def _install_runtime_dependency_guard() -> None:
    if not _R11_VERIFIED_DEPENDENCY_FILES:
        raise ValueError("dependency_binding")
    try:
        index = sys.meta_path.index(importlib.machinery.PathFinder)
    except ValueError:
        raise ValueError("path_finder") from None
    if _R11VerifiedDependencyFinder not in sys.meta_path:
        sys.meta_path.insert(index, _R11VerifiedDependencyFinder)


def _runtime_module_origins_are_bound(
    modules: Mapping[str, object],
    *,
    closure_only: bool,
) -> bool:
    try:
        for name, module in modules.items():
            if closure_only and name.partition(".")[0] not in (
                _R11_VERIFIED_IMPORT_TOP_LEVELS
            ):
                continue
            origin = getattr(module, "__file__", None)
            locations = getattr(module, "__path__", None)
            specification = type(
                "_R11ObservedSpec",
                (),
                {
                    "origin": origin,
                    "submodule_search_locations": locations,
                },
            )()
            if not _runtime_dependency_spec_is_verified(specification):
                return False
    except (OSError, TypeError, ValueError):
        return False
    return True


def _aws_cli_tree_sha256() -> str:
    digest = hashlib.sha256()
    entry_count = 0
    file_bytes = 0
    allowed_links = {
        "bin/aws": "../dist/aws",
        "bin/aws_completer": "../dist/aws_completer",
    }
    entries = sorted(
        _R11_AWS_CLI_VERSION_ROOT.rglob("*"),
        key=lambda path: path.relative_to(_R11_AWS_CLI_VERSION_ROOT).as_posix(),
    )
    for path in entries:
        relative = path.relative_to(_R11_AWS_CLI_VERSION_ROOT).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if metadata.st_uid != os.geteuid():
            raise ValueError("aws_owner")
        if stat.S_ISLNK(metadata.st_mode):
            target = os.readlink(path)
            if allowed_links.get(relative) != target:
                raise ValueError("aws_symlink")
            line = (
                f"L\t{relative}\t{mode:o}\t{metadata.st_uid}\t"
                f"{metadata.st_gid}\t{target}\n"
            ).encode("utf-8")
        elif stat.S_ISDIR(metadata.st_mode):
            if mode & 0o022:
                raise ValueError("aws_directory_mode")
            line = (
                f"D\t{relative}\t{mode:o}\t{metadata.st_uid}\t"
                f"{metadata.st_gid}\n"
            ).encode("utf-8")
        elif stat.S_ISREG(metadata.st_mode):
            payload = _bootstrap_read_regular(
                path,
                maximum_bytes=64 * 1024 * 1024,
                allow_empty=True,
            )
            file_bytes += len(payload)
            line = (
                f"F\t{relative}\t{mode:o}\t{metadata.st_uid}\t"
                f"{metadata.st_gid}\t{len(payload)}\t"
                f"{hashlib.sha256(payload).hexdigest()}\n"
            ).encode("utf-8")
        else:
            raise ValueError("aws_entry")
        digest.update(line)
        entry_count += 1
    if (
        entry_count != _R11_AWS_CLI_TREE_ENTRY_COUNT
        or file_bytes != _R11_AWS_CLI_TREE_FILE_BYTES
    ):
        raise ValueError("aws_tree_shape")
    return digest.hexdigest()


def _credential_file_identity() -> tuple[int, ...]:
    metadata = Path("/home/developer/.aws/credentials").lstat()
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or not 0 < metadata.st_size <= 64 * 1024
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise ValueError("credential_file")
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _secure_credential_file_present() -> bool:
    try:
        _credential_file_identity()
        return True
    except (OSError, ValueError):
        return False


def _validate_aws_cli_binding() -> bool:
    expected_links = (
        (
            Path("/home/developer/.local/bin/aws"),
            "/home/developer/.local/aws-cli/v2/current/bin/aws",
        ),
        (
            Path("/home/developer/.local/aws-cli/v2/current"),
            "/home/developer/.local/aws-cli/v2/2.35.24",
        ),
        (_R11_AWS_CLI_VERSION_ROOT / "bin" / "aws", "../dist/aws"),
    )
    try:
        for path, expected_target in expected_links:
            metadata = path.lstat()
            if (
                not stat.S_ISLNK(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or os.readlink(path) != expected_target
            ):
                return False
        executable = _bootstrap_read_regular(
            _R11_AWS_CLI_CANONICAL_PATH,
            maximum_bytes=16 * 1024 * 1024,
        )
        executable_metadata = _R11_AWS_CLI_CANONICAL_PATH.lstat()
        if (
            executable_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(executable_metadata.st_mode) != 0o755
            or hashlib.sha256(executable).hexdigest() != _R11_AWS_CLI_SHA256
            or _aws_cli_tree_sha256() != _R11_AWS_CLI_TREE_SHA256
            or not _secure_credential_file_present()
        ):
            return False
        completed = subprocess.run(
            [str(_R11_AWS_CLI_CANONICAL_PATH), "--version"],
            env={
                "AWS_CLI_HISTORY_FILE": "/dev/null",
                "AWS_CONFIG_FILE": "/dev/null",
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
                "HOME": "/nonexistent",
                "LC_ALL": "C",
                "PATH": str(_R11_AWS_CLI_CANONICAL_PATH.parent),
            },
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return (
            completed.stdout + completed.stderr
        ).strip() == _R11_AWS_CLI_VERSION_OUTPUT
    except Exception:
        return False


def _bootstrap_dependency_site_is_valid() -> bool:
    try:
        if not stat.S_ISDIR(_R11_DEPENDENCY_SITE.lstat().st_mode):
            return False
        metadata_root = _R11_DEPENDENCY_SITE / _R11_SDK_DIST_INFO_NAME
        sdk_metadata = {
            path.name
            for path in _R11_DEPENDENCY_SITE.glob(
                "coinbase_advanced_py-*.dist-info"
            )
        }
        if sdk_metadata != {_R11_SDK_DIST_INFO_NAME} or not stat.S_ISDIR(
            metadata_root.lstat().st_mode
        ):
            return False
        recorded = _recorded_sdk_paths()
        metadata_text = (metadata_root / "METADATA").read_text(encoding="utf-8")
        if metadata_text.splitlines().count("Name: coinbase-advanced-py") != 1:
            return False
        if metadata_text.splitlines().count("Version: 1.8.4") != 1:
            return False
        for relative, expected_sha256 in _R11_SDK_SOURCE_SHA256.items():
            path = _R11_DEPENDENCY_SITE / relative
            if (
                relative not in recorded
                or not stat.S_ISREG(path.lstat().st_mode)
                or _bootstrap_file_sha256(path) != expected_sha256
            ):
                return False
        for root in (_R11_DEPENDENCY_SITE / "coinbase", metadata_root):
            if not stat.S_ISDIR(root.lstat().st_mode):
                return False
            for path in root.rglob("*"):
                if path.is_symlink():
                    return False
                if path.is_dir():
                    continue
                relative = path.relative_to(_R11_DEPENDENCY_SITE).as_posix()
                if (
                    relative not in recorded
                    or "__pycache__" in path.parts
                    or path.suffix in {".pyc", ".pyo"}
                ):
                    return False
        for path in _R11_DEPENDENCY_SITE.iterdir():
            if (
                path.name.startswith("coinbase_advanced_py-")
                and path.name.endswith(".dist-info")
                and path.name != _R11_SDK_DIST_INFO_NAME
            ):
                return False
            if path.name != "coinbase" and path.name.startswith("coinbase."):
                return False
    except (OSError, UnicodeError, ValueError):
        return False
    return True


def _bootstrap_system_dependency_site_is_valid() -> bool:
    try:
        if not stat.S_ISDIR(_R11_SYSTEM_DEPENDENCY_SITE.lstat().st_mode):
            return False
        return not any(
            path.name == "coinbase"
            or path.name.startswith("coinbase.")
            or (
                path.name.startswith("coinbase_advanced_py-")
                and path.name.endswith(".dist-info")
            )
            for path in _R11_SYSTEM_DEPENDENCY_SITE.iterdir()
        )
    except OSError:
        return False


def _bootstrap_runtime_is_valid() -> bool:
    base_valid = (
        Path(sys.executable).resolve() == Path("/usr/local/bin/python3.13")
        and sys.version_info[:2] == (3, 13)
        and _bootstrap_dependency_site_is_valid()
        and _bootstrap_system_dependency_site_is_valid()
        and _verify_runtime_dependencies()
        and _validate_aws_cli_binding()
    )
    if __name__ != "__main__":
        return base_valid
    return (
        base_valid
        and sys.flags.isolated == 1
        and sys.flags.no_site == 1
        and sys.flags.dont_write_bytecode == 1
        and sys.pycache_prefix == _R11_PYCACHE_PREFIX
    )


def _bootstrap_git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", "-c", "core.fsmonitor=false", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def _backend_import_shadows_absent(
    root: Path,
    output: Callable[..., str],
) -> bool:
    tracked = set(
        filter(None, output(root, "ls-files", "--cached").splitlines())
    )
    _R11_TRACKED_BACKEND_IMPORT_FILES.clear()
    _R11_TRACKED_BACKEND_IMPORT_FILES.update(
        os.path.abspath(root.joinpath(*PurePosixPath(relative).parts))
        for relative in tracked
        if relative.endswith(".py")
    )
    import_roots = {
        PurePosixPath(relative).parts[0]
        for relative in tracked
        if relative.endswith(".py") and "/" in relative
    }
    extension_suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    for relative in filter(
        None,
        output(root, "ls-files", "--others").splitlines(),
    ):
        candidate = PurePosixPath(relative)
        if "__pycache__" in candidate.parts:
            continue
        top_level = candidate.parts[0] if candidate.parts else ""
        if len(candidate.parts) > 1 and top_level not in import_roots:
            if not top_level.isidentifier():
                continue
        path = root.joinpath(*candidate.parts)
        try:
            if path.is_symlink():
                return False
        except OSError:
            return False
        name = candidate.name
        if name.endswith((".py", ".pyc", ".pyo", ".pyd", ".so")) or (
            extension_suffixes and name.endswith(extension_suffixes)
        ):
            return False
    return True


def _repository_clean_with_output(
    root: Path,
    output: Callable[..., str],
    file_sha256: Callable[[Path], str] = _bootstrap_file_sha256,
) -> bool:
    if (
        output(root, "branch", "--show-current") != "main"
        or output(root, "rev-parse", "HEAD")
        != output(root, "rev-parse", "origin/main")
        or output(root, "status", "--porcelain", "--untracked-files=no")
        != ""
    ):
        return False
    untracked = set(
        filter(
            None,
            output(
                root,
                "ls-files",
                "--others",
                "--exclude-standard",
            ).splitlines(),
        )
    )
    if root == REPO_ROOT:
        return not untracked and _backend_import_shadows_absent(root, output)
    if root != FRONTEND_ROOT or untracked != set(
        _FRONTEND_INERT_UNTRACKED_SHA256
    ):
        return False
    for relative, expected_sha256 in _FRONTEND_INERT_UNTRACKED_SHA256.items():
        path = root / relative
        observed = path.lstat()
        if (
            not stat.S_ISREG(observed.st_mode)
            or file_sha256(path) != expected_sha256
        ):
            return False
    return True


def _early_bootstrap() -> tuple[dict[str, object], bool]:
    source = Path(__file__).read_text(encoding="utf-8")
    block, _start, _end = _audit_binding_block(source)
    values = _literal_audit_binding_values(block)
    if not _repository_clean_with_output(
        REPO_ROOT, _bootstrap_git_output
    ) or not _repository_clean_with_output(
        FRONTEND_ROOT, _bootstrap_git_output
    ) or not _bootstrap_runtime_is_valid():
        raise ValueError("source_state")
    return values, __name__ == "__main__"


try:
    _R11_AUDIT_BINDING_VALUES, _R11_CLI_BOOTSTRAP_VALIDATED = _early_bootstrap()
    _R11_SOURCE_BOOTSTRAP_VALIDATED = True
except Exception:
    if __name__ == "__main__":
        sys.stderr.write(
            '{"blocker":"futures_preview_r11_bootstrap_source_invalid",'
            '"status":"blocked"}\n'
        )
        raise SystemExit(2)
    raise RuntimeError("futures Preview R11 bootstrap source is invalid") from None


# BEGIN R11 AUDIT BINDINGS
if False:
    R11_PREVIEW_CALL_AUTHORITY_ACTIVE = False
    R11_FINAL_AUDIT_BINDING_READY = False
    R11_PREPARATION_REVISION = ""
    R11_FRONTEND_REVISION = ""
    R11_NORMALIZED_RUNNER_SHA256 = ""
    R11_AUTHORIZATION_SHA256 = ""
    R11_SAFETY_AUDIT_RECEIPT_SHA256 = ""
    R11_BLIND_AUDIT_RECEIPT_SHA256 = ""
    R11_ACTIVATION_NOT_AFTER = ""
    R11_AUDITED_COMPONENT_SHA256: dict[str, str] = {}
# END R11 AUDIT BINDINGS

R11_PREVIEW_CALL_AUTHORITY_ACTIVE = _R11_AUDIT_BINDING_VALUES[
    "R11_PREVIEW_CALL_AUTHORITY_ACTIVE"
]
R11_FINAL_AUDIT_BINDING_READY = _R11_AUDIT_BINDING_VALUES[
    "R11_FINAL_AUDIT_BINDING_READY"
]
R11_PREPARATION_REVISION = _R11_AUDIT_BINDING_VALUES[
    "R11_PREPARATION_REVISION"
]
R11_FRONTEND_REVISION = _R11_AUDIT_BINDING_VALUES["R11_FRONTEND_REVISION"]
R11_NORMALIZED_RUNNER_SHA256 = _R11_AUDIT_BINDING_VALUES[
    "R11_NORMALIZED_RUNNER_SHA256"
]
R11_AUTHORIZATION_SHA256 = _R11_AUDIT_BINDING_VALUES[
    "R11_AUTHORIZATION_SHA256"
]
R11_SAFETY_AUDIT_RECEIPT_SHA256 = _R11_AUDIT_BINDING_VALUES[
    "R11_SAFETY_AUDIT_RECEIPT_SHA256"
]
R11_BLIND_AUDIT_RECEIPT_SHA256 = _R11_AUDIT_BINDING_VALUES[
    "R11_BLIND_AUDIT_RECEIPT_SHA256"
]
R11_ACTIVATION_NOT_AFTER = _R11_AUDIT_BINDING_VALUES[
    "R11_ACTIVATION_NOT_AFTER"
]
R11_AUDITED_COMPONENT_SHA256 = dict(
    _R11_AUDIT_BINDING_VALUES["R11_AUDITED_COMPONENT_SHA256"]
)


def _sdk_module_origins_are_bound(
    modules: Mapping[str, object],
) -> bool:
    try:
        recorded = _recorded_sdk_paths()
        for name, module in modules.items():
            if name != "coinbase" and not name.startswith("coinbase."):
                continue
            raw_origin = getattr(module, "__file__", None)
            if not isinstance(raw_origin, str):
                return False
            origin = Path(raw_origin)
            if origin.is_symlink() or not stat.S_ISREG(origin.lstat().st_mode):
                return False
            relative = origin.resolve().relative_to(
                _R11_DEPENDENCY_SITE.resolve()
            ).as_posix()
            if relative not in recorded or "__pycache__" in origin.parts:
                return False
    except (OSError, ValueError):
        return False
    return True


def _load_hash_bound_sdk_modules() -> None:
    dependency_site = str(_R11_DEPENDENCY_SITE)
    system_site = str(_R11_SYSTEM_DEPENDENCY_SITE)
    sys.path[:] = [
        entry for entry in sys.path if entry not in {dependency_site, system_site}
    ]
    sys.path.insert(0, dependency_site)
    sys.path.insert(1, system_site)
    loaded_before = {
        name: module
        for name, module in sys.modules.items()
        if name.partition(".")[0] in _R11_VERIFIED_IMPORT_TOP_LEVELS
    }
    if loaded_before and not _runtime_module_origins_are_bound(
        loaded_before,
        closure_only=True,
    ):
        raise ValueError("dependency_preloaded_origin")
    _install_runtime_dependency_guard()
    for name in _R11_SDK_REQUIRED_MODULES:
        importlib.import_module(name)
    loaded_after = {
        name: module
        for name, module in sys.modules.items()
        if name.partition(".")[0] in _R11_VERIFIED_IMPORT_TOP_LEVELS
    }
    if not set(_R11_SDK_REQUIRED_MODULES).issubset(loaded_after) or not (
        _runtime_module_origins_are_bound(loaded_after, closure_only=True)
        and _sdk_module_origins_are_bound(loaded_after)
    ):
        raise ValueError("dependency_loaded_origin")


try:
    _load_hash_bound_sdk_modules()
except Exception:
    if __name__ == "__main__":
        sys.stderr.write(
            '{"blocker":"futures_preview_r11_bootstrap_source_invalid",'
            '"status":"blocked"}\n'
        )
        raise SystemExit(2)
    raise RuntimeError("futures Preview R11 SDK source is invalid") from None

_R11_MODULES_BEFORE_PROJECT_IMPORTS = frozenset(sys.modules)

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.futures_order_preview import (  # noqa: E402
    FUTURES_PREVIEW_R10_FILE_SHA256,
    FUTURES_PREVIEW_R10_TERMINAL_BINDING,
    FUTURES_PREVIEW_R11_ARTIFACT_PATH,
    FUTURES_PREVIEW_R11_ARTIFACT_TYPE,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
    _validate_r11_claim_record,
    _validate_r11_ephemeral_claim_record,
    validate_production_futures_order_preview_r10_terminal,
)
from application.admin_api import models as _admin_api_models  # noqa: E402,F401
from tools import run_admin_api_futures_no_live_preview as base_tool  # noqa: E402


_R11_PROJECT_IMPORT_MODULES = {
    name: module
    for name, module in sys.modules.items()
    if name not in _R11_MODULES_BEFORE_PROJECT_IMPORTS
    or name.partition(".")[0] in _R11_VERIFIED_IMPORT_TOP_LEVELS
}
if not _runtime_module_origins_are_bound(
    _R11_PROJECT_IMPORT_MODULES,
    closure_only=False,
):
    if __name__ == "__main__":
        sys.stderr.write(
            '{"blocker":"futures_preview_r11_bootstrap_source_invalid",'
            '"status":"blocked"}\n'
        )
        raise SystemExit(2)
    raise RuntimeError("futures Preview R11 dependency source is invalid")
if __name__ != "__main__" and _R11VerifiedDependencyFinder in sys.meta_path:
    sys.meta_path.remove(_R11VerifiedDependencyFinder)


FuturesPreviewOnlyRestClient = base_tool.FuturesPreviewOnlyRestClient
_suppress_coinbase_sdk_logging = base_tool._suppress_coinbase_sdk_logging


def _validate_literal_audit_binding_block(block: str) -> None:
    """Accept only the inert wrapper and ten named literal assignments."""

    try:
        _literal_audit_binding_values(block)
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 literal audit binding block is invalid"
        ) from None


def _normalized_runner_bytes(payload: bytes | None = None) -> bytes:
    """Return runner bytes with only the literal audit block normalized."""

    text = (
        Path(__file__).read_text(encoding="utf-8")
        if payload is None
        else payload.decode("utf-8")
    )
    try:
        block, start, end = _audit_binding_block(text)
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 audit binding markers are invalid"
        ) from None
    _validate_literal_audit_binding_block(block)
    return (
        text[:start] + _AUDIT_BINDING_PLACEHOLDER + text[end:]
    ).encode("utf-8")


def normalized_runner_sha256() -> str:
    return hashlib.sha256(_normalized_runner_bytes()).hexdigest()


def _file_sha256(path: Path) -> str:
    return _bootstrap_file_sha256(path)


def _installed_sdk_source_sha256() -> dict[str, str]:
    """Hash the official v1.8.4 source files used by the Preview boundary."""

    installed = distribution("coinbase-advanced-py")
    return {
        relative: _file_sha256(Path(installed.locate_file(relative)))
        for relative in _R11_SDK_SOURCE_SHA256
    }


def current_audited_component_sha256() -> dict[str, str]:
    """Hash the fixed prepared implementation without opening artifacts."""

    result: dict[str, str] = {}
    for component in sorted(_R11_EXPECTED_COMPONENTS):
        scope, relative = component.split(":", 1)
        root = REPO_ROOT if scope == "backend" else FRONTEND_ROOT
        result[component] = _file_sha256(root / relative)
    return result


def _git_output(root: Path, *args: str) -> str:
    try:
        return _bootstrap_git_output(root, *args)
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 audited revision is unavailable"
        ) from None


def _repository_is_clean_synced_main(root: Path) -> bool:
    try:
        return _repository_clean_with_output(root, _git_output, _file_sha256)
    except Exception:
        return False


def _validate_fixed_production_artifact_path() -> None:
    if (
        os.environ.get(
            "COINBASE_ADMIN_API_FUTURES_ORDER_PREVIEW_ARTIFACT_ROOT",
            "",
        ).strip()
        or FUTURES_PREVIEW_R11_ARTIFACT_PATH
        != _FIXED_R11_PRODUCTION_ARTIFACT_PATH
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 fixed production artifact path is invalid"
        )


def _validate_sdk_pin() -> None:
    project = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    if (
        version("coinbase-advanced-py") != "1.8.4"
        or "coinbase-advanced-py==1.8.4"
        not in project.get("project", {}).get("dependencies", [])
        or not _bootstrap_dependency_site_is_valid()
        or not _verify_runtime_dependencies()
        or not _validate_aws_cli_binding()
        or _installed_sdk_source_sha256() != _R11_SDK_SOURCE_SHA256
        or not _runtime_module_origins_are_bound(
            sys.modules,
            closure_only=__name__ != "__main__",
        )
        or not _sdk_module_origins_are_bound(
            {
                name: module
                for name, module in sys.modules.items()
                if name == "coinbase" or name.startswith("coinbase.")
            }
        )
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 SDK binding is invalid"
        )


def _validate_final_audit_binding() -> None:
    """Validate the constants-only activation commit and audited components."""

    hashes = (
        R11_PREPARATION_REVISION,
        R11_FRONTEND_REVISION,
        R11_NORMALIZED_RUNNER_SHA256,
        R11_AUTHORIZATION_SHA256,
        R11_SAFETY_AUDIT_RECEIPT_SHA256,
        R11_BLIND_AUDIT_RECEIPT_SHA256,
    )
    if (
        not R11_PREVIEW_CALL_AUTHORITY_ACTIVE
        or not R11_FINAL_AUDIT_BINDING_READY
        or any(_HEX_SHA256.fullmatch(value) is None for value in hashes)
        or R11_SAFETY_AUDIT_RECEIPT_SHA256
        == R11_BLIND_AUDIT_RECEIPT_SHA256
        or set(R11_AUDITED_COMPONENT_SHA256) != _R11_EXPECTED_COMPONENTS
        or any(
            _HEX_SHA256.fullmatch(value) is None
            for value in R11_AUDITED_COMPONENT_SHA256.values()
        )
        or normalized_runner_sha256() != R11_NORMALIZED_RUNNER_SHA256
        or current_audited_component_sha256()
        != R11_AUDITED_COMPONENT_SHA256
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 final audit binding is invalid"
        )
    try:
        not_after = datetime.fromisoformat(
            R11_ACTIVATION_NOT_AFTER.replace("Z", "+00:00")
        )
    except (TypeError, ValueError):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 activation window is invalid"
        ) from None
    if (
        not_after.tzinfo is None
        or datetime.now(timezone.utc) >= not_after.astimezone(timezone.utc)
        or not _repository_is_clean_synced_main(REPO_ROOT)
        or not _repository_is_clean_synced_main(FRONTEND_ROOT)
        or _git_output(FRONTEND_ROOT, "rev-parse", "HEAD")
        != R11_FRONTEND_REVISION
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 activation environment is invalid"
        )
    head = _git_output(REPO_ROOT, "rev-parse", "HEAD")
    parent = _git_output(REPO_ROOT, "rev-parse", "HEAD^")
    changed = set(
        filter(
            None,
            _git_output(
                REPO_ROOT,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                head,
            ).splitlines(),
        )
    )
    if parent != R11_PREPARATION_REVISION or changed != {
        _R11_RUNNER_RELATIVE_PATH
    }:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 activation commit is invalid"
        )
    _validate_sdk_pin()


def _require_production_factory_authority() -> None:
    if (
        not _R11_CLI_BOOTSTRAP_VALIDATED
        or not R11_PREVIEW_CALL_AUTHORITY_ACTIVE
        or not R11_FINAL_AUDIT_BINDING_READY
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 production factory authority is unavailable"
        )


def _assert_exclusive_r11_claim(
    store: FuturesOrderPreviewArtifactStore,
) -> None:
    try:
        rows = store._read_rows()  # noqa: SLF001
        artifact_stat = store.path.lstat()
        claim = rows[0].get("record") if len(rows) == 1 else None
        if (
            len(rows) != 1
            or rows[0].get("record_type") != "claim"
            or not isinstance(claim, Mapping)
            or stat.S_IMODE(artifact_stat.st_mode) != 0o600
            or artifact_stat.st_nlink != 1
        ):
            raise ValueError("claim_not_exclusive")
        _validate_r11_claim_record(claim)
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 claim is unavailable"
        ) from None


class _R11ClaimBoundSecretLookup:
    """One-use capability minted only for the exclusive production claim."""

    __slots__ = ("__store", "__used")

    def __init__(self, store: FuturesOrderPreviewArtifactStore) -> None:
        _require_production_factory_authority()
        if (
            not isinstance(store, FuturesOrderPreviewArtifactStore)
            or store.path != _FIXED_R11_PRODUCTION_ARTIFACT_PATH
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R11 credential preparation failed"
            )
        _assert_exclusive_r11_claim(store)
        self.__store = store
        self.__used = False

    def _consume_claim(self) -> FuturesOrderPreviewArtifactStore:
        if self.__used:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R11 credential preparation failed"
            )
        self.__used = True
        _require_production_factory_authority()
        _assert_exclusive_r11_claim(self.__store)
        return self.__store

    def __call__(self, secret_id: str, region: str | None) -> str:
        return _lookup_fixed_r11_secret(
            secret_id,
            region,
            _claim_capability=self,
        )


def _lookup_fixed_r11_secret(
    secret_id: str,
    region: str | None,
    *,
    _claim_capability: _R11ClaimBoundSecretLookup | None = None,
) -> str:
    """Resolve only the fixed Default secret with a closed AWS CLI process."""

    diagnostic = "futures Preview R11 credential preparation failed"
    argv = [
        str(_R11_AWS_CLI_CANONICAL_PATH),
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        "coinbase",
        "--region",
        "us-east-1",
        "--endpoint-url",
        "https://secretsmanager.us-east-1.amazonaws.com",
        "--ca-bundle",
        str(_R11_AWS_CLI_CA_BUNDLE),
        "--output",
        "json",
        "--no-cli-pager",
        "--cli-connect-timeout",
        "10",
        "--cli-read-timeout",
        "20",
    ]
    environment = {
        "AWS_CLI_AUTO_PROMPT": "off",
        "AWS_CLI_HISTORY_FILE": "/dev/null",
        "AWS_CONFIG_FILE": "/dev/null",
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_MAX_ATTEMPTS": "1",
        "AWS_PAGER": "",
        "AWS_PROFILE": "default",
        "AWS_REGION": "us-east-1",
        "AWS_RETRY_MODE": "standard",
        "AWS_SHARED_CREDENTIALS_FILE": "/home/developer/.aws/credentials",
        "HOME": "/nonexistent",
        "LC_ALL": "C",
        "PATH": str(_R11_AWS_CLI_CANONICAL_PATH.parent),
    }
    try:
        if (
            secret_id != "coinbase"
            or region != "us-east-1"
            or type(_claim_capability) is not _R11ClaimBoundSecretLookup
        ):
            raise FuturesOrderPreviewArtifactError(diagnostic)
        _claim_capability._consume_claim()  # noqa: SLF001
        credential_identity = _credential_file_identity()
        if not _validate_aws_cli_binding():
            raise FuturesOrderPreviewArtifactError(diagnostic)
        completed = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=35,
        )
        payload = completed.stdout
        binding_still_valid = _validate_aws_cli_binding()
        credential_still_bound = (
            _credential_file_identity() == credential_identity
        )
        if (
            completed.returncode != 0
            or not isinstance(payload, str)
            or not payload.strip()
            or len(payload.encode("utf-8")) > _R11_MAX_AWS_SECRET_RESPONSE_BYTES
            or not binding_still_valid
            or not credential_still_bound
        ):
            raise FuturesOrderPreviewArtifactError(diagnostic)
        return payload
    except FuturesOrderPreviewArtifactError:
        raise
    except Exception:
        raise FuturesOrderPreviewArtifactError(diagnostic) from None


def _build_r11_preview_rest_client(
    *,
    store: FuturesOrderPreviewArtifactStore,
) -> FuturesPreviewOnlyRestClient:
    """Hydrate one canonical zero-retry client behind the Preview-only facade."""

    _require_production_factory_authority()
    lookup = _R11ClaimBoundSecretLookup(store)
    return FuturesPreviewOnlyRestClient(
        base_tool._build_canonical_default_rest_client(
            run_secret_lookup=lookup,
        )
    )


class DeferredR11PreviewRestClient:
    """Hydrate credentials only after the exclusive persisted R11 claim."""

    __slots__ = (
        "__call_attempts",
        "__claim_asserted",
        "__client",
        "__client_factory",
        "__hydration_attempted",
        "__store",
    )

    def __init__(
        self,
        *,
        store: FuturesOrderPreviewArtifactStore,
        client_factory: Callable[[], FuturesPreviewOnlyRestClient] | None = None,
        prepared_client: FuturesPreviewOnlyRestClient | None = None,
    ) -> None:
        if not isinstance(store, FuturesOrderPreviewArtifactStore):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R11 artifact store is invalid"
            )
        if prepared_client is not None and client_factory is not None:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R11 client source is invalid"
            )
        if prepared_client is None and client_factory is None:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R11 client source is invalid"
            )
        if prepared_client is not None and type(
            prepared_client
        ) is not FuturesPreviewOnlyRestClient:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R11 client source is invalid"
            )
        self.__store = store
        self.__client = prepared_client
        self.__client_factory = (
            None
            if prepared_client is not None
            else client_factory
        )
        self.__hydration_attempted = prepared_client is not None
        self.__claim_asserted = False
        self.__call_attempts = {name: 0 for name in _R11_DEFERRED_CALLS}

    def _assert_r11_claimed(self) -> None:
        _assert_exclusive_r11_claim(self.__store)

    def _get(self) -> FuturesPreviewOnlyRestClient:
        if not self.__claim_asserted:
            self._assert_r11_claimed()
            self.__claim_asserted = True
        if self.__client is None:
            if self.__hydration_attempted:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R11 client is unavailable"
                )
            self.__hydration_attempted = True
            factory = self.__client_factory
            if factory is None:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R11 client is unavailable"
                )
            with _suppress_coinbase_sdk_logging():
                client = factory()
            if type(client) is not FuturesPreviewOnlyRestClient:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R11 client is invalid"
                )
            self.__client = client
        return self.__client

    def _consume_call(self, name: str) -> None:
        if self.__call_attempts.get(name) != 0:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R11 call was already attempted"
            )
        self.__call_attempts[name] = 1

    def get_api_key_permissions(self):
        self._consume_call("api_key_permissions")
        return self._get().get_api_key_permissions()

    def list_portfolios(self):
        self._consume_call("portfolio_catalog")
        return self._get().list_portfolios()

    def get_product_dict(self, product_id: str):
        self._consume_call("product")
        return self._get().get_product_dict(product_id)

    def get_best_bid_ask(self, *, product_ids: list[str]):
        self._consume_call("best_bid_ask")
        return self._get().get_best_bid_ask(product_ids=product_ids)

    def get_futures_positions(self):
        self._consume_call("futures_positions")
        return self._get().get_futures_positions()

    def get_futures_margin_collateral_snapshot(self):
        self._consume_call("futures_margin_collateral")
        return self._get().get_futures_margin_collateral_snapshot()

    def preview_order(self, **kwargs):
        self._consume_call("preview_order")
        return self._get().preview_order(**kwargs)


def production_artifact_path() -> Path:
    """Return the fixed R11 path; environment cannot redirect it."""

    _validate_fixed_production_artifact_path()
    return _FIXED_R11_PRODUCTION_ARTIFACT_PATH


def validate_production_predecessor() -> dict[str, Any]:
    """Bind R10 and its chain while keeping opaque R8 bytes inaccessible."""

    return validate_production_futures_order_preview_r10_terminal()


def _build_production_r11_store() -> FuturesOrderPreviewArtifactStore:
    _require_production_factory_authority()
    return FuturesOrderPreviewArtifactStore(
        _FIXED_R11_PRODUCTION_ARTIFACT_PATH,
        reservation_lock_nonblocking=True,
    )


def _build_production_r11_deferred_client(
    store: FuturesOrderPreviewArtifactStore,
) -> DeferredR11PreviewRestClient:
    _require_production_factory_authority()
    if store.path != _FIXED_R11_PRODUCTION_ARTIFACT_PATH:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 production artifact path is invalid"
        )
    return DeferredR11PreviewRestClient(
        store=store,
        client_factory=partial(_build_r11_preview_rest_client, store=store),
    )


def _build_production_r11_producer(
    store: FuturesOrderPreviewArtifactStore,
    rest_client: DeferredR11PreviewRestClient,
) -> FuturesOrderPreviewProducer:
    _require_production_factory_authority()
    if (
        store.path != _FIXED_R11_PRODUCTION_ARTIFACT_PATH
        or type(rest_client) is not DeferredR11PreviewRestClient
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R11 production boundary is invalid"
        )
    return FuturesOrderPreviewProducer(
        rest_client=rest_client,
        store=store,
        predecessor_binding=dict(FUTURES_PREVIEW_R10_TERMINAL_BINDING),
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R11_ARTIFACT_TYPE,
    )


def _validate_fresh_claim_contract(path: Path) -> None:
    producer = FuturesOrderPreviewProducer(
        rest_client=None,
        store=FuturesOrderPreviewArtifactStore(path),
        predecessor_binding=dict(FUTURES_PREVIEW_R10_TERMINAL_BINDING),
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R11_ARTIFACT_TYPE,
    )
    _validate_r11_ephemeral_claim_record(producer.build_claim())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or consume exactly one audited Default-profile AVAX "
            "Futures R11 Preview; no exchange mutation is possible."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Validate R11 locally without credentials or Coinbase access.",
    )
    mode.add_argument(
        "--confirm-one-r11-preview",
        action="store_true",
        help="Consume the single audited R11 Preview claim.",
    )
    return parser


def _summary_before_attempt(
    *,
    status: str,
    blocker: str | None,
    path: Path,
    artifact_created: bool,
) -> dict[str, object]:
    return {
        "status": status,
        "blocker": blocker,
        "artifact_path": str(path),
        "artifact_created": artifact_created,
        "coinbase_read_ran": False,
        "preview_order_attempt_count": 0,
        "exchange_submission_attempt_count": 0,
        "live_coinbase_execution": "not_run",
    }


def _fixed_blocked_summary(blocker: str) -> dict[str, object]:
    return _summary_before_attempt(
        status="blocked",
        blocker=blocker,
        path=_FIXED_R11_PRODUCTION_ARTIFACT_PATH,
        artifact_created=False,
    )


def _path_is_consumed(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.confirm_one_r11_preview and not _R11_CLI_BOOTSTRAP_VALIDATED:
        print(
            json.dumps(
                _fixed_blocked_summary(
                    "futures_preview_r11_bootstrap_validation_required"
                ),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    if args.confirm_one_r11_preview and not R11_PREVIEW_CALL_AUTHORITY_ACTIVE:
        print(
            json.dumps(
                _fixed_blocked_summary(
                    "futures_preview_r11_call_authority_inactive"
                ),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    if args.confirm_one_r11_preview and not R11_FINAL_AUDIT_BINDING_READY:
        print(
            json.dumps(
                _fixed_blocked_summary(
                    "futures_preview_r11_final_audit_binding_incomplete"
                ),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    if args.confirm_one_r11_preview:
        try:
            _validate_final_audit_binding()
        except Exception:
            print(
                json.dumps(
                    _fixed_blocked_summary(
                        "futures_preview_r11_final_audit_binding_invalid"
                    ),
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 2

    if args.preflight:
        try:
            path = production_artifact_path()
            if _path_is_consumed(path):
                print(
                    json.dumps(
                        _summary_before_attempt(
                            status="blocked",
                            blocker="futures_preview_attempt_already_consumed",
                            path=path,
                            artifact_created=False,
                        ),
                        sort_keys=True,
                    )
                )
                return 2
            predecessor = validate_production_predecessor()
            if predecessor != FUTURES_PREVIEW_R10_TERMINAL_BINDING:
                raise FuturesOrderPreviewArtifactError(
                    "futures Preview R10 terminal binding changed"
                )
            _validate_sdk_pin()
            _validate_fresh_claim_contract(path)
        except Exception:
            print(
                json.dumps(
                    _fixed_blocked_summary(
                        "futures_preview_r11_preflight_validation_blocked"
                    ),
                    sort_keys=True,
                )
            )
            return 2
        summary = _summary_before_attempt(
            status="prepared",
            blocker=None,
            path=path,
            artifact_created=False,
        )
        summary.update(
            {
                "predecessor_artifact": predecessor["artifact_name"],
                "predecessor_file_sha256": predecessor["file_sha256"],
                "claim_contract_ready": True,
                "live_authority_active": R11_PREVIEW_CALL_AUTHORITY_ACTIVE,
                "final_audit_binding_ready": R11_FINAL_AUDIT_BINDING_READY,
            }
        )
        print(json.dumps(summary, sort_keys=True))
        return 0

    path = production_artifact_path()
    if _path_is_consumed(path):
        print(
            json.dumps(
                _summary_before_attempt(
                    status="blocked",
                    blocker="futures_preview_attempt_already_consumed",
                    path=path,
                    artifact_created=False,
                ),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    try:
        predecessor = validate_production_predecessor()
        if predecessor != FUTURES_PREVIEW_R10_TERMINAL_BINDING:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R10 terminal binding changed"
            )
        _validate_sdk_pin()
        _validate_fresh_claim_contract(path)
        _validate_final_audit_binding()
    except Exception:
        print(
            json.dumps(
                _fixed_blocked_summary(
                    "futures_preview_r11_preflight_validation_blocked"
                ),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    store = _build_production_r11_store()
    deferred_client = _build_production_r11_deferred_client(store)
    producer = _build_production_r11_producer(store, deferred_client)
    try:
        with _suppress_coinbase_sdk_logging():
            evidence = producer.run()
    except Exception:
        try:
            terminal = store.read_completed()
        except Exception:
            terminal = None
        if terminal is None:
            summary: dict[str, object] = {
                "status": "unknown",
                "outcome": "unknown",
                "blocker": "futures_preview_r11_consumed_without_terminal",
                "artifact_path": str(path),
                "artifact_created": _path_is_consumed(path),
                "attempt_counters": None,
                "exchange_submission_attempt_count": 0,
                "live_execution": "not_run",
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
            }
        else:
            summary = {
                "status": terminal["status"],
                "outcome": terminal["outcome"],
                "blocker": terminal.get("blocker"),
                "artifact_path": str(path),
                "artifact_created": True,
                "attempt_counters": terminal["attempt_counters"],
                "exchange_submission_attempt_count": terminal[
                    "exchange_submission_attempt_count"
                ],
                "live_execution": terminal["live_execution"],
                "submitted_notional_usdc": terminal[
                    "submitted_notional_usdc"
                ],
                "executed_notional_usdc": terminal[
                    "executed_notional_usdc"
                ],
            }
        print(json.dumps(summary, sort_keys=True), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": evidence["status"],
                "outcome": evidence["outcome"],
                "artifact_path": str(path),
                "product_id": evidence["product_id"],
                "evidence_sha256": evidence["evidence_sha256"],
                "attempt_counters": evidence["attempt_counters"],
                "live_execution": "not_run",
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
