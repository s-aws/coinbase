import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.enums import (
    OrderOwnershipProvenance,
    OrderSide,
    RevealConditionType,
    StealthOrderStatus,
)
from core.exceptions import OrderPersistenceError
from core.models import RevealExecutionPlan
from core.stealth_order_manager import (
    ControlledAdminChildRevealAuthority,
    StealthOrderManager,
)
from database.order import prepare_controlled_admin_first_child_reveal_atomic


ROOT_ID = "11111111-1111-4111-8111-111111111111"
CHILD_ID = str(
    uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"coinbase://filled-follow-up/{ROOT_ID}/{ROOT_ID}",
    )
)
PORTFOLIO_ID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 7, 11, 15, 0, tzinfo=timezone.utc)
V8_ROOT_ID = "12a52c06-e368-5c39-bfa0-6eb5880f3c64"
V8_CHILD_ID = "252b6389-d544-58db-a796-e9bc258f794f"
V8_PORTFOLIO_ID = "62f28f44-8e72-4fe0-ace7-d71a01f54883"
V8_ROOT_EXCHANGE_ID = "2ed7d436-b16e-4a7e-b0af-cb8f8bb86e68"
V8_PREPARATION_SHA256 = (
    "af16bf8f7867c3f8a385b0d0cef31371d4381289cc1fd7a58e81c29102d783a9"
)
CONTROLLED_PLAN_SHA256 = "b" * 64


def _root_row(**overrides):
    row = {
        "client_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "size": Decimal("0.00002"),
        "price": Decimal("100.00"),
        "status": "FILLED",
        "parent_order_id": None,
        "ownership_provenance": (
            OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value
        ),
        "retail_portfolio_id": PORTFOLIO_ID,
        "correlation_id": "corr-1",
        "audit_id": "root-audit-1",
        "exchange_order_id": "exchange-root-1",
    }
    row.update(overrides)
    return row


def _child_parent_row(**overrides):
    row = {
        "client_order_id": CHILD_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "size": Decimal("0.00002"),
        "price": Decimal("101.00"),
        "status": "PENDING",
        "parent_order_id": ROOT_ID,
        "ownership_provenance": (
            OrderOwnershipProvenance.ADMIN_FILL_FOLLOW_UP.value
        ),
        "retail_portfolio_id": PORTFOLIO_ID,
        "correlation_id": "corr-1",
        "audit_id": "root-audit-1",
        "exchange_order_id": None,
    }
    row.update(overrides)
    return row


def _stealth_row(**overrides):
    row = {
        "stealth_order_id": CHILD_ID,
        "parent_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": "SELL",
        "total_size": Decimal("0.00002"),
        "remaining_size": Decimal("0.00002"),
        "revealed_size": Decimal("0"),
        "executed_size": Decimal("0"),
        "limit_price": Decimal("101.00"),
        "status": "HIDDEN",
        "reveal_condition_type": RevealConditionType.PRICE_THRESHOLD.value,
        "reveal_condition_json": {
            "type": RevealConditionType.PRICE_THRESHOLD.value,
            "price_threshold": 101.0,
            "direction": "above",
            "hold_duration_seconds": 0,
            "standing_price_limit_policy": "admin_test_profile",
        },
        "revealed_orders": [],
        "last_placement_at": None,
        "reason": "follow_up_replacement",
        "anchor_repricing_state_json": {"unrelated": "preserve"},
    }
    row.update(overrides)
    return row


class _Cursor:
    def __init__(self, *, root=None, child=None, stealth=None, siblings=None):
        self.root = root if root is not None else _root_row()
        self.child = child if child is not None else _child_parent_row()
        self.stealth = stealth if stealth is not None else _stealth_row()
        self.siblings = siblings if siblings is not None else [self.child]
        self.description = []
        self._one = None
        self._all = []
        self.rowcount = 0
        self.statements = []

    def _set_one(self, row):
        if row is None:
            self.description = []
            self._one = None
            return
        self.description = [(key,) for key in row]
        self._one = tuple(row.values())

    def execute(self, query, params=()):
        normalized = " ".join(query.split())
        self.statements.append((normalized, params))
        self.rowcount = 0
        self._one = None
        self._all = []
        if normalized.startswith("SELECT") and "FROM order_parent" in normalized:
            if "parent_order_id = %s" in normalized:
                rows = self.siblings
                keys = list(rows[0]) if rows else ["client_order_id"]
                self.description = [(key,) for key in keys]
                self._all = [tuple(row[key] for key in keys) for row in rows]
            elif params in {
                (CHILD_ID,),
                (str(self.child["client_order_id"]),),
            }:
                self._set_one(self.child)
            elif params in {
                (ROOT_ID,),
                (str(self.root["client_order_id"]),),
            }:
                self._set_one(self.root)
        elif normalized.startswith("SELECT") and "FROM stealth_orders" in normalized:
            self._set_one(self.stealth)
        elif normalized.startswith("UPDATE order_parent"):
            self.rowcount = 1
        elif normalized.startswith("UPDATE stealth_orders"):
            self.rowcount = 1

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _Db:
    def __init__(self, cursor):
        self.cursor = cursor

    @contextmanager
    def get_cursor(self):
        yield self.cursor


def _prepare(cursor, monkeypatch, **overrides):
    monkeypatch.setattr("database.order.DB_CLIENT", _Db(cursor))
    kwargs = {
        "stealth_order_id": CHILD_ID,
        "expected_root_client_order_id": ROOT_ID,
        "expected_portfolio_id": PORTFOLIO_ID,
        "submitted_limit_price": 160.001,
        "quote_increment": "0.01",
        "max_notional_usdc": 9.99,
        "market_bid": 100.0,
        "market_source": "coinbase_rest_best_bid",
        "market_observed_at": NOW - timedelta(seconds=2),
        "approval_snapshot_id": "approval-1",
        "admission_audit_id": "admission-1",
        "cap_guard_decision_id": "cap-1",
        "reconciliation_plan_id": "reconcile-1",
        "batch_id": "batch-1",
        "batch_slot": 1,
        "authority_id": "authority-1",
        "now": NOW,
    }
    kwargs.update(overrides)
    return prepare_controlled_admin_first_child_reveal_atomic(**kwargs)


def test_atomic_prepare_rounds_sell_up_and_preserves_original_audit(monkeypatch):
    cursor = _Cursor()

    result = _prepare(cursor, monkeypatch)

    assert result["prepared_limit_price"] == Decimal("160.01")
    assert result["reference_notional_usdc"] == Decimal("0.0032002")
    updates = [item for item in cursor.statements if item[0].startswith("UPDATE")]
    assert len(updates) == 2
    parent_update, stealth_update = updates
    assert parent_update[1][0] == Decimal("160.01")
    condition = json.loads(stealth_update[1][2])
    state = json.loads(stealth_update[1][3])
    assert condition["price_threshold"] == 160.01
    evidence = state["controlled_admin_first_child_reveal_preparation"]
    assert evidence["original_order_parent_price"] == 101.0
    assert evidence["original_stealth_limit_price"] == 101.0
    assert evidence["original_price_threshold"] == 101.0
    assert evidence["approval_snapshot_id"] == "approval-1"
    assert evidence["admission_audit_id"] == "admission-1"
    assert evidence["cap_guard_decision_id"] == "cap-1"
    assert evidence["reconciliation_plan_id"] == "reconcile-1"
    assert evidence["batch_id"] == "batch-1"
    assert evidence["batch_slot"] == 1
    assert evidence["market_bid"] == "100.0"
    assert evidence["market_source"] == "coinbase_rest_best_bid"
    assert evidence["market_observed_at"] == (
        NOW - timedelta(seconds=2)
    ).isoformat()
    assert state["unrelated"] == "preserve"


def test_atomic_prepare_persists_and_reads_back_exact_controlled_plan_hash(
    monkeypatch,
):
    cursor = _Cursor()

    result = _prepare(
        cursor,
        monkeypatch,
        controlled_plan_sha256=CONTROLLED_PLAN_SHA256,
    )

    stealth_update = next(
        item for item in cursor.statements if item[0].startswith("UPDATE stealth_orders")
    )
    state = json.loads(stealth_update[1][3])
    preparation = state["controlled_admin_first_child_reveal_preparation"]
    assert preparation["controlled_plan_sha256"] == CONTROLLED_PLAN_SHA256
    assert result["controlled_plan_sha256"] == CONTROLLED_PLAN_SHA256
    assert result["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ]["controlled_plan_sha256"] == CONTROLLED_PLAN_SHA256


@pytest.mark.parametrize(
    "controlled_plan_sha256",
    ["b" * 63, "b" * 65, "B" * 64, f"{'b' * 64} ", 7],
)
def test_atomic_prepare_rejects_invalid_controlled_plan_hash_before_locking(
    monkeypatch,
    controlled_plan_sha256,
):
    cursor = _Cursor()

    with pytest.raises(OrderPersistenceError, match="controlled_plan_sha256"):
        _prepare(
            cursor,
            monkeypatch,
            controlled_plan_sha256=controlled_plan_sha256,
        )

    assert cursor.statements == []


def test_atomic_prepare_keeps_v14_plan_hash_optional(monkeypatch):
    cursor = _Cursor()

    result = _prepare(cursor, monkeypatch)

    preparation = result["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ]
    assert "controlled_plan_sha256" not in preparation
    assert result["controlled_plan_sha256"] is None


@pytest.mark.parametrize("alias_location", ["column", "condition"])
def test_atomic_prepare_rejects_noncanonical_price_threshold_alias(
    monkeypatch,
    alias_location,
):
    stealth = _stealth_row()
    if alias_location == "column":
        stealth["reveal_condition_type"] = "price_threshold"
    else:
        stealth["reveal_condition_json"] = {
            **stealth["reveal_condition_json"],
            "type": "price_threshold",
        }
    cursor = _Cursor(stealth=stealth)

    with pytest.raises(OrderPersistenceError, match="policy evidence"):
        _prepare(cursor, monkeypatch)

    assert not any(
        statement.startswith("UPDATE") for statement, _params in cursor.statements
    )


@pytest.mark.parametrize(
    ("cursor", "match"),
    [
        (
            _Cursor(child=_child_parent_row(retail_portfolio_id=uuid.uuid4())),
            "portfolio",
        ),
        (
            _Cursor(stealth=_stealth_row(revealed_orders=[{"placed": True}])),
            "unsubmitted",
        ),
        (
            _Cursor(
                child=_child_parent_row(
                    client_order_id="33333333-3333-4333-8333-333333333333"
                )
            ),
            "deterministic",
        ),
        (
            _Cursor(siblings=[_child_parent_row(), _child_parent_row()]),
            "exactly one",
        ),
        (
            _Cursor(
                stealth=_stealth_row(
                    anchor_repricing_state_json={
                        "controlled_admin_first_child_reveal_preparation": {
                            "authority_id": "historical"
                        }
                    }
                )
            ),
            "already prepared",
        ),
    ],
)
def test_atomic_prepare_rejects_unowned_historical_or_wrong_state_without_update(
    monkeypatch,
    cursor,
    match,
):
    with pytest.raises(OrderPersistenceError, match=match):
        _prepare(cursor, monkeypatch)

    assert not any(
        statement.startswith("UPDATE") for statement, _params in cursor.statements
    )


def _prior_preparation() -> dict:
    return {
        "authority_id": "prior-authority",
        "approval_snapshot_id": "prior-approval",
        "admission_audit_id": "prior-admission",
        "cap_guard_decision_id": "prior-cap",
        "reconciliation_plan_id": "prior-reconciliation",
        "batch_id": "prior-batch",
        "batch_slot": 2,
        "root_client_order_id": ROOT_ID,
        "stealth_order_id": CHILD_ID,
        "portfolio_id": PORTFOLIO_ID,
        "root_exchange_order_id": "exchange-root-1",
    }


def _v8_prior_preparation() -> dict:
    return {
        "admission_audit_id": "6d2dd88a-e974-4c55-88a8-e869ae6ce492",
        "approval_snapshot_id": "bb1d8b0b-a32f-5acd-be46-a91af74ef701",
        "authority_id": "d67b89be-549b-4778-9061-e6decb20f550",
        "batch_id": "4b4322db-64c6-57fc-8e2b-0890b64507e6",
        "batch_slot": 2,
        "cap_guard_decision_id": (
            "cap-v8-slot-2-child-reveal-f88967db-5156-4a8a-b121-dd56dd5a24a3"
        ),
        "correlation_id": (
            "corr-4b4322db-64c6-57fc-8e2b-0890b64507e6-root-2"
        ),
        "market_age_seconds": 0.19536,
        "market_bid": "64143.89",
        "market_observed_at": "2026-07-12T04:17:03.886752+00:00",
        "market_source": "coinbase_rest_best_bid",
        "max_notional_usdc": 2.0,
        "minimum_standing_price": 96215.835,
        "original_condition_confirmed_at": None,
        "original_condition_first_met_at": None,
        "original_order_parent_price": 64582.69,
        "original_price_threshold": 64582.69,
        "original_stealth_limit_price": 64582.69,
        "original_stealth_status": "HIDDEN",
        "portfolio_id": V8_PORTFOLIO_ID,
        "prepared_at": "2026-07-12T04:17:04.082112+00:00",
        "prepared_limit_price": 102630.23,
        "quote_increment": "0.01",
        "reconciliation_plan_id": (
            "reconciliation-v8-slot-2-child-reveal-"
            "ee4daeb4-7ab6-4f86-973f-977e502c6653"
        ),
        "reference_notional_usdc": 1.7560032353,
        "requested_limit_price": 102630.23,
        "root_audit_id": "d7c642bb-9d7a-4a76-a1c6-2b0eb73590d8",
        "root_client_order_id": V8_ROOT_ID,
        "root_exchange_order_id": V8_ROOT_EXCHANGE_ID,
        "stealth_order_id": V8_CHILD_ID,
    }


def _canonical_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def _v8_recovery_cursor(*, history=None) -> _Cursor:
    prior = _v8_prior_preparation()
    root = _root_row(
        client_order_id=V8_ROOT_ID,
        size=Decimal("0.00001711"),
        retail_portfolio_id=V8_PORTFOLIO_ID,
        correlation_id=prior["correlation_id"],
        audit_id=prior["root_audit_id"],
        exchange_order_id=V8_ROOT_EXCHANGE_ID,
    )
    child = _child_parent_row(
        client_order_id=V8_CHILD_ID,
        parent_order_id=V8_ROOT_ID,
        size=Decimal("0.00001711"),
        price=Decimal("102630.23"),
        retail_portfolio_id=V8_PORTFOLIO_ID,
        correlation_id=prior["correlation_id"],
        audit_id=prior["root_audit_id"],
    )
    state = {
        "unrelated": "preserve",
        "controlled_admin_first_child_reveal_preparation": prior,
    }
    if history is not None:
        state["controlled_admin_first_child_reveal_preparation_history"] = history
    return _Cursor(
        root=root,
        child=child,
        siblings=[child],
        stealth=_stealth_row(
            stealth_order_id=V8_CHILD_ID,
            parent_order_id=V8_ROOT_ID,
            total_size=Decimal("0.00001711"),
            remaining_size=Decimal("0.00001711"),
            limit_price=Decimal("102630.23"),
            reveal_condition_json={
                **_stealth_row()["reveal_condition_json"],
                "price_threshold": 102630.23,
            },
            anchor_repricing_state_json=state,
        ),
    )


def _prepare_v8_recovery(cursor, monkeypatch, **overrides):
    prior = _v8_prior_preparation()
    kwargs = {
        "stealth_order_id": V8_CHILD_ID,
        "expected_root_client_order_id": V8_ROOT_ID,
        "expected_portfolio_id": V8_PORTFOLIO_ID,
        "expected_prior_preparation_sha256": V8_PREPARATION_SHA256,
        "submitted_limit_price": 102630.23,
        "max_notional_usdc": 2.0,
        "market_bid": 64143.89,
        "market_observed_at": datetime.fromisoformat(prior["market_observed_at"]),
        "approval_snapshot_id": "approval-v9",
        "admission_audit_id": "admission-v9",
        "cap_guard_decision_id": "cap-v9",
        "reconciliation_plan_id": "reconciliation-v9",
        "batch_id": "successor-v9-batch",
        "batch_slot": 2,
        "authority_id": "authority-v9",
        "now": datetime(2026, 7, 12, 4, 17, 5, tzinfo=timezone.utc),
    }
    kwargs.update(overrides)
    return _prepare(cursor, monkeypatch, **kwargs)


def test_atomic_prepare_supersedes_only_exact_bound_prior_preparation(
    monkeypatch,
):
    prior = _v8_prior_preparation()
    prior_hash = _canonical_sha256(prior)
    assert prior_hash == V8_PREPARATION_SHA256
    cursor = _v8_recovery_cursor()

    result = _prepare_v8_recovery(cursor, monkeypatch)

    state = result["anchor_repricing_state_json"]
    current = state["controlled_admin_first_child_reveal_preparation"]
    history = state[
        "controlled_admin_first_child_reveal_preparation_history"
    ]
    assert current["batch_id"] == "successor-v9-batch"
    assert current["supersedes_preparation_sha256"] == prior_hash
    assert current["supersedes_batch_id"] == prior["batch_id"]
    assert history == [
        {
            "preparation": prior,
            "preparation_sha256": prior_hash,
            "superseded_at": "2026-07-12T04:17:05+00:00",
            "superseded_by_batch_id": "successor-v9-batch",
            "superseded_by_authority_id": "authority-v9",
        }
    ]
    assert state["unrelated"] == "preserve"


def test_atomic_prepare_rejects_generic_client_driven_supersession(
    monkeypatch,
):
    prior = _prior_preparation()
    cursor = _Cursor(
        stealth=_stealth_row(
            anchor_repricing_state_json={
                "controlled_admin_first_child_reveal_preparation": prior,
            }
        )
    )

    with pytest.raises(OrderPersistenceError, match="sealed v8 recovery"):
        _prepare(
            cursor,
            monkeypatch,
            expected_prior_preparation_sha256=_canonical_sha256(prior),
            batch_id="successor-batch",
            batch_slot=2,
        )

    assert not any(
        statement.startswith("UPDATE") for statement, _params in cursor.statements
    )


def test_atomic_prepare_rejects_wrong_prior_preparation_hash_without_update(
    monkeypatch,
):
    prior = _prior_preparation()
    cursor = _Cursor(
        stealth=_stealth_row(
            anchor_repricing_state_json={
                "controlled_admin_first_child_reveal_preparation": prior,
            }
        )
    )

    with pytest.raises(OrderPersistenceError, match="prior preparation hash"):
        _prepare(
            cursor,
            monkeypatch,
            expected_prior_preparation_sha256="0" * 64,
            batch_id="successor-batch",
            batch_slot=2,
        )

    assert not any(
        statement.startswith("UPDATE") for statement, _params in cursor.statements
    )


def test_atomic_prepare_rejects_a_second_supersession_without_update(
    monkeypatch,
):
    cursor = _v8_recovery_cursor(
        history=[{"preparation_sha256": "f" * 64}]
    )

    with pytest.raises(OrderPersistenceError, match="history"):
        _prepare_v8_recovery(cursor, monkeypatch)

    assert not any(
        statement.startswith("UPDATE") for statement, _params in cursor.statements
    )


@pytest.mark.parametrize(
    "drift",
    [
        "pre_v8_prices",
        "condition_threshold",
        "stealth_status",
        "condition_timestamp",
        "size",
        "trace",
    ],
)
def test_atomic_prepare_rejects_drift_from_sealed_v8_materialized_state(
    monkeypatch,
    drift,
):
    cursor = _v8_recovery_cursor()
    if drift == "pre_v8_prices":
        cursor.child["price"] = Decimal("64582.69")
        cursor.stealth["limit_price"] = Decimal("64582.69")
        cursor.stealth["reveal_condition_json"]["price_threshold"] = 64582.69
    elif drift == "condition_threshold":
        cursor.stealth["reveal_condition_json"]["price_threshold"] = 102630.22
    elif drift == "stealth_status":
        cursor.stealth["status"] = "PENDING"
    elif drift == "condition_timestamp":
        cursor.stealth["condition_first_met_at"] = NOW
    elif drift == "size":
        cursor.root["size"] = Decimal("0.00001712")
        cursor.child["size"] = Decimal("0.00001712")
        cursor.stealth["total_size"] = Decimal("0.00001712")
        cursor.stealth["remaining_size"] = Decimal("0.00001712")
    else:
        cursor.root["correlation_id"] = "drifted-correlation"
        cursor.child["correlation_id"] = "drifted-correlation"
        cursor.root["audit_id"] = "drifted-audit"
        cursor.child["audit_id"] = "drifted-audit"

    with pytest.raises(OrderPersistenceError, match="sealed v8 materialized state"):
        _prepare_v8_recovery(cursor, monkeypatch)

    assert not any(
        statement.startswith("UPDATE") for statement, _params in cursor.statements
    )


def test_atomic_prepare_rejects_stale_bid_and_notional_cap_without_db_mutation(
    monkeypatch,
):
    stale_cursor = _Cursor()
    with pytest.raises(OrderPersistenceError, match="fresh"):
        _prepare(
            stale_cursor,
            monkeypatch,
            market_observed_at=NOW - timedelta(seconds=31),
        )
    assert stale_cursor.statements == []

    cap_cursor = _Cursor(
        root=_root_row(size=Decimal("0.1")),
        child=_child_parent_row(size=Decimal("0.1")),
        stealth=_stealth_row(
            total_size=Decimal("0.1"), remaining_size=Decimal("0.1")
        ),
    )
    with pytest.raises(OrderPersistenceError, match="notional"):
        _prepare(cap_cursor, monkeypatch)
    assert not any(
        statement.startswith("UPDATE")
        for statement, _params in cap_cursor.statements
    )

    second_generation_cursor = _Cursor()
    with pytest.raises(OrderPersistenceError, match="deterministic first"):
        _prepare(
            second_generation_cursor,
            monkeypatch,
            stealth_order_id="44444444-4444-4444-8444-444444444444",
        )
    assert second_generation_cursor.statements == []


def test_atomic_prepare_rejects_noncanonical_market_source_without_db_mutation(
    monkeypatch,
):
    cursor = _Cursor()

    with pytest.raises(OrderPersistenceError, match="market source"):
        _prepare(cursor, monkeypatch, market_source="placeholder")

    assert cursor.statements == []


@pytest.mark.parametrize("original_status", ["PENDING", "TRIGGERED"])
def test_atomic_prepare_normalizes_unsubmitted_preexchange_condition_state(
    monkeypatch,
    original_status,
):
    cursor = _Cursor(stealth=_stealth_row(status=original_status))

    result = _prepare(cursor, monkeypatch)

    evidence = result["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ]
    assert evidence["original_stealth_status"] == original_status
    stealth_update = next(
        params
        for statement, params in cursor.statements
        if statement.startswith("UPDATE stealth_orders")
    )
    assert "status = %s" in next(
        statement
        for statement, _params in cursor.statements
        if statement.startswith("UPDATE stealth_orders")
    )
    assert "HIDDEN" in stealth_update


def test_atomic_prepare_clears_raced_condition_timestamps_before_authority(
    monkeypatch,
):
    first_met_at = NOW - timedelta(seconds=1)
    confirmed_at = NOW - timedelta(milliseconds=500)
    cursor = _Cursor(
        stealth=_stealth_row(
            status="TRIGGERED",
            condition_first_met_at=first_met_at,
            condition_confirmed_at=confirmed_at,
        )
    )

    result = _prepare(cursor, monkeypatch)

    evidence = result["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ]
    assert evidence["original_stealth_status"] == "TRIGGERED"
    assert evidence["original_condition_first_met_at"] == first_met_at
    assert evidence["original_condition_confirmed_at"] == confirmed_at
    statement, _params = next(
        item
        for item in cursor.statements
        if item[0].startswith("UPDATE stealth_orders")
    )
    assert "condition_first_met_at = NULL" in statement
    assert "condition_confirmed_at = NULL" in statement


def test_atomic_prepare_rejects_batch_slot_above_approved_ten(monkeypatch):
    cursor = _Cursor()

    with pytest.raises(OrderPersistenceError, match="batch_slot"):
        _prepare(cursor, monkeypatch, batch_slot=11)

    assert cursor.statements == []


def _manager_order():
    return {
        "stealth_order_id": CHILD_ID,
        "parent_order_id": ROOT_ID,
        "product_id": "BTC-USDC",
        "side": OrderSide.SELL.value,
        "total_size": 0.00002,
        "remaining_size": 0.00002,
        "revealed_size": 0.0,
        "executed_size": 0.0,
        "limit_price": 101.0,
        "status": StealthOrderStatus.HIDDEN.value,
        "reveal_condition_type": RevealConditionType.PRICE_THRESHOLD.value,
        "reveal_condition_json": _stealth_row()["reveal_condition_json"].copy(),
        "revealed_orders": [],
        "anchor_repricing_state_json": {"unrelated": "preserve"},
    }


def _manager():
    manager = StealthOrderManager.__new__(StealthOrderManager)
    manager.in_memory_orders = {CHILD_ID: _manager_order()}
    manager.expected_retail_portfolio_id = PORTFOLIO_ID
    manager._controlled_admin_child_reveal_authorities = {}
    manager.log_callback = MagicMock()
    return manager


def _prepare_result(**overrides):
    observed_at = NOW - timedelta(seconds=2)
    result = {
        "stealth_order_id": CHILD_ID,
        "root_client_order_id": ROOT_ID,
        "portfolio_id": PORTFOLIO_ID,
        "correlation_id": "corr-1",
        "root_audit_id": "root-audit-1",
        "prepared_limit_price": Decimal("160.01"),
        "reference_notional_usdc": Decimal("0.0032002"),
        "market_bid": "100.0",
        "market_source": "coinbase_rest_best_bid",
        "market_observed_at": observed_at,
        "reveal_condition_json": {
            **_stealth_row()["reveal_condition_json"],
            "price_threshold": 160.01,
        },
        "anchor_repricing_state_json": {
            "unrelated": "preserve",
            "controlled_admin_first_child_reveal_preparation": {
                "authority_id": "authority-from-db",
                "market_bid": "100.0",
                "market_source": "coinbase_rest_best_bid",
                "market_observed_at": observed_at.isoformat(),
            },
        },
    }
    result.update(overrides)
    return result


def _manager_prepare_kwargs():
    return {
        "stealth_order_id": CHILD_ID,
        "expected_root_client_order_id": ROOT_ID,
        "expected_portfolio_id": PORTFOLIO_ID,
        "submitted_limit_price": 160.001,
        "max_notional_usdc": 9.99,
        "market_bid": "100.0",
        "market_source": "coinbase_rest_best_bid",
        "market_observed_at": NOW - timedelta(seconds=2),
        "approval_snapshot_id": "approval-1",
        "admission_audit_id": "admission-1",
        "cap_guard_decision_id": "cap-1",
        "reconciliation_plan_id": "reconcile-1",
        "batch_id": "batch-1",
        "batch_slot": 1,
    }


def test_manager_prepares_durably_then_updates_memory_and_issues_frozen_authority(
    monkeypatch,
):
    manager = _manager()
    manager._get_price_increment = MagicMock(return_value="0.01")
    atomic = MagicMock(side_effect=lambda **kwargs: _prepare_result(
        anchor_repricing_state_json={
            "unrelated": "preserve",
            "controlled_admin_first_child_reveal_preparation": {
                "authority_id": kwargs["authority_id"],
                "market_bid": str(kwargs["market_bid"]),
                "market_source": kwargs["market_source"],
                "market_observed_at": kwargs[
                    "market_observed_at"
                ].isoformat(),
            },
        }
    ))
    monkeypatch.setattr(
        "core.stealth_order_manager.prepare_controlled_admin_first_child_reveal_atomic",
        atomic,
    )

    authority = manager.prepare_controlled_admin_first_child_reveal(
        **_manager_prepare_kwargs()
    )

    assert isinstance(authority, ControlledAdminChildRevealAuthority)
    assert authority.stealth_order_id == CHILD_ID
    assert authority.root_client_order_id == ROOT_ID
    assert authority.prepared_limit_price == 160.01
    assert authority.market_bid == "100.0"
    assert authority.market_source == "coinbase_rest_best_bid"
    assert authority.market_observed_at == NOW - timedelta(seconds=2)
    assert manager.in_memory_orders[CHILD_ID]["limit_price"] == 160.01
    assert manager.in_memory_orders[CHILD_ID]["reveal_condition_json"][
        "price_threshold"
    ] == 160.01
    assert atomic.call_args.kwargs["quote_increment"] == "0.01"
    assert atomic.call_args.kwargs["market_source"] == "coinbase_rest_best_bid"
    with pytest.raises(FrozenInstanceError):
        authority.prepared_limit_price = 999.0


def test_manager_durable_failure_leaves_memory_untouched(monkeypatch):
    manager = _manager()
    before = json.loads(json.dumps(manager.in_memory_orders[CHILD_ID]))
    manager._get_price_increment = MagicMock(return_value="0.01")
    monkeypatch.setattr(
        "core.stealth_order_manager.prepare_controlled_admin_first_child_reveal_atomic",
        MagicMock(side_effect=OrderPersistenceError("test", "durable failure")),
    )

    with pytest.raises(OrderPersistenceError):
        manager.prepare_controlled_admin_first_child_reveal(
            **_manager_prepare_kwargs()
        )

    assert manager.in_memory_orders[CHILD_ID] == before
    assert manager._controlled_admin_child_reveal_authorities == {}


def test_manager_binds_prior_preparation_hash_into_atomic_supersession(
    monkeypatch,
):
    manager = _manager()
    manager._get_price_increment = MagicMock(return_value="0.01")
    atomic = MagicMock(return_value=_prepare_result())
    monkeypatch.setattr(
        "core.stealth_order_manager.prepare_controlled_admin_first_child_reveal_atomic",
        atomic,
    )
    kwargs = _manager_prepare_kwargs()
    kwargs["expected_prior_preparation_sha256"] = "a" * 64

    manager.prepare_controlled_admin_first_child_reveal(**kwargs)

    assert atomic.call_args.kwargs[
        "expected_prior_preparation_sha256"
    ] == "a" * 64


def test_manager_binds_v15_plan_hash_through_durable_active_child_readback(
    monkeypatch,
):
    manager = _manager()
    manager._get_price_increment = MagicMock(return_value="0.01")

    def prepare_result(**kwargs):
        plan_hash = kwargs["controlled_plan_sha256"]
        return _prepare_result(
            controlled_plan_sha256=plan_hash,
            anchor_repricing_state_json={
                "unrelated": "preserve",
                "controlled_admin_first_child_reveal_preparation": {
                    "authority_id": kwargs["authority_id"],
                    "market_bid": str(kwargs["market_bid"]),
                    "market_source": kwargs["market_source"],
                    "market_observed_at": kwargs[
                        "market_observed_at"
                    ].isoformat(),
                    "controlled_plan_sha256": plan_hash,
                },
            },
        )

    atomic = MagicMock(side_effect=prepare_result)
    monkeypatch.setattr(
        "core.stealth_order_manager.prepare_controlled_admin_first_child_reveal_atomic",
        atomic,
    )
    kwargs = _manager_prepare_kwargs()
    kwargs["controlled_plan_sha256"] = CONTROLLED_PLAN_SHA256

    authority = manager.prepare_controlled_admin_first_child_reveal(**kwargs)

    assert atomic.call_args.kwargs[
        "controlled_plan_sha256"
    ] == CONTROLLED_PLAN_SHA256
    assert authority.controlled_plan_sha256 == CONTROLLED_PLAN_SHA256
    active_child_preparation = manager.in_memory_orders[CHILD_ID][
        "anchor_repricing_state_json"
    ]["controlled_admin_first_child_reveal_preparation"]
    assert active_child_preparation[
        "controlled_plan_sha256"
    ] == CONTROLLED_PLAN_SHA256


def test_manager_prepare_normalizes_unsubmitted_triggered_child(monkeypatch):
    manager = _manager()
    manager.in_memory_orders[CHILD_ID]["status"] = "TRIGGERED"
    manager._get_price_increment = MagicMock(return_value="0.01")
    monkeypatch.setattr(
        "core.stealth_order_manager.prepare_controlled_admin_first_child_reveal_atomic",
        MagicMock(return_value=_prepare_result()),
    )

    manager.prepare_controlled_admin_first_child_reveal(
        **_manager_prepare_kwargs()
    )

    assert manager.in_memory_orders[CHILD_ID]["status"] == "HIDDEN"


def test_controlled_authority_is_exact_and_consumed_once():
    manager = _manager()
    authority = ControlledAdminChildRevealAuthority(
        stealth_order_id=CHILD_ID,
        root_client_order_id=ROOT_ID,
        prepared_limit_price=160.01,
        total_size=0.00002,
        reference_notional_usdc=0.0032002,
        market_bid="100.0",
        market_source="coinbase_rest_best_bid",
        market_observed_at=NOW - timedelta(seconds=2),
        portfolio_id=PORTFOLIO_ID,
        correlation_id="corr-1",
        root_audit_id="root-audit-1",
        authority_id="authority-1",
        approval_snapshot_id="approval-1",
        admission_audit_id="admission-1",
        cap_guard_decision_id="cap-1",
        reconciliation_plan_id="reconcile-1",
        batch_id="batch-1",
        batch_slot=1,
        controlled_plan_sha256=CONTROLLED_PLAN_SHA256,
    )
    manager._controlled_admin_child_reveal_authorities["authority-1"] = authority
    order = manager.in_memory_orders[CHILD_ID]
    order["limit_price"] = 160.01
    order["reveal_condition_json"]["price_threshold"] = 160.01
    order["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ] = {
        "authority_id": "authority-1",
        "approval_snapshot_id": "approval-1",
        "admission_audit_id": "admission-1",
        "cap_guard_decision_id": "cap-1",
        "reconciliation_plan_id": "reconcile-1",
        "batch_id": "batch-1",
        "batch_slot": 1,
        "root_client_order_id": ROOT_ID,
        "stealth_order_id": CHILD_ID,
        "portfolio_id": PORTFOLIO_ID,
        "correlation_id": "corr-1",
        "root_audit_id": "root-audit-1",
        "market_bid": "100.0",
        "market_source": "coinbase_rest_best_bid",
        "market_observed_at": (NOW - timedelta(seconds=2)).isoformat(),
        "controlled_plan_sha256": CONTROLLED_PLAN_SHA256,
    }

    allowed, reason = manager._consume_controlled_admin_child_reveal_authority(
        stealth_order_id=CHILD_ID,
        order=order,
        authority=authority,
    )
    repeated, repeated_reason = (
        manager._consume_controlled_admin_child_reveal_authority(
            stealth_order_id=CHILD_ID,
            order=order,
            authority=authority,
        )
    )
    drifted_authority = replace(
        authority,
        authority_id="authority-2",
        controlled_plan_sha256="c" * 64,
    )
    manager._controlled_admin_child_reveal_authorities[
        "authority-2"
    ] = drifted_authority
    order["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ]["authority_id"] = "authority-2"
    drifted, drifted_reason = (
        manager._consume_controlled_admin_child_reveal_authority(
            stealth_order_id=CHILD_ID,
            order=order,
            authority=drifted_authority,
        )
    )

    assert (allowed, reason) == (True, None)
    assert repeated is False
    assert repeated_reason == "controlled_admin_authority_not_issued"
    assert drifted is False
    assert drifted_reason == "controlled_admin_authority_plan_mismatch"


def test_prepared_child_without_one_call_authority_stays_pre_exchange(monkeypatch):
    manager = _manager()
    order = manager.in_memory_orders[CHILD_ID]
    order["limit_price"] = 160.01
    order["reveal_condition_json"]["price_threshold"] = 160.01
    order["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ] = {"authority_id": "authority-1"}
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=order["total_size"])
    manager.build_reveal_execution_plan = MagicMock(
        return_value=SimpleNamespace(
            configured_limit_price=160.01,
            submitted_limit_price=160.01,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
            market_source="ticker",
            market_bid=100.0,
            market_ask=100.1,
            post_only=False,
        )
    )
    manager._get_action_guard_blocked_until = MagicMock(return_value=0)
    manager._resolve_admin_fill_follow_up_reveal_authority = MagicMock(
        return_value={"required": True, "ready": True, "blockers": []}
    )
    manager._record_admin_fill_follow_up_reveal_block = MagicMock()
    capability = MagicMock()
    capability.allowed = True
    monkeypatch.setattr(
        "core.stealth_order_manager.evaluate_product_capability",
        MagicMock(return_value=capability),
    )
    manager._evaluate_action_condition_guard = MagicMock(return_value=(True, None))

    assert manager.reveal_order_slice(CHILD_ID) is None

    manager._record_admin_fill_follow_up_reveal_block.assert_called_once()
    assert manager._record_admin_fill_follow_up_reveal_block.call_args.kwargs[
        "block_category"
    ] == "controlled_admin_authority_required"
    manager._evaluate_action_condition_guard.assert_not_called()


def test_unprepared_admin_child_requires_controlled_authority_even_when_enabled(
    monkeypatch,
):
    manager = _manager()
    order = manager.in_memory_orders[CHILD_ID]
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=order["total_size"])
    manager.build_reveal_execution_plan = MagicMock(
        return_value=RevealExecutionPlan(
            configured_limit_price=101.0,
            submitted_limit_price=101.0,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
            market_source="ticker",
            market_bid=100.0,
            market_ask=100.1,
            post_only=False,
        )
    )
    manager._get_action_guard_blocked_until = MagicMock(return_value=0)
    manager._resolve_admin_fill_follow_up_reveal_authority = MagicMock(
        return_value={"required": True, "ready": True, "blockers": []}
    )
    manager._record_admin_fill_follow_up_reveal_block = MagicMock()
    manager._evaluate_action_condition_guard = MagicMock(return_value=(True, None))
    capability = SimpleNamespace(
        allowed=True,
        reason="enabled",
        to_dict=lambda: {"allowed": True},
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.evaluate_product_capability",
        MagicMock(return_value=capability),
    )

    assert manager.reveal_order_slice(CHILD_ID) is None

    manager._record_admin_fill_follow_up_reveal_block.assert_called_once()
    assert manager._record_admin_fill_follow_up_reveal_block.call_args.kwargs[
        "block_category"
    ] == "controlled_admin_authority_required"
    manager._evaluate_action_condition_guard.assert_not_called()


def test_controlled_authority_revalidates_instead_of_obeying_stale_guard_cooldown(
    monkeypatch,
):
    manager = _manager()
    order = manager.in_memory_orders[CHILD_ID]
    order["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ] = {"authority_id": "authority-1"}
    authority = MagicMock(spec=ControlledAdminChildRevealAuthority)
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=order["total_size"])
    manager.build_reveal_execution_plan = MagicMock(
        return_value=RevealExecutionPlan(
            configured_limit_price=101.0,
            submitted_limit_price=101.0,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
            market_source="ticker",
            market_bid=100.0,
            market_ask=100.1,
            post_only=False,
        )
    )
    manager._get_action_guard_blocked_until = MagicMock(
        return_value=__import__("time").monotonic() + 10
    )
    manager._consume_controlled_admin_child_reveal_authority = MagicMock(
        return_value=(True, None)
    )
    manager._resolve_admin_fill_follow_up_reveal_authority = MagicMock(
        return_value={"required": True, "ready": True, "blockers": []}
    )
    manager._evaluate_action_condition_guard = MagicMock(
        return_value=(False, {"reason": "fresh guard rejection"})
    )
    manager._set_action_guard_blocked_until = MagicMock()
    manager._dispatch_lifecycle_event = MagicMock()
    capability = SimpleNamespace(
        allowed=False,
        reason="global stealth reveal disabled",
        to_dict=lambda: {"allowed": False},
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.evaluate_product_capability",
        MagicMock(return_value=capability),
    )

    assert manager.reveal_order_slice(
        CHILD_ID,
        controlled_admin_authority=authority,
    ) is None

    manager._consume_controlled_admin_child_reveal_authority.assert_called_once()
    manager._evaluate_action_condition_guard.assert_called_once()


@pytest.mark.parametrize(
    (
        "authority_market_source",
        "authority_market_age_seconds",
        "expected_result",
        "expected_blocker",
    ),
    [
        ("coinbase_rest_best_bid", 0, CHILD_ID, None),
        ("coinbase_rest_best_bid", 31, None, "live_ticker_bid_stale"),
        (
            "placeholder",
            0,
            None,
            "controlled_admin_authority_market_source_invalid",
        ),
    ],
)
def test_exact_authority_uses_bound_market_when_manager_cache_is_placeholder(
    monkeypatch,
    authority_market_source,
    authority_market_age_seconds,
    expected_result,
    expected_blocker,
):
    manager = StealthOrderManager(db_client=None, log_callback=MagicMock())
    manager.expected_retail_portfolio_id = PORTFOLIO_ID
    order = _manager_order()
    order["limit_price"] = 160.01
    order["reveal_condition_json"]["price_threshold"] = 160.01
    manager.in_memory_orders[CHILD_ID] = order
    market_observed_at = datetime.now(timezone.utc) - timedelta(
        seconds=authority_market_age_seconds
    )
    authority = ControlledAdminChildRevealAuthority(
        stealth_order_id=CHILD_ID,
        root_client_order_id=ROOT_ID,
        prepared_limit_price=160.01,
        total_size=0.00002,
        reference_notional_usdc=0.0032002,
        market_bid="100.0",
        market_source=authority_market_source,
        market_observed_at=market_observed_at,
        portfolio_id=PORTFOLIO_ID,
        correlation_id="corr-1",
        root_audit_id="root-audit-1",
        authority_id="authority-1",
        approval_snapshot_id="approval-1",
        admission_audit_id="admission-1",
        cap_guard_decision_id="cap-1",
        reconciliation_plan_id="reconcile-1",
        batch_id="batch-1",
        batch_slot=1,
    )
    order["anchor_repricing_state_json"][
        "controlled_admin_first_child_reveal_preparation"
    ] = {
        "authority_id": "authority-1",
        "approval_snapshot_id": "approval-1",
        "admission_audit_id": "admission-1",
        "cap_guard_decision_id": "cap-1",
        "reconciliation_plan_id": "reconcile-1",
        "batch_id": "batch-1",
        "batch_slot": 1,
        "root_client_order_id": ROOT_ID,
        "stealth_order_id": CHILD_ID,
        "portfolio_id": PORTFOLIO_ID,
        "correlation_id": "corr-1",
        "root_audit_id": "root-audit-1",
        "market_bid": "100.0",
        "market_source": authority_market_source,
        "market_observed_at": market_observed_at.isoformat(),
    }
    manager._controlled_admin_child_reveal_authorities = {
        "authority-1": authority
    }
    manager.profit_validator = None
    manager._calculate_reveal_size = MagicMock(return_value=0.00002)
    manager.build_reveal_execution_plan = MagicMock(
        return_value=RevealExecutionPlan(
            configured_limit_price=160.01,
            submitted_limit_price=160.01,
            reveal_pricing_policy="configured_limit",
            reveal_price_source="configured_limit",
            fallback_used=False,
            market_source="ticker",
            market_bid=100.0,
            market_ask=100.1,
            post_only=False,
        )
    )
    manager._resolve_admin_fill_follow_up_reveal_authority = MagicMock(
        return_value={"required": True, "ready": True, "blockers": []}
    )
    manager._record_admin_fill_follow_up_reveal_block = MagicMock()
    manager._evaluate_action_condition_guard = MagicMock(return_value=(True, None))
    manager._resolve_target_movement_for_plan = MagicMock(
        return_value=(None, None, "none")
    )
    manager._get_current_market_data = MagicMock(
        return_value={
            "price": None,
            "bid": None,
            "ask": None,
            "time": None,
            "source": "placeholder",
        }
    )
    manager._update_stealth_order = MagicMock()
    manager._record_reveal_event = MagicMock()
    manager._dispatch_lifecycle_event = MagicMock()
    manager.order_placement_hooks = SimpleNamespace(
        call_pre_submission_hooks=MagicMock(),
        call_post_submission_hooks=MagicMock(),
    )
    capability = SimpleNamespace(
        allowed=False,
        reason="global stealth reveal disabled",
        to_dict=lambda: {"allowed": False, "capability": "stealth_reveal"},
    )
    monkeypatch.setattr(
        "core.stealth_order_manager.evaluate_product_capability",
        MagicMock(return_value=capability),
    )
    rest_client = SimpleNamespace(
        place_limit_order=MagicMock(
            return_value={
                "success": True,
                "success_response": {"order_id": "exchange-child-1"},
            }
        )
    )
    monkeypatch.setattr("configuration.REST_CLIENT", rest_client, raising=True)

    assert manager.reveal_order_slice(
        CHILD_ID,
        controlled_admin_authority=authority,
    ) == expected_result

    if expected_result is not None:
        rest_client.place_limit_order.assert_called_once_with(
            product_id="BTC-USDC",
            side="SELL",
            limit_price="160.01",
            base_size="2e-05",
            client_order_id=CHILD_ID,
            post_only=False,
        )
    else:
        rest_client.place_limit_order.assert_not_called()
        assert manager._record_admin_fill_follow_up_reveal_block.call_args.kwargs[
            "block_category"
        ] == expected_blocker
    # The initial admission and immediately-pre-REST revalidation both remain.
    expected_guard_calls = 2 if authority_market_source != "placeholder" else 0
    assert manager._evaluate_action_condition_guard.call_count == expected_guard_calls
    expected_cache_reads = 1 if authority_market_source != "placeholder" else 0
    assert manager._get_current_market_data.call_count == expected_cache_reads
    if authority_market_source != "placeholder":
        manager.order_placement_hooks.call_pre_submission_hooks.assert_called_once()
    else:
        manager.order_placement_hooks.call_pre_submission_hooks.assert_not_called()
    assert manager._controlled_admin_child_reveal_authorities == {}
