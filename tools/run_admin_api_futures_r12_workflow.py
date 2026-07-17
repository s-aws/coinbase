"""Run the fixed, integrated Slice 2R12 eligibility/Preview workflow.

This runner has one production configuration and no path, product, profile,
cap, cycle-count, or call-count overrides.  A durable claim-only artifact is
recovered offline before the release gate or any credential/client factory can
run.  New Coinbase reads remain hard-disabled until the audited source
constant below is changed in a separate release step.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, Final, Mapping, Sequence
from uuid import uuid4


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.futures_order_preview import (  # noqa: E402
    FUTURES_PREVIEW_ARTIFACT_ROOT,
)
from application.admin_api.futures_order_preview_r12 import (  # noqa: E402
    FUTURES_PREVIEW_R12_ARTIFACT_PATH,
    FUTURES_PREVIEW_R12_ELIGIBILITY_PATH,
    FUTURES_PREVIEW_R12_PREDECESSOR_BINDING,
    FuturesPreviewR12ArtifactStore,
    FuturesPreviewR12AttemptWorkflow,
    FuturesPreviewR12EligibilityStore,
    FuturesPreviewR12EligibilityWorkflow,
    _PRODUCTION_FUTURES_PREVIEW_R12_ARTIFACT_PATH,
    _PRODUCTION_FUTURES_PREVIEW_R12_ELIGIBILITY_PATH,
    validate_production_futures_order_preview_r12_predecessor,
)
from application.admin_api.models import (  # noqa: E402
    AdminFuturesOrderPreviewR12Response,
)
from tools import (  # noqa: E402
    run_admin_api_futures_no_live_preview as base_preview_tool,
)


# Deliberately source-bound.  Environment variables and CLI flags cannot
# activate it.  A later audited release must change this exact source value.
R12_RELEASE_READY: Final[bool] = True

_R12_ARTIFACT_NAME = "futures_exact_no_live_preview_slice_2r12.jsonl"
_R12_ELIGIBILITY_NAME = (
    "futures_exact_no_live_preview_slice_2r12_eligibility.jsonl"
)
_R12_AWS_CLI_VERSION_ROOT = Path(
    "/home/developer/.local/aws-cli/v2/2.35.24"
)
_R12_AWS_CLI_CANONICAL_PATH = _R12_AWS_CLI_VERSION_ROOT / "dist" / "aws"
_R12_AWS_CLI_CA_BUNDLE = (
    _R12_AWS_CLI_VERSION_ROOT / "dist" / "awscli" / "botocore" / "cacert.pem"
)
_R12_AWS_CLI_USER_LINK = Path("/home/developer/.local/bin/aws")
_R12_AWS_CLI_CURRENT_LINK = Path(
    "/home/developer/.local/aws-cli/v2/current"
)
_R12_AWS_CLI_VERSION_BIN_LINK = _R12_AWS_CLI_VERSION_ROOT / "bin" / "aws"
_R12_AWS_CREDENTIALS_PATH = Path("/home/developer/.aws/credentials")
_R12_AWS_CLI_SHA256 = (
    "cf06831bd626c1132effdff0c403cc115ae15fe83aaf455f43e504c148d344e5"
)
_R12_AWS_CLI_VERSION_OUTPUT = (
    "aws-cli/2.35.24 Python/3.14.6 Linux/6.18.33.2-microsoft-standard-WSL2 "
    "exe/x86_64.debian.12"
)
_R12_AWS_CLI_TREE_ENTRY_COUNT = 8_649
_R12_AWS_CLI_TREE_FILE_BYTES = 254_415_287
_R12_AWS_CLI_TREE_SHA256 = (
    "ec5b4574cc2fd9ee0f91afe7cef682a52ded5ac98faeae9bbc23b0b6f04ff7c1"
)
_R12_MAX_AWS_SECRET_RESPONSE_BYTES = 128 * 1024
_ELIGIBILITY_CLASSIFICATIONS = frozenset(
    {
        "permission_or_portfolio_ineligible",
        "product_contract_ineligible",
        "market_book_ineligible",
        "position_exposure_ineligible",
        "candidate_caps_ineligible",
        "margin_collateral_ineligible",
        "read_outcome_unknown",
        "internal_validation_blocked",
    }
)


class FuturesPreviewR12RunnerError(ValueError):
    """Fixed, value-blind production-runner failure."""


def _r12_bootstrap_read_regular(
    path: Path,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> bytes:
    """Read one stable, unlinked, non-writable provenance-bound file."""

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
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            payload = handle.read(maximum_bytes + 1)
            opened = os.fstat(handle.fileno())
    finally:
        os.close(descriptor)
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


def _r12_aws_cli_tree_sha256() -> str:
    """Return the fixed AWS CLI tree digest after strict metadata checks."""

    root_metadata = _R12_AWS_CLI_VERSION_ROOT.lstat()
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or root_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(root_metadata.st_mode) & 0o022
    ):
        raise ValueError("aws_root")
    digest = hashlib.sha256()
    entry_count = 0
    file_bytes = 0
    allowed_links = {
        "bin/aws": "../dist/aws",
        "bin/aws_completer": "../dist/aws_completer",
    }
    entries = sorted(
        _R12_AWS_CLI_VERSION_ROOT.rglob("*"),
        key=lambda path: path.relative_to(
            _R12_AWS_CLI_VERSION_ROOT
        ).as_posix(),
    )
    for path in entries:
        relative = path.relative_to(_R12_AWS_CLI_VERSION_ROOT).as_posix()
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
            payload = _r12_bootstrap_read_regular(
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
        entry_count != _R12_AWS_CLI_TREE_ENTRY_COUNT
        or file_bytes != _R12_AWS_CLI_TREE_FILE_BYTES
    ):
        raise ValueError("aws_tree_shape")
    return digest.hexdigest()


def _r12_credential_file_identity() -> tuple[int, ...]:
    """Return metadata only for the fixed owner-only credential file."""

    metadata = _R12_AWS_CREDENTIALS_PATH.lstat()
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


def _validate_r12_aws_cli_binding() -> bool:
    """Validate the exact AWS CLI/CA tree and secure credential location."""

    expected_links = (
        (
            _R12_AWS_CLI_USER_LINK,
            "/home/developer/.local/aws-cli/v2/current/bin/aws",
        ),
        (
            _R12_AWS_CLI_CURRENT_LINK,
            "/home/developer/.local/aws-cli/v2/2.35.24",
        ),
        (_R12_AWS_CLI_VERSION_BIN_LINK, "../dist/aws"),
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
        executable = _r12_bootstrap_read_regular(
            _R12_AWS_CLI_CANONICAL_PATH,
            maximum_bytes=16 * 1024 * 1024,
        )
        executable_metadata = _R12_AWS_CLI_CANONICAL_PATH.lstat()
        ca_bundle = _r12_bootstrap_read_regular(
            _R12_AWS_CLI_CA_BUNDLE,
            maximum_bytes=1024 * 1024,
        )
        ca_metadata = _R12_AWS_CLI_CA_BUNDLE.lstat()
        if (
            executable_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(executable_metadata.st_mode) != 0o755
            or hashlib.sha256(executable).hexdigest()
            != _R12_AWS_CLI_SHA256
            or ca_metadata.st_uid != os.geteuid()
            or not ca_bundle
            or _r12_aws_cli_tree_sha256() != _R12_AWS_CLI_TREE_SHA256
        ):
            return False
        _r12_credential_file_identity()
        completed = subprocess.run(
            [str(_R12_AWS_CLI_CANONICAL_PATH), "--version"],
            env={
                "AWS_CLI_HISTORY_FILE": "/dev/null",
                "AWS_CONFIG_FILE": "/dev/null",
                "AWS_EC2_METADATA_DISABLED": "true",
                "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
                "HOME": "/nonexistent",
                "LC_ALL": "C",
                "PATH": str(_R12_AWS_CLI_CANONICAL_PATH.parent),
            },
            check=True,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=10,
        )
        return (
            completed.stdout + completed.stderr
        ).strip() == _R12_AWS_CLI_VERSION_OUTPUT
    except Exception:
        return False


def _lookup_fixed_r12_secret(secret_id: str, region: str | None) -> str:
    """Resolve the fixed Default secret with one closed AWS CLI attempt."""

    diagnostic = "R12 credential preparation failed"
    if secret_id != "coinbase" or region != "us-east-1":
        raise FuturesPreviewR12RunnerError(diagnostic)
    argv = [
        str(_R12_AWS_CLI_CANONICAL_PATH),
        "secretsmanager",
        "get-secret-value",
        "--secret-id",
        "coinbase",
        "--region",
        "us-east-1",
        "--endpoint-url",
        "https://secretsmanager.us-east-1.amazonaws.com",
        "--ca-bundle",
        str(_R12_AWS_CLI_CA_BUNDLE),
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
        "PATH": str(_R12_AWS_CLI_CANONICAL_PATH.parent),
    }
    try:
        if not _validate_r12_aws_cli_binding():
            raise FuturesPreviewR12RunnerError(diagnostic)
        credential_identity_before = _r12_credential_file_identity()
        process_error = False
        completed: Any | None = None
        try:
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
        except Exception:
            process_error = True
        post_binding_valid = _validate_r12_aws_cli_binding()
        credential_identity_after = _r12_credential_file_identity()
        if (
            process_error
            or completed is None
            or not post_binding_valid
            or credential_identity_before != credential_identity_after
        ):
            raise FuturesPreviewR12RunnerError(diagnostic)
        payload = completed.stdout
        if (
            completed.returncode != 0
            or not isinstance(payload, str)
            or not payload.strip()
            or len(payload.encode("utf-8"))
            > _R12_MAX_AWS_SECRET_RESPONSE_BYTES
        ):
            raise FuturesPreviewR12RunnerError(diagnostic)
        return payload
    except FuturesPreviewR12RunnerError:
        raise
    except Exception:
        raise FuturesPreviewR12RunnerError(diagnostic) from None


class _R12SingleUseSecretLookup:
    """Consume the one credential-hydration attempt for one cycle process."""

    __slots__ = ("__used",)

    def __init__(self) -> None:
        self.__used = False

    def __call__(self, secret_id: str, region: str | None) -> str:
        if self.__used:
            raise FuturesPreviewR12RunnerError(
                "R12 credential preparation failed"
            )
        self.__used = True
        return _lookup_fixed_r12_secret(secret_id, region)


def build_parser() -> argparse.ArgumentParser:
    """Return the option-minimal R12 production parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Run the fixed Slice 2R12 eligibility workflow and, only after "
            "eligibility, its integrated single Preview-only attempt."
        )
    )
    parser.add_argument(
        "--confirm-one-r12-workflow",
        action="store_true",
        required=True,
        help=(
            "Confirm the fixed production workflow; the source-bound release "
            "gate must also be active."
        ),
    )
    return parser


def _validate_production_singleton_paths() -> None:
    """Reject any drift from the two imported production singleton paths."""

    expected_artifact = FUTURES_PREVIEW_ARTIFACT_ROOT / _R12_ARTIFACT_NAME
    expected_eligibility = (
        FUTURES_PREVIEW_ARTIFACT_ROOT / _R12_ELIGIBILITY_NAME
    )
    paths = (
        FUTURES_PREVIEW_R12_ARTIFACT_PATH,
        _PRODUCTION_FUTURES_PREVIEW_R12_ARTIFACT_PATH,
        expected_artifact,
        FUTURES_PREVIEW_R12_ELIGIBILITY_PATH,
        _PRODUCTION_FUTURES_PREVIEW_R12_ELIGIBILITY_PATH,
        expected_eligibility,
    )
    if (
        any(not isinstance(path, Path) or not path.is_absolute() for path in paths)
        or FUTURES_PREVIEW_R12_ARTIFACT_PATH
        != _PRODUCTION_FUTURES_PREVIEW_R12_ARTIFACT_PATH
        or FUTURES_PREVIEW_R12_ARTIFACT_PATH != expected_artifact
        or FUTURES_PREVIEW_R12_ELIGIBILITY_PATH
        != _PRODUCTION_FUTURES_PREVIEW_R12_ELIGIBILITY_PATH
        or FUTURES_PREVIEW_R12_ELIGIBILITY_PATH != expected_eligibility
        or FUTURES_PREVIEW_R12_ARTIFACT_PATH
        == FUTURES_PREVIEW_R12_ELIGIBILITY_PATH
    ):
        raise FuturesPreviewR12RunnerError(
            "R12 production singleton paths are invalid"
        )


@lru_cache(maxsize=1)
def _cached_canonical_default_rest_client() -> Any:
    """Return one canonical Default client for both authorized phases."""

    with base_preview_tool._suppress_coinbase_sdk_logging():  # noqa: SLF001
        return base_preview_tool._build_canonical_default_rest_client(  # noqa: SLF001
            run_secret_lookup=_R12SingleUseSecretLookup(),
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _uuid4_text() -> str:
    return str(uuid4())


def _build_attempt_workflow(
    *,
    eligibility_store: FuturesPreviewR12EligibilityStore,
    artifact_store: FuturesPreviewR12ArtifactStore,
) -> FuturesPreviewR12AttemptWorkflow:
    """Construct the only production R12 attempt workflow without hydrating."""

    return FuturesPreviewR12AttemptWorkflow(
        eligibility_store=eligibility_store,
        store=artifact_store,
        predecessor_binding=FUTURES_PREVIEW_R12_PREDECESSOR_BINDING,
        predecessor_validator=(
            validate_production_futures_order_preview_r12_predecessor
        ),
        now=_utc_now,
        correlation_id_factory=_uuid4_text,
        idempotency_key_factory=_uuid4_text,
    )


def _recover_existing_attempt(
    workflow: FuturesPreviewR12AttemptWorkflow,
) -> dict[str, Any] | None:
    """Recover claim-only state or read an existing terminal, fully offline."""

    with workflow.eligibility_store.workflow_lease() as lease_nonce:
        return workflow.recover_claim_only(_lease_nonce=lease_nonce)


def _artifact_present() -> bool:
    try:
        FUTURES_PREVIEW_R12_ARTIFACT_PATH.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _blocked_summary(*, blocker: str, consumed: bool) -> dict[str, object]:
    return {
        "status": "blocked",
        "blocker": blocker,
        "artifact_path": str(FUTURES_PREVIEW_R12_ARTIFACT_PATH),
        "eligibility_path": str(FUTURES_PREVIEW_R12_ELIGIBILITY_PATH),
        "artifact_created": _artifact_present(),
        "r12_attempt_consumed": consumed,
        "preview_order_attempt_count": 1 if consumed else 0,
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "live_coinbase_execution": "not_run",
    }


def _validated_terminal_summary(
    value: Mapping[str, Any],
) -> dict[str, object]:
    """Validate the full terminal, then emit only a fixed safe projection."""

    try:
        validated = AdminFuturesOrderPreviewR12Response.model_validate(value)
        terminal = validated.model_dump(mode="json")
        attempts = terminal["attempt_counters"]
        preview_attempts = attempts["preview_order"]
        if type(preview_attempts) is not int or preview_attempts not in {0, 1}:
            raise ValueError("attempt count")
    except Exception:
        raise FuturesPreviewR12RunnerError(
            "R12 terminal readback is invalid"
        ) from None
    return {
        "status": terminal["status"],
        "outcome": terminal["outcome"],
        "blocker": terminal["blocker"],
        "artifact_path": str(FUTURES_PREVIEW_R12_ARTIFACT_PATH),
        "eligibility_path": str(FUTURES_PREVIEW_R12_ELIGIBILITY_PATH),
        "artifact_created": True,
        "r12_attempt_consumed": True,
        "preview_order_attempt_count": preview_attempts,
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "live_coinbase_execution": "not_run",
    }


def _eligibility_summary(value: Mapping[str, Any]) -> dict[str, object]:
    """Project a non-attempt eligibility terminal without identifiers/hashes."""

    status = value.get("status")
    classification = value.get("classification")
    cycle_number = value.get("cycle_number")
    if (
        status not in {"ineligible", "unknown"}
        or classification not in _ELIGIBILITY_CLASSIFICATIONS
        or type(cycle_number) is not int
        or not 1 <= cycle_number <= 10
        or value.get("r12_claim_created") is not False
        or value.get("r12_idempotency_key_created") is not False
        or value.get("r12_attempt_consumed") is not False
    ):
        raise FuturesPreviewR12RunnerError(
            "R12 eligibility result is invalid"
        )
    return {
        "status": status,
        "classification": classification,
        "eligibility_cycle_number": cycle_number,
        "artifact_path": str(FUTURES_PREVIEW_R12_ARTIFACT_PATH),
        "eligibility_path": str(FUTURES_PREVIEW_R12_ELIGIBILITY_PATH),
        "artifact_created": False,
        "r12_attempt_consumed": False,
        "preview_order_attempt_count": 0,
        "exchange_submission_attempt_count": 0,
        "submitted_notional_usdc": "0",
        "executed_notional_usdc": "0",
        "live_coinbase_execution": "not_run",
    }


def _write_summary(summary: Mapping[str, object], *, success: bool) -> int:
    print(
        json.dumps(dict(summary), sort_keys=True, separators=(",", ":")),
        file=sys.stdout if success else sys.stderr,
    )
    return 0 if success else 2


def main(argv: Sequence[str] | None = None) -> int:
    """Recover offline first; otherwise run exactly one integrated cycle."""

    build_parser().parse_args(argv)
    try:
        _validate_production_singleton_paths()
    except Exception:
        return _write_summary(
            _blocked_summary(
                blocker="futures_preview_r12_production_path_blocked",
                consumed=False,
            ),
            success=False,
        )

    eligibility_store = FuturesPreviewR12EligibilityStore(
        FUTURES_PREVIEW_R12_ELIGIBILITY_PATH
    )
    artifact_store = FuturesPreviewR12ArtifactStore(
        FUTURES_PREVIEW_R12_ARTIFACT_PATH
    )
    attempt_workflow = _build_attempt_workflow(
        eligibility_store=eligibility_store,
        artifact_store=artifact_store,
    )

    # Recovery is intentionally before the source gate and before any client
    # factory.  It can only append/read local terminal evidence.
    try:
        recovered = _recover_existing_attempt(attempt_workflow)
    except Exception:
        return _write_summary(
            _blocked_summary(
                blocker="futures_preview_r12_recovery_blocked",
                consumed=_artifact_present(),
            ),
            success=False,
        )
    if recovered is not None:
        try:
            summary = _validated_terminal_summary(recovered)
        except Exception:
            return _write_summary(
                _blocked_summary(
                    blocker="futures_preview_r12_terminal_readback_blocked",
                    consumed=True,
                ),
                success=False,
            )
        return _write_summary(
            summary,
            success=summary["status"] == "accepted",
        )

    if R12_RELEASE_READY is not True:
        return _write_summary(
            _blocked_summary(
                blocker="futures_preview_r12_release_gate_inactive",
                consumed=False,
            ),
            success=False,
        )

    try:
        predecessor = dict(
            validate_production_futures_order_preview_r12_predecessor()
        )
    except Exception:
        return _write_summary(
            _blocked_summary(
                blocker="futures_preview_r12_predecessor_blocked",
                consumed=False,
            ),
            success=False,
        )
    if predecessor != FUTURES_PREVIEW_R12_PREDECESSOR_BINDING:
        return _write_summary(
            _blocked_summary(
                blocker="futures_preview_r12_predecessor_binding_blocked",
                consumed=False,
            ),
            success=False,
        )

    eligibility_workflow = FuturesPreviewR12EligibilityWorkflow(
        store=eligibility_store,
        attempt_artifact_path=FUTURES_PREVIEW_R12_ARTIFACT_PATH,
        rest_client_factory=_cached_canonical_default_rest_client,
        now=_utc_now,
        correlation_id_factory=_uuid4_text,
    )
    try:
        with base_preview_tool._suppress_coinbase_sdk_logging():  # noqa: SLF001
            result = eligibility_workflow.run_cycle(
                attempt_workflow=attempt_workflow
            )
    except Exception:
        # If a claim exists, this is an offline terminal read/recovery only;
        # it cannot invoke the client factory.
        try:
            terminal = _recover_existing_attempt(attempt_workflow)
        except Exception:
            terminal = None
        if terminal is not None:
            try:
                summary = _validated_terminal_summary(terminal)
            except Exception:
                summary = _blocked_summary(
                    blocker="futures_preview_r12_terminal_readback_blocked",
                    consumed=True,
                )
            return _write_summary(
                summary,
                success=summary["status"] == "accepted",
            )
        return _write_summary(
            _blocked_summary(
                blocker="futures_preview_r12_workflow_blocked",
                consumed=_artifact_present(),
            ),
            success=False,
        )

    try:
        if (
            result.get("artifact_type")
            == "futures_exact_no_live_preview_slice_2r12"
            and result.get("outcome") in {"accepted", "blocked", "unknown"}
        ):
            summary = _validated_terminal_summary(result)
            return _write_summary(
                summary,
                success=summary["status"] == "accepted",
            )
        summary = _eligibility_summary(result)
    except Exception:
        return _write_summary(
            _blocked_summary(
                blocker="futures_preview_r12_result_validation_blocked",
                consumed=_artifact_present(),
            ),
            success=False,
        )
    return _write_summary(summary, success=False)


if __name__ == "__main__":
    raise SystemExit(main())
