from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass, field
import hashlib
import inspect
import json

import pytest

from application.admin_api.operator_single_order_reprice_now_models import (
    OperatorSingleOrderRepriceNowIntentRequest,
)
from application.admin_api.operator_single_order_reprice_now_service import (
    OperatorSingleOrderRepriceNowCommandContext,
    OperatorSingleOrderRepriceNowConflict,
    OperatorSingleOrderRepriceNowService,
)


STEALTH_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_ID = "22222222-2222-4222-8222-222222222222"
SOURCE_EVIDENCE_SHA256 = "b" * 64
DEFINITION_SHA256 = "a" * 64


def _definition() -> dict[str, object]:
    return {
        "definition_id": STEALTH_ID,
        "revision": 7,
        "definition_sha256": DEFINITION_SHA256,
    }


def _selection() -> dict[str, object]:
    return {
        "stealth_order_id": STEALTH_ID,
        "source_client_order_id": SOURCE_ID,
        "found": True,
        "eligible": True,
        "diagnostic_code": "operator_reprice_now_source_eligible",
        "definition_revision": 7,
        "definition_sha256": DEFINITION_SHA256,
        "root_client_order_id": STEALTH_ID,
        "source_status": "REVEALED",
        "zero_fill_proven": True,
        "system_owned": True,
        "direct_parent": True,
        "source_evidence_sha256": SOURCE_EVIDENCE_SHA256,
    }


@dataclass
class _Definitions:
    calls: int = 0

    def get_definition(self, stealth_order_id: str):
        self.calls += 1
        assert stealth_order_id == STEALTH_ID
        return _definition()


@dataclass
class _Resolver:
    calls: int = 0

    def resolve(self, **kwargs):
        self.calls += 1
        assert kwargs["stealth_order_id"] == STEALTH_ID
        assert kwargs["source_client_order_id"] == SOURCE_ID
        return _selection()


@dataclass
class _Repository:
    row: dict[str, object] | None = None
    calls: list[str] = field(default_factory=list)
    replay: bool = False

    @staticmethod
    def prepare_lock():
        return nullcontext()

    def get_intent(self, **kwargs):
        self.calls.append("get_intent")
        return deepcopy(self.row)

    def get_intent_replay(self, **kwargs):
        self.calls.append("get_intent_replay")
        if self.replay:
            assert self.row is not None
            return {**deepcopy(self.row), "command_replayed": True}
        return None

    def goal_is_bound(self) -> bool:
        return self.row is not None

    def create_intent(self, **kwargs):
        self.calls.append("create_intent")
        plan = deepcopy(kwargs["intent"])
        self.row = {
            "state": "INTENT_PREPARED",
            "diagnostic_code": "operator_reprice_now_intent_prepared",
            "intent": plan,
            "intent_sha256": plan["intent_sha256"],
            "source_selection": deepcopy(kwargs["source_selection"]),
            "local_cycles_used": 1,
            "latest_cycle_idempotency_key_sha256": "d" * 64,
            "latest_cycle_payload_sha256": "e" * 64,
            "latest_cycle_actor_id_sha256": "f" * 64,
            "latest_cycle_evidence_sha256": "1" * 64,
            "events": [
                {
                    "event_id": (
                        "33333333-3333-4333-8333-333333333333"
                    ),
                    "event_type": "REPRICE_NOW_INTENT_PREPARED",
                    "cycle_number": 1,
                    "diagnostic_code": (
                        "operator_reprice_now_intent_prepared"
                    ),
                    "correlation_id": kwargs["correlation_id"],
                    "evidence_sha256": "c" * 64,
                    "recorded_at": "2026-07-27T00:00:00Z",
                }
            ],
            "correlation_id": kwargs["correlation_id"],
        }
        return deepcopy(self.row)


def _body() -> OperatorSingleOrderRepriceNowIntentRequest:
    return OperatorSingleOrderRepriceNowIntentRequest(
        expected_definition_revision=7,
        expected_definition_sha256=DEFINITION_SHA256,
        expected_source_evidence_sha256=SOURCE_EVIDENCE_SHA256,
        operator_reason="Operator reviewed the exact source.",
        confirm_prepare_reprice_now_intent=True,
    )


def _context() -> OperatorSingleOrderRepriceNowCommandContext:
    return OperatorSingleOrderRepriceNowCommandContext(
        actor_id="operator-1",
        roles=("trader",),
        correlation_id="corr-goal15-1",
        idempotency_key="idem-goal15-1",
        operator_intent="prepare_single_order_reprice_now",
    )


def test_service_has_no_live_execution_authority_dependency() -> None:
    parameters = inspect.signature(
        OperatorSingleOrderRepriceNowService
    ).parameters

    assert "execution_authority_checker" not in parameters


def test_prepare_persists_only_non_market_intent() -> None:
    repository = _Repository()
    service = OperatorSingleOrderRepriceNowService(
        definition_repository=_Definitions(),
        repository=repository,
        source_resolver=_Resolver(),
    )

    result = service.prepare_reprice_now_intent(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
        body=_body(),
        context=_context(),
    )

    assert result.state == "INTENT_PREPARED"
    assert result.market_terms_bound is False
    assert result.cap_policy_bound is False
    assert result.live_authority_terms_complete is False
    assert result.execution_authority_enabled is False
    assert result.source_cancel_call_count == 0
    assert result.replacement_create_call_count == 0
    assert result.latest_cycle_idempotency_key_sha256 == "d" * 64
    assert result.latest_cycle_payload_sha256 == "e" * 64
    assert result.latest_cycle_actor_id_sha256 == "f" * 64
    assert result.latest_cycle_evidence_sha256 == "1" * 64
    assert result.allowed_actions == []
    payload = result.intent.model_dump(mode="json")
    assert not {
        "product_id",
        "portfolio_id",
        "price",
        "size",
        "cap",
    }.intersection(payload)


def test_exact_replay_precedes_mutable_definition_or_source_lookup() -> None:
    repository = _Repository()
    definitions = _Definitions()
    resolver = _Resolver()
    service = OperatorSingleOrderRepriceNowService(
        definition_repository=definitions,
        repository=repository,
        source_resolver=resolver,
    )
    first = service.prepare_reprice_now_intent(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
        body=_body(),
        context=_context(),
    )
    repository.replay = True
    definitions.calls = 0
    resolver.calls = 0

    replay = service.prepare_reprice_now_intent(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
        body=_body(),
        context=_context(),
    )

    assert replay.intent_sha256 == first.intent_sha256
    assert replay.command_replayed is True
    assert definitions.calls == 0
    assert resolver.calls == 0
    assert repository.calls[-1] == "get_intent_replay"


def test_expected_source_evidence_prevents_stale_prepare() -> None:
    body = _body().model_copy(
        update={"expected_source_evidence_sha256": "d" * 64}
    )
    service = OperatorSingleOrderRepriceNowService(
        definition_repository=_Definitions(),
        repository=_Repository(),
        source_resolver=_Resolver(),
    )

    with pytest.raises(OperatorSingleOrderRepriceNowConflict) as exc:
        service.prepare_reprice_now_intent(
            stealth_order_id=STEALTH_ID,
            source_client_order_id=SOURCE_ID,
            body=body,
            context=_context(),
        )

    assert exc.value.code == (
        "operator_reprice_now_source_evidence_conflict"
    )


def test_prepared_get_uses_durable_snapshot_and_prepare_provenance() -> None:
    repository = _Repository()
    definitions = _Definitions()
    resolver = _Resolver()
    service = OperatorSingleOrderRepriceNowService(
        definition_repository=definitions,
        repository=repository,
        source_resolver=resolver,
    )
    service.prepare_reprice_now_intent(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
        body=_body(),
        context=_context(),
    )
    definitions.calls = 0
    resolver.calls = 0

    restored = service.get_single_order_reprice_now(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
        allow_prepare=True,
    )

    assert restored.state == "INTENT_PREPARED"
    assert restored.operator_intent == (
        "prepare_single_order_reprice_now"
    )
    assert restored.command_service_method == (
        "prepare_reprice_now_intent"
    )
    assert restored.execution_authority_enabled is False
    assert definitions.calls == 0
    assert resolver.calls == 0


def test_different_source_get_reports_value_blind_goal_binding() -> None:
    repository = _Repository(
        row={
            "goal_bound_elsewhere": True,
            "local_cycles_used": 1,
        }
    )
    definitions = _Definitions()
    resolver = _Resolver()
    service = OperatorSingleOrderRepriceNowService(
        definition_repository=definitions,
        repository=repository,
        source_resolver=resolver,
    )
    other_source = "44444444-4444-4444-8444-444444444444"

    readback = service.get_single_order_reprice_now(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=other_source,
        allow_prepare=True,
    )

    assert readback.state == "GOAL_ALREADY_BOUND"
    assert readback.diagnostic_code == (
        "operator_reprice_now_goal_already_bound"
    )
    assert readback.source_client_order_id == other_source
    assert readback.allowed_actions == []
    assert readback.intent is None
    assert readback.reserved_successor_client_order_id is None
    assert definitions.calls == 0
    assert resolver.calls == 0
    assert SOURCE_ID not in readback.model_dump_json()


def test_different_source_prepare_fails_before_mutable_lookup() -> None:
    repository = _Repository(
        row={
            "goal_bound_elsewhere": True,
            "local_cycles_used": 1,
        }
    )
    definitions = _Definitions()
    resolver = _Resolver()
    service = OperatorSingleOrderRepriceNowService(
        definition_repository=definitions,
        repository=repository,
        source_resolver=resolver,
    )

    with pytest.raises(OperatorSingleOrderRepriceNowConflict) as exc:
        service.prepare_reprice_now_intent(
            stealth_order_id=STEALTH_ID,
            source_client_order_id=(
                "44444444-4444-4444-8444-444444444444"
            ),
            body=_body(),
            context=_context(),
        )

    assert exc.value.code == "operator_reprice_now_goal_already_bound"
    assert definitions.calls == 0
    assert resolver.calls == 0


def test_prepare_payload_hash_binds_reason_by_hash_not_plaintext() -> None:
    repository = _Repository()
    service = OperatorSingleOrderRepriceNowService(
        definition_repository=_Definitions(),
        repository=repository,
        source_resolver=_Resolver(),
    )
    body = _body()

    service.prepare_reprice_now_intent(
        stealth_order_id=STEALTH_ID,
        source_client_order_id=SOURCE_ID,
        body=body,
        context=_context(),
    )

    create_call = repository.row
    assert create_call is not None
    assert body.operator_reason not in json.dumps(create_call)
    assert hashlib.sha256(body.operator_reason.encode()).hexdigest()
