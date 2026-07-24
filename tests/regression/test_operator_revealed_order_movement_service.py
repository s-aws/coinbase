from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

import pytest

from application.admin_api.operator_revealed_order_movement_service import (
    OperatorRevealedOrderMoveExecuteRequest,
    OperatorRevealedOrderMovePlanRequest,
    OperatorRevealedOrderMovementConflict,
    OperatorRevealedOrderMovementService,
)


STEALTH_ID = "11111111-1111-4111-8111-111111111111"
SOURCE_CLIENT_ORDER_ID = "22222222-2222-4222-8222-222222222222"
REPLACEMENT_CLIENT_ORDER_ID = "33333333-3333-4333-8333-333333333333"
DEFINITION_SHA256 = "a" * 64
PORTFOLIO_SHA256 = "c" * 64
SOURCE_EXCHANGE_SHA256 = "d" * 64


def _definition() -> dict[str, Any]:
    return {
        "definition_id": STEALTH_ID,
        "revision": 4,
        "definition_sha256": DEFINITION_SHA256,
        "portfolio_scope_sha256": PORTFOLIO_SHA256,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": "0.00001",
        "target_movement": "0.01",
        "target_movement_type": "P",
        "lifecycle_state": "DRAFT",
    }


def _plan_payload() -> dict[str, Any]:
    return {
        "stealth_order_id": STEALTH_ID,
        "definition_revision": 4,
        "definition_sha256": DEFINITION_SHA256,
        "portfolio_scope_sha256": PORTFOLIO_SHA256,
        "source_client_order_id": SOURCE_CLIENT_ORDER_ID,
        "source_exchange_order_id_sha256": SOURCE_EXCHANGE_SHA256,
        "replacement_client_order_id": REPLACEMENT_CLIENT_ORDER_ID,
        "root_client_order_id": STEALTH_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": "0.00001",
        "old_limit_price": "50000",
        "requested_limit_price": "50000.127",
        "replacement_limit_price": "50000.12",
        "price_increment": "0.01",
        "target_movement": "0.01",
        "target_movement_type": "P",
        "post_only": True,
        "submitted_notional_usdc": "0.5000012",
        "possible_execution_notional_usdc": "0.5000012",
        "profitability_validated": True,
        "zero_fill_validated": True,
    }


PLAN_SHA256 = hashlib.sha256(
    json.dumps(
        _plan_payload(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


def _plan() -> dict[str, Any]:
    return {**_plan_payload(), "plan_sha256": PLAN_SHA256}


@dataclass
class _DefinitionRepository:
    definition: dict[str, Any] = field(default_factory=_definition)

    def get_definition(self, definition_id: str) -> dict[str, Any]:
        assert definition_id == STEALTH_ID
        return deepcopy(self.definition)


@dataclass
class _Repository:
    row: dict[str, Any] | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def get_goal(self, stealth_order_id: str) -> dict[str, Any] | None:
        assert stealth_order_id == STEALTH_ID
        return deepcopy(self.row)

    def replay_plan(self, **kwargs: Any) -> dict[str, Any] | None:
        for name, call in self.calls:
            if (
                name == "create_plan"
                and call["plan"]["stealth_order_id"]
                == kwargs["stealth_order_id"]
                and call["idempotency_key"] == kwargs["idempotency_key"]
                and call["payload_sha256"] == kwargs["payload_sha256"]
            ):
                replay = deepcopy(self.row)
                assert replay is not None
                replay["command_replayed"] = True
                return replay
        return None

    def replay_execute(self, **kwargs: Any) -> dict[str, Any] | None:
        for name, call in self.calls:
            if (
                name == "begin_execute"
                and call["stealth_order_id"] == kwargs["stealth_order_id"]
                and call["expected_plan_sha256"]
                == kwargs["expected_plan_sha256"]
                and call["correlation_id"] == kwargs["correlation_id"]
                and call["idempotency_key"] == kwargs["idempotency_key"]
                and call["payload_sha256"] == kwargs["payload_sha256"]
            ):
                replay = deepcopy(self.row)
                assert replay is not None
                replay["command_replayed"] = True
                return replay
        return None

    def create_plan(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_plan", deepcopy(kwargs)))
        self.row = {
            **deepcopy(kwargs["plan"]),
            "goal_id": "operator_revealed_order_movement_and_repricing_v1",
            "state": "PLANNED",
            "diagnostic_code": "operator_move_plan_ready",
            "cancel_allowance_consumed": False,
            "create_allowance_consumed": False,
            "cancel_call_count": 0,
            "create_call_count": 0,
            "read_call_count": 0,
            "correlation_id": kwargs["correlation_id"],
            "plan_idempotency_key_sha256": "e" * 64,
            "execute_idempotency_key_sha256": None,
            "command_cycle_status": "COMPLETED",
            "command_cycle_phase": "PLAN",
            "command_cycle_number": 1,
            "command_cycle_correlation_id": kwargs["correlation_id"],
            "command_cycle_evidence_sha256": "f" * 64,
        }
        return deepcopy(self.row)

    def begin_execute(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("begin_execute", deepcopy(kwargs)))
        assert self.row is not None
        self.row["correlation_id"] = kwargs["correlation_id"]
        self.row["execute_idempotency_key_sha256"] = "1" * 64
        self.row["command_cycle_status"] = "IN_FLIGHT"
        self.row["command_cycle_phase"] = "EXECUTE"
        self.row["command_cycle_number"] = 2
        return deepcopy(self.row)

    def claim_read(self, **kwargs: Any) -> None:
        self.calls.append(("claim_read", deepcopy(kwargs)))
        assert self.row is not None
        self.row["read_call_count"] += 1

    def record_read(self, **kwargs: Any) -> None:
        self.calls.append(("record_read", deepcopy(kwargs)))

    def claim_cancel(self, **kwargs: Any) -> None:
        self.calls.append(("claim_cancel", deepcopy(kwargs)))
        assert self.row is not None
        self.row["state"] = "CANCEL_CLAIMED"
        self.row["cancel_allowance_consumed"] = True
        self.row["cancel_call_count"] = 1

    def record_cancel_outcome(
        self, *, stealth_order_id: str, outcome: str, diagnostic_code: str
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "record_cancel_outcome",
                {
                    "stealth_order_id": stealth_order_id,
                    "outcome": outcome,
                    "diagnostic_code": diagnostic_code,
                },
            )
        )
        assert self.row is not None
        self.row["state"] = {
            "CANCELLED": "SOURCE_CANCELLED",
            "FILLED": "SOURCE_FILLED",
            "REJECTED": "CANCEL_REJECTED",
            "UNKNOWN": "CANCEL_UNKNOWN",
        }[outcome]
        self.row["diagnostic_code"] = diagnostic_code
        return deepcopy(self.row)

    def claim_create(self, **kwargs: Any) -> None:
        self.calls.append(("claim_create", deepcopy(kwargs)))
        assert self.row is not None
        assert self.row["state"] == "SOURCE_CANCELLED"
        self.row["state"] = "CREATE_CLAIMED"
        self.row["create_allowance_consumed"] = True
        self.row["create_call_count"] = 1

    def record_create_outcome(
        self,
        *,
        stealth_order_id: str,
        outcome: str,
        diagnostic_code: str,
        replacement_exchange_order_id_sha256: str | None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "record_create_outcome",
                {
                    "stealth_order_id": stealth_order_id,
                    "outcome": outcome,
                    "diagnostic_code": diagnostic_code,
                    "replacement_exchange_order_id_sha256": (
                        replacement_exchange_order_id_sha256
                    ),
                },
            )
        )
        assert self.row is not None
        self.row["state"] = {
            "ACCEPTED": "REPLACED",
            "REJECTED": "CREATE_REJECTED",
            "UNKNOWN": "CREATE_UNKNOWN",
        }[outcome]
        self.row["diagnostic_code"] = diagnostic_code
        self.row["replacement_exchange_order_id_sha256"] = (
            replacement_exchange_order_id_sha256
        )
        return deepcopy(self.row)

    def complete_command(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("complete_command", deepcopy(kwargs)))
        assert self.row is not None
        self.row["command_cycle_status"] = "COMPLETED"
        self.row["command_cycle_evidence_sha256"] = "2" * 64
        return deepcopy(self.row)


@dataclass
class _Runtime:
    plan: dict[str, Any] = field(default_factory=_plan)
    cancel_outcome: str = "CANCELLED"
    create_outcome: str = "ACCEPTED"
    claim_create: bool = True
    calls: list[str] = field(default_factory=list)

    def build_plan(
        self,
        definition: dict[str, Any],
        *,
        requested_limit_price: str,
    ) -> dict[str, Any]:
        self.calls.append("build_plan")
        assert definition["definition_id"] == STEALTH_ID
        assert requested_limit_price == "50000.127"
        return deepcopy(self.plan)

    def revalidate_plan(
        self,
        definition: dict[str, Any],
        plan: dict[str, Any],
    ) -> None:
        self.calls.append("revalidate_plan")
        assert definition["definition_sha256"] == DEFINITION_SHA256
        assert plan["plan_sha256"] == PLAN_SHA256

    def cancel_source(
        self,
        plan: dict[str, Any],
        *,
        before_pre_cancel_read,
        after_pre_cancel_read,
        before_cancel_call,
        before_post_cancel_read,
        after_post_cancel_read,
    ) -> str:
        self.calls.append("cancel_source")
        if self.cancel_outcome == "PRE_CANCEL_UNKNOWN":
            return "PRE_CANCEL_UNKNOWN"
        before_pre_cancel_read()
        after_pre_cancel_read("OPEN")
        if self.cancel_outcome == "FILLED":
            return "FILLED"
        before_cancel_call()
        if self.cancel_outcome == "UNKNOWN":
            return "UNKNOWN"
        before_post_cancel_read()
        after_post_cancel_read(self.cancel_outcome)
        return self.cancel_outcome

    def create_replacement(
        self,
        plan: dict[str, Any],
        *,
        before_create_call,
        before_wallet_read,
        after_wallet_read,
        before_post_create_read,
        after_post_create_read,
    ) -> dict[str, Any]:
        self.calls.append("create_replacement")
        before_wallet_read()
        after_wallet_read("RETURNED")
        if self.claim_create:
            before_create_call()
        if self.create_outcome == "UNKNOWN":
            return {
                "outcome": "UNKNOWN",
                "replacement_exchange_order_id_sha256": None,
            }
        if self.create_outcome == "REJECTED":
            return {
                "outcome": "REJECTED",
                "replacement_exchange_order_id_sha256": None,
            }
        before_post_create_read()
        after_post_create_read("OPEN")
        return {
            "outcome": "ACCEPTED",
            "replacement_exchange_order_id_sha256": "3" * 64,
        }


def _service(
    *,
    repository: _Repository | None = None,
    runtime: _Runtime | None = None,
) -> OperatorRevealedOrderMovementService:
    return OperatorRevealedOrderMovementService(
        definition_repository=_DefinitionRepository(),
        repository=repository or _Repository(),
        runtime=runtime or _Runtime(),
        execution_authority_checker=lambda: True,
    )


def test_prepare_persists_one_quantized_review_plan_without_live_calls() -> None:
    repository = _Repository()
    runtime = _Runtime()
    response = _service(repository=repository, runtime=runtime).prepare_plan(
        stealth_order_id=STEALTH_ID,
        body=OperatorRevealedOrderMovePlanRequest(
            expected_definition_revision=4,
            expected_definition_sha256=DEFINITION_SHA256,
            requested_limit_price="50000.127",
            operator_reason="Review this exact zero-fill replacement price",
            confirm_operator_move_plan=True,
        ),
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
    )

    assert response.state == "PLANNED"
    assert response.plan is not None
    assert response.plan.replacement_limit_price == "50000.12"
    assert response.plan.post_only is True
    assert response.plan.zero_fill_validated is True
    assert response.cancel_call_count == 0
    assert response.create_call_count == 0
    assert runtime.calls == ["build_plan"]
    assert [name for name, _ in repository.calls] == ["create_plan"]


def test_prepare_exact_replay_does_not_rebuild_identity() -> None:
    repository = _Repository()
    runtime = _Runtime()
    service = _service(repository=repository, runtime=runtime)
    request = OperatorRevealedOrderMovePlanRequest(
        expected_definition_revision=4,
        expected_definition_sha256=DEFINITION_SHA256,
        requested_limit_price="50000.127",
        operator_reason="Review this exact zero-fill replacement price",
        confirm_operator_move_plan=True,
    )

    first = service.prepare_plan(
        stealth_order_id=STEALTH_ID,
        body=request,
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
    )
    replay = service.prepare_plan(
        stealth_order_id=STEALTH_ID,
        body=request,
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
    )

    assert first.plan_sha256 == replay.plan_sha256
    assert replay.command_replayed is True
    assert runtime.calls == ["build_plan"]
    assert [name for name, _ in repository.calls].count("create_plan") == 1


def test_execute_never_creates_after_unknown_cancel() -> None:
    repository = _Repository()
    repository.create_plan(
        plan=_plan(),
        actor_id="operator",
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
        payload_sha256="4" * 64,
    )
    runtime = _Runtime(cancel_outcome="UNKNOWN")
    response = _service(repository=repository, runtime=runtime).execute_move(
        stealth_order_id=STEALTH_ID,
        body=OperatorRevealedOrderMoveExecuteRequest(
            expected_plan_sha256=PLAN_SHA256,
            operator_reason="Execute this exact reviewed cancel replacement",
            confirm_operator_cancel_then_replace=True,
        ),
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-execute-correlation",
        idempotency_key="goal7-execute-idempotency",
    )

    assert response.state == "CANCEL_UNKNOWN"
    assert response.cancel_allowance_consumed is True
    assert response.create_allowance_consumed is False
    assert response.cancel_call_count == 1
    assert response.create_call_count == 0
    assert "create_replacement" not in runtime.calls
    assert not any(name == "claim_create" for name, _ in repository.calls)


def test_execute_closes_pre_cancel_unknown_without_consuming_cancel() -> None:
    repository = _Repository()
    repository.create_plan(
        plan=_plan(),
        actor_id="operator",
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
        payload_sha256="4" * 64,
    )
    runtime = _Runtime(cancel_outcome="PRE_CANCEL_UNKNOWN")
    response = _service(
        repository=repository,
        runtime=runtime,
    ).execute_move(
        stealth_order_id=STEALTH_ID,
        body=OperatorRevealedOrderMoveExecuteRequest(
            expected_plan_sha256=PLAN_SHA256,
            operator_reason="Review exact pre-cancel read failure evidence",
            confirm_operator_cancel_then_replace=True,
        ),
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-execute-correlation",
        idempotency_key="goal7-execute-idempotency",
    )

    assert response.state == "CANCEL_UNKNOWN"
    assert response.diagnostic_code == (
        "operator_move_pre_cancel_read_unknown"
    )
    assert response.cancel_allowance_consumed is False
    assert response.cancel_call_count == 0
    assert response.create_call_count == 0
    assert "create_replacement" not in runtime.calls


def test_execute_claims_cancel_before_create_and_reconciles_both_legs() -> None:
    repository = _Repository()
    repository.create_plan(
        plan=_plan(),
        actor_id="operator",
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
        payload_sha256="4" * 64,
    )
    runtime = _Runtime()
    response = _service(repository=repository, runtime=runtime).execute_move(
        stealth_order_id=STEALTH_ID,
        body=OperatorRevealedOrderMoveExecuteRequest(
            expected_plan_sha256=PLAN_SHA256,
            operator_reason="Execute this exact reviewed cancel replacement",
            confirm_operator_cancel_then_replace=True,
        ),
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-execute-correlation",
        idempotency_key="goal7-execute-idempotency",
    )

    assert response.state == "REPLACED"
    assert response.cancel_call_count == 1
    assert response.create_call_count == 1
    assert response.read_call_count == 4
    assert response.replacement_exchange_order_id_sha256 == "3" * 64
    names = [name for name, _ in repository.calls]
    assert names.index("claim_cancel") < names.index("claim_create")
    assert names.index("record_cancel_outcome") < names.index("claim_create")
    assert runtime.calls == [
        "revalidate_plan",
        "cancel_source",
        "create_replacement",
    ]


def test_execute_exact_terminal_replay_performs_no_more_runtime_work() -> None:
    repository = _Repository()
    repository.create_plan(
        plan=_plan(),
        actor_id="operator",
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
        payload_sha256="4" * 64,
    )
    runtime = _Runtime()
    service = _service(repository=repository, runtime=runtime)
    request = OperatorRevealedOrderMoveExecuteRequest(
        expected_plan_sha256=PLAN_SHA256,
        operator_reason="Execute this exact reviewed cancel replacement",
        confirm_operator_cancel_then_replace=True,
    )
    first = service.execute_move(
        stealth_order_id=STEALTH_ID,
        body=request,
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-execute-correlation",
        idempotency_key="goal7-execute-idempotency",
    )
    calls = list(runtime.calls)
    replay = service.execute_move(
        stealth_order_id=STEALTH_ID,
        body=request,
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-execute-correlation",
        idempotency_key="goal7-execute-idempotency",
    )

    assert first.state == replay.state == "REPLACED"
    assert replay.command_replayed is True
    assert runtime.calls == calls


def test_execute_closes_local_create_rejection_without_consuming_create() -> None:
    repository = _Repository()
    repository.create_plan(
        plan=_plan(),
        actor_id="operator",
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
        payload_sha256="4" * 64,
    )
    runtime = _Runtime(
        create_outcome="REJECTED",
        claim_create=False,
    )
    response = _service(
        repository=repository,
        runtime=runtime,
    ).execute_move(
        stealth_order_id=STEALTH_ID,
        body=OperatorRevealedOrderMoveExecuteRequest(
            expected_plan_sha256=PLAN_SHA256,
            operator_reason="Review exact local create rejection evidence",
            confirm_operator_cancel_then_replace=True,
        ),
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-execute-correlation",
        idempotency_key="goal7-execute-idempotency",
    )

    assert response.state == "CREATE_REJECTED"
    assert response.cancel_call_count == 1
    assert response.create_allowance_consumed is False
    assert response.create_call_count == 0


def test_execute_resumes_confirmed_cancel_without_second_cancel() -> None:
    repository = _Repository()
    repository.create_plan(
        plan=_plan(),
        actor_id="operator",
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
        payload_sha256="4" * 64,
    )
    assert repository.row is not None
    repository.row["state"] = "SOURCE_CANCELLED"
    repository.row["diagnostic_code"] = "operator_move_source_cancelled"
    repository.row["cancel_allowance_consumed"] = True
    repository.row["cancel_call_count"] = 1
    runtime = _Runtime()

    response = _service(
        repository=repository,
        runtime=runtime,
    ).execute_move(
        stealth_order_id=STEALTH_ID,
        body=OperatorRevealedOrderMoveExecuteRequest(
            expected_plan_sha256=PLAN_SHA256,
            operator_reason="Resume exact replacement after confirmed cancel",
            confirm_operator_cancel_then_replace=True,
        ),
        actor_id="operator",
        roles=["admin", "trader"],
        correlation_id="goal7-resume-correlation",
        idempotency_key="goal7-resume-idempotency",
    )

    assert response.state == "REPLACED"
    assert response.cancel_call_count == 1
    assert response.create_call_count == 1
    assert "cancel_source" not in runtime.calls
    assert runtime.calls == ["revalidate_plan", "create_replacement"]
    assert not any(name == "claim_cancel" for name, _ in repository.calls)


def test_execute_rejects_plan_hash_drift_before_any_call_claim() -> None:
    repository = _Repository()
    repository.create_plan(
        plan=_plan(),
        actor_id="operator",
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
        payload_sha256="4" * 64,
    )
    runtime = _Runtime()

    with pytest.raises(
        OperatorRevealedOrderMovementConflict,
        match="operator_move_plan_binding_conflict",
    ):
        _service(repository=repository, runtime=runtime).execute_move(
            stealth_order_id=STEALTH_ID,
            body=OperatorRevealedOrderMoveExecuteRequest(
                expected_plan_sha256="9" * 64,
                operator_reason="Execute this exact reviewed cancel replacement",
                confirm_operator_cancel_then_replace=True,
            ),
            actor_id="operator",
            roles=["admin", "trader"],
            correlation_id="goal7-execute-correlation",
            idempotency_key="goal7-execute-idempotency",
        )

    assert runtime.calls == []
    assert not any(
        name in {"claim_read", "claim_cancel", "claim_create"}
        for name, _ in repository.calls
    )


def test_in_flight_cycle_exposes_no_operator_replay_action() -> None:
    repository = _Repository()
    repository.create_plan(
        plan=_plan(),
        actor_id="operator",
        correlation_id="goal7-plan-correlation",
        idempotency_key="goal7-plan-idempotency",
        payload_sha256="4" * 64,
    )
    assert repository.row is not None
    repository.row["command_cycle_status"] = "IN_FLIGHT"
    repository.row["command_cycle_phase"] = "EXECUTE"

    response = _service(repository=repository).get_execution(
        STEALTH_ID,
        roles=["admin", "trader"],
    )

    assert response.allowed_actions == []
