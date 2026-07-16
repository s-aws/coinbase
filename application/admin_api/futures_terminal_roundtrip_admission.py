"""Immutable, sanitized admission evidence for the Slice 3 roundtrip.

The module turns an already-built in-memory Slice 3 plan and ten explicit
backend evidence references into one short-lived hash chain.  It has no HTTP
surface, exchange client, credential hydration, or execution method.  Raw
operator and Coinbase identifiers are accepted only by the upstream plan and
are represented here solely by SHA-256 bindings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
from uuid import UUID

from application.admin_api.futures_terminal_roundtrip import (
    SLICE3_ACTOR_ID,
    SLICE3_CLOSE_BUFFER,
    SLICE3_EXPOSURE_CAP_USDC,
    SLICE3_LIVE_POLICY,
    SLICE3_MAX_READ_AGE,
    SLICE3_MAX_RISK_OFF_TTL,
    SLICE3_METHOD,
    SLICE3_OPENING_CAP_USDC,
    SLICE3_PERMISSION,
    SLICE3_PRODUCT_ID,
    SLICE3_ROLES,
    SLICE3_ROUTE,
    SLICE3_SERVICE_METHOD,
    SLICE3_TURNOVER_CAP_USDC,
    Slice3AcceptedPreview,
    Slice3CapEvidence,
    Slice3CreateRequest,
    Slice3DirectiveKind,
    Slice3ExecutionAuthority,
    Slice3Plan,
    Slice3PortfolioBinding,
    Slice3ReadSlot,
)
from application.admin_api.futures_terminal_roundtrip_activation import (
    Slice3AcceptedR8Binding,
)
from application.admin_api.futures_terminal_roundtrip_coinbase import (
    Slice3CoinbaseAccountBinding,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
SLICE3_ADMISSION_ARTIFACT_PATH = (
    _REPO_ROOT / "runtime_state" / "futures_slice3_admission_evidence.json"
)
SLICE3_ADMISSION_SCHEMA_VERSION = "slice3-admission-evidence-chain-v2"
SLICE3_ADMISSION_RECORD_SCHEMA_VERSION = "slice3-admission-evidence-record-v1"
SLICE3_ADMISSION_ARTIFACT_SCHEMA_VERSION = "slice3-admission-artifact-v1"
SLICE3_ADMISSION_GENESIS_SHA256 = "0" * 64
SLICE3_ADMISSION_MAX_TTL = SLICE3_MAX_RISK_OFF_TTL
SLICE3_OPERATOR_AUTHORIZATION_SHA256 = (
    "5c9c2432179989446d79da2e8f173729103844a96f00e1eeec56dcf5c8e2dc51"
)
_AUTHORIZATION_SCOPE = (
    "futures_preview_acceptance_recovery_r8_r10_and_"
    "conditional_terminal_roundtrip_slice_3"
)

_FIXED_CREDENTIAL_BINDING: Mapping[str, str] = {
    "source": "secrets_manager",
    "secret_id": "coinbase",
    "region": "us-east-1",
}
_ATTEMPT_LIMITS: Mapping[str, int] = {
    "preview": 0,
    "create": 1,
    "cancel": 1,
    "close": 1,
    "reduce": 0,
    "retry": 0,
    "fallback": 0,
    "redirect": 0,
}
_MAX_ARTIFACT_BYTES = 128 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_STATE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PRIVATE_IDENTIFIER_FIELDS = frozenset(
    {
        "client_order_id",
        "close_client_order_id",
        "correlation_id",
        "idempotency_key",
        "preview_idempotency_key",
        "preview_id",
        "portfolio_id",
        "order_id",
        "exchange_order_id",
        "api_key",
        "api_secret",
        "secret",
        "raw_response",
        "response",
        "withheld_exception_text",
    }
)


class Slice3AdmissionValidationError(ValueError):
    """Raised when the evidence chain is not the exact authorized contract."""


class Slice3AdmissionArtifactError(RuntimeError):
    """Raised when immutable artifact persistence or readback is unsafe."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Slice3AdmissionValidationError(
            "slice3_admission_canonical_json_invalid"
        ) from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256 = _canonical_sha256(
    dict(_FIXED_CREDENTIAL_BINDING)
)


def _private_sha256(value: str, reason: str) -> str:
    if not (
        isinstance(value, str)
        and value == value.strip()
        and value.isprintable()
        and 0 < len(value) <= 512
    ):
        raise Slice3AdmissionValidationError(reason)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_sha256(value: object, reason: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise Slice3AdmissionValidationError(reason)
    return value


def _require_uuid4(value: object, reason: str) -> str:
    if not isinstance(value, str):
        raise Slice3AdmissionValidationError(reason)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError) as exc:
        raise Slice3AdmissionValidationError(reason) from exc
    if parsed.version != 4 or str(parsed) != value.lower():
        raise Slice3AdmissionValidationError(reason)
    return value


def _aware_utc(value: object, reason: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise Slice3AdmissionValidationError(reason)
    try:
        normalized = value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise Slice3AdmissionValidationError(reason) from exc
    if normalized.utcoffset() != timedelta(0):
        raise Slice3AdmissionValidationError(reason)
    return normalized


def _parse_timestamp(value: object, reason: str) -> datetime:
    if not isinstance(value, str):
        raise Slice3AdmissionValidationError(reason)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise Slice3AdmissionValidationError(reason) from exc
    normalized = _aware_utc(parsed, reason)
    if normalized.isoformat() != value:
        raise Slice3AdmissionValidationError(f"{reason}_noncanonical")
    return normalized


def _decimal(value: object, reason: str) -> Decimal:
    if isinstance(value, bool):
        raise Slice3AdmissionValidationError(reason)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Slice3AdmissionValidationError(reason) from exc
    if not result.is_finite():
        raise Slice3AdmissionValidationError(reason)
    return result


def _reject_private_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            rendered = str(key)
            if rendered in _PRIVATE_IDENTIFIER_FIELDS:
                raise Slice3AdmissionValidationError(
                    "slice3_admission_raw_private_field_present"
                )
            _reject_private_fields(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_private_fields(item)


class Slice3AdmissionEvidenceKind(str, Enum):
    """The exact record kinds permitted in the Slice 3 admission chain."""

    AUTHORIZATION = "authorization"
    OPERATOR_REQUEST = "operator_request"
    APPROVAL = "approval"
    ADMISSION_AUDIT = "admission_audit"
    CAP_GUARD = "cap_guard"
    RECONCILIATION = "reconciliation"
    LIVE_SERVICE = "live_service"
    ADAPTER = "adapter"
    CREDENTIAL = "credential"
    PORTFOLIO = "portfolio"
    PERMISSION = "permission"
    CATALOG = "catalog"


SLICE3_ADMISSION_RECORD_ORDER = (
    Slice3AdmissionEvidenceKind.AUTHORIZATION,
    Slice3AdmissionEvidenceKind.OPERATOR_REQUEST,
    Slice3AdmissionEvidenceKind.APPROVAL,
    Slice3AdmissionEvidenceKind.ADMISSION_AUDIT,
    Slice3AdmissionEvidenceKind.CAP_GUARD,
    Slice3AdmissionEvidenceKind.RECONCILIATION,
    Slice3AdmissionEvidenceKind.LIVE_SERVICE,
    Slice3AdmissionEvidenceKind.ADAPTER,
    Slice3AdmissionEvidenceKind.CREDENTIAL,
    Slice3AdmissionEvidenceKind.PORTFOLIO,
    Slice3AdmissionEvidenceKind.PERMISSION,
    Slice3AdmissionEvidenceKind.CATALOG,
)

_SOURCE_STATE: Mapping[Slice3AdmissionEvidenceKind, str] = {
    Slice3AdmissionEvidenceKind.APPROVAL: "approved",
    Slice3AdmissionEvidenceKind.ADMISSION_AUDIT: "allowed",
    Slice3AdmissionEvidenceKind.CAP_GUARD: "allowed",
    Slice3AdmissionEvidenceKind.RECONCILIATION: "approved",
    Slice3AdmissionEvidenceKind.LIVE_SERVICE: "enabled",
    Slice3AdmissionEvidenceKind.ADAPTER: "approved",
    Slice3AdmissionEvidenceKind.CREDENTIAL: "bound",
    Slice3AdmissionEvidenceKind.PORTFOLIO: "permission_selected",
    Slice3AdmissionEvidenceKind.PERMISSION: "allowed",
    Slice3AdmissionEvidenceKind.CATALOG: "matched",
}


@dataclass(frozen=True, slots=True)
class Slice3AdmissionSourceEvidence:
    """Hash-only reference to one independently produced control record."""

    kind: Slice3AdmissionEvidenceKind
    evidence_id_sha256: str
    evidence_sha256: str
    observed_at: datetime
    state: str
    allowed: bool
    approved: bool

    @classmethod
    def from_private_evidence_id(
        cls,
        *,
        kind: Slice3AdmissionEvidenceKind,
        evidence_id: str,
        evidence_sha256: str,
        observed_at: datetime,
        state: str,
        allowed: bool,
        approved: bool,
    ) -> Slice3AdmissionSourceEvidence:
        """Hash an ephemeral evidence id without retaining the raw value."""

        return cls(
            kind=kind,
            evidence_id_sha256=_private_sha256(
                evidence_id,
                "slice3_admission_evidence_id_invalid",
            ),
            evidence_sha256=evidence_sha256,
            observed_at=observed_at,
            state=state,
            allowed=allowed,
            approved=approved,
        )

    def validate(self, *, now: datetime) -> None:
        if self.kind not in _SOURCE_STATE:
            raise Slice3AdmissionValidationError("slice3_admission_source_kind_invalid")
        _require_sha256(
            self.evidence_id_sha256,
            f"slice3_admission_{self.kind.value}_evidence_id_invalid",
        )
        _require_sha256(
            self.evidence_sha256,
            f"slice3_admission_{self.kind.value}_evidence_hash_invalid",
        )
        if (
            not isinstance(self.state, str)
            or _SAFE_STATE_RE.fullmatch(self.state) is None
            or self.state != _SOURCE_STATE[self.kind]
        ):
            raise Slice3AdmissionValidationError(
                f"slice3_admission_{self.kind.value}_state_invalid"
            )
        if self.allowed is not True or self.approved is not True:
            raise Slice3AdmissionValidationError(
                f"slice3_admission_{self.kind.value}_not_allowed"
            )
        observed = _aware_utc(
            self.observed_at,
            f"slice3_admission_{self.kind.value}_timestamp_invalid",
        )
        current = _aware_utc(now, "slice3_admission_now_invalid")
        age = current - observed
        if age < timedelta(0) or age > SLICE3_MAX_READ_AGE:
            raise Slice3AdmissionValidationError(
                f"slice3_admission_{self.kind.value}_stale"
            )

    def sanitized_evidence(self) -> dict[str, object]:
        return {
            "evidence_id_sha256": self.evidence_id_sha256,
            "evidence_sha256": self.evidence_sha256,
            "observed_at": self.observed_at.astimezone(timezone.utc).isoformat(),
            "state": self.state,
            "allowed": self.allowed,
            "approved": self.approved,
        }


@dataclass(frozen=True, slots=True)
class Slice3AdmissionEvidenceSet:
    """The ten mandatory source records, named to prevent record swapping."""

    approval: Slice3AdmissionSourceEvidence
    admission_audit: Slice3AdmissionSourceEvidence
    cap_guard: Slice3AdmissionSourceEvidence
    reconciliation: Slice3AdmissionSourceEvidence
    live_service: Slice3AdmissionSourceEvidence
    adapter: Slice3AdmissionSourceEvidence
    credential: Slice3AdmissionSourceEvidence
    portfolio: Slice3AdmissionSourceEvidence
    permission: Slice3AdmissionSourceEvidence
    catalog: Slice3AdmissionSourceEvidence

    def ordered(self) -> tuple[Slice3AdmissionSourceEvidence, ...]:
        return (
            self.approval,
            self.admission_audit,
            self.cap_guard,
            self.reconciliation,
            self.live_service,
            self.adapter,
            self.credential,
            self.portfolio,
            self.permission,
            self.catalog,
        )

    def validate(self, *, plan: Slice3Plan, now: datetime) -> None:
        authority = plan.execution_authority
        expected_hashes = {
            Slice3AdmissionEvidenceKind.APPROVAL: (authority.approval_evidence_sha256),
            Slice3AdmissionEvidenceKind.ADMISSION_AUDIT: (
                authority.admission_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.CAP_GUARD: (
                authority.cap_guard_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.RECONCILIATION: (
                authority.reconciliation_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.LIVE_SERVICE: (
                authority.live_service_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.ADAPTER: (authority.adapter_evidence_sha256),
            Slice3AdmissionEvidenceKind.CREDENTIAL: (
                SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256
            ),
            Slice3AdmissionEvidenceKind.PORTFOLIO: _canonical_sha256(
                plan.portfolio.sanitized_evidence()
            ),
            Slice3AdmissionEvidenceKind.PERMISSION: (
                plan.portfolio.permission_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.CATALOG: (
                plan.portfolio.portfolio_catalog_sha256
            ),
        }
        expected_kinds = tuple(_SOURCE_STATE)
        sources = self.ordered()
        if tuple(source.kind for source in sources) != expected_kinds:
            raise Slice3AdmissionValidationError(
                "slice3_admission_source_order_invalid"
            )
        evidence_ids: set[str] = set()
        for source in sources:
            source.validate(now=now)
            if source.evidence_sha256 != expected_hashes[source.kind]:
                raise Slice3AdmissionValidationError(
                    f"slice3_admission_{source.kind.value}_evidence_mismatch"
                )
            if source.evidence_id_sha256 in evidence_ids:
                raise Slice3AdmissionValidationError(
                    "slice3_admission_duplicate_evidence_id"
                )
            evidence_ids.add(source.evidence_id_sha256)


def _derived_source(
    *,
    kind: Slice3AdmissionEvidenceKind,
    evidence_sha256: str,
    observed_at: datetime,
) -> Slice3AdmissionSourceEvidence:
    """Create one deterministic hash-only control-record reference."""

    evidence_hash = _require_sha256(
        evidence_sha256,
        f"slice3_admission_{kind.value}_evidence_hash_invalid",
    )
    return Slice3AdmissionSourceEvidence(
        kind=kind,
        evidence_id_sha256=hashlib.sha256(
            f"slice3:{kind.value}:{evidence_hash}".encode("utf-8")
        ).hexdigest(),
        evidence_sha256=evidence_hash,
        observed_at=observed_at,
        state=_SOURCE_STATE[kind],
        allowed=True,
        approved=True,
    )


@dataclass(frozen=True, slots=True)
class Slice3AdmissionAuthorityBundle:
    """Pre-plan authority derived from concrete sanitized control records."""

    authority: Slice3ExecutionAuthority
    evidence: Slice3AdmissionEvidenceSet
    accepted_r8_binding_sha256: str
    account_binding_sha256: str
    portfolio_evidence_sha256: str
    create_evidence_sha256: str
    preview_evidence_sha256: str
    caps_evidence_sha256: str
    close_client_order_id_sha256: str
    control_records_json: str
    built_at: datetime

    def control_records(self) -> dict[str, object]:
        try:
            value = json.loads(self.control_records_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise Slice3AdmissionValidationError(
                "slice3_admission_control_records_invalid"
            ) from exc
        if not isinstance(value, dict):
            raise Slice3AdmissionValidationError(
                "slice3_admission_control_records_invalid"
            )
        return value

    def validate_at(self, *, now: datetime) -> None:
        current = _aware_utc(now, "slice3_admission_now_invalid")
        built = _aware_utc(
            self.built_at,
            "slice3_admission_authority_built_at_invalid",
        )
        age = current - built
        if age < timedelta(0) or age > SLICE3_MAX_READ_AGE:
            raise Slice3AdmissionValidationError(
                "slice3_admission_authority_bundle_stale"
            )
        for field_name, value in (
            ("accepted_r8_binding", self.accepted_r8_binding_sha256),
            ("account_binding", self.account_binding_sha256),
            ("portfolio_evidence", self.portfolio_evidence_sha256),
            ("create_evidence", self.create_evidence_sha256),
            ("preview_evidence", self.preview_evidence_sha256),
            ("caps_evidence", self.caps_evidence_sha256),
            ("close_client_order_id", self.close_client_order_id_sha256),
        ):
            _require_sha256(
                value,
                f"slice3_admission_{field_name}_hash_invalid",
            )
        try:
            self.authority.validate(now=current)
        except (TypeError, ValueError) as exc:
            raise Slice3AdmissionValidationError(
                "slice3_admission_derived_authority_invalid"
            ) from exc
        if self.authority.authorization_sha256 != SLICE3_OPERATOR_AUTHORIZATION_SHA256:
            raise Slice3AdmissionValidationError(
                "slice3_admission_derived_authority_authorization_invalid"
            )
        records = self.control_records()
        if set(records) != {
            "approval",
            "admission_audit",
            "cap_guard",
            "reconciliation",
            "live_service",
            "adapter",
        }:
            raise Slice3AdmissionValidationError(
                "slice3_admission_control_records_invalid"
            )
        expected_hashes = {
            "approval": self.authority.approval_evidence_sha256,
            "admission_audit": self.authority.admission_evidence_sha256,
            "cap_guard": self.authority.cap_guard_evidence_sha256,
            "reconciliation": self.authority.reconciliation_evidence_sha256,
            "live_service": self.authority.live_service_evidence_sha256,
        }
        for name, expected_hash in expected_hashes.items():
            record = records.get(name)
            if (
                not isinstance(record, Mapping)
                or _canonical_sha256(record) != expected_hash
            ):
                raise Slice3AdmissionValidationError(
                    f"slice3_admission_{name}_derivation_invalid"
                )
        adapter = records.get("adapter")
        if not isinstance(adapter, Mapping) or not (
            adapter.get("account_binding_sha256") == self.account_binding_sha256
            and adapter.get("adapter_evidence_sha256")
            == self.authority.adapter_evidence_sha256
            and adapter.get("credential_binding_sha256")
            == SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256
            and adapter.get("backed_by_slice3_coinbase_account_binding") is True
        ):
            raise Slice3AdmissionValidationError(
                "slice3_admission_adapter_derivation_invalid"
            )
        expected_sources = {
            Slice3AdmissionEvidenceKind.APPROVAL: (
                self.authority.approval_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.ADMISSION_AUDIT: (
                self.authority.admission_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.CAP_GUARD: (
                self.authority.cap_guard_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.RECONCILIATION: (
                self.authority.reconciliation_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.LIVE_SERVICE: (
                self.authority.live_service_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.ADAPTER: (
                self.authority.adapter_evidence_sha256
            ),
            Slice3AdmissionEvidenceKind.CREDENTIAL: (
                SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256
            ),
            Slice3AdmissionEvidenceKind.PORTFOLIO: (self.portfolio_evidence_sha256),
        }
        seen: set[str] = set()
        for source in self.evidence.ordered():
            source.validate(now=current)
            expected = expected_sources.get(source.kind)
            if expected is not None and source.evidence_sha256 != expected:
                raise Slice3AdmissionValidationError(
                    f"slice3_admission_{source.kind.value}_derivation_invalid"
                )
            if source.evidence_id_sha256 in seen:
                raise Slice3AdmissionValidationError(
                    "slice3_admission_duplicate_evidence_id"
                )
            seen.add(source.evidence_id_sha256)

    def validate_plan(self, plan: Slice3Plan, *, now: datetime) -> None:
        self.validate_at(now=now)
        if not isinstance(plan, Slice3Plan):
            raise Slice3AdmissionValidationError("slice3_admission_plan_invalid")
        try:
            plan.validate_at(now)
        except (TypeError, ValueError) as exc:
            raise Slice3AdmissionValidationError(
                "slice3_admission_plan_invalid"
            ) from exc
        exact = {
            "authority": plan.execution_authority == self.authority,
            "portfolio": _canonical_sha256(plan.portfolio.sanitized_evidence())
            == self.portfolio_evidence_sha256,
            "create": _canonical_sha256(plan.create.sanitized_evidence())
            == self.create_evidence_sha256,
            "preview": _canonical_sha256(plan.preview.sanitized_evidence())
            == self.preview_evidence_sha256,
            "caps": _canonical_sha256(plan.caps.sanitized_evidence())
            == self.caps_evidence_sha256,
            "close_client_order_id": hashlib.sha256(
                plan.close_client_order_id.encode("utf-8")
            ).hexdigest()
            == self.close_client_order_id_sha256,
        }
        for name, matches in exact.items():
            if not matches:
                raise Slice3AdmissionValidationError(
                    f"slice3_admission_plan_{name}_mismatch"
                )
        self.evidence.validate(plan=plan, now=now)


def build_slice3_execution_authority(
    *,
    authorization_sha256: str,
    accepted_r8_binding: Slice3AcceptedR8Binding,
    account_binding: Slice3CoinbaseAccountBinding,
    portfolio: Slice3PortfolioBinding,
    create: Slice3CreateRequest,
    preview: Slice3AcceptedPreview,
    caps: Slice3CapEvidence,
    correlation_id: str,
    preview_idempotency_key: str,
    close_client_order_id: str,
    product_evidence_sha256: str,
    market_evidence_sha256: str,
    margin_collateral_evidence_sha256: str,
    liquidation_evidence_sha256: str,
    fee_funding_evidence_sha256: str,
    now: datetime,
) -> Slice3AdmissionAuthorityBundle:
    """Derive authority before plan construction from exact accepted evidence."""

    current = _aware_utc(now, "slice3_admission_now_invalid")
    if authorization_sha256 != SLICE3_OPERATOR_AUTHORIZATION_SHA256:
        raise Slice3AdmissionValidationError(
            "slice3_admission_authorization_hash_invalid"
        )
    close_id = _require_uuid4(
        close_client_order_id,
        "slice3_admission_close_client_order_id_invalid",
    )
    if close_id == create.client_order_id:
        raise Slice3AdmissionValidationError(
            "slice3_admission_client_order_id_collision"
        )
    close_id_hash = hashlib.sha256(close_id.encode("utf-8")).hexdigest()
    if not isinstance(accepted_r8_binding, Slice3AcceptedR8Binding):
        raise Slice3AdmissionValidationError("slice3_admission_r8_binding_invalid")
    try:
        accepted_r8_binding.validate()
    except (TypeError, ValueError) as exc:
        raise Slice3AdmissionValidationError(
            "slice3_admission_r8_binding_invalid"
        ) from exc
    if not isinstance(account_binding, Slice3CoinbaseAccountBinding):
        raise Slice3AdmissionValidationError("slice3_admission_account_binding_invalid")
    try:
        account_binding.validate()
        portfolio.validate(now=current)
        create.validate()
        preview.validate(now=current)
        caps.validate()
    except (TypeError, ValueError, RuntimeError) as exc:
        raise Slice3AdmissionValidationError(
            "slice3_admission_authority_input_invalid"
        ) from exc
    if not (
        account_binding.portfolio_id == portfolio.portfolio_id
        and account_binding.portfolio_id_sha256 == portfolio.portfolio_id_sha256
        and account_binding.permission_evidence_sha256
        == portfolio.permission_evidence_sha256
        and account_binding.portfolio_catalog_sha256
        == portfolio.portfolio_catalog_sha256
        and account_binding.credential_binding == dict(_FIXED_CREDENTIAL_BINDING)
        and accepted_r8_binding.preview_id_sha256 == preview.preview_id_sha256
        and accepted_r8_binding.portfolio_id_sha256 == portfolio.portfolio_id_sha256
        and create.preview_id == preview.preview_id
        and create.preview_request() == preview.preview_request()
        and caps.opening
        == _decimal(
            preview.candidate_opening_reference_usdc,
            "slice3_admission_preview_cap_binding_invalid",
        )
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_cross_evidence_binding_invalid"
        )
    supplied_hashes = {
        "product": product_evidence_sha256,
        "market": market_evidence_sha256,
        "margin_collateral": margin_collateral_evidence_sha256,
        "liquidation": liquidation_evidence_sha256,
        "fee_funding": fee_funding_evidence_sha256,
    }
    for name, value in supplied_hashes.items():
        _require_sha256(
            value,
            f"slice3_admission_{name}_evidence_hash_invalid",
        )

    r8_binding_evidence = accepted_r8_binding.sanitized_evidence()
    r8_binding_hash = _canonical_sha256(r8_binding_evidence)
    account_evidence = account_binding.sanitized_evidence()
    account_binding_hash = _canonical_sha256(account_evidence)
    portfolio_hash = _canonical_sha256(portfolio.sanitized_evidence())
    create_hash = _canonical_sha256(create.sanitized_evidence())
    preview_hash = _canonical_sha256(preview.sanitized_evidence())
    caps_hash = _canonical_sha256(caps.sanitized_evidence())
    observed_at = current.isoformat()

    approval_record = {
        "schema_version": "slice3-derived-approval-v1",
        "authorization_sha256": authorization_sha256,
        "authorization_scope": _AUTHORIZATION_SCOPE,
        "actor_id": SLICE3_ACTOR_ID,
        "roles": list(SLICE3_ROLES),
        "state": "approved",
        "allowed": True,
        "approved": True,
        "observed_at": observed_at,
    }
    admission_record = {
        "schema_version": "slice3-derived-admission-audit-v1",
        "authorization_sha256": authorization_sha256,
        "accepted_r8_binding_sha256": r8_binding_hash,
        "accepted_r8_evidence_sha256": accepted_r8_binding.evidence_sha256,
        "actor_id": SLICE3_ACTOR_ID,
        "roles": list(SLICE3_ROLES),
        "route": SLICE3_ROUTE,
        "method": SLICE3_METHOD,
        "service_method": SLICE3_SERVICE_METHOD,
        "permission": SLICE3_PERMISSION,
        "correlation_id_sha256": _private_sha256(
            correlation_id,
            "slice3_admission_correlation_id_invalid",
        ),
        "idempotency_key_sha256": _private_sha256(
            preview_idempotency_key,
            "slice3_admission_idempotency_key_invalid",
        ),
        "client_order_id_sha256": _private_sha256(
            create.client_order_id,
            "slice3_admission_client_order_id_invalid",
        ),
        "close_client_order_id_sha256": close_id_hash,
        "portfolio_id_sha256": portfolio.portfolio_id_sha256,
        "product_id": SLICE3_PRODUCT_ID,
        "side": "BUY",
        "contract_count": "1",
        "preview_request_sha256": create.preview_request_sha256,
        "preview_id_sha256": preview.preview_id_sha256,
        "permission_evidence_sha256": portfolio.permission_evidence_sha256,
        "portfolio_catalog_sha256": portfolio.portfolio_catalog_sha256,
        "product_evidence_sha256": product_evidence_sha256,
        "market_evidence_sha256": market_evidence_sha256,
        "margin_collateral_evidence_sha256": (margin_collateral_evidence_sha256),
        "liquidation_evidence_sha256": liquidation_evidence_sha256,
        "fee_funding_evidence_sha256": fee_funding_evidence_sha256,
        "state": "allowed",
        "allowed": True,
        "approved": True,
        "observed_at": observed_at,
    }
    cap_guard_record = {
        "schema_version": "slice3-derived-cap-guard-v1",
        **caps.sanitized_evidence(),
        "comparison": "strictly_less_than",
        "state": "allowed",
        "allowed": True,
        "approved": True,
        "observed_at": observed_at,
    }
    reconciliation_record = {
        "schema_version": "slice3-derived-reconciliation-v1",
        "directives": [directive.value for directive in Slice3DirectiveKind],
        "read_slots": [slot.value for slot in Slice3ReadSlot],
        "read_attempt_limit_per_slot": 1,
        "polling_allowed": False,
        "pagination_allowed": False,
        "retry_allowed": False,
        "fallback_allowed": False,
        "redirect_allowed": False,
        "state": "approved",
        "allowed": True,
        "approved": True,
        "observed_at": observed_at,
    }
    live_service_record = {
        "schema_version": "slice3-derived-live-service-v1",
        "route": SLICE3_ROUTE,
        "method": SLICE3_METHOD,
        "service_method": SLICE3_SERVICE_METHOD,
        "permission": SLICE3_PERMISSION,
        "live_policy_sha256": _canonical_sha256(
            SLICE3_LIVE_POLICY.sanitized_evidence()
        ),
        "backend_only": True,
        "route_registered": False,
        "state": "enabled",
        "allowed": True,
        "approved": True,
        "observed_at": observed_at,
    }
    adapter_record = {
        "schema_version": "slice3-derived-adapter-binding-v1",
        "account_binding_sha256": account_binding_hash,
        "adapter_evidence_sha256": account_binding.adapter_evidence_sha256,
        "portfolio_id_sha256": account_binding.portfolio_id_sha256,
        "session_binding_token_sha256": (account_binding.session_binding_token_sha256),
        "permission_evidence_sha256": (account_binding.permission_evidence_sha256),
        "portfolio_catalog_sha256": account_binding.portfolio_catalog_sha256,
        "credential_binding_sha256": _canonical_sha256(
            account_binding.credential_binding
        ),
        "backed_by_slice3_coinbase_account_binding": True,
        "same_session_preview_and_slice3": True,
        "state": "approved",
        "allowed": True,
        "approved": True,
        "observed_at": observed_at,
    }
    control_records = {
        "approval": approval_record,
        "admission_audit": admission_record,
        "cap_guard": cap_guard_record,
        "reconciliation": reconciliation_record,
        "live_service": live_service_record,
        "adapter": adapter_record,
    }
    approval_hash = _canonical_sha256(approval_record)
    admission_hash = _canonical_sha256(admission_record)
    cap_guard_hash = _canonical_sha256(cap_guard_record)
    reconciliation_hash = _canonical_sha256(reconciliation_record)
    live_service_hash = _canonical_sha256(live_service_record)

    authority = Slice3ExecutionAuthority(
        actor_id=SLICE3_ACTOR_ID,
        roles=SLICE3_ROLES,
        correlation_id=correlation_id,
        preview_idempotency_key=preview_idempotency_key,
        authorization_sha256=authorization_sha256,
        route=SLICE3_ROUTE,
        method=SLICE3_METHOD,
        service_method=SLICE3_SERVICE_METHOD,
        permission=SLICE3_PERMISSION,
        approval_evidence_sha256=approval_hash,
        admission_evidence_sha256=admission_hash,
        cap_guard_evidence_sha256=cap_guard_hash,
        reconciliation_evidence_sha256=reconciliation_hash,
        live_service_evidence_sha256=live_service_hash,
        adapter_evidence_sha256=account_binding.adapter_evidence_sha256,
        product_evidence_sha256=product_evidence_sha256,
        market_evidence_sha256=market_evidence_sha256,
        margin_collateral_evidence_sha256=(margin_collateral_evidence_sha256),
        liquidation_evidence_sha256=liquidation_evidence_sha256,
        fee_funding_evidence_sha256=fee_funding_evidence_sha256,
        observed_at=current,
    )
    try:
        authority.validate(now=current)
    except (TypeError, ValueError) as exc:
        raise Slice3AdmissionValidationError(
            "slice3_admission_derived_authority_invalid"
        ) from exc

    evidence_set = Slice3AdmissionEvidenceSet(
        approval=_derived_source(
            kind=Slice3AdmissionEvidenceKind.APPROVAL,
            evidence_sha256=approval_hash,
            observed_at=current,
        ),
        admission_audit=_derived_source(
            kind=Slice3AdmissionEvidenceKind.ADMISSION_AUDIT,
            evidence_sha256=admission_hash,
            observed_at=current,
        ),
        cap_guard=_derived_source(
            kind=Slice3AdmissionEvidenceKind.CAP_GUARD,
            evidence_sha256=cap_guard_hash,
            observed_at=current,
        ),
        reconciliation=_derived_source(
            kind=Slice3AdmissionEvidenceKind.RECONCILIATION,
            evidence_sha256=reconciliation_hash,
            observed_at=current,
        ),
        live_service=_derived_source(
            kind=Slice3AdmissionEvidenceKind.LIVE_SERVICE,
            evidence_sha256=live_service_hash,
            observed_at=current,
        ),
        adapter=_derived_source(
            kind=Slice3AdmissionEvidenceKind.ADAPTER,
            evidence_sha256=account_binding.adapter_evidence_sha256,
            observed_at=current,
        ),
        credential=_derived_source(
            kind=Slice3AdmissionEvidenceKind.CREDENTIAL,
            evidence_sha256=SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256,
            observed_at=current,
        ),
        portfolio=_derived_source(
            kind=Slice3AdmissionEvidenceKind.PORTFOLIO,
            evidence_sha256=portfolio_hash,
            observed_at=current,
        ),
        permission=_derived_source(
            kind=Slice3AdmissionEvidenceKind.PERMISSION,
            evidence_sha256=portfolio.permission_evidence_sha256,
            observed_at=current,
        ),
        catalog=_derived_source(
            kind=Slice3AdmissionEvidenceKind.CATALOG,
            evidence_sha256=portfolio.portfolio_catalog_sha256,
            observed_at=current,
        ),
    )
    bundle = Slice3AdmissionAuthorityBundle(
        authority=authority,
        evidence=evidence_set,
        accepted_r8_binding_sha256=r8_binding_hash,
        account_binding_sha256=account_binding_hash,
        portfolio_evidence_sha256=portfolio_hash,
        create_evidence_sha256=create_hash,
        preview_evidence_sha256=preview_hash,
        caps_evidence_sha256=caps_hash,
        close_client_order_id_sha256=close_id_hash,
        control_records_json=_canonical_bytes(control_records).decode("utf-8"),
        built_at=current,
    )
    bundle.validate_at(now=current)
    return bundle


@dataclass(frozen=True, slots=True)
class Slice3AdmissionRecord:
    """One immutable hash-chain record with canonical evidence JSON."""

    index: int
    kind: Slice3AdmissionEvidenceKind
    previous_record_sha256: str
    evidence_json: str
    record_sha256: str

    @classmethod
    def build(
        cls,
        *,
        index: int,
        kind: Slice3AdmissionEvidenceKind,
        previous_record_sha256: str,
        evidence: Mapping[str, object],
    ) -> Slice3AdmissionRecord:
        if not isinstance(index, int) or isinstance(index, bool) or index <= 0:
            raise Slice3AdmissionValidationError(
                "slice3_admission_record_index_invalid"
            )
        if not isinstance(kind, Slice3AdmissionEvidenceKind):
            raise Slice3AdmissionValidationError("slice3_admission_record_kind_invalid")
        _require_sha256(
            previous_record_sha256,
            "slice3_admission_previous_record_hash_invalid",
        )
        _reject_private_fields(evidence)
        canonical_evidence = _canonical_bytes(dict(evidence)).decode("utf-8")
        unhashed = {
            "schema_version": SLICE3_ADMISSION_RECORD_SCHEMA_VERSION,
            "index": index,
            "kind": kind.value,
            "previous_record_sha256": previous_record_sha256,
            "evidence": json.loads(canonical_evidence),
        }
        return cls(
            index=index,
            kind=kind,
            previous_record_sha256=previous_record_sha256,
            evidence_json=canonical_evidence,
            record_sha256=_canonical_sha256(unhashed),
        )

    @classmethod
    def from_sanitized_evidence(
        cls,
        value: object,
    ) -> Slice3AdmissionRecord:
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "index",
            "kind",
            "previous_record_sha256",
            "evidence",
            "record_sha256",
        }:
            raise Slice3AdmissionValidationError(
                "slice3_admission_record_fields_invalid"
            )
        if value.get("schema_version") != SLICE3_ADMISSION_RECORD_SCHEMA_VERSION:
            raise Slice3AdmissionValidationError(
                "slice3_admission_record_schema_invalid"
            )
        try:
            kind = Slice3AdmissionEvidenceKind(str(value.get("kind")))
        except ValueError as exc:
            raise Slice3AdmissionValidationError(
                "slice3_admission_record_kind_invalid"
            ) from exc
        evidence = value.get("evidence")
        if not isinstance(evidence, Mapping):
            raise Slice3AdmissionValidationError(
                "slice3_admission_record_evidence_invalid"
            )
        record = cls.build(
            index=value.get("index"),  # type: ignore[arg-type]
            kind=kind,
            previous_record_sha256=_require_sha256(
                value.get("previous_record_sha256"),
                "slice3_admission_previous_record_hash_invalid",
            ),
            evidence={str(key): item for key, item in evidence.items()},
        )
        if record.record_sha256 != value.get("record_sha256"):
            raise Slice3AdmissionValidationError("slice3_admission_record_hash_invalid")
        return record

    def evidence(self) -> dict[str, object]:
        value = json.loads(self.evidence_json)
        if not isinstance(value, dict):
            raise Slice3AdmissionValidationError(
                "slice3_admission_record_evidence_invalid"
            )
        return value

    def sanitized_evidence(self) -> dict[str, object]:
        return {
            "schema_version": SLICE3_ADMISSION_RECORD_SCHEMA_VERSION,
            "index": self.index,
            "kind": self.kind.value,
            "previous_record_sha256": self.previous_record_sha256,
            "evidence": self.evidence(),
            "record_sha256": self.record_sha256,
        }


def _validate_standard_record_evidence(
    record: Slice3AdmissionRecord,
    *,
    now: datetime,
    admitted_at: datetime,
) -> None:
    evidence = record.evidence()
    required = {
        "evidence_id_sha256",
        "evidence_sha256",
        "observed_at",
        "state",
        "allowed",
        "approved",
    }
    if not required.issubset(evidence):
        raise Slice3AdmissionValidationError(
            "slice3_admission_record_control_fields_missing"
        )
    _require_sha256(
        evidence.get("evidence_id_sha256"),
        "slice3_admission_record_evidence_id_invalid",
    )
    _require_sha256(
        evidence.get("evidence_sha256"),
        "slice3_admission_record_evidence_hash_invalid",
    )
    if evidence.get("allowed") is not True or evidence.get("approved") is not True:
        raise Slice3AdmissionValidationError("slice3_admission_record_not_allowed")
    observed = _parse_timestamp(
        evidence.get("observed_at"),
        "slice3_admission_record_timestamp_invalid",
    )
    current = _aware_utc(now, "slice3_admission_now_invalid")
    admitted = _aware_utc(
        admitted_at,
        "slice3_admission_created_at_invalid",
    )
    age_at_admission = admitted - observed
    if (
        observed > current
        or age_at_admission < timedelta(0)
        or age_at_admission > SLICE3_MAX_READ_AGE
    ):
        raise Slice3AdmissionValidationError("slice3_admission_record_stale")


def _validate_operator_request(evidence: Mapping[str, object]) -> None:
    exact = {
        "actor_id": SLICE3_ACTOR_ID,
        "roles": list(SLICE3_ROLES),
        "route": SLICE3_ROUTE,
        "method": SLICE3_METHOD,
        "service_method": SLICE3_SERVICE_METHOD,
        "permission": SLICE3_PERMISSION,
        "product_id": SLICE3_PRODUCT_ID,
        "side": "BUY",
        "contract_count": "1",
        "time_in_force": "GTC",
        "post_only": True,
        "portfolio_name": "Default",
        "portfolio_type": "DEFAULT",
        "product_family": "US_CFM",
        "can_view": True,
        "can_trade": True,
        "intx_excluded": True,
        "request_override_allowed": False,
        "selection_authority": "cdp_api_key_permissioned_portfolio",
        "operator_defined_pair_not_coinbase_documented": True,
        "credential_binding_sha256": SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256,
        "attempt_limits": dict(_ATTEMPT_LIMITS),
    }
    for field, expected in exact.items():
        if evidence.get(field) != expected:
            raise Slice3AdmissionValidationError(
                f"slice3_admission_request_{field}_invalid"
            )
    for field in (
        "plan_sha256",
        "client_order_id_sha256",
        "close_client_order_id_sha256",
        "correlation_id_sha256",
        "idempotency_key_sha256",
        "preview_id_sha256",
        "portfolio_id_sha256",
        "preview_request_sha256",
        "create_payload_sha256",
        "preview_evidence_sha256",
        "permission_evidence_sha256",
        "portfolio_catalog_sha256",
        "portfolio_evidence_sha256",
        "product_evidence_sha256",
        "market_evidence_sha256",
        "margin_collateral_evidence_sha256",
        "liquidation_evidence_sha256",
        "fee_funding_evidence_sha256",
        "accepted_r8_binding_sha256",
        "account_binding_sha256",
    ):
        _require_sha256(
            evidence.get(field),
            f"slice3_admission_request_{field}_invalid",
        )
    if evidence.get("client_order_id_sha256") == evidence.get(
        "close_client_order_id_sha256"
    ) or evidence.get("correlation_id_sha256") == evidence.get(
        "idempotency_key_sha256"
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_identifier_collision"
        )
    order_configuration = evidence.get("order_configuration")
    if not isinstance(order_configuration, Mapping) or set(order_configuration) != {
        "limit_limit_gtc"
    }:
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_order_configuration_invalid"
        )
    limit_gtc = order_configuration.get("limit_limit_gtc")
    if not isinstance(limit_gtc, Mapping) or set(limit_gtc) != {
        "base_size",
        "limit_price",
        "post_only",
    }:
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_order_configuration_invalid"
        )
    if (
        limit_gtc.get("base_size") != "1"
        or limit_gtc.get("post_only") is not True
        or _decimal(
            limit_gtc.get("limit_price"),
            "slice3_admission_request_limit_price_invalid",
        )
        <= 0
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_order_configuration_invalid"
        )
    pair = evidence.get("margin_window_pair")
    if not isinstance(pair, Mapping) or set(pair) != {
        "retail_regular",
        "retail_intraday_margin_1",
        "intraday_margin_setting",
        "intraday_margin_killswitch_enabled",
        "intraday_margin_enrollment_killswitch_enabled",
    } or not (
        pair.get("retail_regular") == "MARGIN_WINDOW_TYPE_UNSPECIFIED"
        and pair.get("retail_intraday_margin_1")
        == "MARGIN_WINDOW_TYPE_INTRADAY"
        and pair.get("intraday_margin_setting")
        in {
            "INTRADAY_MARGIN_SETTING_STANDARD",
            "INTRADAY_MARGIN_SETTING_INTRADAY",
        }
        and pair.get("intraday_margin_killswitch_enabled") is False
        and pair.get("intraday_margin_enrollment_killswitch_enabled") is False
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_margin_pair_invalid"
        )
    caps = evidence.get("caps")
    if (
        not isinstance(caps, Mapping)
        or caps.get("opening_cap") != "<100"
        or (
            caps.get("exposure_and_buffered_close_cap") != "<150"
            or caps.get("branch_turnover_cap") != "<300"
        )
    ):
        raise Slice3AdmissionValidationError("slice3_admission_request_caps_invalid")
    controls = evidence.get("control_records")
    if not isinstance(controls, Mapping) or set(controls) != {
        "approval",
        "admission_audit",
        "cap_guard",
        "reconciliation",
        "live_service",
        "adapter",
    }:
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_control_records_invalid"
        )
    approval = controls.get("approval")
    if not isinstance(approval, Mapping) or not (
        approval.get("schema_version") == "slice3-derived-approval-v1"
        and approval.get("authorization_sha256") == SLICE3_OPERATOR_AUTHORIZATION_SHA256
        and approval.get("authorization_scope") == _AUTHORIZATION_SCOPE
        and approval.get("actor_id") == SLICE3_ACTOR_ID
        and approval.get("roles") == list(SLICE3_ROLES)
        and approval.get("state") == "approved"
        and approval.get("allowed") is True
        and approval.get("approved") is True
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_approval_control_invalid"
        )
    admission = controls.get("admission_audit")
    if not isinstance(admission, Mapping) or not (
        admission.get("schema_version") == "slice3-derived-admission-audit-v1"
        and admission.get("authorization_sha256")
        == SLICE3_OPERATOR_AUTHORIZATION_SHA256
        and admission.get("accepted_r8_binding_sha256")
        == evidence.get("accepted_r8_binding_sha256")
        and admission.get("actor_id") == SLICE3_ACTOR_ID
        and admission.get("roles") == list(SLICE3_ROLES)
        and admission.get("route") == SLICE3_ROUTE
        and admission.get("method") == SLICE3_METHOD
        and admission.get("service_method") == SLICE3_SERVICE_METHOD
        and admission.get("permission") == SLICE3_PERMISSION
        and admission.get("correlation_id_sha256")
        == evidence.get("correlation_id_sha256")
        and admission.get("idempotency_key_sha256")
        == evidence.get("idempotency_key_sha256")
        and admission.get("client_order_id_sha256")
        == evidence.get("client_order_id_sha256")
        and admission.get("close_client_order_id_sha256")
        == evidence.get("close_client_order_id_sha256")
        and admission.get("portfolio_id_sha256") == evidence.get("portfolio_id_sha256")
        and admission.get("product_id") == SLICE3_PRODUCT_ID
        and admission.get("side") == "BUY"
        and admission.get("contract_count") == "1"
        and admission.get("preview_request_sha256")
        == evidence.get("preview_request_sha256")
        and admission.get("preview_id_sha256") == evidence.get("preview_id_sha256")
        and admission.get("permission_evidence_sha256")
        == evidence.get("permission_evidence_sha256")
        and admission.get("portfolio_catalog_sha256")
        == evidence.get("portfolio_catalog_sha256")
        and admission.get("product_evidence_sha256")
        == evidence.get("product_evidence_sha256")
        and admission.get("market_evidence_sha256")
        == evidence.get("market_evidence_sha256")
        and admission.get("margin_collateral_evidence_sha256")
        == evidence.get("margin_collateral_evidence_sha256")
        and admission.get("liquidation_evidence_sha256")
        == evidence.get("liquidation_evidence_sha256")
        and admission.get("fee_funding_evidence_sha256")
        == evidence.get("fee_funding_evidence_sha256")
        and admission.get("state") == "allowed"
        and admission.get("allowed") is True
        and admission.get("approved") is True
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_admission_control_invalid"
        )
    cap_control = controls.get("cap_guard")
    expected_cap_fields = {
        "schema_version": "slice3-derived-cap-guard-v1",
        **dict(caps),
        "comparison": "strictly_less_than",
        "state": "allowed",
        "allowed": True,
        "approved": True,
    }
    if not isinstance(cap_control, Mapping) or any(
        cap_control.get(key) != expected
        for key, expected in expected_cap_fields.items()
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_cap_control_invalid"
        )
    reconciliation = controls.get("reconciliation")
    if not isinstance(reconciliation, Mapping) or not (
        reconciliation.get("schema_version") == "slice3-derived-reconciliation-v1"
        and reconciliation.get("directives")
        == [directive.value for directive in Slice3DirectiveKind]
        and reconciliation.get("read_slots") == [slot.value for slot in Slice3ReadSlot]
        and reconciliation.get("read_attempt_limit_per_slot") == 1
        and reconciliation.get("polling_allowed") is False
        and reconciliation.get("pagination_allowed") is False
        and reconciliation.get("retry_allowed") is False
        and reconciliation.get("fallback_allowed") is False
        and reconciliation.get("redirect_allowed") is False
        and reconciliation.get("state") == "approved"
        and reconciliation.get("allowed") is True
        and reconciliation.get("approved") is True
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_reconciliation_control_invalid"
        )
    live = controls.get("live_service")
    if not isinstance(live, Mapping) or not (
        live.get("schema_version") == "slice3-derived-live-service-v1"
        and live.get("route") == SLICE3_ROUTE
        and live.get("method") == SLICE3_METHOD
        and live.get("service_method") == SLICE3_SERVICE_METHOD
        and live.get("permission") == SLICE3_PERMISSION
        and live.get("live_policy_sha256")
        == _canonical_sha256(SLICE3_LIVE_POLICY.sanitized_evidence())
        and live.get("backend_only") is True
        and live.get("route_registered") is False
        and live.get("state") == "enabled"
        and live.get("allowed") is True
        and live.get("approved") is True
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_live_control_invalid"
        )
    adapter = controls.get("adapter")
    if not isinstance(adapter, Mapping) or not (
        adapter.get("schema_version") == "slice3-derived-adapter-binding-v1"
        and adapter.get("account_binding_sha256")
        == evidence.get("account_binding_sha256")
        and adapter.get("credential_binding_sha256")
        == SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256
        and adapter.get("backed_by_slice3_coinbase_account_binding") is True
        and adapter.get("same_session_preview_and_slice3") is True
        and adapter.get("state") == "approved"
        and adapter.get("allowed") is True
        and adapter.get("approved") is True
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_request_adapter_control_invalid"
        )
    opening = _decimal(
        caps.get("opening_reference_usdc"),
        "slice3_admission_request_caps_invalid",
    )
    exposure = _decimal(
        caps.get("maximum_concurrent_exposure_usdc"),
        "slice3_admission_request_caps_invalid",
    )
    close = _decimal(
        caps.get("conservative_close_usdc"),
        "slice3_admission_request_caps_invalid",
    )
    turnover = _decimal(
        caps.get("branch_turnover_usdc"),
        "slice3_admission_request_caps_invalid",
    )
    if not (
        Decimal("0") < opening < SLICE3_OPENING_CAP_USDC
        and exposure == opening
        and exposure < SLICE3_EXPOSURE_CAP_USDC
        and close == exposure * SLICE3_CLOSE_BUFFER
        and close < SLICE3_EXPOSURE_CAP_USDC
        and turnover == opening + close
        and turnover < SLICE3_TURNOVER_CAP_USDC
    ):
        raise Slice3AdmissionValidationError("slice3_admission_request_caps_invalid")


@dataclass(frozen=True, slots=True)
class Slice3AdmissionChain:
    """Validated, short-lived admission chain containing no raw identifiers."""

    plan_sha256: str
    authorization_sha256: str
    created_at: datetime
    expires_at: datetime
    records: tuple[Slice3AdmissionRecord, ...]

    @classmethod
    def from_sanitized_evidence(
        cls,
        value: object,
        *,
        now: datetime,
    ) -> Slice3AdmissionChain:
        expected_fields = {
            "schema_version",
            "readiness",
            "approved",
            "allowed",
            "plan_sha256",
            "authorization_sha256",
            "created_at",
            "expires_at",
            "record_order",
            "record_count",
            "records",
            "head_record_sha256",
            "route_registered",
            "coinbase_calls_permitted",
            "exchange_mutations_permitted",
            "raw_private_identifier_values_included",
            "canonicalization",
            "hash_algorithm",
        }
        if not isinstance(value, Mapping) or set(value) != expected_fields:
            raise Slice3AdmissionValidationError(
                "slice3_admission_chain_fields_invalid"
            )
        if not (
            value.get("schema_version") == SLICE3_ADMISSION_SCHEMA_VERSION
            and value.get("readiness") == "allowed"
            and value.get("approved") is True
            and value.get("allowed") is True
            and value.get("route_registered") is False
            and value.get("coinbase_calls_permitted") is False
            and value.get("exchange_mutations_permitted") is False
            and value.get("raw_private_identifier_values_included") is False
            and value.get("canonicalization") == "sorted_keys_compact_utf8_json"
            and value.get("hash_algorithm") == "sha256"
        ):
            raise Slice3AdmissionValidationError(
                "slice3_admission_chain_posture_invalid"
            )
        rows = value.get("records")
        if not isinstance(rows, list):
            raise Slice3AdmissionValidationError(
                "slice3_admission_chain_records_invalid"
            )
        records = tuple(
            Slice3AdmissionRecord.from_sanitized_evidence(row) for row in rows
        )
        if value.get("record_count") != len(records) or value.get("record_order") != [
            kind.value for kind in SLICE3_ADMISSION_RECORD_ORDER
        ]:
            raise Slice3AdmissionValidationError(
                "slice3_admission_chain_record_order_invalid"
            )
        if not records or value.get("head_record_sha256") != records[-1].record_sha256:
            raise Slice3AdmissionValidationError("slice3_admission_chain_head_invalid")
        chain = cls(
            plan_sha256=_require_sha256(
                value.get("plan_sha256"),
                "slice3_admission_plan_hash_invalid",
            ),
            authorization_sha256=_require_sha256(
                value.get("authorization_sha256"),
                "slice3_admission_authorization_hash_invalid",
            ),
            created_at=_parse_timestamp(
                value.get("created_at"),
                "slice3_admission_created_at_invalid",
            ),
            expires_at=_parse_timestamp(
                value.get("expires_at"),
                "slice3_admission_expires_at_invalid",
            ),
            records=records,
        )
        chain.validate_at(now)
        return chain

    def validate_at(self, now: datetime) -> None:
        if self.authorization_sha256 != SLICE3_OPERATOR_AUTHORIZATION_SHA256:
            raise Slice3AdmissionValidationError(
                "slice3_admission_authorization_hash_invalid"
            )
        _require_sha256(
            self.plan_sha256,
            "slice3_admission_plan_hash_invalid",
        )
        created = _aware_utc(
            self.created_at,
            "slice3_admission_created_at_invalid",
        )
        expires = _aware_utc(
            self.expires_at,
            "slice3_admission_expires_at_invalid",
        )
        current = _aware_utc(now, "slice3_admission_now_invalid")
        if expires <= created or expires - created > SLICE3_ADMISSION_MAX_TTL:
            raise Slice3AdmissionValidationError("slice3_admission_expiry_invalid")
        if current < created:
            raise Slice3AdmissionValidationError("slice3_admission_not_yet_valid")
        if current >= expires:
            raise Slice3AdmissionValidationError("slice3_admission_expired")
        if len(self.records) != len(SLICE3_ADMISSION_RECORD_ORDER):
            raise Slice3AdmissionValidationError(
                "slice3_admission_record_count_invalid"
            )
        previous = SLICE3_ADMISSION_GENESIS_SHA256
        evidence_ids: set[str] = set()
        for expected_index, (expected_kind, record) in enumerate(
            zip(SLICE3_ADMISSION_RECORD_ORDER, self.records, strict=True),
            start=1,
        ):
            if (
                record.index != expected_index
                or record.kind is not expected_kind
                or record.previous_record_sha256 != previous
            ):
                raise Slice3AdmissionValidationError(
                    "slice3_admission_record_chain_invalid"
                )
            rebuilt = Slice3AdmissionRecord.build(
                index=record.index,
                kind=record.kind,
                previous_record_sha256=record.previous_record_sha256,
                evidence=record.evidence(),
            )
            if rebuilt != record:
                raise Slice3AdmissionValidationError(
                    "slice3_admission_record_hash_invalid"
                )
            _validate_standard_record_evidence(
                record,
                now=current,
                admitted_at=created,
            )
            evidence = record.evidence()
            evidence_id = str(evidence["evidence_id_sha256"])
            if evidence_id in evidence_ids:
                raise Slice3AdmissionValidationError(
                    "slice3_admission_duplicate_evidence_id"
                )
            evidence_ids.add(evidence_id)
            if expected_kind is Slice3AdmissionEvidenceKind.AUTHORIZATION:
                expected_authorization_id = hashlib.sha256(
                    (
                        "slice3-authorization:" + SLICE3_OPERATOR_AUTHORIZATION_SHA256
                    ).encode("utf-8")
                ).hexdigest()
                if not (
                    evidence.get("state") == "approved"
                    and evidence.get("evidence_id_sha256") == expected_authorization_id
                    and evidence.get("evidence_sha256")
                    == SLICE3_OPERATOR_AUTHORIZATION_SHA256
                    and evidence.get("authorization_scope") == _AUTHORIZATION_SCOPE
                ):
                    raise Slice3AdmissionValidationError(
                        "slice3_admission_authorization_record_invalid"
                    )
            elif expected_kind is Slice3AdmissionEvidenceKind.OPERATOR_REQUEST:
                expected_request_id = hashlib.sha256(
                    f"slice3-operator-request:{self.plan_sha256}".encode("utf-8")
                ).hexdigest()
                request_binding = {
                    key: value
                    for key, value in evidence.items()
                    if key
                    not in {
                        "evidence_id_sha256",
                        "evidence_sha256",
                        "observed_at",
                        "state",
                        "allowed",
                        "approved",
                    }
                }
                if evidence.get("state") != "allowed":
                    raise Slice3AdmissionValidationError(
                        "slice3_admission_request_state_invalid"
                    )
                if not (
                    evidence.get("evidence_id_sha256") == expected_request_id
                    and evidence.get("evidence_sha256")
                    == _canonical_sha256(request_binding)
                ):
                    raise Slice3AdmissionValidationError(
                        "slice3_admission_request_evidence_hash_invalid"
                    )
                _validate_operator_request(evidence)
                if evidence.get("plan_sha256") != self.plan_sha256:
                    raise Slice3AdmissionValidationError(
                        "slice3_admission_request_plan_mismatch"
                    )
            else:
                expected_state = _SOURCE_STATE[expected_kind]
                if (
                    set(evidence)
                    != {
                        "evidence_id_sha256",
                        "evidence_sha256",
                        "observed_at",
                        "state",
                        "allowed",
                        "approved",
                    }
                    or evidence.get("state") != expected_state
                ):
                    raise Slice3AdmissionValidationError(
                        f"slice3_admission_{expected_kind.value}_record_invalid"
                    )
                expected_source_id = hashlib.sha256(
                    (
                        f"slice3:{expected_kind.value}:{evidence['evidence_sha256']}"
                    ).encode("utf-8")
                ).hexdigest()
                if evidence.get("evidence_id_sha256") != expected_source_id:
                    raise Slice3AdmissionValidationError(
                        f"slice3_admission_{expected_kind.value}_evidence_id_invalid"
                    )
            previous = record.record_sha256

        request = self.records[1].evidence()
        controls = request["control_records"]
        if not isinstance(controls, dict):
            raise Slice3AdmissionValidationError(
                "slice3_admission_request_control_records_invalid"
            )
        source_by_kind = {record.kind: record.evidence() for record in self.records[2:]}
        for control_name, kind in (
            ("approval", Slice3AdmissionEvidenceKind.APPROVAL),
            ("admission_audit", Slice3AdmissionEvidenceKind.ADMISSION_AUDIT),
            ("cap_guard", Slice3AdmissionEvidenceKind.CAP_GUARD),
            ("reconciliation", Slice3AdmissionEvidenceKind.RECONCILIATION),
            ("live_service", Slice3AdmissionEvidenceKind.LIVE_SERVICE),
        ):
            if (
                _canonical_sha256(controls[control_name])
                != source_by_kind[kind]["evidence_sha256"]
            ):
                raise Slice3AdmissionValidationError(
                    f"slice3_admission_{control_name}_chain_binding_invalid"
                )
        adapter = controls["adapter"]
        if not isinstance(adapter, dict):
            raise Slice3AdmissionValidationError(
                "slice3_admission_request_adapter_control_invalid"
            )
        if not (
            adapter.get("adapter_evidence_sha256")
            == source_by_kind[Slice3AdmissionEvidenceKind.ADAPTER]["evidence_sha256"]
            and adapter.get("credential_binding_sha256")
            == source_by_kind[Slice3AdmissionEvidenceKind.CREDENTIAL]["evidence_sha256"]
            and request.get("portfolio_id_sha256") == adapter.get("portfolio_id_sha256")
            and request.get("permission_evidence_sha256")
            == source_by_kind[Slice3AdmissionEvidenceKind.PERMISSION]["evidence_sha256"]
            and request.get("portfolio_evidence_sha256")
            == source_by_kind[Slice3AdmissionEvidenceKind.PORTFOLIO]["evidence_sha256"]
            and request.get("portfolio_catalog_sha256")
            == source_by_kind[Slice3AdmissionEvidenceKind.CATALOG]["evidence_sha256"]
        ):
            raise Slice3AdmissionValidationError(
                "slice3_admission_account_chain_binding_invalid"
            )

    def sanitized_evidence(self) -> dict[str, object]:
        return {
            "schema_version": SLICE3_ADMISSION_SCHEMA_VERSION,
            "readiness": "allowed",
            "approved": True,
            "allowed": True,
            "plan_sha256": self.plan_sha256,
            "authorization_sha256": self.authorization_sha256,
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "record_order": [kind.value for kind in SLICE3_ADMISSION_RECORD_ORDER],
            "record_count": len(self.records),
            "records": [record.sanitized_evidence() for record in self.records],
            "head_record_sha256": self.records[-1].record_sha256,
            "route_registered": False,
            "coinbase_calls_permitted": False,
            "exchange_mutations_permitted": False,
            "raw_private_identifier_values_included": False,
            "canonicalization": "sorted_keys_compact_utf8_json",
            "hash_algorithm": "sha256",
        }

    @property
    def chain_sha256(self) -> str:
        return _canonical_sha256(self.sanitized_evidence())


def _authorization_record_evidence(now: datetime) -> dict[str, object]:
    return {
        "evidence_id_sha256": hashlib.sha256(
            ("slice3-authorization:" + SLICE3_OPERATOR_AUTHORIZATION_SHA256).encode(
                "utf-8"
            )
        ).hexdigest(),
        "evidence_sha256": SLICE3_OPERATOR_AUTHORIZATION_SHA256,
        "observed_at": now.isoformat(),
        "state": "approved",
        "allowed": True,
        "approved": True,
        "authorization_scope": _AUTHORIZATION_SCOPE,
    }


def _operator_request_evidence(
    plan: Slice3Plan,
    authority_bundle: Slice3AdmissionAuthorityBundle,
    now: datetime,
) -> dict[str, object]:
    authority = plan.execution_authority
    create = plan.create.sanitized_evidence()
    portfolio = plan.portfolio.sanitized_evidence()
    request_binding: dict[str, object] = {
        "plan_sha256": plan.plan_sha256,
        "actor_id": authority.actor_id,
        "roles": list(authority.roles),
        "route": authority.route,
        "method": authority.method,
        "service_method": authority.service_method,
        "permission": authority.permission,
        "client_order_id_sha256": create["client_order_id_sha256"],
        "close_client_order_id_sha256": (authority_bundle.close_client_order_id_sha256),
        "correlation_id_sha256": hashlib.sha256(
            authority.correlation_id.encode("utf-8")
        ).hexdigest(),
        "idempotency_key_sha256": hashlib.sha256(
            authority.preview_idempotency_key.encode("utf-8")
        ).hexdigest(),
        "preview_id_sha256": create["preview_id_sha256"],
        "portfolio_id_sha256": portfolio["portfolio_id_sha256"],
        "product_id": create["product_id"],
        "side": create["side"],
        "contract_count": create["base_size"],
        "time_in_force": "GTC",
        "post_only": create["post_only"],
        "order_configuration": plan.create.preview_request()["order_configuration"],
        "preview_request_sha256": create["preview_request_sha256"],
        "create_payload_sha256": create["create_payload_sha256"],
        "preview_evidence_sha256": plan.preview.evidence_sha256,
        "portfolio_name": portfolio["portfolio_name"],
        "portfolio_type": portfolio["portfolio_type"],
        "product_family": portfolio["product_family"],
        "can_view": portfolio["can_view"],
        "can_trade": portfolio["can_trade"],
        "intx_excluded": portfolio["intx_excluded"],
        "request_override_allowed": portfolio["request_override_allowed"],
        "selection_authority": portfolio["selection_authority"],
        "permission_evidence_sha256": portfolio["permission_evidence_sha256"],
        "portfolio_catalog_sha256": portfolio["portfolio_catalog_sha256"],
        "portfolio_evidence_sha256": (authority_bundle.portfolio_evidence_sha256),
        "product_evidence_sha256": authority.product_evidence_sha256,
        "market_evidence_sha256": authority.market_evidence_sha256,
        "margin_collateral_evidence_sha256": (
            authority.margin_collateral_evidence_sha256
        ),
        "liquidation_evidence_sha256": (authority.liquidation_evidence_sha256),
        "fee_funding_evidence_sha256": (authority.fee_funding_evidence_sha256),
        "margin_window_pair": plan.margin_windows.sanitized_evidence(),
        "operator_defined_pair_not_coinbase_documented": True,
        "caps": plan.caps.sanitized_evidence(),
        "attempt_limits": dict(_ATTEMPT_LIMITS),
        "credential_binding_sha256": SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256,
        "accepted_r8_binding_sha256": (authority_bundle.accepted_r8_binding_sha256),
        "account_binding_sha256": authority_bundle.account_binding_sha256,
        "control_records": authority_bundle.control_records(),
    }
    request_hash = _canonical_sha256(request_binding)
    return {
        "evidence_id_sha256": hashlib.sha256(
            f"slice3-operator-request:{plan.plan_sha256}".encode("utf-8")
        ).hexdigest(),
        "evidence_sha256": request_hash,
        "observed_at": now.isoformat(),
        "state": "allowed",
        "allowed": True,
        "approved": True,
        **request_binding,
    }


def build_slice3_admission_chain(
    *,
    plan: Slice3Plan,
    authority_bundle: Slice3AdmissionAuthorityBundle,
    now: datetime,
    expires_at: datetime,
) -> Slice3AdmissionChain:
    """Build the exact offline admission chain for one already-sealed plan."""

    if not isinstance(plan, Slice3Plan):
        raise Slice3AdmissionValidationError("slice3_admission_plan_invalid")
    current = _aware_utc(now, "slice3_admission_now_invalid")
    expiry = _aware_utc(expires_at, "slice3_admission_expires_at_invalid")
    if not isinstance(authority_bundle, Slice3AdmissionAuthorityBundle):
        raise Slice3AdmissionValidationError(
            "slice3_admission_authority_bundle_invalid"
        )
    authority_bundle.validate_plan(plan, now=current)
    if plan.policy != SLICE3_LIVE_POLICY:
        raise Slice3AdmissionValidationError("slice3_admission_live_policy_invalid")
    if (
        plan.execution_authority.authorization_sha256
        != SLICE3_OPERATOR_AUTHORIZATION_SHA256
    ):
        raise Slice3AdmissionValidationError(
            "slice3_admission_plan_authorization_mismatch"
        )
    if expiry != plan.risk_off_expires_at:
        raise Slice3AdmissionValidationError(
            "slice3_admission_expiry_not_risk_off_bound"
        )
    rows: list[tuple[Slice3AdmissionEvidenceKind, Mapping[str, object]]] = [
        (
            Slice3AdmissionEvidenceKind.AUTHORIZATION,
            _authorization_record_evidence(current),
        ),
        (
            Slice3AdmissionEvidenceKind.OPERATOR_REQUEST,
            _operator_request_evidence(plan, authority_bundle, current),
        ),
    ]
    rows.extend(
        (source.kind, source.sanitized_evidence())
        for source in authority_bundle.evidence.ordered()
    )
    records: list[Slice3AdmissionRecord] = []
    previous = SLICE3_ADMISSION_GENESIS_SHA256
    for index, (kind, row) in enumerate(rows, start=1):
        record = Slice3AdmissionRecord.build(
            index=index,
            kind=kind,
            previous_record_sha256=previous,
            evidence=row,
        )
        records.append(record)
        previous = record.record_sha256
    chain = Slice3AdmissionChain(
        plan_sha256=plan.plan_sha256,
        authorization_sha256=SLICE3_OPERATOR_AUTHORIZATION_SHA256,
        created_at=current,
        expires_at=expiry,
        records=tuple(records),
    )
    chain.validate_at(current)
    return chain


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise Slice3AdmissionArtifactError("slice3_admission_artifact_write_failed")
        offset += written


def _stable_metadata(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


@dataclass(frozen=True, slots=True)
class Slice3AdmissionSeal:
    """Validated chain plus stable artifact content and metadata evidence."""

    chain: Slice3AdmissionChain
    chain_sha256: str
    record_sha256: str
    artifact_file_sha256: str
    device: int
    inode: int
    size: int
    mode: int
    owner_uid: int
    link_count: int
    mtime_ns: int


class FileSlice3AdmissionArtifactStore:
    """Owner-only O_EXCL store for the one immutable admission artifact."""

    def __init__(self, path: Path | str) -> None:
        supplied = Path(path)
        rendered = os.fspath(supplied)
        if (
            not supplied.is_absolute()
            or os.path.normpath(rendered) != rendered
            or supplied.name in {"", ".", ".."}
        ):
            raise Slice3AdmissionArtifactError("slice3_admission_artifact_path_invalid")
        self.path = supplied
        self._owner_uid = os.geteuid()

    def _assert_no_symlink_components(self) -> None:
        current = Path(self.path.anchor)
        for part in self.path.parent.parts[1:]:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError as exc:
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_parent_missing"
                ) from exc
            except OSError as exc:
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_parent_invalid"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_parent_symlink"
                )
            if not stat.S_ISDIR(metadata.st_mode):
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_parent_invalid"
                )

    def _open_parent_fd(self) -> int:
        self._assert_no_symlink_components()
        try:
            before = self.path.parent.lstat()
            descriptor = os.open(
                self.path.parent,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
            )
        except OSError as exc:
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_parent_invalid"
            ) from exc
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or opened.st_uid != self._owner_uid
        ):
            os.close(descriptor)
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_parent_metadata_invalid"
            )
        return descriptor

    def _target_lstat(self, parent_fd: int) -> os.stat_result:
        try:
            return os.stat(
                self.path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_missing"
            ) from exc
        except OSError as exc:
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_invalid"
            ) from exc

    def _validate_file_metadata(self, value: os.stat_result) -> None:
        if stat.S_ISLNK(value.st_mode):
            raise Slice3AdmissionArtifactError("slice3_admission_artifact_path_symlink")
        if not stat.S_ISREG(value.st_mode):
            raise Slice3AdmissionArtifactError("slice3_admission_artifact_not_regular")
        if value.st_uid != self._owner_uid:
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_owner_invalid"
            )
        if stat.S_IMODE(value.st_mode) != 0o400:
            raise Slice3AdmissionArtifactError("slice3_admission_artifact_mode_invalid")
        if value.st_nlink != 1:
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_link_count_invalid"
            )
        if value.st_size <= 0 or value.st_size > _MAX_ARTIFACT_BYTES:
            raise Slice3AdmissionArtifactError("slice3_admission_artifact_size_invalid")

    @staticmethod
    def _record(chain: Slice3AdmissionChain) -> dict[str, object]:
        chain_evidence = chain.sanitized_evidence()
        record: dict[str, object] = {
            "schema_version": SLICE3_ADMISSION_ARTIFACT_SCHEMA_VERSION,
            "record_type": "slice3_admission_evidence",
            "chain": chain_evidence,
            "chain_sha256": _canonical_sha256(chain_evidence),
        }
        record["record_sha256"] = _canonical_sha256(record)
        return record

    def seal(
        self,
        chain: Slice3AdmissionChain,
        *,
        now: datetime,
    ) -> Slice3AdmissionSeal:
        if not isinstance(chain, Slice3AdmissionChain):
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_chain_invalid"
            )
        try:
            chain.validate_at(now)
            payload = _canonical_bytes(self._record(chain)) + b"\n"
        except Slice3AdmissionValidationError as exc:
            raise Slice3AdmissionArtifactError(str(exc)) from exc
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise Slice3AdmissionArtifactError("slice3_admission_artifact_size_invalid")
        parent_fd = self._open_parent_fd()
        descriptor: int | None = None
        try:
            try:
                existing = os.stat(
                    self.path.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if stat.S_ISLNK(existing.st_mode):
                    raise Slice3AdmissionArtifactError(
                        "slice3_admission_artifact_path_symlink"
                    )
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_already_exists"
                )
            try:
                descriptor = os.open(
                    self.path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError as exc:
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_already_exists"
                ) from exc
            except OSError as exc:
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_create_failed"
                ) from exc
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != self._owner_uid
                or opened.st_nlink != 1
            ):
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_created_metadata_invalid"
                )
            _write_all(descriptor, payload)
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            completed = os.fstat(descriptor)
            self._validate_file_metadata(completed)
            if completed.st_size != len(payload):
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_size_invalid"
                )
            os.close(descriptor)
            descriptor = None
            os.fsync(parent_fd)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_fd)
        return self.read(
            now=now,
            expected_chain_sha256=chain.chain_sha256,
        )

    def read(
        self,
        *,
        now: datetime,
        expected_chain_sha256: str,
    ) -> Slice3AdmissionSeal:
        try:
            expected = _require_sha256(
                expected_chain_sha256,
                "slice3_admission_expected_chain_hash_invalid",
            )
        except Slice3AdmissionValidationError as exc:
            raise Slice3AdmissionArtifactError(str(exc)) from exc
        parent_fd = self._open_parent_fd()
        descriptor: int | None = None
        try:
            before = self._target_lstat(parent_fd)
            self._validate_file_metadata(before)
            try:
                descriptor = os.open(
                    self.path.name,
                    os.O_RDONLY | _NOFOLLOW | _CLOEXEC,
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_read_failed"
                ) from exc
            opened = os.fstat(descriptor)
            if _stable_metadata(opened) != _stable_metadata(before):
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_metadata_changed"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, 8192)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_ARTIFACT_BYTES:
                    raise Slice3AdmissionArtifactError(
                        "slice3_admission_artifact_size_invalid"
                    )
                chunks.append(chunk)
            after_fd = os.fstat(descriptor)
            after_path = self._target_lstat(parent_fd)
            if _stable_metadata(after_fd) != _stable_metadata(
                opened
            ) or _stable_metadata(after_path) != _stable_metadata(opened):
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_metadata_changed"
                )
            raw = b"".join(chunks)
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(parent_fd)
        if len(raw) != before.st_size or not raw.endswith(b"\n"):
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_record_incomplete"
            )
        try:
            decoded = raw[:-1].decode("utf-8")
            record = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKey) as exc:
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_tampered"
            ) from exc
        if not isinstance(record, dict):
            raise Slice3AdmissionArtifactError("slice3_admission_artifact_tampered")
        try:
            if raw != _canonical_bytes(record) + b"\n":
                raise Slice3AdmissionArtifactError(
                    "slice3_admission_artifact_noncanonical"
                )
        except Slice3AdmissionValidationError as exc:
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_tampered"
            ) from exc
        if set(record) != {
            "schema_version",
            "record_type",
            "chain",
            "chain_sha256",
            "record_sha256",
        } or not (
            record.get("schema_version") == SLICE3_ADMISSION_ARTIFACT_SCHEMA_VERSION
            and record.get("record_type") == "slice3_admission_evidence"
        ):
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_identity_invalid"
            )
        chain_evidence = record.get("chain")
        if not isinstance(chain_evidence, Mapping):
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_chain_invalid"
            )
        chain_hash = record.get("chain_sha256")
        if (
            not isinstance(chain_hash, str)
            or _canonical_sha256(chain_evidence) != chain_hash
        ):
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_chain_tampered"
            )
        record_hash = record.get("record_sha256")
        unhashed = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        if (
            not isinstance(record_hash, str)
            or _canonical_sha256(unhashed) != record_hash
        ):
            raise Slice3AdmissionArtifactError(
                "slice3_admission_artifact_record_tampered"
            )
        if chain_hash != expected:
            raise Slice3AdmissionArtifactError(
                "slice3_admission_expected_chain_hash_mismatch"
            )
        try:
            chain = Slice3AdmissionChain.from_sanitized_evidence(
                chain_evidence,
                now=now,
            )
        except Slice3AdmissionValidationError as exc:
            raise Slice3AdmissionArtifactError(str(exc)) from exc
        return Slice3AdmissionSeal(
            chain=chain,
            chain_sha256=chain_hash,
            record_sha256=record_hash,
            artifact_file_sha256=hashlib.sha256(raw).hexdigest(),
            device=before.st_dev,
            inode=before.st_ino,
            size=before.st_size,
            mode=stat.S_IMODE(before.st_mode),
            owner_uid=before.st_uid,
            link_count=before.st_nlink,
            mtime_ns=before.st_mtime_ns,
        )


def production_slice3_admission_store() -> FileSlice3AdmissionArtifactStore:
    """Return the sole fixed-path production admission evidence store."""

    return FileSlice3AdmissionArtifactStore(SLICE3_ADMISSION_ARTIFACT_PATH)


__all__ = [
    "SLICE3_ADMISSION_ARTIFACT_PATH",
    "SLICE3_ADMISSION_GENESIS_SHA256",
    "SLICE3_ADMISSION_MAX_TTL",
    "SLICE3_ADMISSION_RECORD_ORDER",
    "SLICE3_ADMISSION_SCHEMA_VERSION",
    "SLICE3_FIXED_CREDENTIAL_EVIDENCE_SHA256",
    "SLICE3_OPERATOR_AUTHORIZATION_SHA256",
    "FileSlice3AdmissionArtifactStore",
    "Slice3AdmissionAuthorityBundle",
    "Slice3AdmissionArtifactError",
    "Slice3AdmissionChain",
    "Slice3AdmissionEvidenceKind",
    "Slice3AdmissionEvidenceSet",
    "Slice3AdmissionRecord",
    "Slice3AdmissionSeal",
    "Slice3AdmissionSourceEvidence",
    "Slice3AdmissionValidationError",
    "build_slice3_admission_chain",
    "build_slice3_execution_authority",
    "production_slice3_admission_store",
]
