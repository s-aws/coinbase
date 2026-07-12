"""Focused sealed-lineage tests for the controlled v10 successor runner."""

from decimal import Decimal
import inspect

import pytest

from tools import run_controlled_admin_spot_root_child_batch as runner


V8_ROOT_TRADE_ID = "2e04bf96-b12c-4625-938e-58c0d15e881d"
V8_ROOT_ENTRY_ID = (
    "1972fbd5f680102e70e6ea4a09f2cbf685140830b3573040884d0ce3897f43c6"
)
V8_ROOT_DERIVED_TRADE_KEY = "77de4354-7b95-59b1-9d33-f7164c60ed1b"
V9_PLAN_SHA256 = "faeae65a024564ac97c12c4acca822fa6dd4abb6085d0020fa67dc035c2d317f"
V9_APPROVAL_ID = (
    "controlled-root-child-successor-v9-dce2a030-ce7f-4133-9900-e25f65d01fd3"
)
V9_BATCH_ID = "57ddc531-7e1e-5680-bb2e-9ed73949e57c"
EXPECTED_V10_AUTHORITY_PARENT = "47092520ccd1cd94b0dd02671b82c7aeb9aeb236"


def _preflight() -> dict[str, object]:
    return {
        "portfolio_id": runner.TEST_PORTFOLIO_ID,
        "wallets": {"USDC": Decimal("993"), "BTC": Decimal("0.00005364")},
        "product": {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "base_min_size": "0.00000001",
            "quote_min_size": "1",
        },
        "best_bid": Decimal("63708.48"),
        "best_ask": Decimal("63708.49"),
        "market": {
            "product_id": runner.PRODUCT_ID,
            "source": "coinbase_rest_get_best_bid_ask_exact_product",
            "observed_at": "2026-07-12T06:36:00+00:00",
        },
    }


def _bindings() -> dict[str, dict[str, object]]:
    return {
        "predecessor_binding": runner.offline_predecessor_binding_fixture(),
        "failed_successor_binding": runner.offline_failed_successor_binding_fixture(),
        "failed_v2_binding": runner.offline_failed_v2_binding_fixture(),
        "failed_v3_binding": runner.offline_failed_v3_binding_fixture(),
        "failed_v4_binding": runner.offline_failed_v4_binding_fixture(),
        "failed_v5_binding": runner.offline_failed_v5_binding_fixture(),
        "failed_v6_binding": runner.offline_failed_v6_binding_fixture(),
        "failed_v7_binding": runner.offline_failed_v7_binding_fixture(),
        "v8_binding": runner.offline_v8_binding_fixture(),
        "v9_binding": runner.offline_v9_binding_fixture(),
        "v10_binding": runner.offline_v10_binding_fixture(),
        "v11_binding": runner.offline_v11_binding_fixture(),
    }


def _reconciled_row(
    *,
    client_order_id: str,
    derived_trade_key: str,
    exchange_trade_id: str,
    exchange_entry_id: str,
) -> dict[str, object]:
    return {
        "client_order_id": client_order_id,
        "derived_trade_key": derived_trade_key,
        "reconciliation_status": "RECONCILED",
        "exchange_trade_id": exchange_trade_id,
        "exchange_entry_id": exchange_entry_id,
        "reconciled_at": "2026-07-12T04:17:02.815730+00:00",
    }


def test_exact_v8_slot_2_pre_reconciled_fill_is_accepted() -> None:
    row = _reconciled_row(
        client_order_id=runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
        derived_trade_key=V8_ROOT_DERIVED_TRADE_KEY,
        exchange_trade_id=V8_ROOT_TRADE_ID,
        exchange_entry_id=V8_ROOT_ENTRY_ID,
    )

    assert runner._classify_fill_ledger_reconciliation_mode(
        [row],
        client_order_id=runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
        exchange_order_id=runner.V8_SLOT_2_ROOT_EXCHANGE_ORDER_ID,
        portfolio_id=runner.TEST_PORTFOLIO_ID,
        expected_filled_size=runner.V8_SLOT_2_ROOT_FILLED_SIZE,
        expected_filled_value=runner.V8_SLOT_2_ROOT_FILLED_VALUE,
        expected_total_fees=runner.V8_SLOT_2_ROOT_TOTAL_FEES,
        expected_identity_pairs={
            V8_ROOT_DERIVED_TRADE_KEY: (
                V8_ROOT_TRADE_ID,
                V8_ROOT_ENTRY_ID,
            )
        },
    ) == "exact_v8_slot_2_root_already_reconciled"


def test_unrelated_pre_reconciled_fill_remains_rejected() -> None:
    row = _reconciled_row(
        client_order_id="00000000-0000-0000-0000-000000000001",
        derived_trade_key="00000000-0000-0000-0000-000000000002",
        exchange_trade_id="00000000-0000-0000-0000-000000000003",
        exchange_entry_id="4" * 64,
    )

    with pytest.raises(
        runner.ProofFailure,
        match="pre_reconciled_fill_not_exact_sealed_root",
    ):
        runner._classify_fill_ledger_reconciliation_mode(
            [row],
            client_order_id=str(row["client_order_id"]),
            exchange_order_id="00000000-0000-0000-0000-000000000005",
            portfolio_id=runner.TEST_PORTFOLIO_ID,
            expected_filled_size=Decimal("0.00001711"),
            expected_filled_value=Decimal("1.0974591127851021"),
            expected_total_fees=Decimal("0.0009328402458673"),
            expected_identity_pairs={
                str(row["derived_trade_key"]): (
                    str(row["exchange_trade_id"]),
                    str(row["exchange_entry_id"]),
                )
            },
        )


def test_only_exact_sealed_pre_reconciled_modes_bypass_canonical_mutation() -> None:
    assert runner.is_exact_sealed_pre_reconciled_mode(
        "exact_carried_root_already_reconciled"
    )
    assert runner.is_exact_sealed_pre_reconciled_mode(
        "exact_v8_slot_2_root_already_reconciled"
    )
    assert not runner.is_exact_sealed_pre_reconciled_mode(
        "arbitrary_root_already_reconciled"
    )


def test_v8_pre_reconciled_fill_rejects_wrong_derived_key_with_right_pair() -> None:
    wrong_key = "00000000-0000-0000-0000-000000000006"
    row = _reconciled_row(
        client_order_id=runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
        derived_trade_key=wrong_key,
        exchange_trade_id=V8_ROOT_TRADE_ID,
        exchange_entry_id=V8_ROOT_ENTRY_ID,
    )

    with pytest.raises(
        runner.ProofFailure,
        match="pre_reconciled_fill_not_exact_sealed_root",
    ):
        runner._classify_fill_ledger_reconciliation_mode(
            [row],
            client_order_id=runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
            exchange_order_id=runner.V8_SLOT_2_ROOT_EXCHANGE_ORDER_ID,
            portfolio_id=runner.TEST_PORTFOLIO_ID,
            expected_filled_size=runner.V8_SLOT_2_ROOT_FILLED_SIZE,
            expected_filled_value=runner.V8_SLOT_2_ROOT_FILLED_VALUE,
            expected_total_fees=runner.V8_SLOT_2_ROOT_TOTAL_FEES,
            expected_identity_pairs={
                wrong_key: (V8_ROOT_TRADE_ID, V8_ROOT_ENTRY_ID)
            },
        )


@pytest.mark.parametrize(
    ("argument", "wrong_value"),
    [
        ("exchange_order_id", "00000000-0000-0000-0000-000000000010"),
        ("portfolio_id", "00000000-0000-0000-0000-000000000011"),
        ("expected_filled_size", Decimal("0.00001712")),
        ("expected_filled_value", Decimal("1.0974591127851022")),
        ("expected_total_fees", Decimal("0.0009328402458674")),
    ],
)
def test_v8_pre_reconciled_fill_rejects_each_wrong_sealed_discriminant(
    argument: str,
    wrong_value: object,
) -> None:
    row = _reconciled_row(
        client_order_id=runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
        derived_trade_key=V8_ROOT_DERIVED_TRADE_KEY,
        exchange_trade_id=V8_ROOT_TRADE_ID,
        exchange_entry_id=V8_ROOT_ENTRY_ID,
    )
    arguments: dict[str, object] = {
        "client_order_id": runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
        "exchange_order_id": runner.V8_SLOT_2_ROOT_EXCHANGE_ORDER_ID,
        "portfolio_id": runner.TEST_PORTFOLIO_ID,
        "expected_filled_size": runner.V8_SLOT_2_ROOT_FILLED_SIZE,
        "expected_filled_value": runner.V8_SLOT_2_ROOT_FILLED_VALUE,
        "expected_total_fees": runner.V8_SLOT_2_ROOT_TOTAL_FEES,
        "expected_identity_pairs": {
            V8_ROOT_DERIVED_TRADE_KEY: (V8_ROOT_TRADE_ID, V8_ROOT_ENTRY_ID)
        },
    }
    arguments[argument] = wrong_value

    with pytest.raises(
        runner.ProofFailure,
        match="pre_reconciled_fill_not_exact_sealed_root",
    ):
        runner._classify_fill_ledger_reconciliation_mode([row], **arguments)


def test_v8_artifact_validator_seals_the_exact_reconciled_trade_identity() -> None:
    assert runner.load_v8_binding() == runner.offline_v8_binding_fixture()
    binding = runner.sealed_v8_slot_2_reconciled_fill_binding()

    assert binding["slot_2_root_derived_trade_key"] == (
        V8_ROOT_DERIVED_TRADE_KEY
    )
    assert binding["slot_2_root_exchange_trade_id"] == V8_ROOT_TRADE_ID
    assert binding["slot_2_root_exchange_entry_id"] == V8_ROOT_ENTRY_ID
    assert binding["slot_2_root_reconciliation_mode"] == (
        "canonical_reconciliation_required"
    )
    assert binding["slot_2_root_reconciliation_rows_updated"] == 1


def test_v8_pre_reconciled_fill_skips_canonical_reconciler_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {
        "status": "FILLED",
        "order_id": runner.V8_SLOT_2_ROOT_EXCHANGE_ORDER_ID,
        "avg_price": "64141.38590211",
        "order_side": "BUY",
        "product_id": runner.PRODUCT_ID,
        "total_fees": str(runner.V8_SLOT_2_ROOT_TOTAL_FEES),
        "filled_value": str(runner.V8_SLOT_2_ROOT_FILLED_VALUE),
        "number_of_fills": "1",
        "client_order_id": runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
        "cumulative_quantity": str(runner.V8_SLOT_2_ROOT_FILLED_SIZE),
        "retail_portfolio_id": runner.TEST_PORTFOLIO_ID,
    }
    ledger_row = {
        "client_order_id": runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
        "derived_trade_key": V8_ROOT_DERIVED_TRADE_KEY,
        "reconciliation_status": "RECONCILED",
        "exchange_trade_id": V8_ROOT_TRADE_ID,
        "exchange_entry_id": V8_ROOT_ENTRY_ID,
        "reconciled_at": "2026-07-12T04:17:02.815730+00:00",
    }
    audit_row = {
        "client_order_id": runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
        "derived_trade_key": V8_ROOT_DERIVED_TRADE_KEY,
    }
    joined_row = {
        "derived_trade_key": V8_ROOT_DERIVED_TRADE_KEY,
        "instrument": runner.PRODUCT_ID,
        "side": "BUY",
        "ledger_quantity": runner.V8_SLOT_2_ROOT_FILLED_SIZE,
        "ledger_price": Decimal("64141.38590211"),
        "ledger_fees": Decimal("0.00093284"),
        "reconciliation_status": "RECONCILED",
        "snapshot_seq": 1,
        "cumulative_quantity": runner.V8_SLOT_2_ROOT_FILLED_SIZE,
        "filled_value": Decimal("1.09745911"),
        "total_fees": Decimal("0.00093284"),
        "number_of_fills": 1,
        "audit_status": "FILLED",
        "derived_size_delta": runner.V8_SLOT_2_ROOT_FILLED_SIZE,
        "derived_value_delta": Decimal("1.09745911"),
        "derived_fee_delta": Decimal("0.00093284"),
        "derived_price": Decimal("64141.38590211"),
        "emitted_fill_ledger_row": True,
        "raw_payload_json": raw,
    }

    class FakeDb:
        def execute_query(self, _sql: str, _params: tuple[str]) -> list[dict]:
            return [joined_row]

    class FakeRest:
        def get_fills(self, **_kwargs: object) -> dict[str, object]:
            return {
                "fills": [
                    {
                        "order_id": runner.V8_SLOT_2_ROOT_EXCHANGE_ORDER_ID,
                        "retail_portfolio_id": runner.TEST_PORTFOLIO_ID,
                        "product_id": runner.PRODUCT_ID,
                        "side": "BUY",
                        "size_in_quote": False,
                        "trade_id": V8_ROOT_TRADE_ID,
                        "entry_id": V8_ROOT_ENTRY_ID,
                        "size": str(runner.V8_SLOT_2_ROOT_FILLED_SIZE),
                        "price": "64141.38590211",
                        "commission": str(runner.V8_SLOT_2_ROOT_TOTAL_FEES),
                    }
                ],
                "cursor": "",
            }

    from database import order

    monkeypatch.setattr(order, "DB_CLIENT", FakeDb())
    monkeypatch.setattr(
        order,
        "get_fills_by_order",
        lambda _client_order_id: [dict(ledger_row)],
    )
    monkeypatch.setattr(
        runner,
        "_read_order_match_audit_rows",
        lambda _db, _client_order_id: [dict(audit_row)],
    )

    evidence = runner._reconcile_fill_ledger_with_exact_rest_fills(
        FakeRest(),
        client_order_id=runner.V8_SLOT_2_ROOT_CLIENT_ORDER_ID,
        exchange_order_id=runner.V8_SLOT_2_ROOT_EXCHANGE_ORDER_ID,
        portfolio_id=runner.TEST_PORTFOLIO_ID,
        expected_filled_size=runner.V8_SLOT_2_ROOT_FILLED_SIZE,
        expected_filled_value=runner.V8_SLOT_2_ROOT_FILLED_VALUE,
        expected_total_fees=runner.V8_SLOT_2_ROOT_TOTAL_FEES,
    )

    assert evidence["reconciliation_mode"] == (
        "exact_v8_slot_2_root_already_reconciled"
    )
    assert evidence["canonical_reconciler_invoked"] is False
    assert evidence["rows_updated"] == 0
    assert evidence["already_reconciled_exact_sealed_root"] is True
    assert evidence["identity_pairs"] == [[V8_ROOT_TRADE_ID, V8_ROOT_ENTRY_ID]]


def test_burned_v9_zero_sdk_failure_is_exactly_sealed() -> None:
    binding = runner.load_v9_binding()

    assert binding == runner.offline_v9_binding_fixture()
    assert binding["plan_sha256"] == V9_PLAN_SHA256
    assert binding["approval_id"] == V9_APPROVAL_ID
    assert binding["batch_id"] == V9_BATCH_ID
    assert binding["attempt_count"] == 0
    assert binding["root_sdk_call_count"] == 0
    assert binding["child_sdk_call_count"] == 0
    assert binding["active_spot_orders_at_closeout"] == []
    assert binding["exchange_safe_to_shutdown"] is True
    assert binding["retry_authorized"] is False
    assert binding["slot_2_child_account_wide_absent"] is True
    assert binding["slot_2_local_phase"] == "v8_prepared_hidden"
    assert len(binding["burned_root_client_order_ids"]) == 8
    assert len(binding["burned_child_client_order_ids"]) == 8


def test_v10_uses_a_fresh_fixed_authority_namespace() -> None:
    assert runner.V10_RUNNER_AUTHORITY_PARENT_COMMIT == (
        EXPECTED_V10_AUTHORITY_PARENT
    )
    assert runner.PLAN_SCHEMA_VERSION == "16"
    assert runner.SUCCESSOR_V12_PLAN_PATH.name.endswith(
        "successor-v12-20260712.plan.json"
    )
    assert runner.GLOBAL_BATCH_MARKER_FILENAME.endswith(
        "successor-v12-20260712.authority.json"
    )
    assert runner.GLOBAL_BATCH_LEDGER_FILENAME.endswith(
        "successor-v12-20260712.attempts.jsonl"
    )


def test_v10_plan_binds_v9_and_burns_every_v9_fresh_identity() -> None:
    preflight = _preflight()
    bindings = _bindings()
    plan = runner.build_successor_live_plan(preflight, **bindings)
    roots, _ = runner.validate_successor_live_plan(
        plan,
        expected_hash=str(plan["plan_sha256"]),
        preflight=preflight,
        **bindings,
    )

    assert plan["schema_version"] == "16"
    assert plan["approval_id"].startswith(
        "controlled-root-child-successor-v12-"
    )
    assert plan["continuation_kind"] == (
        "sealed_v11_terminal_failure_fresh_pairs_slots_5_to_10_v12"
    )
    assert plan["v9_binding"] == bindings["v9_binding"]
    assert plan["v10_binding"] == bindings["v10_binding"]
    assert plan["v11_binding"] == bindings["v11_binding"]
    assert [root["slot"] for root in roots] == list(range(5, 11))
    fresh_ids = {
        value
        for root in roots
        for value in (
            root["root_client_order_id"],
            root["child_client_order_id"],
        )
    }
    burned_v11 = set(bindings["v11_binding"]["burned_root_client_order_ids"])
    burned_v11 |= set(bindings["v11_binding"]["burned_child_client_order_ids"])
    assert not fresh_ids & burned_v11
    assert "recovery_slot_3" not in plan


def test_v10_marker_and_runtime_authority_bind_v9_lineage() -> None:
    preflight = _preflight()
    bindings = _bindings()
    plan = runner.build_successor_live_plan(preflight, **bindings)
    marker = runner.build_global_batch_marker_payload(
        runner.SUCCESSOR_V12_PLAN_PATH,
        confirmed_plan=plan,
        expected_hash=str(plan["plan_sha256"]),
        expected_runner_sha256=str(plan["runner_sha256"]),
        registered_at="2026-07-12T07:00:00+00:00",
        process_id=1,
    )

    assert marker["schema_version"] == "12"
    assert marker["authority"] == (
        "controlled-admin-spot-root-child-successor-v12-batch"
    )
    assert marker["v9_binding"] == bindings["v9_binding"]
    assert marker["v10_binding"] == bindings["v10_binding"]
    assert marker["v11_binding"] == bindings["v11_binding"]
    assert marker["reference_cap_scope"] == runner.V12_REFERENCE_CAP_SCOPE
    runner._validate_authority_plan_structure(
        plan,
        expected_plan_hash=str(plan["plan_sha256"]),
    )


def test_failed_v9_absence_gate_checks_all_fresh_ids_and_recovery_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def local_scope(**kwargs: object) -> dict[str, bool]:
        observed.update(kwargs)
        return {
            "planned_ids_absent_from_order_parent": True,
            "planned_ids_absent_from_stealth_orders": True,
            "planned_ids_absent_from_fill_ledger": True,
            "planned_ids_absent_from_order_match_audit": True,
        }

    monkeypatch.setattr(
        runner,
        "prove_local_scope_with_historical_hidden_child",
        local_scope,
    )
    monkeypatch.setattr(
        runner,
        "read_failed_v6_v7_order_catalog",
        lambda _client: (
            [],
            {
                "authoritative": True,
                "pagination_complete": True,
                "page_count": 1,
                "order_count": 0,
            },
        ),
    )
    monkeypatch.setattr(
        runner,
        "prove_completed_v11_flat_chains_local",
        lambda: {"chain_count": 4, "chains": [], "fresh_local_read": True},
    )

    evidence = runner.prove_failed_v11_unused_client_ids_absent(object())

    assert evidence["planned_client_order_id_count"] == 12
    assert observed["planned_client_order_ids"] == (
        set(runner.FAILED_SUCCESSOR_V11_PLANNED_ROOT_CLIENT_ORDER_IDS[1:])
        | set(runner.FAILED_SUCCESSOR_V11_PLANNED_CHILD_CLIENT_ORDER_IDS[1:])
    )


def test_v10_commit_scope_is_only_runner_focused_tests_and_ownership() -> None:
    runner_path = "tools/run_controlled_admin_spot_root_child_batch.py"
    digest = "c" * 64
    topology = runner.validate_runner_commit_topology(
        production_commit="a" * 40,
        head_commit="b" * 40,
        head_parents=["a" * 40],
        changed_paths=[
            runner_path,
            runner.V9_RUNNER_TEST_PATH,
            runner.V10_RUNNER_TEST_PATH,
            runner.V11_RUNNER_TEST_PATH,
            runner.V12_RUNNER_TEST_PATH,
            runner.OWNERSHIP_MANIFEST_PATH,
        ],
        runner_path=runner_path,
        committed_runner_sha256=digest,
        working_runner_sha256=digest,
        additional_allowed_paths=(
            runner.V9_RUNNER_TEST_PATH,
            runner.V10_RUNNER_TEST_PATH,
            runner.V11_RUNNER_TEST_PATH,
            runner.V12_RUNNER_TEST_PATH,
            runner.OWNERSHIP_MANIFEST_PATH,
        ),
    )

    assert topology["scoped_commit_proven"] is True


def test_slot_2_reconciliation_precedes_enable_ledger_and_child_http() -> None:
    source = inspect.getsource(runner.execute_controlled_batch)

    reconciliation = source.index(
        "fill_reconciliation = _reconcile_fill_ledger_with_exact_rest_fills("
    )
    pre_enable_guard = source.index(
        'slot_result["child_pre_enable_fresh_bid_guard"]'
    )
    child_ledger = source.index("child_attempt = consume_batch_attempt(")
    first_enable = source.index(
        "set_live_service(runtime, enabled=True)",
        child_ledger,
    )
    child_http = source.index(
        "child_status_code, child_response, child_headers = runtime.request("
    )

    assert reconciliation < pre_enable_guard < child_ledger < first_enable < child_http
