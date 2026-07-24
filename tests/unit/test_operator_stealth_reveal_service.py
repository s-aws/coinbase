from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from application.admin_api.operator_stealth_reveal_service import (
    OperatorStealthCloseoutRequest,
    OperatorStealthResumeAcceptedCreateRequest,
    OperatorStealthRevealRequest,
    OperatorStealthRevealService,
)


DEFINITION_ID = "11111111-1111-4111-8111-111111111111"
PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"


def _frozen_plan(*, base_size: str = "0.00001") -> dict[str, Any]:
    return {
        "product_id": "BTC-USDC",
        "side": "BUY",
        "base_size": base_size,
        "limit_price": "59999.99",
        "configured_limit_price": "60000",
        "submitted_limit_price": "59999.99",
        "reveal_pricing_policy": "top_of_book",
        "reveal_price_source": "best_bid",
        "fallback_used": False,
        "market_source": "ticker",
        "market_bid": "59999.99",
        "market_ask": "60000.01",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "target_movement_source": "operator_definition",
        "post_only": True,
    }


def _frozen_plan_sha(*, base_size: str = "0.00001") -> str:
    return hashlib.sha256(
        json.dumps(
            _frozen_plan(base_size=base_size),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _definition() -> dict[str, Any]:
    return {
        "definition_id": DEFINITION_ID,
        "portfolio_scope_sha256": hashlib.sha256(
            PORTFOLIO_ID.encode()
        ).hexdigest(),
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": "0.00001",
        "limit_price": "60000",
        "reveal_condition_type": "TIME_DELAY",
        "reveal_price_threshold": None,
        "reveal_direction": None,
        "hold_duration_seconds": 0,
        "delay_seconds": 0,
        "reveal_pricing_policy": "TOP_OF_BOOK",
        "sizing_mode": "FIXED",
        "follow_up_reveal_direction": "OPPOSITE",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "max_order_replacements": 0,
        "allow_partial_fills": False,
        "post_only": True,
        "lifecycle_state": "DRAFT",
        "revision": 2,
        "definition_sha256": "b" * 64,
        "runtime_status": None,
        "runtime_classification": "UNMATERIALIZED",
    }


@dataclass
class _DefinitionRepository:
    definition: dict[str, Any] = field(default_factory=_definition)

    def get_definition(self, definition_id: str) -> dict[str, Any]:
        assert definition_id == DEFINITION_ID
        return dict(self.definition)


@dataclass
class _RevealRepository:
    row: dict[str, Any] | None = None
    calls: list[str] = field(default_factory=list)
    read_claims: dict[tuple[str, str], dict[str, Any]] = field(
        default_factory=dict
    )
    command_cycles: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _base(self) -> dict[str, Any]:
        return {
            "goal_id": "operator_stealth_reveal_and_exact_closeout_v1",
            "state": "MATERIALIZING",
            "definition_id": DEFINITION_ID,
            "definition_revision": 2,
            "definition_sha256": "b" * 64,
            "portfolio_scope_sha256": hashlib.sha256(
                PORTFOLIO_ID.encode()
            ).hexdigest(),
            "client_order_id": DEFINITION_ID,
            "plan": None,
            "plan_sha256": None,
            "prepreview_admission_sha256": None,
            "preview_claim_id":
                "33333333-3333-4333-8333-333333333333",
            "preview_allowance_consumed": False,
            "create_allowance_consumed": False,
            "cancel_allowance_consumed": False,
            "preview_call_count": 0,
            "create_call_count": 0,
            "cancel_call_count": 0,
            "read_call_count": 0,
            "preview_outcome": None,
            "create_outcome": None,
            "cancel_outcome": None,
            "exchange_order_id_sha256": None,
            "diagnostic_code": "operator_stealth_materializing",
            "correlation_id": "goal6-correlation",
            "command_idempotency_key_sha256": hashlib.sha256(
                b"goal6-reveal-key"
            ).hexdigest(),
            "command_identity_bound": False,
            "command_cycle_status": None,
            "command_cycle_phase": None,
            "command_cycle_number": None,
            "command_cycle_correlation_id": None,
            "command_cycle_idempotency_key_sha256": None,
            "command_cycle_payload_sha256": None,
            "command_cycle_terminal_goal_state": None,
            "command_cycle_terminal_diagnostic_code": None,
            "command_cycle_preview_call_count": None,
            "command_cycle_create_call_count": None,
            "command_cycle_cancel_call_count": None,
            "command_cycle_read_call_count": None,
            "command_cycle_evidence_sha256": None,
            "created_at": "2026-07-24T00:00:00+00:00",
            "updated_at": "2026-07-24T00:00:00+00:00",
            "command_replayed": False,
        }

    def get_goal(self, definition_id: str | None = None):
        if definition_id is not None:
            assert definition_id == DEFINITION_ID
        return dict(self.row) if self.row else None

    def begin_materialization(self, **kwargs: Any):
        self.calls.append("begin")
        if self.row is not None:
            return {**self.row, "command_replayed": True}
        self.row = self._base()
        self.row["correlation_id"] = kwargs["correlation_id"]
        return dict(self.row)

    def record_materialized(self, definition_id: str):
        self.calls.append("materialized")
        assert definition_id == DEFINITION_ID
        self.row["state"] = "MATERIALIZED"
        self.row["diagnostic_code"] = "operator_stealth_materialized"
        return dict(self.row)

    def begin_command_cycle(
        self,
        definition_id: str,
        *,
        phase: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ):
        assert definition_id == DEFINITION_ID
        existing = self.command_cycles.get(idempotency_key)
        if existing is not None:
            assert existing["phase"] == phase
            assert existing["correlation_id"] == correlation_id
            assert existing["payload_sha256"] == payload_sha256
            return {
                "cycle_number": list(self.command_cycles).index(
                    idempotency_key
                )
                + 1,
                "command_replayed": True,
            }
        self.command_cycles[idempotency_key] = {
            "phase": phase,
            "correlation_id": correlation_id,
            "payload_sha256": payload_sha256,
            "completion_status": "IN_FLIGHT",
        }
        self.calls.append(f"begin_{phase.lower()}_cycle")
        return {
            "cycle_number": len(self.command_cycles),
            "command_replayed": False,
        }

    def record_command_completion(
        self,
        definition_id: str,
        *,
        phase: str,
        correlation_id: str,
        idempotency_key: str,
    ):
        assert definition_id == DEFINITION_ID
        cycle = self.command_cycles[idempotency_key]
        assert cycle["phase"] == phase
        assert cycle["correlation_id"] == correlation_id
        evidence = {
            "goal_id": self.row["goal_id"],
            "cycle_number": list(self.command_cycles).index(idempotency_key)
            + 1,
            "phase": phase,
            "correlation_id": correlation_id,
            "idempotency_key_sha256": hashlib.sha256(
                idempotency_key.encode()
            ).hexdigest(),
            "payload_sha256": cycle["payload_sha256"],
            "terminal_goal_state": self.row["state"],
            "terminal_diagnostic_code": self.row["diagnostic_code"],
            "preview_call_count": self.row["preview_call_count"],
            "create_call_count": self.row["create_call_count"],
            "cancel_call_count": self.row["cancel_call_count"],
            "read_call_count": self.row["read_call_count"],
        }
        cycle["completion_status"] = "COMPLETED"
        self.row.update(
            command_cycle_status="COMPLETED",
            command_cycle_phase=phase,
            command_cycle_number=evidence["cycle_number"],
            command_cycle_correlation_id=correlation_id,
            command_cycle_idempotency_key_sha256=evidence[
                "idempotency_key_sha256"
            ],
            command_cycle_payload_sha256=cycle["payload_sha256"],
            command_cycle_terminal_goal_state=self.row["state"],
            command_cycle_terminal_diagnostic_code=self.row[
                "diagnostic_code"
            ],
            command_cycle_preview_call_count=self.row[
                "preview_call_count"
            ],
            command_cycle_create_call_count=self.row["create_call_count"],
            command_cycle_cancel_call_count=self.row["cancel_call_count"],
            command_cycle_read_call_count=self.row["read_call_count"],
            command_cycle_evidence_sha256=hashlib.sha256(
                json.dumps(
                    evidence,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
        )
        self.calls.append(f"complete_{phase.lower()}_cycle")
        return dict(self.row)

    def record_condition_not_ready(self, definition_id: str):
        assert definition_id == DEFINITION_ID
        self.row["diagnostic_code"] = (
            "operator_stealth_condition_not_ready"
        )
        return dict(self.row)

    def claim_preview(self, definition_id: str, **kwargs: Any):
        self.calls.append("claim_preview")
        assert definition_id == DEFINITION_ID
        self.row.update(
            state="PREVIEW_CLAIMED",
            plan=kwargs["plan"],
            plan_sha256=kwargs["plan_sha256"],
            preview_allowance_consumed=True,
            preview_call_count=1,
        )
        return dict(self.row)

    def record_prepreview_admission(
        self,
        definition_id: str,
        *,
        plan: dict[str, Any],
        plan_sha256: str,
        admission_sha256: str,
    ):
        assert definition_id == DEFINITION_ID
        self.row.update(
            plan=plan,
            plan_sha256=plan_sha256,
            prepreview_admission_sha256=admission_sha256,
        )
        return dict(self.row)

    def record_prepreview_cap_blocked(
        self,
        definition_id: str,
        *,
        plan: dict[str, Any],
        plan_sha256: str,
    ):
        assert definition_id == DEFINITION_ID
        self.row.update(
            plan=plan,
            plan_sha256=plan_sha256,
            prepreview_admission_sha256=None,
            diagnostic_code="operator_stealth_prepreview_cap_blocked",
        )
        return dict(self.row)

    def record_preview_preflight_rejection(self, definition_id: str):
        assert definition_id == DEFINITION_ID
        self.row.update(
            state="PREVIEW_REJECTED",
            preview_outcome="REJECTED",
            diagnostic_code="operator_stealth_preview_preflight_rejected",
        )
        return dict(self.row)

    def record_preview_outcome(
        self,
        definition_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
    ):
        self.calls.append(f"preview_{outcome.lower()}")
        self.row.update(
            state=f"PREVIEW_{outcome}",
            preview_outcome=outcome,
            diagnostic_code=diagnostic_code,
        )
        return dict(self.row)

    def claim_create(self, definition_id: str):
        self.calls.append("claim_create")
        self.row.update(
            state="CREATE_CLAIMED",
            create_allowance_consumed=True,
            create_call_count=1,
        )
        return dict(self.row)

    def record_create_preflight_rejection(self, definition_id: str):
        assert definition_id == DEFINITION_ID
        self.row.update(
            state="CREATE_REJECTED",
            create_outcome="REJECTED",
            diagnostic_code="operator_stealth_create_preflight_rejected",
        )
        return dict(self.row)

    def record_create_cap_rejection(self, definition_id: str):
        assert definition_id == DEFINITION_ID
        self.row.update(
            state="CREATE_REJECTED",
            create_outcome="REJECTED",
            diagnostic_code="operator_stealth_create_cap_blocked",
        )
        return dict(self.row)

    def record_create_outcome(
        self,
        definition_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
        exchange_order_id_sha256: str | None = None,
    ):
        self.calls.append(f"create_{outcome.lower()}")
        self.row.update(
            state=(
                "REVEALED"
                if outcome == "ACCEPTED"
                else f"CREATE_{outcome}"
            ),
            create_outcome=outcome,
            diagnostic_code=diagnostic_code,
            exchange_order_id_sha256=exchange_order_id_sha256,
        )
        return dict(self.row)

    def claim_cancel(self, definition_id: str):
        self.calls.append("claim_cancel")
        self.row.update(
            state="CANCEL_CLAIMED",
            cancel_allowance_consumed=True,
            cancel_call_count=1,
        )
        return dict(self.row)

    def record_cancel_preflight_rejection(self, definition_id: str):
        assert definition_id == DEFINITION_ID
        self.row["diagnostic_code"] = (
            "operator_stealth_cancel_preflight_rejected"
        )
        return dict(self.row)

    def record_cancel_outcome(
        self,
        definition_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
    ):
        self.calls.append(f"cancel_{outcome.lower()}")
        self.row.update(
            state=outcome if outcome != "UNKNOWN" else "CANCEL_UNKNOWN",
            cancel_outcome=outcome,
            diagnostic_code=diagnostic_code,
        )
        return dict(self.row)

    def record_terminal_without_cancel(
        self,
        definition_id: str,
        *,
        outcome: str,
        diagnostic_code: str,
    ):
        self.calls.append(f"terminal_{outcome.lower()}")
        self.row.update(
            state=outcome,
            cancel_outcome=outcome,
            diagnostic_code=diagnostic_code,
        )
        return dict(self.row)

    def claim_read_call(
        self,
        definition_id: str,
        *,
        category: str,
        correlation_id: str,
        wire_call: bool = True,
    ):
        assert definition_id == DEFINITION_ID
        key = (category, correlation_id)
        existing = self.read_claims.get(key)
        if existing is not None:
            return {**existing, "invoke_required": False}
        if wire_call:
            self.row["read_call_count"] += 1
        claimed = {
            "category": category,
            "correlation_id": correlation_id,
            "call_state": "STARTED",
            "result_code": None,
            "authoritative_status": None,
            "wire_call_count": 1 if wire_call else 0,
            "invoke_required": True,
        }
        self.read_claims[key] = claimed
        self.calls.append(f"claim_read_{category.lower()}")
        return dict(claimed)

    def record_read_call_outcome(
        self,
        definition_id: str,
        *,
        category: str,
        correlation_id: str,
        result_code: str,
        authoritative_status: str | None = None,
    ):
        assert definition_id == DEFINITION_ID
        key = (category, correlation_id)
        self.read_claims[key].update(
            call_state=(
                "UNKNOWN" if result_code == "UNKNOWN" else "RETURNED"
            ),
            result_code=result_code,
            authoritative_status=authoritative_status,
        )
        self.calls.append(f"read_{category.lower()}_{result_code.lower()}")
        return {**self.read_claims[key], "invoke_required": False}

    def begin_closeout(
        self,
        definition_id: str,
        *,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        payload_sha256: str,
    ):
        assert definition_id == DEFINITION_ID
        self.calls.append("begin_closeout")
        existing_key = self.row.get("cancel_idempotency_key")
        if existing_key is not None:
            assert existing_key == idempotency_key
            assert self.row["cancel_payload_sha256"] == payload_sha256
            return {**self.row, "command_replayed": True}
        self.row.update(
            cancel_idempotency_key=idempotency_key,
            cancel_payload_sha256=payload_sha256,
            correlation_id=correlation_id,
        )
        return dict(self.row)


@dataclass
class _Runtime:
    preview_outcome: str = "ACCEPTED"
    placement_outcome: str = "ACCEPTED"
    readback_statuses: list[str] = field(
        default_factory=lambda: ["OPEN", "CANCELLED"]
    )
    calls: list[str] = field(default_factory=list)
    condition_ready_results: list[bool] = field(
        default_factory=lambda: [True]
    )

    def condition_ready(self, definition: dict[str, Any]) -> bool:
        self.calls.append("condition")
        return self.condition_ready_results.pop(0)

    def materialize(
        self,
        definition: dict[str, Any],
        *,
        portfolio_id: str,
        correlation_id: str,
        audit_id: str,
    ) -> None:
        self.calls.append("materialize")

    def portfolio_binding_ready(
        self,
        *,
        expected_portfolio_id: str,
        expected_portfolio_label: str,
        before_permissions_call,
        before_catalog_call,
    ) -> dict[str, bool]:
        assert expected_portfolio_id == PORTFOLIO_ID
        assert expected_portfolio_label == "Test"
        before_permissions_call()
        self.calls.append("portfolio_permissions")
        before_catalog_call()
        self.calls.append("portfolio_catalog")
        return {
            "ready": True,
            "permissions_returned": True,
            "catalog_returned": True,
        }

    def build_plan(self, definition: dict[str, Any]):
        self.calls.append("build_plan")
        return SimpleNamespace(
            configured_limit_price=60000.0,
            submitted_limit_price=59999.99,
            reveal_pricing_policy="top_of_book",
            reveal_price_source="best_bid",
            fallback_used=False,
            market_source="ticker",
            market_bid=59999.99,
            market_ask=60000.01,
            target_movement=0.005,
            target_movement_type="P",
            target_movement_source="operator_definition",
            post_only=True,
        )

    def prepreview_admission(
        self,
        definition: dict[str, Any],
        *,
        plan: dict[str, Any],
        plan_sha256: str,
        portfolio_id: str,
        before_wallet_call,
    ) -> str:
        assert portfolio_id == PORTFOLIO_ID
        before_wallet_call()
        self.calls.append("wallet_admission")
        return "c" * 64

    def preview(
        self,
        plan: dict[str, Any],
        *,
        before_call,
    ) -> str:
        self.calls.append("preview")
        assert plan == _frozen_plan()
        before_call()
        return self.preview_outcome

    def reveal(
        self,
        definition: dict[str, Any],
        *,
        plan: dict[str, Any],
        plan_sha256: str,
        preview_claim_id: str,
        portfolio_id: str,
        prepreview_admission_sha256: str,
        before_create_call,
    ) -> dict[str, Any]:
        self.calls.append("reveal")
        assert prepreview_admission_sha256 == "c" * 64
        before_create_call()
        return {
            "outcome": self.placement_outcome,
            "placement_attempted": True,
            "client_order_id": DEFINITION_ID,
            "exchange_order_id": (
                "withheld-exchange-id"
                if self.placement_outcome == "ACCEPTED"
                else None
            ),
            "diagnostic_code": (
                "operator_stealth_create_accepted"
                if self.placement_outcome == "ACCEPTED"
                else "operator_stealth_create_unknown"
            ),
        }

    def exact_readback(
        self,
        *,
        client_order_id: str,
        product_id: str,
        expected_exchange_order_id_sha256: str,
        before_call,
    ) -> dict[str, Any]:
        before_call()
        self.calls.append("readback")
        exchange_order_id = "withheld-exchange-id"
        assert product_id == "BTC-USDC"
        assert expected_exchange_order_id_sha256 == hashlib.sha256(
            exchange_order_id.encode()
        ).hexdigest()
        return {
            "authoritative": True,
            "client_order_id": client_order_id,
            "exchange_order_id": exchange_order_id,
            "exchange_order_id_sha256": expected_exchange_order_id_sha256,
            "portfolio_matches": True,
            "status": self.readback_statuses.pop(0),
        }

    def cancel_exchange_only(
        self,
        *,
        client_order_id: str,
        verified_exchange_order_id: str,
        before_cancel_call,
    ) -> bool:
        assert verified_exchange_order_id == "withheld-exchange-id"
        before_cancel_call()
        self.calls.append("cancel")
        return True

    def reconcile_terminal(
        self,
        *,
        client_order_id: str,
        status: str,
    ) -> None:
        self.calls.append(f"reconcile_{status.lower()}")


def _service(
    runtime: _Runtime,
    repository: _RevealRepository | None = None,
) -> tuple[OperatorStealthRevealService, _RevealRepository]:
    ledger = repository or _RevealRepository()

    service = OperatorStealthRevealService(
        definition_repository=_DefinitionRepository(),
        reveal_repository=ledger,
        runtime=runtime,
        configured_portfolio_id=PORTFOLIO_ID,
        execution_authority_checker=lambda: True,
    )
    return service, ledger


def _request() -> OperatorStealthRevealRequest:
    return OperatorStealthRevealRequest(
        expected_revision=2,
        expected_definition_sha256="b" * 64,
        operator_reason="reveal this exact reviewed definition",
        confirm_operator_stealth_reveal=True,
    )


def test_rejected_preview_consumes_preview_but_never_create() -> None:
    runtime = _Runtime(preview_outcome="REJECTED")
    service, repository = _service(runtime)

    response = service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-correlation",
        idempotency_key="goal6-reveal-key",
    )

    assert response.state == "PREVIEW_REJECTED"
    assert response.preview_allowance_consumed is True
    assert response.create_allowance_consumed is False
    assert runtime.calls == [
        "portfolio_permissions",
        "portfolio_catalog",
        "materialize",
        "condition",
        "build_plan",
        "wallet_admission",
        "preview",
    ]
    assert "claim_create" not in repository.calls


def test_accepted_preview_submits_one_identical_manager_create() -> None:
    runtime = _Runtime()
    service, _ = _service(runtime)

    response = service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-correlation",
        idempotency_key="goal6-reveal-key",
    )

    assert response.state == "REVEALED"
    assert response.client_order_id == DEFINITION_ID
    assert response.preview_call_count == 1
    assert response.create_call_count == 1
    assert response.cancel_call_count == 0
    assert response.read_call_count == 3
    assert response.exchange_order_id_withheld is True
    assert response.exchange_order_id_sha256 == hashlib.sha256(
        b"withheld-exchange-id"
    ).hexdigest()
    assert runtime.calls.count("preview") == 1
    assert runtime.calls.count("reveal") == 1


def test_plan_above_possible_execution_cap_stops_before_wallet_and_preview() -> None:
    runtime = _Runtime()
    service, repository = _service(runtime)
    service.definition_repository.definition["total_size"] = "0.0001"

    response = service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-cap-correlation",
        idempotency_key="goal6-cap-key",
    )

    assert response.state == "MATERIALIZED"
    assert response.diagnostic_code == (
        "operator_stealth_prepreview_cap_blocked"
    )
    assert response.submitted_notional_usdc == "5.999999"
    assert response.preview_allowance_consumed is False
    assert response.create_allowance_consumed is False
    assert response.cancel_allowance_consumed is False
    assert response.allowed_actions == []
    assert runtime.calls == [
        "portfolio_permissions",
        "portfolio_catalog",
        "materialize",
        "condition",
        "build_plan",
    ]
    assert "claim_preview" not in repository.calls
    assert "claim_create" not in repository.calls


def test_preview_accepted_restart_exposes_and_executes_one_resume_action() -> None:
    runtime = _Runtime()
    service, repository = _service(runtime)
    service.reveal_repository.row = {
        **repository._base(),
        "state": "PREVIEW_ACCEPTED",
        "plan": _frozen_plan(),
        "plan_sha256": _frozen_plan_sha(),
        "prepreview_admission_sha256": "c" * 64,
        "preview_allowance_consumed": True,
        "preview_call_count": 1,
        "preview_outcome": "ACCEPTED",
        "diagnostic_code": "operator_stealth_preview_accepted",
    }

    readback = service.get_execution(DEFINITION_ID, roles=["trader"])
    assert readback.allowed_actions == ["RESUME_ACCEPTED_CREATE"]
    resumed = service.resume_accepted_create(
        definition_id=DEFINITION_ID,
        body=OperatorStealthResumeAcceptedCreateRequest(
            expected_plan_sha256=readback.plan_sha256,
            operator_reason="resume the accepted exact preview create",
            confirm_operator_stealth_resume_create=True,
        ),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-resume-correlation",
        idempotency_key="goal6-resume-key",
    )

    assert resumed.state == "REVEALED"
    assert resumed.preview_call_count == 1
    assert resumed.create_call_count == 1
    assert runtime.calls == ["reveal"]
    assert repository.command_cycles["goal6-resume-key"]["phase"] == (
        "RESUME_CREATE"
    )


def test_readback_actions_require_mutation_role_and_complete_policy() -> None:
    runtime = _Runtime()
    service, repository = _service(runtime)

    assert service.get_execution(
        DEFINITION_ID,
        roles=["viewer"],
    ).allowed_actions == []
    assert service.get_execution(
        DEFINITION_ID,
        roles=["trader"],
    ).allowed_actions == ["REVEAL"]

    service.definition_repository.definition["max_order_replacements"] = 1
    assert service.get_execution(
        DEFINITION_ID,
        roles=["trader"],
    ).allowed_actions == []
    service.definition_repository.definition["max_order_replacements"] = 0
    service.definition_repository.definition["allow_partial_fills"] = True
    assert service.get_execution(
        DEFINITION_ID,
        roles=["trader"],
    ).allowed_actions == []
    service.definition_repository.definition["allow_partial_fills"] = False
    service.definition_repository.definition["sizing_mode"] = "ADAPTIVE"
    assert service.get_execution(
        DEFINITION_ID,
        roles=["trader"],
    ).allowed_actions == []


def test_terminal_reveal_replay_makes_no_runtime_or_exchange_call() -> None:
    runtime = _Runtime()
    service, repository = _service(runtime)
    first = service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-correlation",
        idempotency_key="goal6-reveal-key",
    )
    runtime.calls.clear()

    replay = service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-correlation",
        idempotency_key="goal6-reveal-key",
    )

    assert replay.state == first.state
    assert runtime.calls == []
    assert repository.row["preview_call_count"] == 1
    assert repository.row["create_call_count"] == 1


def test_exact_closeout_cancels_once_then_requires_terminal_readback() -> None:
    runtime = _Runtime()
    service, _ = _service(runtime)
    service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-correlation",
        idempotency_key="goal6-reveal-key",
    )
    runtime.calls.clear()

    response = service.closeout(
        definition_id=DEFINITION_ID,
        body=OperatorStealthCloseoutRequest(
            expected_plan_sha256=service.get_execution(
                DEFINITION_ID,
                roles=["trader"],
            ).plan_sha256,
            operator_reason="safely close this exact placement",
            confirm_operator_stealth_closeout=True,
        ),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-closeout-correlation",
        idempotency_key="goal6-closeout-key",
    )

    assert response.state == "CANCELLED"
    assert response.cancel_call_count == 1
    assert response.read_call_count == 7
    assert runtime.calls == [
        "portfolio_permissions",
        "portfolio_catalog",
        "readback",
        "cancel",
        "readback",
        "reconcile_cancelled",
    ]


def test_nonterminal_post_cancel_readback_completes_unknown_cycle_for_restart(
) -> None:
    runtime = _Runtime(readback_statuses=["OPEN", "PENDING"])
    service, repository = _service(runtime)
    service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-correlation",
        idempotency_key="goal6-reveal-key",
    )

    response = service.closeout(
        definition_id=DEFINITION_ID,
        body=OperatorStealthCloseoutRequest(
            expected_plan_sha256=service.get_execution(
                DEFINITION_ID,
                roles=["trader"],
            ).plan_sha256,
            operator_reason="safely close this exact placement",
            confirm_operator_stealth_closeout=True,
        ),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-closeout-correlation",
        idempotency_key="goal6-closeout-key",
    )

    assert response.state == "CANCEL_UNKNOWN"
    assert response.diagnostic_code == "operator_stealth_cancel_unknown"
    assert response.cancel_call_count == 1
    assert response.command_cycle_status == "COMPLETED"
    assert response.command_cycle_phase == "CLOSEOUT"
    assert response.command_cycle_terminal_goal_state == "CANCEL_UNKNOWN"
    assert response.command_cycle_cancel_call_count == 1
    assert response.command_cycle_evidence_sha256

    restarted = OperatorStealthRevealService(
        definition_repository=service.definition_repository,
        reveal_repository=repository,
        runtime=_Runtime(),
        configured_portfolio_id=PORTFOLIO_ID,
        execution_authority_checker=lambda: True,
    )
    recovered = restarted.get_execution(DEFINITION_ID, roles=["trader"])
    assert recovered.command_cycle_status == "COMPLETED"
    assert recovered.command_cycle_evidence_sha256 == (
        response.command_cycle_evidence_sha256
    )


def test_filled_readback_closes_without_consuming_cancel() -> None:
    runtime = _Runtime(readback_statuses=["FILLED"])
    service, _ = _service(runtime)
    service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-correlation",
        idempotency_key="goal6-reveal-key",
    )
    runtime.calls.clear()

    response = service.closeout(
        definition_id=DEFINITION_ID,
        body=OperatorStealthCloseoutRequest(
            expected_plan_sha256=service.get_execution(
                DEFINITION_ID,
                roles=["trader"],
            ).plan_sha256,
            operator_reason="reconcile exact filled placement",
            confirm_operator_stealth_closeout=True,
        ),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-closeout-correlation",
        idempotency_key="goal6-closeout-key",
    )

    assert response.state == "FILLED"
    assert response.cancel_allowance_consumed is False
    assert response.cancel_call_count == 0
    assert response.read_call_count == 6
    assert runtime.calls == [
        "portfolio_permissions",
        "portfolio_catalog",
        "readback",
        "reconcile_filled",
    ]


def test_closeout_replay_after_terminal_makes_no_read_or_exchange_call() -> None:
    runtime = _Runtime()
    service, repository = _service(runtime)
    reveal = service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-correlation",
        idempotency_key="goal6-reveal-key",
    )
    closeout = OperatorStealthCloseoutRequest(
        expected_plan_sha256=reveal.plan_sha256,
        operator_reason="safely close this exact placement",
        confirm_operator_stealth_closeout=True,
    )
    first = service.closeout(
        definition_id=DEFINITION_ID,
        body=closeout,
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-closeout-correlation",
        idempotency_key="goal6-closeout-key",
    )
    runtime.calls.clear()

    replay = service.closeout(
        definition_id=DEFINITION_ID,
        body=closeout,
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-closeout-correlation",
        idempotency_key="goal6-closeout-key",
    )

    assert replay.state == first.state == "CANCELLED"
    assert runtime.calls == []
    assert repository.row["cancel_call_count"] == 1


def test_not_ready_condition_can_use_a_distinct_later_refresh_cycle() -> None:
    runtime = _Runtime(condition_ready_results=[False, True])
    service, repository = _service(runtime)

    waiting = service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-cycle-1",
        idempotency_key="goal6-cycle-key-1",
    )
    revealed = service.reveal(
        definition_id=DEFINITION_ID,
        body=_request(),
        actor_id="operator",
        roles=["trader"],
        correlation_id="goal6-cycle-2",
        idempotency_key="goal6-cycle-key-2",
    )

    assert waiting.state == "MATERIALIZED"
    assert waiting.diagnostic_code == "operator_stealth_condition_not_ready"
    assert waiting.command_cycle_status == "COMPLETED"
    assert waiting.command_cycle_terminal_goal_state == "MATERIALIZED"
    assert waiting.command_cycle_preview_call_count == 0
    assert waiting.command_cycle_create_call_count == 0
    assert waiting.command_cycle_cancel_call_count == 0
    assert waiting.allowed_actions == ["REVEAL"]
    assert revealed.state == "REVEALED"
    assert revealed.read_call_count == 5
    assert len(repository.command_cycles) == 2
    assert runtime.calls.count("preview") == 1
    assert runtime.calls.count("reveal") == 1


def test_cancelled_local_definition_never_advertises_reveal() -> None:
    runtime = _Runtime()
    definition_repository = _DefinitionRepository()
    definition_repository.definition.update(
        lifecycle_state="CANCELLED",
        runtime_classification="UNMATERIALIZED",
    )
    service = OperatorStealthRevealService(
        definition_repository=definition_repository,
        reveal_repository=_RevealRepository(),
        runtime=runtime,
        configured_portfolio_id=PORTFOLIO_ID,
        execution_authority_checker=lambda: True,
    )

    response = service.get_execution(DEFINITION_ID, roles=["trader"])

    assert response.state == "UNCONSUMED"
    assert response.allowed_actions == []


def test_readback_does_not_advertise_live_action_without_master_authority() -> None:
    runtime = _Runtime()
    service = OperatorStealthRevealService(
        definition_repository=_DefinitionRepository(),
        reveal_repository=_RevealRepository(),
        runtime=runtime,
        configured_portfolio_id=PORTFOLIO_ID,
        execution_authority_checker=lambda: False,
    )

    response = service.get_execution(DEFINITION_ID, roles=["trader"])

    assert response.execution_authority_enabled is False
    assert response.allowed_actions == []
