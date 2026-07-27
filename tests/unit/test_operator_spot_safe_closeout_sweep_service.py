from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json

import pytest

from application.admin_api.operator_spot_safe_closeout_sweep_models import (
    OperatorSpotSafeCloseoutSweepActionRequest,
    OperatorSpotSafeCloseoutSweepCreateRequest,
)
from application.admin_api.operator_spot_safe_closeout_sweep_service import (
    OperatorSpotSafeCloseoutSweepCommandContext,
    OperatorSpotSafeCloseoutSweepConflict,
    OperatorSpotSafeCloseoutSweepService,
    _payload_hash,
)


PORTFOLIO_SHA256 = "a" * 64
CLIENT_ID = "22222222-2222-4222-8222-222222222222"
ROOT_ID = "11111111-1111-4111-8111-111111111111"
CANDIDATE_EVIDENCE = "c" * 64


def _candidate() -> dict[str, object]:
    return {
        "client_order_id": CLIENT_ID,
        "root_client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "status": "OPEN",
        "ownership_provenance": "ADMIN_FILL_FOLLOW_UP",
        "portfolio_scope_sha256": PORTFOLIO_SHA256,
        "exchange_order_id_sha256": "d" * 64,
        "predecessor_evidence_sha256": "b" * 64,
        "candidate_evidence_sha256": CANDIDATE_EVIDENCE,
        "created_at": "2026-07-27T00:00:00Z",
    }


@dataclass
class _Resolver:
    calls: int = 0

    @property
    def configured_portfolio_scope_sha256(self) -> str:
        return PORTFOLIO_SHA256

    def list_candidates(self, **_kwargs):
        self.calls += 1
        return [_candidate()], 1

    def resolve_selected(self, selections):
        self.calls += 1
        assert selections == [(CLIENT_ID, CANDIDATE_EVIDENCE)]
        return [_candidate()]


@dataclass
class _Repository:
    row: dict[str, object] | None = None
    replay: bool = False
    calls: list[str] = field(default_factory=list)

    @staticmethod
    def command_lock():
        return nullcontext()

    def get_command_replay(self, **_kwargs):
        self.calls.append("get_command_replay")
        if self.replay and self.row is not None:
            return {**deepcopy(self.row), "command_replayed": True}
        return None

    def create_plan(self, **kwargs):
        self.calls.append("create_plan")
        plan = kwargs["plan"]
        now = "2026-07-27T00:00:00Z"
        item = plan["items"][0]
        self.row = {
            "sweep_id": plan["sweep_id"],
            "revision": 1,
            "state": "READY",
            "diagnostic_code": "operator_spot_sweep_plan_ready",
            "plan": deepcopy(plan),
            "plan_sha256": kwargs["plan_sha256"],
            "configured_portfolio_scope_sha256": (
                PORTFOLIO_SHA256
            ),
            "items": [
                {
                    **item,
                    "state": "PENDING",
                    "diagnostic_code": (
                        "operator_spot_sweep_item_pending"
                    ),
                    "last_event_sequence": 4,
                    "updated_at": now,
                }
            ],
            "events": [
                {
                    "event_id": (
                        "33333333-3333-4333-8333-333333333333"
                    ),
                    "event_sequence": 4,
                    "event_type": "PLAN_CREATED",
                    "diagnostic_code": (
                        "operator_spot_sweep_plan_ready"
                    ),
                    "correlation_id": kwargs["correlation_id"],
                    "evidence_sha256": "e" * 64,
                    "recorded_at": now,
                }
            ],
            "local_cycles_used": 1,
            "latest_idempotency_key_sha256": "f" * 64,
            "latest_payload_sha256": "1" * 64,
            "latest_actor_id_sha256": "2" * 64,
            "latest_evidence_sha256": "e" * 64,
            "correlation_id": kwargs["correlation_id"],
            "created_at": now,
            "updated_at": now,
        }
        return deepcopy(self.row)

    def get_plan(self, **_kwargs):
        self.calls.append("get_plan")
        return deepcopy(self.row)

    def get_current_plan(self):
        self.calls.append("get_current_plan")
        return deepcopy(self.row)

    def apply_local_action(self, **kwargs):
        self.calls.append(f"apply_{kwargs['action'].lower()}")
        assert self.row is not None
        state = {
            "PAUSE": "PAUSED",
            "RESUME": "READY",
            "ABORT": "ABORTED",
        }[kwargs["action"]]
        self.row["state"] = state
        self.row["revision"] = int(self.row["revision"]) + 1
        self.row["diagnostic_code"] = (
            f"operator_spot_sweep_{state.lower()}"
        )
        self.row["local_cycles_used"] = (
            int(self.row["local_cycles_used"]) + 1
        )
        event_sequence = 9 + len(self.row["events"])
        self.row["events"].append(
            {
                "event_id": (
                    "44444444-4444-4444-8444-444444444444"
                ),
                "event_sequence": event_sequence,
                "event_type": {
                    "PAUSE": "SWEEP_PAUSED",
                    "RESUME": "SWEEP_RESUMED",
                    "ABORT": "SWEEP_ABORTED",
                }[kwargs["action"]],
                "diagnostic_code": self.row["diagnostic_code"],
                "correlation_id": kwargs["correlation_id"],
                "evidence_sha256": "9" * 64,
                "recorded_at": "2026-07-27T00:01:00Z",
            }
        )
        return deepcopy(self.row)


def _context(intent: str, key: str = "goal16-key"):
    return OperatorSpotSafeCloseoutSweepCommandContext(
        actor_id="operator-1",
        roles=("trader",),
        correlation_id=f"corr-{key}",
        idempotency_key=key,
        operator_intent=intent,
    )


def _body() -> OperatorSpotSafeCloseoutSweepCreateRequest:
    return OperatorSpotSafeCloseoutSweepCreateRequest(
        items=[
            {
                "client_order_id": CLIENT_ID,
                "expected_candidate_evidence_sha256": (
                    CANDIDATE_EVIDENCE
                ),
            }
        ],
        operator_reason="Operator reviewed this exact cancel-only set.",
        confirm_create_cancel_only_sweep=True,
    )


def test_create_replay_precedes_candidate_resolution_and_never_grants_live() -> None:
    resolver = _Resolver()
    repository = _Repository()
    service = OperatorSpotSafeCloseoutSweepService(
        repository=repository,
        candidate_resolver=resolver,
    )
    context = _context("create_operator_spot_safe_closeout_sweep")
    created = service.create_safe_closeout_sweep(
        body=_body(),
        context=context,
    )
    repository.replay = True
    resolver.calls = 0

    replay = service.create_safe_closeout_sweep(
        body=_body(),
        context=context,
    )

    assert created.state == "READY"
    assert replay.sweep_id == created.sweep_id
    assert replay.command_replayed is True
    assert resolver.calls == 0
    assert replay.allowed_actions == ["PAUSE", "ABORT"]
    assert replay.blocker_codes == [
        "operator_spot_sweep_live_read_authority_incomplete"
    ]
    assert {item.category for item in replay.allowances} == {
        "API_KEY_PERMISSIONS",
        "PORTFOLIO_CATALOG",
        "PRE_CANCEL_EXACT_ORDER_READ",
        "CANCEL",
        "POST_CANCEL_EXACT_ORDER_READ",
    }
    assert all(
        allowance.state == "NOT_GRANTED"
        and allowance.call_count == 0
        and not allowance.consumed
        for allowance in replay.allowances
    )
    assert replay.create_call_count == 0
    assert replay.cancel_call_count == 0
    assert replay.total_exchange_call_count == 0


def test_local_pause_resume_abort_are_revision_and_plan_bound() -> None:
    repository = _Repository()
    service = OperatorSpotSafeCloseoutSweepService(
        repository=repository,
        candidate_resolver=_Resolver(),
    )
    created = service.create_safe_closeout_sweep(
        body=_body(),
        context=_context(
            "create_operator_spot_safe_closeout_sweep",
            "create",
        ),
    )

    paused = service.pause_safe_closeout_sweep(
        sweep_id=created.sweep_id,
        body=OperatorSpotSafeCloseoutSweepActionRequest(
            expected_revision=1,
            expected_plan_sha256=created.plan_sha256,
            operator_reason="Operator paused the reviewed local plan.",
            confirm_local_control_action=True,
        ),
        context=_context(
            "pause_operator_spot_safe_closeout_sweep",
            "pause",
        ),
    )

    assert paused.state == "PAUSED"
    assert paused.allowed_actions == ["RESUME", "ABORT"]
    assert [event.event_sequence for event in paused.events] == [4, 10]
    assert paused.items[0].last_event_sequence == 4


def test_get_readback_suppresses_actions_without_both_permissions() -> None:
    repository = _Repository()
    service = OperatorSpotSafeCloseoutSweepService(
        repository=repository,
        candidate_resolver=_Resolver(),
    )
    created = service.create_safe_closeout_sweep(
        body=_body(),
        context=_context(
            "create_operator_spot_safe_closeout_sweep",
            "create-readback",
        ),
    )

    viewer = service.get_safe_closeout_sweep(
        sweep_id=created.sweep_id,
        can_mutate=False,
    )
    trader = service.get_safe_closeout_sweep(
        sweep_id=created.sweep_id,
        can_mutate=True,
    )

    assert viewer.allowed_actions == []
    assert viewer.command_service_method == "get_safe_closeout_sweep"
    assert viewer.operator_intent is None
    assert trader.allowed_actions == ["PAUSE", "ABORT"]

    current = service.get_current_safe_closeout_sweep(
        can_mutate=False,
    )
    assert current.sweep_id == created.sweep_id
    assert current.allowed_actions == []
    assert current.command_service_method == (
        "get_current_safe_closeout_sweep"
    )
    assert current.operator_intent is None


def test_get_readback_suppresses_actions_at_local_cycle_cap() -> None:
    repository = _Repository()
    service = OperatorSpotSafeCloseoutSweepService(
        repository=repository,
        candidate_resolver=_Resolver(),
    )
    created = service.create_safe_closeout_sweep(
        body=_body(),
        context=_context(
            "create_operator_spot_safe_closeout_sweep",
            "create-cycle-cap-readback",
        ),
    )
    assert repository.row is not None
    repository.row["local_cycles_used"] = 10

    trader = service.get_safe_closeout_sweep(
        sweep_id=created.sweep_id,
        can_mutate=True,
    )
    viewer = service.get_safe_closeout_sweep(
        sweep_id=created.sweep_id,
        can_mutate=False,
    )

    assert trader.allowed_actions == []
    assert viewer.allowed_actions == []


def test_service_rejects_wrong_operator_intent_before_repository() -> None:
    repository = _Repository()
    service = OperatorSpotSafeCloseoutSweepService(
        repository=repository,
        candidate_resolver=_Resolver(),
    )

    with pytest.raises(
        OperatorSpotSafeCloseoutSweepConflict
    ) as exc:
        service.create_safe_closeout_sweep(
            body=_body(),
            context=_context("pause_operator_spot_safe_closeout_sweep"),
        )

    assert exc.value.code == "operator_spot_sweep_operator_intent_invalid"
    assert repository.calls == []


def test_current_read_fails_closed_without_singleton() -> None:
    service = OperatorSpotSafeCloseoutSweepService(
        repository=_Repository(),
        candidate_resolver=_Resolver(),
    )

    with pytest.raises(
        OperatorSpotSafeCloseoutSweepConflict
    ) as exc:
        service.get_current_safe_closeout_sweep(can_mutate=False)

    assert exc.value.code == "operator_spot_sweep_not_found"


def test_payload_hash_fixed_create_and_pause_parity_vectors() -> None:
    assert _payload_hash(
        route="/api/v1/spot/safe-closeout-sweeps",
        action="CREATE",
        sweep_id=None,
        body=_body().model_dump(mode="json"),
        operator_intent="create_operator_spot_safe_closeout_sweep",
    ) == "b5550df7b5be2be6a0513fd79f2d6c2a64d967537589d9fca175a409a08a9888"
    assert _payload_hash(
        route=(
            "/api/v1/spot/safe-closeout-sweeps/"
            "11111111-1111-4111-8111-111111111111/pause"
        ),
        action="PAUSE",
        sweep_id="11111111-1111-4111-8111-111111111111",
        body=OperatorSpotSafeCloseoutSweepActionRequest(
            expected_revision=1,
            expected_plan_sha256="d" * 64,
            operator_reason=(
                "Operator paused the reviewed local plan."
            ),
            confirm_local_control_action=True,
        ).model_dump(mode="json"),
        operator_intent="pause_operator_spot_safe_closeout_sweep",
    ) == "cea49c8ce9c5207f1f591720153a7b58e52e9ef417a65b04cd0b01a5aba24c13"
    assert _payload_hash(
        route=(
            "/api/v1/spot/safe-closeout-sweeps/"
            "11111111-1111-4111-8111-111111111111/pause"
        ),
        action="PAUSE",
        sweep_id="11111111-1111-4111-8111-111111111111",
        body=OperatorSpotSafeCloseoutSweepActionRequest(
            expected_revision=7,
            expected_plan_sha256="e" * 64,
            operator_reason=(
                "Operator reviewed résumé ✅ and astral 🚀 closeout."
            ),
            confirm_local_control_action=True,
        ).model_dump(mode="json"),
        operator_intent="pause_operator_spot_safe_closeout_sweep",
    ) == "8b75aa374179cf3f17974dc05c9424a0e6f04a19523f44ea61a5cedcbd8ec90c"
