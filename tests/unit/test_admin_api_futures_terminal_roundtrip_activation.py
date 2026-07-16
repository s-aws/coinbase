from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from typing import Any

import pytest

from application.admin_api.futures_terminal_roundtrip_activation import (
    SLICE3_ACTION_JOURNAL_PATH,
    SLICE3_ACTIVATION_ARTIFACT_PATH,
    SLICE3_ACTIVATION_MAX_TTL,
    SLICE3_FIXED_CREDENTIAL_BINDING,
    SLICE3_READ_JOURNAL_PATH,
    SLICE3_TERMINAL_EVIDENCE_PATH,
    Slice3AcceptedR8Binding,
    Slice3ActivationArtifactError,
    Slice3ActivationArtifactStore,
    Slice3ActivationManifest,
    Slice3ActivationValidationError,
)


NOW = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)
RAW_PREVIEW_ID = "raw-preview-private-8127"
RAW_PORTFOLIO_ID = "raw-portfolio-private-3141"
RAW_CLIENT_ORDER_ID = "raw-client-private-2718"
RAW_EXCHANGE_ORDER_ID = "raw-exchange-private-1618"
RAW_AUTHORIZATION = (
    "I authorize one exact Slice 3 terminal roundtrip; private-auth-marker-99."
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _hash(char: str) -> str:
    return char * 64


def _accepted_r8_evidence() -> dict[str, Any]:
    seal_ready_plan = {
        "authoritative_preview": {
            "preview_id": "withheld",
            "preview_response": {"preview_id": "withheld"},
        },
        "profile_binding": {"portfolio_id": "withheld"},
    }
    preview_response = {"preview_id": "withheld"}
    evidence: dict[str, Any] = {
        "schema_version": "1",
        "type": "admin_futures_order_preview",
        "artifact_type": "futures_exact_no_live_preview_slice_2r8",
        "status": "accepted",
        "outcome": "accepted",
        "claim_sha256": _hash("1"),
        "portfolio_id": "withheld",
        "portfolio_id_sha256": hashlib.sha256(
            RAW_PORTFOLIO_ID.encode("utf-8")
        ).hexdigest(),
        "portfolio_binding": {
            "observed_portfolio_id": "withheld",
            "portfolio_id": "withheld",
        },
        "permission_evidence": {"portfolio_id": "withheld"},
        "portfolio_catalog_evidence": {"selected_portfolio_id": "withheld"},
        "preview_response": preview_response,
        "preview_response_sha256": _canonical_sha256(preview_response),
        "preview_id_sha256": hashlib.sha256(RAW_PREVIEW_ID.encode("utf-8")).hexdigest(),
        "seal_ready_plan": seal_ready_plan,
        "seal_ready_plan_sha256": _canonical_sha256(seal_ready_plan),
    }
    evidence["evidence_sha256"] = _canonical_sha256(evidence)
    return evidence


def _r8_binding() -> Slice3AcceptedR8Binding:
    return Slice3AcceptedR8Binding.from_accepted_evidence(
        artifact_file_sha256=_hash("a"),
        evidence=_accepted_r8_evidence(),
    )


def _manifest(
    *,
    expires_at: datetime = NOW + timedelta(minutes=10),
    backend_revision: str = "backend-main-deadbeef",
    openapi_revision: str = "openapi-sha256-feedface",
) -> Slice3ActivationManifest:
    return Slice3ActivationManifest.build(
        r8_binding=_r8_binding(),
        slice3_plan_sha256=_hash("2"),
        authorization_text=RAW_AUTHORIZATION,
        backend_revision=backend_revision,
        openapi_revision=openapi_revision,
        core_module_sha256=_hash("3"),
        port_module_sha256=_hash("4"),
        orchestrator_module_sha256=_hash("5"),
        admission_module_sha256=_hash("a"),
        admission_chain_sha256=_hash("b"),
        admission_record_sha256=_hash("c"),
        admission_artifact_file_sha256=_hash("d"),
        action_journal_schema_sha256=_hash("6"),
        read_journal_schema_sha256=_hash("7"),
        terminal_evidence_schema_sha256=_hash("8"),
        slice3_live_policy_sha256=_hash("9"),
        now=NOW,
        expires_at=expires_at,
    )


def _read(
    store: Slice3ActivationArtifactStore,
    *,
    now: datetime,
):
    return store.read(
        now=now,
        expected_manifest_sha256=_manifest().manifest_sha256,
    )


def _rewrite_record(
    path: Path,
    mutate: Any,
    *,
    recompute_hashes: bool,
    canonical: bool = True,
) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    mutate(record)
    if recompute_hashes:
        record["manifest_sha256"] = _canonical_sha256(record["manifest"])
        unhashed = {
            key: value for key, value in record.items() if key != "record_sha256"
        }
        record["record_sha256"] = _canonical_sha256(unhashed)
    os.chmod(path, 0o600)
    if canonical:
        payload = _canonical_bytes(record) + b"\n"
    else:
        payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(payload)
    os.chmod(path, 0o400)


def test_r8_binding_validates_hashes_and_discards_private_identifiers() -> None:
    binding = _r8_binding()

    assert binding.artifact_file_sha256 == _hash("a")
    assert binding.evidence_sha256 == _accepted_r8_evidence()["evidence_sha256"]
    assert binding.claim_sha256 == _hash("1")
    assert (
        binding.seal_ready_plan_sha256
        == _accepted_r8_evidence()["seal_ready_plan_sha256"]
    )
    assert (
        binding.preview_id_sha256
        == hashlib.sha256(RAW_PREVIEW_ID.encode("utf-8")).hexdigest()
    )
    assert (
        binding.portfolio_id_sha256
        == hashlib.sha256(RAW_PORTFOLIO_ID.encode("utf-8")).hexdigest()
    )
    rendered = repr(binding)
    assert RAW_PREVIEW_ID not in rendered
    assert RAW_PORTFOLIO_ID not in rendered
    assert RAW_CLIENT_ORDER_ID not in rendered
    assert RAW_EXCHANGE_ORDER_ID not in rendered


def test_binding_accepts_actual_redacted_r8_persisted_serialization(
    tmp_path: Path,
) -> None:
    from application.admin_api.futures_order_preview import (
        FUTURES_PREVIEW_R7_TERMINAL_BINDING,
        FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
    )
    from application.admin_api.models import AdminFuturesOrderPreviewResponse
    from tests.unit.test_admin_api_futures_order_preview import (
        _producer,
        _r8_compatible_rest_client,
    )

    producer, store, artifact_path = _producer(
        tmp_path,
        _r8_compatible_rest_client(),
        artifact_type=FUTURES_PREVIEW_R8_ARTIFACT_TYPE,
        predecessor_binding=FUTURES_PREVIEW_R7_TERMINAL_BINDING,
    )
    producer.run()
    serialized = store.read_completed()
    AdminFuturesOrderPreviewResponse.model_validate(serialized)

    binding = Slice3AcceptedR8Binding.from_accepted_evidence(
        artifact_file_sha256=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
        evidence=serialized,
    )

    assert binding.evidence_sha256 == serialized["evidence_sha256"]
    assert binding.claim_sha256 == serialized["claim_sha256"]
    assert binding.seal_ready_plan_sha256 == serialized["seal_ready_plan_sha256"]
    assert binding.preview_id_sha256 == serialized["preview_id_sha256"]
    assert binding.portfolio_id_sha256 == serialized["portfolio_id_sha256"]
    persisted = artifact_path.read_text(encoding="utf-8")
    assert RAW_PREVIEW_ID not in persisted
    assert RAW_PORTFOLIO_ID not in persisted


def test_binding_rejects_raw_private_identifier_fields_even_when_rehashed() -> None:
    def raw_portfolio(evidence: dict[str, Any]) -> None:
        evidence["portfolio_id"] = RAW_PORTFOLIO_ID

    def raw_preview(evidence: dict[str, Any]) -> None:
        evidence["preview_response"]["preview_id"] = RAW_PREVIEW_ID

    def raw_nested_preview(evidence: dict[str, Any]) -> None:
        evidence["seal_ready_plan"]["authoritative_preview"]["preview_id"] = (
            RAW_PREVIEW_ID
        )

    def raw_client_order(evidence: dict[str, Any]) -> None:
        evidence["seal_ready_plan"]["create"] = {"client_order_id": RAW_CLIENT_ORDER_ID}

    def raw_exchange_order(evidence: dict[str, Any]) -> None:
        evidence["seal_ready_plan"]["cancel"] = {
            "exchange_order_id": RAW_EXCHANGE_ORDER_ID
        }

    for mutate in (
        raw_portfolio,
        raw_preview,
        raw_nested_preview,
        raw_client_order,
        raw_exchange_order,
    ):
        evidence = deepcopy(_accepted_r8_evidence())
        mutate(evidence)
        evidence["preview_response_sha256"] = _canonical_sha256(
            evidence["preview_response"]
        )
        evidence["seal_ready_plan_sha256"] = _canonical_sha256(
            evidence["seal_ready_plan"]
        )
        evidence["evidence_sha256"] = _canonical_sha256(
            {key: value for key, value in evidence.items() if key != "evidence_sha256"}
        )

        with pytest.raises(
            Slice3ActivationValidationError,
            match="r8_private_identifier_present",
        ):
            Slice3AcceptedR8Binding.from_accepted_evidence(
                artifact_file_sha256=_hash("a"),
                evidence=evidence,
            )


@pytest.mark.parametrize("field", ["status", "outcome"])
def test_r8_binding_rejects_nonaccepted_terminal(field: str) -> None:
    evidence = _accepted_r8_evidence()
    evidence[field] = "blocked"
    evidence["evidence_sha256"] = _canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )

    with pytest.raises(Slice3ActivationValidationError, match="r8_not_accepted"):
        Slice3AcceptedR8Binding.from_accepted_evidence(
            artifact_file_sha256=_hash("a"),
            evidence=evidence,
        )


def test_r8_binding_rejects_evidence_or_seal_plan_hash_tamper() -> None:
    evidence = _accepted_r8_evidence()
    evidence["non_private_tamper"] = True
    with pytest.raises(
        Slice3ActivationValidationError,
        match="r8_evidence_sha256_invalid",
    ):
        Slice3AcceptedR8Binding.from_accepted_evidence(
            artifact_file_sha256=_hash("a"),
            evidence=evidence,
        )

    evidence = _accepted_r8_evidence()
    evidence["seal_ready_plan_sha256"] = _hash("f")
    evidence["evidence_sha256"] = _canonical_sha256(
        {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    )
    with pytest.raises(
        Slice3ActivationValidationError,
        match="r8_seal_ready_plan_sha256_invalid",
    ):
        Slice3AcceptedR8Binding.from_accepted_evidence(
            artifact_file_sha256=_hash("a"),
            evidence=evidence,
        )


def test_manifest_binds_exact_readiness_policy_and_no_route() -> None:
    evidence = _manifest().sanitized_evidence()

    assert evidence["r8"] == _r8_binding().sanitized_evidence()
    assert evidence["slice3_plan_sha256"] == _hash("2")
    assert (
        evidence["authorization_text_sha256"]
        == hashlib.sha256(RAW_AUTHORIZATION.encode("utf-8")).hexdigest()
    )
    assert evidence["module_sha256"] == {
        "core": _hash("3"),
        "orchestrator": _hash("5"),
        "port": _hash("4"),
    }
    assert evidence["admission_module_sha256"] == _hash("a")
    assert evidence["admission_chain_sha256"] == _hash("b")
    assert evidence["admission_record_sha256"] == _hash("c")
    assert evidence["admission_artifact_file_sha256"] == _hash("d")
    assert evidence["credential_binding"] == SLICE3_FIXED_CREDENTIAL_BINDING
    assert evidence["journal_path"] == str(SLICE3_ACTION_JOURNAL_PATH)
    assert evidence["read_journal_path"] == str(SLICE3_READ_JOURNAL_PATH)
    assert evidence["terminal_evidence_path"] == str(SLICE3_TERMINAL_EVIDENCE_PATH)
    assert evidence["schema_policy_sha256"] == {
        "action_journal_schema": _hash("6"),
        "read_journal_schema": _hash("7"),
        "slice3_live_policy": _hash("9"),
        "terminal_evidence_schema": _hash("8"),
    }
    assert evidence["schema_versions"] == {
        "action_journal": "slice3-action-claim-record-v4",
        "read_journal": "slice3-read-journal-record-v1",
        "slice3_live_policy": "slice3-terminal-roundtrip-policy-v1",
        "terminal_evidence": "slice3-terminal-roundtrip-evidence-v2",
    }
    assert evidence["attempt_limits"] == {
        "cancel": 1,
        "close": 1,
        "create": 1,
        "fallback": 0,
        "preview": 0,
        "redirect": 0,
        "reduce": 0,
        "retry": 0,
    }
    assert evidence["live_adapter_bound"] is True
    assert evidence["route_registered"] is False
    assert evidence["raw_identifier_values_included"] is False
    assert evidence["authorization_text_included"] is False


@pytest.mark.parametrize(
    "field",
    [
        "admission_module_sha256",
        "admission_chain_sha256",
        "admission_record_sha256",
        "admission_artifact_file_sha256",
    ],
)
def test_manifest_requires_exact_admission_hash_bindings(field: str) -> None:
    evidence = _manifest().sanitized_evidence()
    evidence[field] = "not-a-sha256"

    with pytest.raises(Slice3ActivationValidationError, match="admission"):
        Slice3ActivationManifest.from_sanitized_evidence(
            evidence,
            now=NOW,
        )


def test_manifest_requires_short_aware_expiry_and_safe_revisions() -> None:
    assert SLICE3_ACTIVATION_MAX_TTL == timedelta(minutes=15)
    with pytest.raises(Slice3ActivationValidationError, match="expiry_ttl_invalid"):
        _manifest(expires_at=NOW + SLICE3_ACTIVATION_MAX_TTL + timedelta(seconds=1))
    with pytest.raises(Slice3ActivationValidationError, match="expiry_invalid"):
        _manifest(expires_at=NOW)
    with pytest.raises(Slice3ActivationValidationError, match="expires_at_invalid"):
        _manifest(expires_at=datetime(2026, 7, 15, 20, 1))
    with pytest.raises(Slice3ActivationValidationError, match="backend_revision"):
        _manifest(backend_revision="backend\nsecret")
    with pytest.raises(Slice3ActivationValidationError, match="openapi_revision"):
        _manifest(openapi_revision="")


def test_seal_is_canonical_owner_only_fsynced_and_hash_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "activation.json"
    fsync_kinds: list[str] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        fsync_kinds.append(
            "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
        )
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    sealed = Slice3ActivationArtifactStore(path).seal(_manifest(), now=NOW)
    raw = path.read_bytes()
    parsed = json.loads(raw)

    assert raw == _canonical_bytes(parsed) + b"\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert path.stat().st_uid == os.geteuid()
    assert path.stat().st_nlink == 1
    assert "file" in fsync_kinds
    assert "directory" in fsync_kinds
    assert sealed.artifact_file_sha256 == hashlib.sha256(raw).hexdigest()
    assert sealed.manifest_sha256 == _canonical_sha256(parsed["manifest"])
    assert sealed.record_sha256 == parsed["record_sha256"]
    assert sealed.manifest == _manifest()


def test_seal_contains_no_raw_private_identifiers_or_authorization(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activation.json"
    Slice3ActivationArtifactStore(path).seal(_manifest(), now=NOW)
    raw = path.read_text(encoding="utf-8")

    for forbidden in (
        RAW_PREVIEW_ID,
        RAW_PORTFOLIO_ID,
        RAW_CLIENT_ORDER_ID,
        RAW_EXCHANGE_ORDER_ID,
        RAW_AUTHORIZATION,
    ):
        assert forbidden not in raw
    for raw_identifier_key in (
        "preview_id",
        "portfolio_id",
        "client_order_id",
        "exchange_order_id",
    ):
        assert f'"{raw_identifier_key}":' not in raw


def test_read_revalidates_canonical_hashes_metadata_and_expiry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activation.json"
    store = Slice3ActivationArtifactStore(path)
    expected = store.seal(_manifest(), now=NOW)

    assert _read(store, now=NOW + timedelta(minutes=9)) == expected
    with pytest.raises(Slice3ActivationArtifactError, match="expired"):
        _read(store, now=NOW + timedelta(minutes=10))


def test_seal_is_exclusive_and_never_overwrites_existing_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activation.json"
    path.write_bytes(b"operator-owned-sentinel")

    with pytest.raises(Slice3ActivationArtifactError, match="already_exists"):
        Slice3ActivationArtifactStore(path).seal(_manifest(), now=NOW)

    assert path.read_bytes() == b"operator-owned-sentinel"


def test_concurrent_seal_has_exactly_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    store = Slice3ActivationArtifactStore(path)
    barrier = threading.Barrier(8)

    def attempt() -> str:
        barrier.wait()
        try:
            store.seal(_manifest(), now=NOW)
        except Slice3ActivationArtifactError as exc:
            return str(exc)
        return "sealed"

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(lambda _: attempt(), range(8)))

    assert outcomes.count("sealed") == 1
    assert sum("already_exists" in outcome for outcome in outcomes) == 7
    assert _read(store, now=NOW + timedelta(minutes=1)).manifest == _manifest()


def test_relative_traversal_symlink_target_and_symlink_parent_are_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(Slice3ActivationArtifactError, match="path_invalid"):
        Slice3ActivationArtifactStore(Path("runtime_state/activation.json"))
    with pytest.raises(Slice3ActivationArtifactError, match="path_invalid"):
        Slice3ActivationArtifactStore(tmp_path / "subdir" / ".." / "activation.json")

    target = tmp_path / "target"
    target.write_bytes(b"sentinel")
    link = tmp_path / "activation-link.json"
    link.symlink_to(target)
    with pytest.raises(Slice3ActivationArtifactError, match="symlink"):
        Slice3ActivationArtifactStore(link).seal(_manifest(), now=NOW)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(Slice3ActivationArtifactError, match="symlink"):
        Slice3ActivationArtifactStore(linked_parent / "activation.json").seal(
            _manifest(), now=NOW
        )


def test_hardlink_and_mode_metadata_tamper_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    store = Slice3ActivationArtifactStore(path)
    store.seal(_manifest(), now=NOW)
    hardlink = tmp_path / "activation-hardlink.json"
    os.link(path, hardlink)

    with pytest.raises(Slice3ActivationArtifactError, match="link_count"):
        _read(store, now=NOW + timedelta(minutes=1))

    hardlink.unlink()
    os.chmod(path, 0o600)
    with pytest.raises(Slice3ActivationArtifactError, match="mode_invalid"):
        _read(store, now=NOW + timedelta(minutes=1))


def test_payload_hash_and_noncanonical_tamper_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    store = Slice3ActivationArtifactStore(path)
    store.seal(_manifest(), now=NOW)

    _rewrite_record(
        path,
        lambda record: record["manifest"].__setitem__("slice3_plan_sha256", _hash("6")),
        recompute_hashes=False,
    )
    with pytest.raises(Slice3ActivationArtifactError, match="tampered"):
        _read(store, now=NOW + timedelta(minutes=1))

    _rewrite_record(path, lambda _: None, recompute_hashes=True, canonical=False)
    with pytest.raises(Slice3ActivationArtifactError, match="noncanonical"):
        _read(store, now=NOW + timedelta(minutes=1))


def test_nonfinite_json_is_rejected_as_artifact_tamper(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    path.write_text('{"manifest":NaN}\n', encoding="utf-8")
    os.chmod(path, 0o400)

    with pytest.raises(Slice3ActivationArtifactError, match="tampered"):
        _read(
            Slice3ActivationArtifactStore(path),
            now=NOW + timedelta(minutes=1),
        )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("journal_path", "/tmp/redirected-journal.jsonl", "journal_path"),
        (
            "read_journal_path",
            "/tmp/redirected-read-journal.jsonl",
            "read_journal_path",
        ),
        ("terminal_evidence_path", "/tmp/redirected-terminal.json", "terminal"),
        ("live_adapter_bound", False, "live_adapter"),
        ("route_registered", True, "route_registered"),
    ],
)
def test_semantic_tamper_fails_even_with_recomputed_hashes(
    tmp_path: Path,
    field: str,
    value: object,
    reason: str,
) -> None:
    path = tmp_path / "activation.json"
    store = Slice3ActivationArtifactStore(path)
    store.seal(_manifest(), now=NOW)
    _rewrite_record(
        path,
        lambda record: record["manifest"].__setitem__(field, value),
        recompute_hashes=True,
    )

    with pytest.raises(Slice3ActivationArtifactError, match=reason):
        _read(store, now=NOW + timedelta(minutes=1))


def test_unknown_fields_and_attempt_policy_drift_are_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activation.json"
    store = Slice3ActivationArtifactStore(path)
    store.seal(_manifest(), now=NOW)
    _rewrite_record(
        path,
        lambda record: record["manifest"].__setitem__("extra_authority", True),
        recompute_hashes=True,
    )
    with pytest.raises(Slice3ActivationArtifactError, match="fields_invalid"):
        _read(store, now=NOW + timedelta(minutes=1))

    path.unlink()
    store.seal(_manifest(), now=NOW)
    _rewrite_record(
        path,
        lambda record: record["manifest"]["attempt_limits"].__setitem__("retry", 1),
        recompute_hashes=True,
    )
    with pytest.raises(Slice3ActivationArtifactError, match="attempt_limits"):
        _read(store, now=NOW + timedelta(minutes=1))


def test_recomputed_dynamic_binding_tamper_fails_expected_manifest_hash(
    tmp_path: Path,
) -> None:
    path = tmp_path / "activation.json"
    store = Slice3ActivationArtifactStore(path)
    store.seal(_manifest(), now=NOW)
    _rewrite_record(
        path,
        lambda record: record["manifest"]["schema_policy_sha256"].__setitem__(
            "slice3_live_policy", _hash("a")
        ),
        recompute_hashes=True,
    )

    with pytest.raises(
        Slice3ActivationArtifactError,
        match="expected_manifest_sha256",
    ):
        _read(store, now=NOW + timedelta(minutes=1))


def test_production_paths_are_absolute_fixed_repo_paths() -> None:
    for path in (
        SLICE3_ACTIVATION_ARTIFACT_PATH,
        SLICE3_ACTION_JOURNAL_PATH,
        SLICE3_READ_JOURNAL_PATH,
        SLICE3_TERMINAL_EVIDENCE_PATH,
    ):
        assert path.is_absolute()
        assert path.parts[-2] == "runtime_state"
    assert SLICE3_ACTION_JOURNAL_PATH.name == ("futures_slice3_action_claims.jsonl")
    assert SLICE3_READ_JOURNAL_PATH.name == ("futures_slice3_read_journal.jsonl")
    assert SLICE3_TERMINAL_EVIDENCE_PATH.name == (
        "futures_slice3_terminal_evidence.json"
    )
