from __future__ import annotations

import os
import re
import uuid
import hashlib
import threading
from datetime import datetime

import pytest
from psycopg2 import sql
from psycopg2.errors import CheckViolation

from business.fill_ledger import FillLedger, FillLedgerRepository
from application.admin_api.operator_fill_inventory_repair import (
    FillInventoryCatalogReadResult,
    FillInventoryCatalogSelector,
    FillInventoryRepairSelectorType,
    NormalizedFillCatalogEntry,
    OperatorFillInventoryRepairError,
    build_operator_fill_inventory_repair_case_item,
)
from core.enums import FillInventoryRepairCaseState
from database.database import PostgresDB
from database.fill_ledger_lock import fill_ledger_product_lock_key
from database.operator_fill_inventory_repair import (
    OperatorFillInventoryRepairRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA_PATTERN = re.compile(r"^test_operator_fill_inventory_[0-9a-f]{32}$")
_PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
_PORTFOLIO_HASH = hashlib.sha256(_PORTFOLIO_ID.encode()).hexdigest()


def _new_database() -> PostgresDB:
    assert TEST_DB_HOST == "coinbase-test-postgres"
    assert TEST_DB_PORT == 9876
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )


@pytest.fixture
def repository() -> OperatorFillInventoryRepairRepository:
    schema = f"test_operator_fill_inventory_{uuid.uuid4().hex}"
    assert _SCHEMA_PATTERN.fullmatch(schema)
    database = _new_database()
    database.connect()
    with database.get_cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_parent (
                    client_order_id VARCHAR(40) PRIMARY KEY,
                    product_id VARCHAR(255) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    ownership_provenance VARCHAR(64),
                    retail_portfolio_id UUID,
                    exchange_order_id VARCHAR(128)
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.fill_ledger (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    derived_trade_key UUID NOT NULL UNIQUE,
                    exchange_trade_id TEXT,
                    exchange_entry_id VARCHAR(80),
                    instrument VARCHAR(32) NOT NULL,
                    side VARCHAR(10) NOT NULL
                        CHECK (side IN ('BUY', 'SELL')),
                    quantity DECIMAL(16,8) NOT NULL,
                    price DECIMAL(24,12) NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    fees DECIMAL(16,8) DEFAULT 0,
                    commission_percentage DECIMAL(5,4) DEFAULT 0,
                    client_order_id VARCHAR(128),
                    reconciliation_status VARCHAR(16) NOT NULL DEFAULT
                        'WS_DERIVED'
                        CHECK (
                            reconciliation_status IN (
                                'WS_DERIVED', 'RECONCILED', 'MISMATCH'
                            )
                        ),
                    reconciled_at TIMESTAMP
                )
                """
            ).format(sql.Identifier(schema))
        )
    store = OperatorFillInventoryRepairRepository(
        database,
        schema=schema,
        order_schema=schema,
        fill_schema=schema,
    )
    store.ensure_schema()
    try:
        yield store
    finally:
        with database.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )
        database.disconnect()


def _insert_order(
    repository: OperatorFillInventoryRepairRepository,
    *,
    portfolio_id: str = _PORTFOLIO_ID,
) -> tuple[str, str]:
    client_order_id = str(uuid.uuid4())
    exchange_order_id = str(uuid.uuid4())
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.order_prefix}order_parent (
                client_order_id,
                product_id,
                side,
                status,
                ownership_provenance,
                retail_portfolio_id,
                exchange_order_id
            )
            VALUES (%s, 'BTC-USDC', 'BUY', 'FILLED',
                    'ADMIN_MANUAL_ROOT', %s::uuid, %s)
            """,
            (client_order_id, portfolio_id, exchange_order_id),
        )
    return client_order_id, exchange_order_id


def _selector(
    *,
    client_order_id: str,
    exchange_order_id: str,
) -> FillInventoryCatalogSelector:
    return FillInventoryCatalogSelector(
        selector_type=FillInventoryRepairSelectorType.EXACT_ORDER,
        product_id="BTC-USDC",
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        portfolio_id_sha256=_PORTFOLIO_HASH,
    )


def _entry(
    *,
    client_order_id: str,
    identity: str = "b",
    identity_aliases: list[str] | None = None,
    trade_time: str = "2026-07-22T01:00:00Z",
) -> NormalizedFillCatalogEntry:
    return NormalizedFillCatalogEntry(
        fill_identity_sha256=identity * 64,
        fill_identity_aliases_sha256=(
            identity_aliases or [identity * 64]
        ),
        exchange_order_id_sha256="c" * 64,
        client_order_id=client_order_id,
        product_id="BTC-USDC",
        side="BUY",
        quantity="0.01",
        price="100",
        fees="0.01",
        trade_time=trade_time,
        portfolio_id_sha256=_PORTFOLIO_HASH,
    )


def test_repository_applies_and_rolls_back_exact_import_batch(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    case = repository.create_case(
        selector=_selector(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
        ),
        actor_id="operator",
        operator_reason="repair exact fill",
        correlation_id="fill-repair-create",
    )
    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="fill-repair-refresh",
    )
    repository.record_fill_page_call(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.record_fill_page_returned(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
    )
    ready = repository.complete_refresh(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        catalog=FillInventoryCatalogReadResult(
            entries=[_entry(client_order_id=client_order_id)],
            page_count=1,
            pagination_complete=True,
            unmatched_fill_count=0,
        ),
        actor_id="operator",
        correlation_id="fill-repair-refresh",
    )

    assert ready["state"] == FillInventoryRepairCaseState.PLAN_READY.value
    assert ready["missing_fill_count"] == 1
    assert ready["existing_fill_count"] == 0
    assert ready["fill_read_page_count"] == 1
    assert ready["last_cycle_fill_read_page_count"] == 1
    assert ready["plan_sha256"]

    applied = repository.apply_import(
        case_id=case["case_id"],
        expected_revision=ready["revision"],
        plan_sha256=ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="apply reviewed fill import",
        correlation_id="fill-repair-apply",
    )
    assert applied["state"] == FillInventoryRepairCaseState.APPLIED.value
    assert applied["imported_fill_count"] == 1

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) AS count FROM {repository.fill_prefix}fill_ledger"
        )
        assert cursor.fetchone()[0] == 1
    projection = repository.get_projection("BTC-USDC")
    assert projection is not None
    assert projection["open_quantity"] == "0.01"
    assert projection["average_cost_basis"] == "101"

    rolled_back = repository.rollback_import(
        case_id=case["case_id"],
        expected_revision=applied["revision"],
        plan_sha256=applied["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="rollback exact import batch",
        correlation_id="fill-repair-rollback",
    )
    assert rolled_back["state"] == FillInventoryRepairCaseState.ROLLED_BACK.value
    assert rolled_back["rolled_back_fill_count"] == 1
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) AS count FROM {repository.fill_prefix}fill_ledger"
        )
        assert cursor.fetchone()[0] == 0
    assert repository.get_projection("BTC-USDC") is None


def test_repository_preview_is_idempotent_for_existing_fill_hash(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.fill_prefix}fill_ledger (
                derived_trade_key,
                exchange_fill_identity_sha256,
                instrument,
                side,
                quantity,
                price,
                timestamp,
                fees,
                client_order_id,
                reconciliation_status
            )
            VALUES (%s::uuid, %s, 'BTC-USDC', 'BUY', 0.01, 100,
                    '2026-07-22T01:00:00Z', 0.01, %s, 'RECONCILED')
            """,
            (str(uuid.uuid4()), "b" * 64, client_order_id),
        )
    case = repository.create_case(
        selector=_selector(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
        ),
        actor_id="operator",
        operator_reason="verify idempotent import",
        correlation_id="fill-repair-create",
    )
    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="fill-repair-refresh",
    )
    repository.record_fill_page_call(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.record_fill_page_returned(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
    )
    ready = repository.complete_refresh(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        catalog=FillInventoryCatalogReadResult(
            entries=[_entry(client_order_id=client_order_id)],
            page_count=1,
            pagination_complete=True,
            unmatched_fill_count=0,
        ),
        actor_id="operator",
        correlation_id="fill-repair-refresh",
    )

    assert ready["missing_fill_count"] == 0
    assert ready["existing_fill_count"] == 1
    assert ready["plan"]["apply_available"] is False


def test_repository_matches_a_legacy_trade_id_identity_alias(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    legacy_trade_id = str(uuid.uuid4())
    legacy_trade_hash = hashlib.sha256(
        legacy_trade_id.encode("utf-8")
    ).hexdigest()
    primary_hash = "7" * 64
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.fill_prefix}fill_ledger (
                derived_trade_key, exchange_trade_id, instrument, side,
                quantity, price, timestamp, fees, client_order_id,
                reconciliation_status
            )
            VALUES (%s::uuid, %s::uuid, 'BTC-USDC', 'BUY', 0.01, 100,
                    '2026-07-22T01:00:00Z', 0.01, %s, 'RECONCILED')
            """,
            (str(uuid.uuid4()), legacy_trade_id, client_order_id),
        )
    case = _ready_case(
        repository,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        identity="7",
        identity_aliases=[primary_hash, legacy_trade_hash],
    )
    assert case["missing_fill_count"] == 0
    assert case["existing_fill_count"] == 1
    assert case["plan"]["apply_available"] is False


def test_applied_fill_claims_every_identity_alias_durably(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    entry_hash = "7" * 64
    trade_hash = "8" * 64
    ready = _ready_case(
        repository,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        identity="7",
        identity_aliases=[entry_hash, trade_hash],
    )
    repository.apply_import(
        case_id=ready["case_id"],
        expected_revision=ready["revision"],
        plan_sha256=ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="claim both documented aliases",
        correlation_id="apply-aliases",
    )

    product_case = repository.create_case(
        selector=FillInventoryCatalogSelector(
            selector_type=FillInventoryRepairSelectorType.PRODUCT,
            product_id="BTC-USDC",
            portfolio_id_sha256=_PORTFOLIO_HASH,
        ),
        actor_id="operator",
        operator_reason="verify alternate alias replay",
        correlation_id="alternate-alias",
    )
    claimed = repository.begin_refresh(
        case_id=product_case["case_id"],
        expected_revision=product_case["revision"],
        actor_id="operator",
        correlation_id="alternate-alias",
    )
    repository.record_fill_page_call(
        case_id=product_case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.record_fill_page_returned(
        case_id=product_case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
    )
    replay = repository.complete_refresh(
        case_id=product_case["case_id"],
        expected_revision=claimed["revision"],
        catalog=FillInventoryCatalogReadResult(
            entries=[
                _entry(
                    client_order_id=client_order_id,
                    identity="8",
                )
            ],
            page_count=1,
            pagination_complete=True,
            unmatched_fill_count=0,
        ),
        actor_id="operator",
        correlation_id="alternate-alias",
    )

    assert replay["missing_fill_count"] == 0
    assert replay["existing_fill_count"] == 1
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM {repository.prefix}operator_fill_inventory_identity_alias
            WHERE operator_import_batch_id = %s::uuid
            """,
            (ready["case_id"],),
        )
        assert cursor.fetchone()[0] == 2


def test_repository_restart_consumes_refresh_cycle_without_replaying_read(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    case = repository.create_case(
        selector=_selector(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
        ),
        actor_id="operator",
        operator_reason="restart-safe refresh",
        correlation_id="fill-repair-create",
    )
    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="fill-repair-refresh",
    )
    assert claimed["cycle_count"] == 1
    assert claimed["fill_read_logical_count"] == 1
    repository.record_fill_page_call(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    with pytest.raises(ValueError, match="fill_inventory_page_claim_conflict"):
        repository.record_fill_page_call(
            case_id=case["case_id"],
            expected_revision=claimed["revision"],
            page_ordinal=1,
            cursor_sha256=None,
        )

    repository.ensure_schema()
    recovered = repository.get_case(case["case_id"])
    assert recovered["state"] == FillInventoryRepairCaseState.BLOCKED.value
    assert recovered["cycle_count"] == 1
    assert recovered["fill_read_logical_count"] == 1
    assert recovered["fill_read_page_count"] == 1
    assert recovered["last_cycle_fill_read_page_count"] == 1
    assert (
        recovered["diagnostic_code"]
        == "fill_inventory_refresh_interrupted_unknown"
    )
    events = repository.list_events(case["case_id"])
    assert events[-1]["evidence"]["coinbase_read_state"] == (
        "UNKNOWN_AFTER_PAGE_CLAIM"
    )
    assert "coinbase_read_ran" not in events[-1]["evidence"]


def test_repository_restart_distinguishes_a_returned_fill_page(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    case = repository.create_case(
        selector=_selector(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
        ),
        actor_id="operator",
        operator_reason="restart after returned page",
        correlation_id="returned-page-restart",
    )
    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="returned-page-restart",
    )
    repository.record_fill_page_call(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.record_fill_page_returned(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
    )

    repository.ensure_schema()
    recovered = repository.get_case(case["case_id"])
    assert (
        recovered["diagnostic_code"]
        == "fill_inventory_refresh_interrupted_returned"
    )
    event = repository.list_events(case["case_id"])[-1]
    assert event["evidence"]["coinbase_read_state"] == "RETURNED"
    assert event["evidence"]["coinbase_read_ran"] is True


def test_goal_global_cycle_budget_cannot_be_multiplied_across_cases(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    first_client, first_exchange = _insert_order(repository)
    second_client, second_exchange = _insert_order(repository)
    first = repository.create_case(
        selector=_selector(
            client_order_id=first_client,
            exchange_order_id=first_exchange,
        ),
        actor_id="operator",
        operator_reason="first selector",
        correlation_id="first-case",
    )
    second = repository.create_case(
        selector=_selector(
            client_order_id=second_client,
            exchange_order_id=second_exchange,
        ),
        actor_id="operator",
        operator_reason="second selector",
        correlation_id="second-case",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_fill_inventory_goal_ledger
            SET cycle_count = 9, fill_read_logical_count = 9
            WHERE goal_id = 'operator_fill_ledger_and_inventory_repair_v1'
            """
        )

    repository.begin_refresh(
        case_id=first["case_id"],
        expected_revision=first["revision"],
        actor_id="operator",
        correlation_id="tenth-cycle",
    )
    with pytest.raises(
        ValueError,
        match="fill_inventory_goal_cycles_exhausted",
    ):
        repository.begin_refresh(
            case_id=second["case_id"],
            expected_revision=second["revision"],
            actor_id="operator",
            correlation_id="eleventh-cycle",
        )
    assert repository.get_goal_budget() == {
        "goal_cycle_count": 10,
        "goal_cycle_limit": 10,
        "goal_fill_read_logical_count": 10,
        "goal_fill_read_page_count": 0,
    }


def test_projection_excludes_other_portfolio_and_unowned_fill_rows(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    foreign_client, _ = _insert_order(
        repository,
        portfolio_id="99999999-2222-4333-8444-555555555555",
    )
    with repository.database.get_cursor() as cursor:
        for identity, client_id, quantity in (
            ("d" * 64, client_order_id, "0.01"),
            ("e" * 64, foreign_client, "5"),
            ("f" * 64, str(uuid.uuid4()), "7"),
        ):
            cursor.execute(
                f"""
                INSERT INTO {repository.fill_prefix}fill_ledger (
                    derived_trade_key, exchange_fill_identity_sha256,
                    instrument, side, quantity, price, timestamp, fees,
                    client_order_id, reconciliation_status
                )
                VALUES (%s::uuid, %s, 'BTC-USDC', 'BUY', %s, 100,
                        '2026-07-22T00:00:00Z', 0, %s, 'RECONCILED')
                """,
                (str(uuid.uuid4()), identity, quantity, client_id),
            )
    case = repository.create_case(
        selector=_selector(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
        ),
        actor_id="operator",
        operator_reason="portfolio scoped projection",
        correlation_id="portfolio-scope",
    )
    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="portfolio-scope-refresh",
    )
    repository.record_fill_page_call(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.record_fill_page_returned(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
    )
    ready = repository.complete_refresh(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        catalog=FillInventoryCatalogReadResult(
            entries=[
                _entry(client_order_id=client_order_id, identity="b")
            ],
            page_count=1,
            pagination_complete=True,
            unmatched_fill_count=0,
        ),
        actor_id="operator",
        correlation_id="portfolio-scope-refresh",
    )
    assert ready["plan"]["projection"]["fill_count"] == 2
    assert ready["plan"]["projection"]["open_quantity"] == "0.02"


def test_apply_rejects_a_ledger_baseline_changed_after_review(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    case = _ready_case(
        repository,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        identity="b",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.fill_prefix}fill_ledger (
                derived_trade_key, exchange_fill_identity_sha256,
                instrument, side, quantity, price, timestamp, fees,
                client_order_id, reconciliation_status
            )
            VALUES (%s::uuid, %s, 'BTC-USDC', 'BUY', 0.02, 101,
                    '2026-07-22T00:30:00Z', 0, %s, 'RECONCILED')
            """,
            (str(uuid.uuid4()), "c" * 64, client_order_id),
        )

    with pytest.raises(
        ValueError,
        match="fill_inventory_apply_baseline_changed",
    ):
        repository.apply_import(
            case_id=case["case_id"],
            expected_revision=case["revision"],
            plan_sha256=case["plan_sha256"],
            current_portfolio_id_sha256=_PORTFOLIO_HASH,
            actor_id="operator",
            operator_reason="stale reviewed plan",
            correlation_id="stale-plan",
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM {repository.fill_prefix}fill_ledger
            WHERE exchange_fill_identity_sha256 = %s
            """,
            ("b" * 64,),
        )
        assert cursor.fetchone()[0] == 0


def test_chained_apply_and_rollback_restores_projection_provenance(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    first_client, first_exchange = _insert_order(repository)
    second_client, second_exchange = _insert_order(repository)
    first_ready = _ready_case(
        repository,
        client_order_id=first_client,
        exchange_order_id=first_exchange,
        identity="4",
        trade_time="2026-07-22T01:00:00Z",
    )
    first_applied = repository.apply_import(
        case_id=first_ready["case_id"],
        expected_revision=first_ready["revision"],
        plan_sha256=first_ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="apply first reviewed plan",
        correlation_id="apply-first",
    )
    first_projection = repository.get_projection("BTC-USDC")

    second_ready = _ready_case(
        repository,
        client_order_id=second_client,
        exchange_order_id=second_exchange,
        identity="5",
        trade_time="2026-07-22T02:00:00Z",
    )
    second_applied = repository.apply_import(
        case_id=second_ready["case_id"],
        expected_revision=second_ready["revision"],
        plan_sha256=second_ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="apply second reviewed plan",
        correlation_id="apply-second",
    )
    assert repository.get_projection("BTC-USDC")["fill_count"] == 2

    repository.rollback_import(
        case_id=second_applied["case_id"],
        expected_revision=second_applied["revision"],
        plan_sha256=second_applied["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="restore first projection",
        correlation_id="rollback-second",
    )
    assert repository.get_projection("BTC-USDC") == first_projection
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT source_case_id::text
            FROM {repository.prefix}operator_fill_inventory_projection
            WHERE product_id = 'BTC-USDC'
            """
        )
        assert cursor.fetchone()[0] == first_applied["case_id"]


def test_rollback_rejects_saved_prior_projection_json_drift(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    first_client, first_exchange = _insert_order(repository)
    second_client, second_exchange = _insert_order(repository)
    first_ready = _ready_case(
        repository,
        client_order_id=first_client,
        exchange_order_id=first_exchange,
        identity="a",
        trade_time="2026-07-22T01:00:00Z",
    )
    repository.apply_import(
        case_id=first_ready["case_id"],
        expected_revision=first_ready["revision"],
        plan_sha256=first_ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="establish prior projection",
        correlation_id="prior-json-first",
    )
    second_ready = _ready_case(
        repository,
        client_order_id=second_client,
        exchange_order_id=second_exchange,
        identity="b",
        trade_time="2026-07-22T02:00:00Z",
    )
    second_applied = repository.apply_import(
        case_id=second_ready["case_id"],
        expected_revision=second_ready["revision"],
        plan_sha256=second_ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="capture prior projection",
        correlation_id="prior-json-second",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_fill_inventory_import_batch
            SET before_projection_json = jsonb_set(
                before_projection_json,
                '{{total_fees}}',
                '"999"'::jsonb
            )
            WHERE case_id = %s::uuid
            """,
            (second_applied["case_id"],),
        )

    with pytest.raises(
        ValueError,
        match="fill_inventory_rollback_prior_projection_changed",
    ):
        repository.rollback_import(
            case_id=second_applied["case_id"],
            expected_revision=second_applied["revision"],
            plan_sha256=second_applied["plan_sha256"],
            current_portfolio_id_sha256=_PORTFOLIO_HASH,
            actor_id="operator",
            operator_reason="reject altered prior bytes",
            correlation_id="prior-json-rollback",
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM {repository.fill_prefix}fill_ledger
            WHERE operator_import_batch_id = %s::uuid
            """,
            (second_applied["case_id"],),
        )
        assert cursor.fetchone()[0] == 1


def test_rollback_rejects_saved_prior_projection_source_drift(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    first_client, first_exchange = _insert_order(repository)
    second_client, second_exchange = _insert_order(repository)
    first_ready = _ready_case(
        repository,
        client_order_id=first_client,
        exchange_order_id=first_exchange,
        identity="c",
        trade_time="2026-07-22T01:00:00Z",
    )
    repository.apply_import(
        case_id=first_ready["case_id"],
        expected_revision=first_ready["revision"],
        plan_sha256=first_ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="establish source provenance",
        correlation_id="prior-source-first",
    )
    second_ready = _ready_case(
        repository,
        client_order_id=second_client,
        exchange_order_id=second_exchange,
        identity="d",
        trade_time="2026-07-22T02:00:00Z",
    )
    second_applied = repository.apply_import(
        case_id=second_ready["case_id"],
        expected_revision=second_ready["revision"],
        plan_sha256=second_ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="capture source provenance",
        correlation_id="prior-source-second",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_fill_inventory_import_batch
            SET before_projection_source_case_id = %s::uuid
            WHERE case_id = %s::uuid
            """,
            (str(uuid.uuid4()), second_applied["case_id"]),
        )

    with pytest.raises(
        ValueError,
        match="fill_inventory_rollback_prior_projection_changed",
    ):
        repository.rollback_import(
            case_id=second_applied["case_id"],
            expected_revision=second_applied["revision"],
            plan_sha256=second_applied["plan_sha256"],
            current_portfolio_id_sha256=_PORTFOLIO_HASH,
            actor_id="operator",
            operator_reason="reject altered prior source",
            correlation_id="prior-source-rollback",
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM {repository.fill_prefix}fill_ledger
            WHERE operator_import_batch_id = %s::uuid
            """,
            (second_applied["case_id"],),
        )
        assert cursor.fetchone()[0] == 1


def test_apply_rejects_invalid_existing_projection_hash(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    first_client, first_exchange = _insert_order(repository)
    second_client, second_exchange = _insert_order(repository)
    first_ready = _ready_case(
        repository,
        client_order_id=first_client,
        exchange_order_id=first_exchange,
        identity="e",
        trade_time="2026-07-22T01:00:00Z",
    )
    repository.apply_import(
        case_id=first_ready["case_id"],
        expected_revision=first_ready["revision"],
        plan_sha256=first_ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="establish projection",
        correlation_id="existing-projection-first",
    )
    second_ready = _ready_case(
        repository,
        client_order_id=second_client,
        exchange_order_id=second_exchange,
        identity="f",
        trade_time="2026-07-22T02:00:00Z",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_fill_inventory_projection
            SET projection_json = jsonb_set(
                projection_json,
                '{{total_fees}}',
                '"999"'::jsonb
            )
            WHERE product_id = 'BTC-USDC'
            """
        )

    with pytest.raises(
        ValueError,
        match="fill_inventory_apply_existing_projection_invalid",
    ):
        repository.apply_import(
            case_id=second_ready["case_id"],
            expected_revision=second_ready["revision"],
            plan_sha256=second_ready["plan_sha256"],
            current_portfolio_id_sha256=_PORTFOLIO_HASH,
            actor_id="operator",
            operator_reason="reject invalid prior projection",
            correlation_id="existing-projection-second",
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM {repository.fill_prefix}fill_ledger
            WHERE operator_import_batch_id = %s::uuid
            """,
            (second_ready["case_id"],),
        )
        assert cursor.fetchone()[0] == 0


def test_migrated_unverified_prior_snapshot_cannot_be_rolled_back(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    first_client, first_exchange = _insert_order(repository)
    second_client, second_exchange = _insert_order(repository)
    first_ready = _ready_case(
        repository,
        client_order_id=first_client,
        exchange_order_id=first_exchange,
        identity="1",
        trade_time="2026-07-22T01:00:00Z",
    )
    repository.apply_import(
        case_id=first_ready["case_id"],
        expected_revision=first_ready["revision"],
        plan_sha256=first_ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="establish legacy prior projection",
        correlation_id="legacy-prior-first",
    )
    second_ready = _ready_case(
        repository,
        client_order_id=second_client,
        exchange_order_id=second_exchange,
        identity="2",
        trade_time="2026-07-22T02:00:00Z",
    )
    second_applied = repository.apply_import(
        case_id=second_ready["case_id"],
        expected_revision=second_ready["revision"],
        plan_sha256=second_ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="simulate legacy batch",
        correlation_id="legacy-prior-second",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            ALTER TABLE
                {repository.prefix}operator_fill_inventory_import_batch
            DROP COLUMN IF EXISTS
                before_projection_snapshot_verified CASCADE
            """
        )
        cursor.execute(
            f"""
            ALTER TABLE
                {repository.prefix}operator_fill_inventory_import_batch
            DROP COLUMN before_projection_snapshot_sha256 CASCADE
            """
        )

    repository.ensure_schema()

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT before_projection_snapshot_verified,
                   before_projection_snapshot_sha256
            FROM {repository.prefix}operator_fill_inventory_import_batch
            WHERE case_id = %s::uuid
            """,
            (second_applied["case_id"],),
        )
        verified, snapshot_sha256 = cursor.fetchone()
        assert verified is False
        assert snapshot_sha256 is None

    with pytest.raises(
        ValueError,
        match="fill_inventory_rollback_prior_projection_unverified",
    ):
        repository.rollback_import(
            case_id=second_applied["case_id"],
            expected_revision=second_applied["revision"],
            plan_sha256=second_applied["plan_sha256"],
            current_portfolio_id_sha256=_PORTFOLIO_HASH,
            actor_id="operator",
            operator_reason="reject unauthenticated legacy snapshot",
            correlation_id="legacy-prior-rollback",
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM {repository.fill_prefix}fill_ledger
            WHERE operator_import_batch_id = %s::uuid
            """,
            (second_applied["case_id"],),
        )
        assert cursor.fetchone()[0] == 1


def test_database_rejects_verified_prior_snapshot_without_hash(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    ready = _ready_case(
        repository,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        identity="3",
    )
    applied = repository.apply_import(
        case_id=ready["case_id"],
        expected_revision=ready["revision"],
        plan_sha256=ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="establish verified snapshot",
        correlation_id="verified-snapshot",
    )

    with pytest.raises(CheckViolation):
        with repository.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE
                    {repository.prefix}operator_fill_inventory_import_batch
                SET before_projection_snapshot_sha256 = NULL
                WHERE case_id = %s::uuid
                """,
                (applied["case_id"],),
            )


def test_rollback_rejects_same_case_projection_content_drift(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    ready = _ready_case(
        repository,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        identity="9",
    )
    applied = repository.apply_import(
        case_id=ready["case_id"],
        expected_revision=ready["revision"],
        plan_sha256=ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="apply reviewed batch",
        correlation_id="projection-drift",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_fill_inventory_projection
            SET projection_json = jsonb_set(
                projection_json,
                '{{total_fees}}',
                '"999"'::jsonb
            )
            WHERE product_id = 'BTC-USDC'
            """
        )

    with pytest.raises(
        ValueError,
        match="fill_inventory_rollback_superseded",
    ):
        repository.rollback_import(
            case_id=applied["case_id"],
            expected_revision=applied["revision"],
            plan_sha256=applied["plan_sha256"],
            current_portfolio_id_sha256=_PORTFOLIO_HASH,
            actor_id="operator",
            operator_reason="must reject drift",
            correlation_id="projection-drift",
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM {repository.fill_prefix}fill_ledger
            WHERE operator_import_batch_id = %s::uuid
            """,
            (applied["case_id"],),
        )
        assert cursor.fetchone()[0] == 1


def test_rollback_rejects_same_count_import_ownership_substitution(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    ready = _ready_case(
        repository,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        identity="6",
        identity_aliases=["6" * 64, "7" * 64],
    )
    applied = repository.apply_import(
        case_id=ready["case_id"],
        expected_revision=ready["revision"],
        plan_sha256=ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="apply exact owned batch",
        correlation_id="ownership-substitution",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.fill_prefix}fill_ledger
            SET exchange_fill_identity_sha256 = %s
            WHERE operator_import_batch_id = %s::uuid
            """,
            ("8" * 64, applied["case_id"]),
        )
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_fill_inventory_identity_alias
            SET canonical_identity_sha256 = %s
            WHERE operator_import_batch_id = %s::uuid
              AND alias_sha256 = %s
            """,
            ("8" * 64, applied["case_id"], "7" * 64),
        )

    with pytest.raises(
        ValueError,
        match="fill_inventory_rollback_fill_ownership_mismatch",
    ):
        repository.rollback_import(
            case_id=applied["case_id"],
            expected_revision=applied["revision"],
            plan_sha256=applied["plan_sha256"],
            current_portfolio_id_sha256=_PORTFOLIO_HASH,
            actor_id="operator",
            operator_reason="reject same-count substitution",
            correlation_id="ownership-substitution",
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            SELECT COUNT(*) FROM {repository.fill_prefix}fill_ledger
            WHERE operator_import_batch_id = %s::uuid
            """,
            (applied["case_id"],),
        )
        assert cursor.fetchone()[0] == 1


def test_rollback_rejects_non_batch_ledger_drift_after_apply(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    ready = _ready_case(
        repository,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        identity="3",
    )
    applied = repository.apply_import(
        case_id=ready["case_id"],
        expected_revision=ready["revision"],
        plan_sha256=ready["plan_sha256"],
        current_portfolio_id_sha256=_PORTFOLIO_HASH,
        actor_id="operator",
        operator_reason="apply before later fill",
        correlation_id="later-ledger-fill",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            INSERT INTO {repository.fill_prefix}fill_ledger (
                derived_trade_key, exchange_fill_identity_sha256,
                instrument, side, quantity, price, timestamp, fees,
                client_order_id, reconciliation_status
            )
            VALUES (%s::uuid, %s, 'BTC-USDC', 'BUY', 0.02, 101,
                    '2026-07-22T03:00:00Z', 0, %s, 'RECONCILED')
            """,
            (str(uuid.uuid4()), "2" * 64, client_order_id),
        )

    with pytest.raises(
        ValueError,
        match="fill_inventory_rollback_ledger_changed",
    ):
        repository.rollback_import(
            case_id=applied["case_id"],
            expected_revision=applied["revision"],
            plan_sha256=applied["plan_sha256"],
            current_portfolio_id_sha256=_PORTFOLIO_HASH,
            actor_id="operator",
            operator_reason="reject stale projection restore",
            correlation_id="later-ledger-fill",
        )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) FROM {repository.fill_prefix}fill_ledger"
        )
        assert cursor.fetchone()[0] == 2


def test_canonical_fill_writer_waits_for_repair_product_transaction_lock(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    writer_database = _new_database()
    writer_database.connect()
    with writer_database.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("SET search_path TO {}").format(
                sql.Identifier(repository.schema)
            )
        )
    writer = FillLedgerRepository.__new__(FillLedgerRepository)
    writer.db_client = writer_database
    entered = threading.Event()
    finished = threading.Event()
    result: list[bool] = []
    original_execute_update = writer_database.execute_update

    def observed_execute_update(query, params=None):
        entered.set()
        return original_execute_update(query, params)

    writer_database.execute_update = observed_execute_update
    fill = FillLedger(
        derived_trade_key=str(uuid.uuid4()),
        instrument="BTC-USDC",
        side="BUY",
        quantity=0.01,
        price=100,
        timestamp=datetime(2026, 7, 22, 4, 0, 0),
    )

    def append_fill() -> None:
        try:
            result.append(writer.append_fill(fill))
        finally:
            finished.set()

    thread = threading.Thread(target=append_fill, daemon=True)
    try:
        with repository.database.get_cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (fill_ledger_product_lock_key("BTC-USDC"),),
            )
            thread.start()
            assert entered.wait(timeout=2)
            assert finished.wait(timeout=0.25) is False
        assert finished.wait(timeout=5)
        thread.join(timeout=1)
        assert result == [True]
    finally:
        writer_database.disconnect()


def test_repository_schema_rejects_unallowlisted_public_diagnostic(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    case = repository.create_case(
        selector=_selector(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
        ),
        actor_id="operator",
        operator_reason="verify fixed diagnostic constraint",
        correlation_id="fixed-diagnostic",
    )
    with pytest.raises(CheckViolation):
        with repository.database.get_cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {repository.prefix}operator_fill_inventory_repair_case
                SET diagnostic_code = %s
                WHERE case_id = %s::uuid
                """,
                ("not_allowlisted_private_text", case["case_id"]),
            )
    assert (
        repository.get_case(case["case_id"])["diagnostic_code"]
        == "fill_inventory_case_created"
    )


def test_public_readback_rejects_tampered_internal_plan_binding(
    repository: OperatorFillInventoryRepairRepository,
) -> None:
    client_order_id, exchange_order_id = _insert_order(repository)
    ready = _ready_case(
        repository,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        identity="1",
    )
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {repository.prefix}operator_fill_inventory_repair_case
            SET plan_json = jsonb_set(
                plan_json,
                '{{diagnostic_code}}',
                '"fill_inventory_catalog_unknown"'::jsonb
            )
            WHERE case_id = %s::uuid
            """,
            (ready["case_id"],),
        )
    with pytest.raises(
        OperatorFillInventoryRepairError,
        match="fill_inventory_plan_binding_invalid",
    ):
        build_operator_fill_inventory_repair_case_item(
            repository.get_case(ready["case_id"]),
            events=[],
            portfolio_binding_verified=True,
        )


def _ready_case(
    repository: OperatorFillInventoryRepairRepository,
    *,
    client_order_id: str,
    exchange_order_id: str,
    identity: str,
    identity_aliases: list[str] | None = None,
    trade_time: str = "2026-07-22T01:00:00Z",
) -> dict:
    case = repository.create_case(
        selector=_selector(
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
        ),
        actor_id="operator",
        operator_reason="prepare reviewed case",
        correlation_id=f"prepare-{identity}",
    )
    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id=f"refresh-{identity}",
    )
    repository.record_fill_page_call(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    repository.record_fill_page_returned(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        page_ordinal=1,
    )
    return repository.complete_refresh(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        catalog=FillInventoryCatalogReadResult(
            entries=[
                _entry(
                    client_order_id=client_order_id,
                    identity=identity,
                    identity_aliases=identity_aliases,
                    trade_time=trade_time,
                )
            ],
            page_count=1,
            pagination_complete=True,
            unmatched_fill_count=0,
        ),
        actor_id="operator",
        correlation_id=f"refresh-{identity}",
    )
