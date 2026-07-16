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


if __name__ == "__main__" and not sys.flags.isolated:
    sys.stderr.write(
        '{"blocker":"futures_preview_r11_isolated_runtime_required",'
        '"status":"blocked"}\n'
    )
    raise SystemExit(2)


import argparse
import ast
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distribution, version
import json
import os
from pathlib import Path
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
        "backend:docs/FUTURES_SLICE_2R11_PREPARATION.md",
        "backend:external/coinbase_client.py",
        "backend:genai_data/AGENT_MVP_REBUILD_GOAL.md",
        "backend:openapi/coinbase-admin-api.yaml",
        "backend:pyproject.toml",
        "backend:tests/unit/test_admin_api_futures_order_preview.py",
        "backend:tests/unit/test_run_admin_api_futures_no_live_preview_r11.py",
        "backend:tests/regression/test_spot_readiness_gate.py",
        "backend:tools/run_admin_api_futures_no_live_preview.py",
        "backend:tools/run_autonomous_work_queue_check.py",
        "frontend:AGENTS.md",
        "frontend:docs/CURRENT_MVP_GOAL.md",
        "frontend:docs/TESTING.md",
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
_R11_SDK_DIST_INFO_NAME = "coinbase_advanced_py-1.8.4.dist-info"
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


def _bootstrap_dependency_site_is_valid() -> bool:
    try:
        if not stat.S_ISDIR(_R11_DEPENDENCY_SITE.lstat().st_mode):
            return False
        sdk_metadata = {
            path.name
            for path in _R11_DEPENDENCY_SITE.glob(
                "coinbase_advanced_py-*.dist-info"
            )
        }
        if sdk_metadata != {_R11_SDK_DIST_INFO_NAME} or not stat.S_ISDIR(
            (_R11_DEPENDENCY_SITE / _R11_SDK_DIST_INFO_NAME).lstat().st_mode
        ):
            return False
        for relative, expected_sha256 in _R11_SDK_SOURCE_SHA256.items():
            path = _R11_DEPENDENCY_SITE / relative
            if (
                not stat.S_ISREG(path.lstat().st_mode)
                or _bootstrap_file_sha256(path) != expected_sha256
            ):
                return False
    except OSError:
        return False
    return True


def _bootstrap_runtime_is_valid() -> bool:
    return (
        Path(sys.executable).resolve() == Path("/usr/local/bin/python3.13")
        and sys.version_info[:2] == (3, 13)
        and _bootstrap_dependency_site_is_valid()
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
        return not untracked
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
    if __name__ != "__main__":
        return values, False
    if not _repository_clean_with_output(
        REPO_ROOT, _bootstrap_git_output
    ) or not _repository_clean_with_output(
        FRONTEND_ROOT, _bootstrap_git_output
    ) or not _bootstrap_runtime_is_valid():
        raise ValueError("source_state")
    return values, True


try:
    _R11_AUDIT_BINDING_VALUES, _R11_CLI_BOOTSTRAP_VALIDATED = _early_bootstrap()
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

if str(_R11_DEPENDENCY_SITE) not in sys.path:
    sys.path.append(str(_R11_DEPENDENCY_SITE))
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
from tools import run_admin_api_futures_no_live_preview as base_tool  # noqa: E402


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
        or _installed_sdk_source_sha256() != _R11_SDK_SOURCE_SHA256
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


def _build_r11_preview_rest_client() -> FuturesPreviewOnlyRestClient:
    """Hydrate one canonical zero-retry client behind the Preview-only facade."""

    return FuturesPreviewOnlyRestClient(
        base_tool._build_canonical_default_rest_client()
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
            else (client_factory or _build_r11_preview_rest_client)
        )
        self.__hydration_attempted = prepared_client is not None
        self.__claim_asserted = False
        self.__call_attempts = {name: 0 for name in _R11_DEFERRED_CALLS}

    def _assert_r11_claimed(self) -> None:
        try:
            rows = self.__store._read_rows()  # noqa: SLF001
            artifact_stat = self.__store.path.lstat()
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


def build_r11_store(
    path: Path | None = None,
) -> FuturesOrderPreviewArtifactStore:
    return FuturesOrderPreviewArtifactStore(
        path or FUTURES_PREVIEW_R11_ARTIFACT_PATH,
        reservation_lock_nonblocking=True,
    )


def build_r11_producer(
    *,
    rest_client: object,
    store: FuturesOrderPreviewArtifactStore,
    now: Callable[[], Any] | None = None,
    correlation_id_factory: Callable[[], str] | None = None,
    idempotency_key_factory: Callable[[], str] | None = None,
) -> FuturesOrderPreviewProducer:
    return FuturesOrderPreviewProducer(
        rest_client=rest_client,
        store=store,
        predecessor_binding=dict(FUTURES_PREVIEW_R10_TERMINAL_BINDING),
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R11_ARTIFACT_TYPE,
        now=now,
        correlation_id_factory=correlation_id_factory,
        idempotency_key_factory=idempotency_key_factory,
    )


def _validate_fresh_claim_contract(path: Path) -> None:
    producer = build_r11_producer(
        rest_client=None,
        store=FuturesOrderPreviewArtifactStore(path),
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

    store = build_r11_store(path)
    deferred_client = DeferredR11PreviewRestClient(store=store)
    producer = build_r11_producer(
        rest_client=deferred_client,
        store=store,
    )
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
