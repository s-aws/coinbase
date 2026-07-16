"""Immutable, hash-only Slice 3 activation readiness evidence.

This module does not construct a Coinbase client, register a route, execute a
Preview, or expose any mutation method.  It validates an already-accepted R8
terminal mapping in memory, retains only its binding hashes, and can seal one
short-lived owner-only readiness artifact with exclusive filesystem creation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
SLICE3_ACTIVATION_ARTIFACT_PATH = (
    _REPO_ROOT / "runtime_state" / "futures_slice3_activation.json"
)
SLICE3_ACTION_JOURNAL_PATH = (
    _REPO_ROOT / "runtime_state" / "futures_slice3_action_claims.jsonl"
)
SLICE3_READ_JOURNAL_PATH = (
    _REPO_ROOT / "runtime_state" / "futures_slice3_read_journal.jsonl"
)
SLICE3_TERMINAL_EVIDENCE_PATH = (
    _REPO_ROOT / "runtime_state" / "futures_slice3_terminal_evidence.json"
)

SLICE3_ACTIVATION_SCHEMA_VERSION = "slice3-terminal-roundtrip-activation-v2"
SLICE3_R8_ARTIFACT_TYPE = "futures_exact_no_live_preview_slice_2r8"
SLICE3_ACTIVATION_MAX_TTL = timedelta(minutes=15)
SLICE3_FIXED_CREDENTIAL_BINDING: Mapping[str, str] = MappingProxyType(
    {
        "source": "secrets_manager",
        "secret_id_env": "COINBASE_SECRETS_MANAGER_SECRET_ID",
        "secret_id": "coinbase",
        "region": "us-east-1",
    }
)

_ATTEMPT_LIMITS: Mapping[str, int] = MappingProxyType(
    {
        "preview": 0,
        "create": 1,
        "cancel": 1,
        "close": 1,
        "reduce": 0,
        "retry": 0,
        "fallback": 0,
        "redirect": 0,
    }
)
_SCHEMA_VERSIONS: Mapping[str, str] = MappingProxyType(
    {
        "action_journal": "slice3-action-claim-record-v4",
        "read_journal": "slice3-read-journal-record-v1",
        "terminal_evidence": "slice3-terminal-roundtrip-evidence-v2",
        "slice3_live_policy": "slice3-terminal-roundtrip-policy-v1",
    }
)
_MAX_ARTIFACT_BYTES = 64 * 1024
_MAX_AUTHORIZATION_BYTES = 64 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+~\-]{0,127}$")
_PRIVATE_IDENTIFIER_FIELDS = frozenset(
    {
        "preview_id",
        "portfolio_id",
        "observed_portfolio_id",
        "selected_portfolio_id",
        "retail_portfolio_id",
        "client_order_id",
        "exchange_order_id",
        "order_id",
    }
)


class Slice3ActivationValidationError(ValueError):
    """Raised when readiness evidence is not the exact sealed contract."""


class Slice3ActivationArtifactError(RuntimeError):
    """Raised when activation artifact persistence or readback is unsafe."""


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
        raise Slice3ActivationValidationError(
            "slice3_activation_canonical_json_invalid"
        ) from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, reason: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise Slice3ActivationValidationError(reason)
    return value


def _require_revision(value: object, field: str) -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise Slice3ActivationValidationError(f"slice3_activation_{field}_invalid")
    return value


def _aware_utc(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise Slice3ActivationValidationError(f"slice3_activation_{field}_invalid")
    try:
        normalized = value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise Slice3ActivationValidationError(
            f"slice3_activation_{field}_invalid"
        ) from exc
    if normalized.utcoffset() != timedelta(0):
        raise Slice3ActivationValidationError(f"slice3_activation_{field}_invalid")
    return normalized


def _parse_canonical_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise Slice3ActivationValidationError(f"slice3_activation_{field}_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise Slice3ActivationValidationError(
            f"slice3_activation_{field}_invalid"
        ) from exc
    normalized = _aware_utc(parsed, field)
    if normalized.isoformat() != value:
        raise Slice3ActivationValidationError(f"slice3_activation_{field}_noncanonical")
    return normalized


def _authorization_sha256(value: str | bytes) -> str:
    if isinstance(value, str):
        try:
            raw = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise Slice3ActivationValidationError(
                "slice3_activation_authorization_text_invalid"
            ) from exc
    elif isinstance(value, bytes):
        raw = value
    else:
        raise Slice3ActivationValidationError(
            "slice3_activation_authorization_text_invalid"
        )
    if not raw or len(raw) > _MAX_AUTHORIZATION_BYTES:
        raise Slice3ActivationValidationError(
            "slice3_activation_authorization_text_invalid"
        )
    return hashlib.sha256(raw).hexdigest()


def _reject_raw_private_identifiers(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _PRIVATE_IDENTIFIER_FIELDS and item != "withheld":
                raise Slice3ActivationValidationError(
                    "slice3_activation_r8_private_identifier_present"
                )
            _reject_raw_private_identifiers(item)
    elif isinstance(value, list):
        for item in value:
            _reject_raw_private_identifiers(item)


@dataclass(frozen=True, slots=True)
class Slice3AcceptedR8Binding:
    """The only retained view of an exact accepted R8 terminal result."""

    artifact_file_sha256: str
    evidence_sha256: str
    claim_sha256: str
    seal_ready_plan_sha256: str
    preview_id_sha256: str
    portfolio_id_sha256: str

    @classmethod
    def from_accepted_evidence(
        cls,
        *,
        artifact_file_sha256: str,
        evidence: Mapping[str, Any],
    ) -> Slice3AcceptedR8Binding:
        """Validate accepted R8 in memory and discard all identifier values."""

        artifact_hash = _require_sha256(
            artifact_file_sha256,
            "slice3_activation_r8_artifact_file_sha256_invalid",
        )
        if not isinstance(evidence, Mapping):
            raise Slice3ActivationValidationError(
                "slice3_activation_r8_evidence_invalid"
            )
        if (
            evidence.get("schema_version") != "1"
            or evidence.get("type") != "admin_futures_order_preview"
            or evidence.get("artifact_type") != SLICE3_R8_ARTIFACT_TYPE
        ):
            raise Slice3ActivationValidationError(
                "slice3_activation_r8_identity_invalid"
            )
        if (
            evidence.get("status") != "accepted"
            or evidence.get("outcome") != "accepted"
        ):
            raise Slice3ActivationValidationError("slice3_activation_r8_not_accepted")
        _reject_raw_private_identifiers(evidence)
        evidence_hash = _require_sha256(
            evidence.get("evidence_sha256"),
            "slice3_activation_r8_evidence_sha256_invalid",
        )
        evidence_without_hash = {
            str(key): value
            for key, value in evidence.items()
            if key != "evidence_sha256"
        }
        if _canonical_sha256(evidence_without_hash) != evidence_hash:
            raise Slice3ActivationValidationError(
                "slice3_activation_r8_evidence_sha256_invalid"
            )
        claim_hash = _require_sha256(
            evidence.get("claim_sha256"),
            "slice3_activation_r8_claim_sha256_invalid",
        )
        seal_ready_plan = evidence.get("seal_ready_plan")
        if not isinstance(seal_ready_plan, Mapping):
            raise Slice3ActivationValidationError(
                "slice3_activation_r8_seal_ready_plan_invalid"
            )
        seal_plan_hash = _require_sha256(
            evidence.get("seal_ready_plan_sha256"),
            "slice3_activation_r8_seal_ready_plan_sha256_invalid",
        )
        if _canonical_sha256(dict(seal_ready_plan)) != seal_plan_hash:
            raise Slice3ActivationValidationError(
                "slice3_activation_r8_seal_ready_plan_sha256_invalid"
            )
        preview_id_hash = _require_sha256(
            evidence.get("preview_id_sha256"),
            "slice3_activation_r8_preview_id_sha256_invalid",
        )
        portfolio_id_hash = _require_sha256(
            evidence.get("portfolio_id_sha256"),
            "slice3_activation_r8_portfolio_id_sha256_invalid",
        )
        return cls(
            artifact_file_sha256=artifact_hash,
            evidence_sha256=evidence_hash,
            claim_sha256=claim_hash,
            seal_ready_plan_sha256=seal_plan_hash,
            preview_id_sha256=preview_id_hash,
            portfolio_id_sha256=portfolio_id_hash,
        )

    @classmethod
    def from_sanitized_evidence(
        cls,
        value: object,
    ) -> Slice3AcceptedR8Binding:
        if not isinstance(value, Mapping) or set(value) != {
            "artifact_type",
            "status",
            "outcome",
            "artifact_file_sha256",
            "evidence_sha256",
            "claim_sha256",
            "seal_ready_plan_sha256",
            "preview_id_sha256",
            "portfolio_id_sha256",
        }:
            raise Slice3ActivationValidationError("slice3_activation_r8_fields_invalid")
        if (
            value.get("artifact_type") != SLICE3_R8_ARTIFACT_TYPE
            or value.get("status") != "accepted"
            or value.get("outcome") != "accepted"
        ):
            raise Slice3ActivationValidationError("slice3_activation_r8_not_accepted")
        binding = cls(
            artifact_file_sha256=_require_sha256(
                value.get("artifact_file_sha256"),
                "slice3_activation_r8_artifact_file_sha256_invalid",
            ),
            evidence_sha256=_require_sha256(
                value.get("evidence_sha256"),
                "slice3_activation_r8_evidence_sha256_invalid",
            ),
            claim_sha256=_require_sha256(
                value.get("claim_sha256"),
                "slice3_activation_r8_claim_sha256_invalid",
            ),
            seal_ready_plan_sha256=_require_sha256(
                value.get("seal_ready_plan_sha256"),
                "slice3_activation_r8_seal_ready_plan_sha256_invalid",
            ),
            preview_id_sha256=_require_sha256(
                value.get("preview_id_sha256"),
                "slice3_activation_r8_preview_id_sha256_invalid",
            ),
            portfolio_id_sha256=_require_sha256(
                value.get("portfolio_id_sha256"),
                "slice3_activation_r8_portfolio_id_sha256_invalid",
            ),
        )
        binding.validate()
        return binding

    def validate(self) -> None:
        _require_sha256(
            self.artifact_file_sha256,
            "slice3_activation_r8_artifact_file_sha256_invalid",
        )
        _require_sha256(
            self.evidence_sha256,
            "slice3_activation_r8_evidence_sha256_invalid",
        )
        _require_sha256(
            self.claim_sha256,
            "slice3_activation_r8_claim_sha256_invalid",
        )
        _require_sha256(
            self.seal_ready_plan_sha256,
            "slice3_activation_r8_seal_ready_plan_sha256_invalid",
        )
        _require_sha256(
            self.preview_id_sha256,
            "slice3_activation_r8_preview_id_sha256_invalid",
        )
        _require_sha256(
            self.portfolio_id_sha256,
            "slice3_activation_r8_portfolio_id_sha256_invalid",
        )

    def sanitized_evidence(self) -> dict[str, str]:
        self.validate()
        return {
            "artifact_type": SLICE3_R8_ARTIFACT_TYPE,
            "status": "accepted",
            "outcome": "accepted",
            "artifact_file_sha256": self.artifact_file_sha256,
            "evidence_sha256": self.evidence_sha256,
            "claim_sha256": self.claim_sha256,
            "seal_ready_plan_sha256": self.seal_ready_plan_sha256,
            "preview_id_sha256": self.preview_id_sha256,
            "portfolio_id_sha256": self.portfolio_id_sha256,
        }


@dataclass(frozen=True, slots=True)
class Slice3ActivationManifest:
    """Short-lived readiness contract with no raw private identifiers."""

    r8_binding: Slice3AcceptedR8Binding
    slice3_plan_sha256: str
    authorization_text_sha256: str
    backend_revision: str
    openapi_revision: str
    core_module_sha256: str
    port_module_sha256: str
    orchestrator_module_sha256: str
    admission_module_sha256: str
    admission_chain_sha256: str
    admission_record_sha256: str
    admission_artifact_file_sha256: str
    action_journal_schema_sha256: str
    read_journal_schema_sha256: str
    terminal_evidence_schema_sha256: str
    slice3_live_policy_sha256: str
    created_at: datetime
    expires_at: datetime

    @classmethod
    def build(
        cls,
        *,
        r8_binding: Slice3AcceptedR8Binding,
        slice3_plan_sha256: str,
        authorization_text: str | bytes,
        backend_revision: str,
        openapi_revision: str,
        core_module_sha256: str,
        port_module_sha256: str,
        orchestrator_module_sha256: str,
        admission_module_sha256: str,
        admission_chain_sha256: str,
        admission_record_sha256: str,
        admission_artifact_file_sha256: str,
        action_journal_schema_sha256: str,
        read_journal_schema_sha256: str,
        terminal_evidence_schema_sha256: str,
        slice3_live_policy_sha256: str,
        now: datetime,
        expires_at: datetime,
    ) -> Slice3ActivationManifest:
        if not isinstance(r8_binding, Slice3AcceptedR8Binding):
            raise Slice3ActivationValidationError(
                "slice3_activation_r8_binding_invalid"
            )
        created = _aware_utc(now, "created_at")
        expiry = _aware_utc(expires_at, "expires_at")
        manifest = cls(
            r8_binding=r8_binding,
            slice3_plan_sha256=_require_sha256(
                slice3_plan_sha256,
                "slice3_activation_plan_sha256_invalid",
            ),
            authorization_text_sha256=_authorization_sha256(authorization_text),
            backend_revision=_require_revision(backend_revision, "backend_revision"),
            openapi_revision=_require_revision(openapi_revision, "openapi_revision"),
            core_module_sha256=_require_sha256(
                core_module_sha256,
                "slice3_activation_core_module_sha256_invalid",
            ),
            port_module_sha256=_require_sha256(
                port_module_sha256,
                "slice3_activation_port_module_sha256_invalid",
            ),
            orchestrator_module_sha256=_require_sha256(
                orchestrator_module_sha256,
                "slice3_activation_orchestrator_module_sha256_invalid",
            ),
            admission_module_sha256=_require_sha256(
                admission_module_sha256,
                "slice3_activation_admission_module_sha256_invalid",
            ),
            admission_chain_sha256=_require_sha256(
                admission_chain_sha256,
                "slice3_activation_admission_chain_sha256_invalid",
            ),
            admission_record_sha256=_require_sha256(
                admission_record_sha256,
                "slice3_activation_admission_record_sha256_invalid",
            ),
            admission_artifact_file_sha256=_require_sha256(
                admission_artifact_file_sha256,
                "slice3_activation_admission_artifact_file_sha256_invalid",
            ),
            action_journal_schema_sha256=_require_sha256(
                action_journal_schema_sha256,
                "slice3_activation_action_journal_schema_sha256_invalid",
            ),
            read_journal_schema_sha256=_require_sha256(
                read_journal_schema_sha256,
                "slice3_activation_read_journal_schema_sha256_invalid",
            ),
            terminal_evidence_schema_sha256=_require_sha256(
                terminal_evidence_schema_sha256,
                "slice3_activation_terminal_evidence_schema_sha256_invalid",
            ),
            slice3_live_policy_sha256=_require_sha256(
                slice3_live_policy_sha256,
                "slice3_activation_live_policy_sha256_invalid",
            ),
            created_at=created,
            expires_at=expiry,
        )
        manifest.validate_at(created)
        return manifest

    @classmethod
    def from_sanitized_evidence(
        cls,
        value: object,
        *,
        now: datetime,
    ) -> Slice3ActivationManifest:
        expected_fields = {
            "schema_version",
            "readiness",
            "r8",
            "slice3_plan_sha256",
            "authorization_text_sha256",
            "backend_revision",
            "openapi_revision",
            "module_sha256",
            "admission_module_sha256",
            "admission_chain_sha256",
            "admission_record_sha256",
            "admission_artifact_file_sha256",
            "schema_versions",
            "schema_policy_sha256",
            "created_at",
            "expires_at",
            "credential_binding",
            "activation_artifact_path",
            "journal_path",
            "read_journal_path",
            "terminal_evidence_path",
            "attempt_limits",
            "live_adapter_bound",
            "route_registered",
            "raw_identifier_values_included",
            "authorization_text_included",
            "canonicalization",
            "hash_algorithm",
        }
        if not isinstance(value, Mapping) or set(value) != expected_fields:
            raise Slice3ActivationValidationError(
                "slice3_activation_manifest_fields_invalid"
            )
        if (
            value.get("schema_version") != SLICE3_ACTIVATION_SCHEMA_VERSION
            or value.get("readiness") != "ready"
            or value.get("credential_binding") != dict(SLICE3_FIXED_CREDENTIAL_BINDING)
            or value.get("activation_artifact_path")
            != str(SLICE3_ACTIVATION_ARTIFACT_PATH)
            or value.get("journal_path") != str(SLICE3_ACTION_JOURNAL_PATH)
            or value.get("read_journal_path") != str(SLICE3_READ_JOURNAL_PATH)
            or value.get("terminal_evidence_path") != str(SLICE3_TERMINAL_EVIDENCE_PATH)
            or value.get("schema_versions") != dict(_SCHEMA_VERSIONS)
            or value.get("attempt_limits") != dict(_ATTEMPT_LIMITS)
            or value.get("live_adapter_bound") is not True
            or value.get("route_registered") is not False
            or value.get("raw_identifier_values_included") is not False
            or value.get("authorization_text_included") is not False
            or value.get("canonicalization") != "sorted_keys_compact_utf8_json"
            or value.get("hash_algorithm") != "sha256"
        ):
            if value.get("journal_path") != str(SLICE3_ACTION_JOURNAL_PATH):
                reason = "slice3_activation_journal_path_invalid"
            elif value.get("read_journal_path") != str(SLICE3_READ_JOURNAL_PATH):
                reason = "slice3_activation_read_journal_path_invalid"
            elif value.get("terminal_evidence_path") != str(
                SLICE3_TERMINAL_EVIDENCE_PATH
            ):
                reason = "slice3_activation_terminal_evidence_path_invalid"
            elif value.get("attempt_limits") != dict(_ATTEMPT_LIMITS):
                reason = "slice3_activation_attempt_limits_invalid"
            elif value.get("live_adapter_bound") is not True:
                reason = "slice3_activation_live_adapter_not_bound"
            elif value.get("route_registered") is not False:
                reason = "slice3_activation_route_registered_invalid"
            else:
                reason = "slice3_activation_fixed_contract_invalid"
            raise Slice3ActivationValidationError(reason)
        modules = value.get("module_sha256")
        if not isinstance(modules, Mapping) or set(modules) != {
            "core",
            "port",
            "orchestrator",
        }:
            raise Slice3ActivationValidationError(
                "slice3_activation_module_fields_invalid"
            )
        schema_policy = value.get("schema_policy_sha256")
        if not isinstance(schema_policy, Mapping) or set(schema_policy) != {
            "action_journal_schema",
            "read_journal_schema",
            "terminal_evidence_schema",
            "slice3_live_policy",
        }:
            raise Slice3ActivationValidationError(
                "slice3_activation_schema_policy_fields_invalid"
            )
        manifest = cls(
            r8_binding=Slice3AcceptedR8Binding.from_sanitized_evidence(value.get("r8")),
            slice3_plan_sha256=_require_sha256(
                value.get("slice3_plan_sha256"),
                "slice3_activation_plan_sha256_invalid",
            ),
            authorization_text_sha256=_require_sha256(
                value.get("authorization_text_sha256"),
                "slice3_activation_authorization_text_sha256_invalid",
            ),
            backend_revision=_require_revision(
                value.get("backend_revision"), "backend_revision"
            ),
            openapi_revision=_require_revision(
                value.get("openapi_revision"), "openapi_revision"
            ),
            core_module_sha256=_require_sha256(
                modules.get("core"),
                "slice3_activation_core_module_sha256_invalid",
            ),
            port_module_sha256=_require_sha256(
                modules.get("port"),
                "slice3_activation_port_module_sha256_invalid",
            ),
            orchestrator_module_sha256=_require_sha256(
                modules.get("orchestrator"),
                "slice3_activation_orchestrator_module_sha256_invalid",
            ),
            admission_module_sha256=_require_sha256(
                value.get("admission_module_sha256"),
                "slice3_activation_admission_module_sha256_invalid",
            ),
            admission_chain_sha256=_require_sha256(
                value.get("admission_chain_sha256"),
                "slice3_activation_admission_chain_sha256_invalid",
            ),
            admission_record_sha256=_require_sha256(
                value.get("admission_record_sha256"),
                "slice3_activation_admission_record_sha256_invalid",
            ),
            admission_artifact_file_sha256=_require_sha256(
                value.get("admission_artifact_file_sha256"),
                "slice3_activation_admission_artifact_file_sha256_invalid",
            ),
            action_journal_schema_sha256=_require_sha256(
                schema_policy.get("action_journal_schema"),
                "slice3_activation_action_journal_schema_sha256_invalid",
            ),
            read_journal_schema_sha256=_require_sha256(
                schema_policy.get("read_journal_schema"),
                "slice3_activation_read_journal_schema_sha256_invalid",
            ),
            terminal_evidence_schema_sha256=_require_sha256(
                schema_policy.get("terminal_evidence_schema"),
                "slice3_activation_terminal_evidence_schema_sha256_invalid",
            ),
            slice3_live_policy_sha256=_require_sha256(
                schema_policy.get("slice3_live_policy"),
                "slice3_activation_live_policy_sha256_invalid",
            ),
            created_at=_parse_canonical_timestamp(
                value.get("created_at"), "created_at"
            ),
            expires_at=_parse_canonical_timestamp(
                value.get("expires_at"), "expires_at"
            ),
        )
        manifest.validate_at(now)
        return manifest

    def validate_at(self, now: datetime) -> None:
        self.r8_binding.validate()
        _require_sha256(
            self.slice3_plan_sha256,
            "slice3_activation_plan_sha256_invalid",
        )
        _require_sha256(
            self.authorization_text_sha256,
            "slice3_activation_authorization_text_sha256_invalid",
        )
        _require_revision(self.backend_revision, "backend_revision")
        _require_revision(self.openapi_revision, "openapi_revision")
        _require_sha256(
            self.core_module_sha256,
            "slice3_activation_core_module_sha256_invalid",
        )
        _require_sha256(
            self.port_module_sha256,
            "slice3_activation_port_module_sha256_invalid",
        )
        _require_sha256(
            self.orchestrator_module_sha256,
            "slice3_activation_orchestrator_module_sha256_invalid",
        )
        _require_sha256(
            self.admission_module_sha256,
            "slice3_activation_admission_module_sha256_invalid",
        )
        _require_sha256(
            self.admission_chain_sha256,
            "slice3_activation_admission_chain_sha256_invalid",
        )
        _require_sha256(
            self.admission_record_sha256,
            "slice3_activation_admission_record_sha256_invalid",
        )
        _require_sha256(
            self.admission_artifact_file_sha256,
            "slice3_activation_admission_artifact_file_sha256_invalid",
        )
        _require_sha256(
            self.action_journal_schema_sha256,
            "slice3_activation_action_journal_schema_sha256_invalid",
        )
        _require_sha256(
            self.read_journal_schema_sha256,
            "slice3_activation_read_journal_schema_sha256_invalid",
        )
        _require_sha256(
            self.terminal_evidence_schema_sha256,
            "slice3_activation_terminal_evidence_schema_sha256_invalid",
        )
        _require_sha256(
            self.slice3_live_policy_sha256,
            "slice3_activation_live_policy_sha256_invalid",
        )
        created = _aware_utc(self.created_at, "created_at")
        expiry = _aware_utc(self.expires_at, "expires_at")
        if expiry <= created:
            raise Slice3ActivationValidationError("slice3_activation_expiry_invalid")
        if expiry - created > SLICE3_ACTIVATION_MAX_TTL:
            raise Slice3ActivationValidationError(
                "slice3_activation_expiry_ttl_invalid"
            )
        observed = _aware_utc(now, "now")
        if observed < created:
            raise Slice3ActivationValidationError("slice3_activation_not_yet_valid")
        if observed >= expiry:
            raise Slice3ActivationValidationError("slice3_activation_expired")

    def sanitized_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": SLICE3_ACTIVATION_SCHEMA_VERSION,
            "readiness": "ready",
            "r8": self.r8_binding.sanitized_evidence(),
            "slice3_plan_sha256": self.slice3_plan_sha256,
            "authorization_text_sha256": self.authorization_text_sha256,
            "backend_revision": self.backend_revision,
            "openapi_revision": self.openapi_revision,
            "module_sha256": {
                "core": self.core_module_sha256,
                "port": self.port_module_sha256,
                "orchestrator": self.orchestrator_module_sha256,
            },
            "admission_module_sha256": self.admission_module_sha256,
            "admission_chain_sha256": self.admission_chain_sha256,
            "admission_record_sha256": self.admission_record_sha256,
            "admission_artifact_file_sha256": (self.admission_artifact_file_sha256),
            "schema_versions": dict(_SCHEMA_VERSIONS),
            "schema_policy_sha256": {
                "action_journal_schema": (self.action_journal_schema_sha256),
                "read_journal_schema": self.read_journal_schema_sha256,
                "terminal_evidence_schema": (self.terminal_evidence_schema_sha256),
                "slice3_live_policy": self.slice3_live_policy_sha256,
            },
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "expires_at": self.expires_at.astimezone(timezone.utc).isoformat(),
            "credential_binding": dict(SLICE3_FIXED_CREDENTIAL_BINDING),
            "activation_artifact_path": str(SLICE3_ACTIVATION_ARTIFACT_PATH),
            "journal_path": str(SLICE3_ACTION_JOURNAL_PATH),
            "read_journal_path": str(SLICE3_READ_JOURNAL_PATH),
            "terminal_evidence_path": str(SLICE3_TERMINAL_EVIDENCE_PATH),
            "attempt_limits": dict(_ATTEMPT_LIMITS),
            "live_adapter_bound": True,
            "route_registered": False,
            "raw_identifier_values_included": False,
            "authorization_text_included": False,
            "canonicalization": "sorted_keys_compact_utf8_json",
            "hash_algorithm": "sha256",
        }

    @property
    def manifest_sha256(self) -> str:
        return _canonical_sha256(self.sanitized_evidence())


@dataclass(frozen=True, slots=True)
class Slice3ActivationSeal:
    """Validated artifact plus stable filesystem and content evidence."""

    manifest: Slice3ActivationManifest
    manifest_sha256: str
    record_sha256: str
    artifact_file_sha256: str
    device: int
    inode: int
    size: int
    mode: int
    owner_uid: int
    link_count: int
    mtime_ns: int


class _DuplicateJsonKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise Slice3ActivationArtifactError("slice3_activation_write_failed")
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


class Slice3ActivationArtifactStore:
    """O_EXCL, fsynced, immutable one-file activation artifact store."""

    def __init__(self, path: Path) -> None:
        supplied = Path(path)
        rendered = os.fspath(supplied)
        if (
            not supplied.is_absolute()
            or os.path.normpath(rendered) != rendered
            or supplied.name in {"", ".", ".."}
        ):
            raise Slice3ActivationArtifactError("slice3_activation_path_invalid")
        self.path = supplied
        self._owner_uid = os.geteuid()

    def _assert_no_symlink_components(self) -> None:
        current = Path(self.path.anchor)
        for part in self.path.parent.parts[1:]:
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError as exc:
                raise Slice3ActivationArtifactError(
                    "slice3_activation_parent_missing"
                ) from exc
            except OSError as exc:
                raise Slice3ActivationArtifactError(
                    "slice3_activation_parent_invalid"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise Slice3ActivationArtifactError("slice3_activation_parent_symlink")
            if not stat.S_ISDIR(metadata.st_mode):
                raise Slice3ActivationArtifactError("slice3_activation_parent_invalid")

    def _open_parent_fd(self) -> int:
        self._assert_no_symlink_components()
        try:
            before = self.path.parent.lstat()
            fd = os.open(
                self.path.parent,
                os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC,
            )
        except OSError as exc:
            raise Slice3ActivationArtifactError(
                "slice3_activation_parent_invalid"
            ) from exc
        opened = os.fstat(fd)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or opened.st_uid != self._owner_uid
        ):
            os.close(fd)
            raise Slice3ActivationArtifactError(
                "slice3_activation_parent_metadata_invalid"
            )
        return fd

    def _target_lstat(self, parent_fd: int) -> os.stat_result:
        try:
            return os.stat(
                self.path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            raise Slice3ActivationArtifactError(
                "slice3_activation_artifact_missing"
            ) from exc
        except OSError as exc:
            raise Slice3ActivationArtifactError(
                "slice3_activation_artifact_invalid"
            ) from exc

    def _validate_file_metadata(self, value: os.stat_result) -> None:
        if stat.S_ISLNK(value.st_mode):
            raise Slice3ActivationArtifactError("slice3_activation_path_symlink")
        if not stat.S_ISREG(value.st_mode):
            raise Slice3ActivationArtifactError("slice3_activation_not_regular")
        if value.st_uid != self._owner_uid:
            raise Slice3ActivationArtifactError("slice3_activation_owner_invalid")
        if stat.S_IMODE(value.st_mode) != 0o400:
            raise Slice3ActivationArtifactError("slice3_activation_mode_invalid")
        if value.st_nlink != 1:
            raise Slice3ActivationArtifactError("slice3_activation_link_count_invalid")
        if value.st_size <= 0 or value.st_size > _MAX_ARTIFACT_BYTES:
            raise Slice3ActivationArtifactError("slice3_activation_size_invalid")

    @staticmethod
    def _record(manifest: Slice3ActivationManifest) -> dict[str, Any]:
        evidence = manifest.sanitized_evidence()
        record: dict[str, Any] = {
            "schema_version": SLICE3_ACTIVATION_SCHEMA_VERSION,
            "record_type": "slice3_activation",
            "manifest": evidence,
            "manifest_sha256": _canonical_sha256(evidence),
        }
        record["record_sha256"] = _canonical_sha256(record)
        return record

    def seal(
        self,
        manifest: Slice3ActivationManifest,
        *,
        now: datetime,
    ) -> Slice3ActivationSeal:
        if not isinstance(manifest, Slice3ActivationManifest):
            raise Slice3ActivationArtifactError("slice3_activation_manifest_invalid")
        try:
            manifest.validate_at(now)
            payload = _canonical_bytes(self._record(manifest)) + b"\n"
        except Slice3ActivationValidationError as exc:
            raise Slice3ActivationArtifactError(str(exc)) from exc
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise Slice3ActivationArtifactError("slice3_activation_size_invalid")

        parent_fd = self._open_parent_fd()
        fd: int | None = None
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
                    raise Slice3ActivationArtifactError(
                        "slice3_activation_path_symlink"
                    )
                raise Slice3ActivationArtifactError("slice3_activation_already_exists")
            try:
                fd = os.open(
                    self.path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError as exc:
                raise Slice3ActivationArtifactError(
                    "slice3_activation_already_exists"
                ) from exc
            except OSError as exc:
                raise Slice3ActivationArtifactError(
                    "slice3_activation_create_failed"
                ) from exc
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_uid != self._owner_uid
                or opened.st_nlink != 1
            ):
                raise Slice3ActivationArtifactError(
                    "slice3_activation_created_metadata_invalid"
                )
            _write_all(fd, payload)
            os.fchmod(fd, 0o400)
            os.fsync(fd)
            completed = os.fstat(fd)
            self._validate_file_metadata(completed)
            if completed.st_size != len(payload):
                raise Slice3ActivationArtifactError("slice3_activation_size_invalid")
            os.close(fd)
            fd = None
            os.fsync(parent_fd)
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent_fd)
        return self.read(
            now=now,
            expected_manifest_sha256=manifest.manifest_sha256,
        )

    def read(
        self,
        *,
        now: datetime,
        expected_manifest_sha256: str,
    ) -> Slice3ActivationSeal:
        try:
            expected_manifest_hash = _require_sha256(
                expected_manifest_sha256,
                "slice3_activation_expected_manifest_sha256_invalid",
            )
        except Slice3ActivationValidationError as exc:
            raise Slice3ActivationArtifactError(str(exc)) from exc
        parent_fd = self._open_parent_fd()
        fd: int | None = None
        try:
            before = self._target_lstat(parent_fd)
            self._validate_file_metadata(before)
            try:
                fd = os.open(
                    self.path.name,
                    os.O_RDONLY | _NOFOLLOW | _CLOEXEC,
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                raise Slice3ActivationArtifactError(
                    "slice3_activation_read_failed"
                ) from exc
            opened = os.fstat(fd)
            if _stable_metadata(opened) != _stable_metadata(before):
                raise Slice3ActivationArtifactError(
                    "slice3_activation_metadata_changed"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(fd, 8192)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_ARTIFACT_BYTES:
                    raise Slice3ActivationArtifactError(
                        "slice3_activation_size_invalid"
                    )
                chunks.append(chunk)
            after_fd = os.fstat(fd)
            after_path = self._target_lstat(parent_fd)
            if _stable_metadata(after_fd) != _stable_metadata(
                opened
            ) or _stable_metadata(after_path) != _stable_metadata(opened):
                raise Slice3ActivationArtifactError(
                    "slice3_activation_metadata_changed"
                )
            raw = b"".join(chunks)
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent_fd)

        if len(raw) != before.st_size or not raw.endswith(b"\n"):
            raise Slice3ActivationArtifactError("slice3_activation_record_incomplete")
        try:
            decoded = raw[:-1].decode("utf-8")
            record = json.loads(
                decoded,
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKey) as exc:
            raise Slice3ActivationArtifactError("slice3_activation_tampered") from exc
        if not isinstance(record, dict):
            raise Slice3ActivationArtifactError("slice3_activation_tampered")
        try:
            canonical_record = _canonical_bytes(record) + b"\n"
        except Slice3ActivationValidationError as exc:
            raise Slice3ActivationArtifactError("slice3_activation_tampered") from exc
        if raw != canonical_record:
            raise Slice3ActivationArtifactError("slice3_activation_noncanonical")
        if set(record) != {
            "schema_version",
            "record_type",
            "manifest",
            "manifest_sha256",
            "record_sha256",
        }:
            raise Slice3ActivationArtifactError(
                "slice3_activation_record_fields_invalid"
            )
        if (
            record.get("schema_version") != SLICE3_ACTIVATION_SCHEMA_VERSION
            or record.get("record_type") != "slice3_activation"
        ):
            raise Slice3ActivationArtifactError(
                "slice3_activation_record_identity_invalid"
            )
        manifest_evidence = record.get("manifest")
        if not isinstance(manifest_evidence, Mapping):
            raise Slice3ActivationArtifactError("slice3_activation_manifest_invalid")
        manifest_hash = record.get("manifest_sha256")
        if (
            not isinstance(manifest_hash, str)
            or _canonical_sha256(manifest_evidence) != manifest_hash
        ):
            raise Slice3ActivationArtifactError("slice3_activation_manifest_tampered")
        record_hash = record.get("record_sha256")
        unhashed_record = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        if (
            not isinstance(record_hash, str)
            or _canonical_sha256(unhashed_record) != record_hash
        ):
            raise Slice3ActivationArtifactError("slice3_activation_record_tampered")
        try:
            manifest = Slice3ActivationManifest.from_sanitized_evidence(
                manifest_evidence,
                now=now,
            )
        except Slice3ActivationValidationError as exc:
            raise Slice3ActivationArtifactError(str(exc)) from exc
        if manifest_hash != expected_manifest_hash:
            raise Slice3ActivationArtifactError(
                "slice3_activation_expected_manifest_sha256_mismatch"
            )
        return Slice3ActivationSeal(
            manifest=manifest,
            manifest_sha256=manifest_hash,
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


def production_slice3_activation_store() -> Slice3ActivationArtifactStore:
    """Return the non-configurable production activation artifact store."""

    return Slice3ActivationArtifactStore(SLICE3_ACTIVATION_ARTIFACT_PATH)
