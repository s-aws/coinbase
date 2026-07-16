"""Opaque, sanitized readback for the accidentally consumed R8 generation.

The fixed R8 artifact predates the persistence-safe successor schema.  It is
therefore never opened or deserialized by this module.  The operator-visible
readback is built only from its documented SHA-256, verified stat metadata,
and the independently localized, strictly allowlisted failure boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from application.admin_api.futures_order_preview import (
    FUTURES_PREVIEW_R8_ARTIFACT_PATH,
    FUTURES_PREVIEW_R8_TERMINAL_BINDING,
    FuturesOrderPreviewArtifactError,
    canonical_sha256,
    validate_production_futures_order_preview_r8_opaque_chain,
)


_AUTHORIZATION_SHA256 = (
    "5c9c2432179989446d79da2e8f173729103844a96f00e1eeec56dcf5c8e2dc51"
)


class AdminFuturesPreviewR8ArtifactMetadata(BaseModel):
    """Exact non-content filesystem metadata for immutable R8."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_name: Literal["futures_exact_no_live_preview_slice_2r8.jsonl"]
    device: Literal["2096"]
    inode: Literal["400341"]
    size_bytes: Literal[14921]
    mode: Literal["0400"]
    mtime_ns: Literal["1784160315297279427"]
    nlink: Literal[1]


class AdminFuturesPreviewR8ReadBoundaryCounters(BaseModel):
    """Boundaries entered by the isolated synthetic test, not network calls."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key_permissions: Literal[1]
    portfolio_catalog: Literal[0]
    product: Literal[0]
    best_bid_ask: Literal[0]
    futures_positions: Literal[0]
    futures_margin_collateral: Literal[0]


class AdminFuturesPreviewR8AttemptCounters(BaseModel):
    """Exact zero-call, zero-mutation R8 terminal counters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    preview_order: Literal[0]
    retry: Literal[0]
    fallback: Literal[0]
    create_order: Literal[0]
    cancel_order: Literal[0]
    close_position: Literal[0]
    reduce_position: Literal[0]


class AdminFuturesPreviewR8Scope(BaseModel):
    """Unchanged operator scope carried forward without private identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_label: Literal["Default"]
    portfolio_type: Literal["DEFAULT"]
    product_id: Literal["AVP-20DEC30-CDE"]
    side: Literal["BUY"]
    contract_count: Literal["1"]
    opening_cap: Literal["<100 USDC"]
    exposure_and_buffered_close_cap: Literal["<150 USDC"]
    branch_turnover_cap: Literal["<300 USDC"]


class AdminFuturesPreviewR8ForensicReadback(BaseModel):
    """Sanitized terminal classification that contains no R8 record content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["futures-preview-r8-forensic-readback-v2"]
    artifact_type: Literal["futures_exact_no_live_preview_slice_2r8"]
    generation: Literal["R8"]
    status: Literal["blocked"]
    outcome: Literal["blocked"]
    blocker: Literal["preflight_or_preview_blocked:Exception"]
    localized_failure_boundary: Literal["api_key_permissions_read_boundary"]
    evidence_origin: Literal["independent_sanitized_forensic_classification"]
    generation_consumed: Literal[True]
    authorization_sha256: Literal[
        "5c9c2432179989446d79da2e8f173729103844a96f00e1eeec56dcf5c8e2dc51"
    ]
    artifact_file_sha256: Literal[
        "b32aba4868f08ee7a44f19ceacbcf42cb7e4d70da1552f2d8b333ef59ddc8696"
    ]
    artifact_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_metadata: AdminFuturesPreviewR8ArtifactMetadata
    scope: AdminFuturesPreviewR8Scope
    read_boundary_counters: AdminFuturesPreviewR8ReadBoundaryCounters
    attempt_counters: AdminFuturesPreviewR8AttemptCounters
    real_aws_service_call_count: Literal[0]
    real_coinbase_request_count: Literal[0]
    exchange_submission_attempt_count: Literal[0]
    submitted_notional_usdc: Literal["0"]
    executed_notional_usdc: Literal["0"]
    live_coinbase_execution: Literal["not_run"]
    slice3_activated: Literal[False]
    documented_sha256_stat_metadata_validated: Literal[True]
    artifact_file_sha256_source: Literal[
        "documented_preexisting_binding_not_recomputed"
    ]
    artifact_bytes_opened: Literal[False]
    raw_response_included: Literal[False]
    private_identifier_values_included: Literal[False]
    withheld_exception_text_included: Literal[False]
    preservation: Literal["immutable_no_modify_delete_or_reuse"]


def build_r8_forensic_readback(
    *,
    observed_binding: Mapping[str, object] | None = None,
) -> AdminFuturesPreviewR8ForensicReadback:
    """Build the fixed R8 readback without deserializing its JSONL bytes."""

    observed = dict(
        validate_production_futures_order_preview_r8_opaque_chain()
        if observed_binding is None
        else observed_binding
    )
    if observed != FUTURES_PREVIEW_R8_TERMINAL_BINDING:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R8 forensic binding changed"
        )
    return AdminFuturesPreviewR8ForensicReadback(
        schema_version="futures-preview-r8-forensic-readback-v2",
        artifact_type="futures_exact_no_live_preview_slice_2r8",
        generation="R8",
        status="blocked",
        outcome="blocked",
        blocker="preflight_or_preview_blocked:Exception",
        localized_failure_boundary="api_key_permissions_read_boundary",
        evidence_origin="independent_sanitized_forensic_classification",
        generation_consumed=True,
        authorization_sha256=_AUTHORIZATION_SHA256,
        artifact_file_sha256=observed["file_sha256"],
        artifact_binding_sha256=canonical_sha256(observed),
        artifact_metadata={
            "artifact_name": observed["artifact_name"],
            "device": observed["device"],
            "inode": observed["inode"],
            "size_bytes": observed["size_bytes"],
            "mode": observed["mode"],
            "mtime_ns": observed["mtime_ns"],
            "nlink": observed["nlink"],
        },
        scope={
            "profile_label": "Default",
            "portfolio_type": "DEFAULT",
            "product_id": "AVP-20DEC30-CDE",
            "side": "BUY",
            "contract_count": "1",
            "opening_cap": "<100 USDC",
            "exposure_and_buffered_close_cap": "<150 USDC",
            "branch_turnover_cap": "<300 USDC",
        },
        read_boundary_counters={
            "api_key_permissions": 1,
            "portfolio_catalog": 0,
            "product": 0,
            "best_bid_ask": 0,
            "futures_positions": 0,
            "futures_margin_collateral": 0,
        },
        attempt_counters={
            "preview_order": 0,
            "retry": 0,
            "fallback": 0,
            "create_order": 0,
            "cancel_order": 0,
            "close_position": 0,
            "reduce_position": 0,
        },
        real_aws_service_call_count=0,
        real_coinbase_request_count=0,
        exchange_submission_attempt_count=0,
        submitted_notional_usdc="0",
        executed_notional_usdc="0",
        live_coinbase_execution="not_run",
        slice3_activated=False,
        documented_sha256_stat_metadata_validated=True,
        artifact_file_sha256_source=(
            "documented_preexisting_binding_not_recomputed"
        ),
        artifact_bytes_opened=False,
        raw_response_included=False,
        private_identifier_values_included=False,
        withheld_exception_text_included=False,
        preservation="immutable_no_modify_delete_or_reuse",
    )


def is_fixed_r8_forensic_artifact_path(path: Path | str) -> bool:
    """Compare lexically so a symlink cannot redirect the forensic boundary."""

    return os.path.abspath(os.fspath(path)) == os.path.abspath(
        os.fspath(FUTURES_PREVIEW_R8_ARTIFACT_PATH)
    )


__all__ = [
    "AdminFuturesPreviewR8ForensicReadback",
    "build_r8_forensic_readback",
    "is_fixed_r8_forensic_artifact_path",
]
