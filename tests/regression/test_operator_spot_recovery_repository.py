from __future__ import annotations

import hashlib
import os
import re
import uuid

import pytest
from psycopg2 import sql

from application.admin_api.operator_spot_recovery import (
    OperatorSpotRecoveryService,
    SpotRecoveryFillEvidence,
    SpotRecoveryLocalOrderEvidence,
    SpotRecoveryOrderEvidence,
    build_spot_recovery_plan,
)
from core.enums import (
    OrderOwnershipProvenance,
    OrderStatus,
    SpotRecoveryCaseState,
)
from database.database import PostgresDB
from database.operator_spot_recovery import OperatorSpotRecoveryRepository


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA_PATTERN = re.compile(r"^test_operator_spot_recovery_[0-9a-f]{32}$")


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
def repository() -> OperatorSpotRecoveryRepository:
    schema = f"test_operator_spot_recovery_{uuid.uuid4().hex}"
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
                    exchange_order_id VARCHAR(64)
                )
                """
            ).format(sql.Identifier(schema))
        )
    store = OperatorSpotRecoveryRepository(
        database,
        schema=schema,
        order_schema=schema,
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
    repository: OperatorSpotRecoveryRepository,
    *,
    status: OrderStatus,
) -> tuple[str, str]:
    client_order_id = str(uuid.uuid4())
    portfolio_id = str(uuid.uuid4())
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
            VALUES (%s, 'BTC-USDC', 'BUY', %s, %s, %s::uuid, %s)
            """,
            (
                client_order_id,
                status.value,
                OrderOwnershipProvenance.ADMIN_MANUAL_ROOT.value,
                portfolio_id,
                str(uuid.uuid4()),
            ),
        )
    return client_order_id, portfolio_id


def _plan(
    *,
    client_order_id: str,
    portfolio_id: str,
    local_status: OrderStatus,
    exchange_status: OrderStatus,
    fill_count: int = 1,
):
    return build_spot_recovery_plan(
        local=SpotRecoveryLocalOrderEvidence(
            client_order_id=client_order_id,
            product_id="BTC-USDC",
            side="BUY",
            status=local_status,
            ownership_provenance=OrderOwnershipProvenance.ADMIN_MANUAL_ROOT,
            portfolio_id_sha256=hashlib.sha256(portfolio_id.encode()).hexdigest(),
            exchange_order_id_present=True,
        ),
        order=SpotRecoveryOrderEvidence(
            exact_identity_match=True,
            authoritative=True,
            confirmed_absent=False,
            status=exchange_status,
            page_count=1,
        ),
        fills=SpotRecoveryFillEvidence(
            authoritative=True,
            fill_count=fill_count,
            page_count=1,
            pagination_complete=True,
        ),
    )


def test_repository_single_use_cancel_claim_can_release_only_before_boundary(
    repository: OperatorSpotRecoveryRepository,
) -> None:
    client_order_id, portfolio_id = _insert_order(
        repository,
        status=OrderStatus.CANCELLED,
    )
    case = repository.create_case(
        client_order_id=client_order_id,
        product_id="BTC-USDC",
        portfolio_id_sha256=hashlib.sha256(portfolio_id.encode()).hexdigest(),
        actor_id="operator",
        operator_reason="active orphan recovery",
        correlation_id="correlation-create",
    )
    refresh = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="correlation-refresh",
    )
    ready = repository.complete_refresh(
        case_id=case["case_id"],
        expected_revision=refresh["revision"],
        plan=_plan(
            client_order_id=client_order_id,
            portfolio_id=portfolio_id,
            local_status=OrderStatus.CANCELLED,
            exchange_status=OrderStatus.OPEN,
            fill_count=0,
        ),
        order_read_page_count=1,
        fill_read_page_count=1,
        diagnostic_code="recovery_cancel_active_orphan_ready",
        actor_id="operator",
        correlation_id="correlation-refresh",
    )

    claimed = repository.begin_cancel(
        case_id=case["case_id"],
        expected_revision=ready["revision"],
        plan_sha256=ready["plan_sha256"],
        actor_id="operator",
        operator_reason="cancel exact active orphan",
        correlation_id="correlation-cancel-1",
    )
    assert claimed["state"] == SpotRecoveryCaseState.CANCEL_PENDING.value
    assert claimed["cancel_allowance_consumed"] is True
    assert claimed["cancel_call_count"] == 0

    released = repository.record_cancel_result(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        actor_id="operator",
        correlation_id="correlation-cancel-1",
        exchange_call_ran=False,
        accepted=False,
        diagnostic_code="recovery_cancel_preboundary_blocked",
    )
    assert released["state"] == SpotRecoveryCaseState.PLAN_READY.value
    assert released["cancel_allowance_consumed"] is False
    assert released["cancel_call_count"] == 0

    reclaimed = repository.begin_cancel(
        case_id=case["case_id"],
        expected_revision=released["revision"],
        plan_sha256=released["plan_sha256"],
        actor_id="operator",
        operator_reason="cancel exact active orphan",
        correlation_id="correlation-cancel-2",
    )
    terminal = repository.record_cancel_result(
        case_id=case["case_id"],
        expected_revision=reclaimed["revision"],
        actor_id="operator",
        correlation_id="correlation-cancel-2",
        exchange_call_ran=True,
        accepted=True,
        diagnostic_code="recovery_cancel_confirmed",
    )
    assert terminal["state"] == SpotRecoveryCaseState.CANCELLED.value
    assert terminal["cancel_allowance_consumed"] is True
    assert terminal["cancel_call_count"] == 1
    with pytest.raises(ValueError, match="recovery_cancel_not_claimable"):
        repository.begin_cancel(
            case_id=case["case_id"],
            expected_revision=terminal["revision"],
            plan_sha256=terminal["plan_sha256"],
            actor_id="operator",
            operator_reason="must not replay",
            correlation_id="correlation-cancel-3",
        )


def test_repository_restart_closes_interrupted_refresh_without_reusing_cycle(
    repository: OperatorSpotRecoveryRepository,
) -> None:
    client_order_id, portfolio_id = _insert_order(
        repository,
        status=OrderStatus.OPEN,
    )
    case = repository.create_case(
        client_order_id=client_order_id,
        product_id="BTC-USDC",
        portfolio_id_sha256=hashlib.sha256(portfolio_id.encode()).hexdigest(),
        actor_id="operator",
        operator_reason="restart recovery",
        correlation_id="correlation-create",
    )
    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="correlation-refresh",
    )

    repository.ensure_schema()

    recovered = repository.get_case(case["case_id"])
    assert recovered is not None
    assert recovered["state"] == SpotRecoveryCaseState.BLOCKED.value
    assert recovered["revision"] == claimed["revision"] + 1
    assert recovered["refresh_count"] == 1
    assert recovered["order_read_logical_count"] == 1
    assert recovered["diagnostic_code"] == "recovery_refresh_interrupted"


def test_repository_restart_consumes_interrupted_cancel_as_unknown(
    repository: OperatorSpotRecoveryRepository,
) -> None:
    client_order_id, portfolio_id = _insert_order(
        repository,
        status=OrderStatus.CANCELLED,
    )
    case = repository.create_case(
        client_order_id=client_order_id,
        product_id="BTC-USDC",
        portfolio_id_sha256=hashlib.sha256(portfolio_id.encode()).hexdigest(),
        actor_id="operator",
        operator_reason="active orphan recovery",
        correlation_id="correlation-create",
    )
    refresh = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="correlation-refresh",
    )
    ready = repository.complete_refresh(
        case_id=case["case_id"],
        expected_revision=refresh["revision"],
        plan=_plan(
            client_order_id=client_order_id,
            portfolio_id=portfolio_id,
            local_status=OrderStatus.CANCELLED,
            exchange_status=OrderStatus.OPEN,
            fill_count=0,
        ),
        order_read_page_count=1,
        fill_read_page_count=1,
        diagnostic_code="recovery_cancel_active_orphan_ready",
        actor_id="operator",
        correlation_id="correlation-refresh",
    )
    claimed = repository.begin_cancel(
        case_id=case["case_id"],
        expected_revision=ready["revision"],
        plan_sha256=ready["plan_sha256"],
        actor_id="operator",
        operator_reason="cancel exact active orphan",
        correlation_id="correlation-cancel",
    )

    repository.ensure_schema()

    recovered = repository.get_case(case["case_id"])
    assert recovered is not None
    assert recovered["state"] == SpotRecoveryCaseState.UNKNOWN.value
    assert recovered["revision"] == claimed["revision"] + 1
    assert recovered["cancel_allowance_consumed"] is True
    assert recovered["cancel_call_count"] == 1
    assert recovered["diagnostic_code"] == "recovery_cancel_interrupted_unknown"


def test_repository_persists_only_hashed_portfolio_scope_and_sanitized_plan(
    repository: OperatorSpotRecoveryRepository,
) -> None:
    client_order_id, portfolio_id = _insert_order(
        repository,
        status=OrderStatus.OPEN,
    )
    case = repository.create_case(
        client_order_id=client_order_id,
        product_id="BTC-USDC",
        portfolio_id_sha256=hashlib.sha256(portfolio_id.encode()).hexdigest(),
        actor_id="operator",
        operator_reason="inspect exact root",
        correlation_id="correlation-create",
    )

    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="correlation-refresh",
    )
    completed = repository.complete_refresh(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        plan=_plan(
            client_order_id=client_order_id,
            portfolio_id=portfolio_id,
            local_status=OrderStatus.OPEN,
            exchange_status=OrderStatus.FILLED,
        ),
        order_read_page_count=1,
        fill_read_page_count=1,
        diagnostic_code="recovery_plan_ready",
        actor_id="operator",
        correlation_id="correlation-refresh",
    )

    assert completed["state"] == SpotRecoveryCaseState.PLAN_READY.value
    assert completed["portfolio_id_sha256"] == hashlib.sha256(
        portfolio_id.encode()
    ).hexdigest()
    assert completed["plan"]["to_status"] == OrderStatus.FILLED.value
    stored = repository.database.execute_query(
        f"""
        SELECT portfolio_id_sha256, plan_json::text AS plan_json
        FROM {repository.prefix}operator_spot_recovery_case
        WHERE case_id = %s::uuid
        """,
        (case["case_id"],),
    )[0]
    assert portfolio_id not in stored["plan_json"]
    assert stored["portfolio_id_sha256"] != portfolio_id


def test_repository_prevents_duplicate_active_case_for_same_order(
    repository: OperatorSpotRecoveryRepository,
) -> None:
    client_order_id, portfolio_id = _insert_order(
        repository,
        status=OrderStatus.OPEN,
    )
    kwargs = {
        "client_order_id": client_order_id,
        "product_id": "BTC-USDC",
        "portfolio_id_sha256": hashlib.sha256(
            portfolio_id.encode()
        ).hexdigest(),
        "actor_id": "operator",
        "operator_reason": "inspect exact root",
        "correlation_id": "correlation-create",
    }
    repository.create_case(**kwargs)

    with pytest.raises(ValueError, match="recovery_case_already_active"):
        repository.create_case(**kwargs)


def test_repository_applies_and_safely_rolls_back_terminal_status_repair(
    repository: OperatorSpotRecoveryRepository,
) -> None:
    client_order_id, portfolio_id = _insert_order(
        repository,
        status=OrderStatus.CANCELLED,
    )
    case = repository.create_case(
        client_order_id=client_order_id,
        product_id="BTC-USDC",
        portfolio_id_sha256=hashlib.sha256(portfolio_id.encode()).hexdigest(),
        actor_id="operator",
        operator_reason="terminal correction",
        correlation_id="correlation-create",
    )
    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="correlation-refresh",
    )
    ready = repository.complete_refresh(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        plan=_plan(
            client_order_id=client_order_id,
            portfolio_id=portfolio_id,
            local_status=OrderStatus.CANCELLED,
            exchange_status=OrderStatus.FILLED,
        ),
        order_read_page_count=1,
        fill_read_page_count=1,
        diagnostic_code="recovery_plan_ready",
        actor_id="operator",
        correlation_id="correlation-refresh",
    )

    applied = repository.apply_plan(
        case_id=case["case_id"],
        expected_revision=ready["revision"],
        actor_id="operator",
        operator_reason="apply reviewed terminal correction",
        correlation_id="correlation-apply",
    )
    assert applied["state"] == SpotRecoveryCaseState.APPLIED.value
    assert repository.read_local_order(client_order_id)["status"] == "FILLED"

    rolled_back = repository.rollback_plan(
        case_id=case["case_id"],
        expected_revision=applied["revision"],
        actor_id="operator",
        operator_reason="restore reviewed terminal snapshot",
        correlation_id="correlation-rollback",
    )
    assert rolled_back["state"] == SpotRecoveryCaseState.ROLLED_BACK.value
    assert repository.read_local_order(client_order_id)["status"] == "CANCELLED"


def test_repository_blocks_unsafe_nonterminal_status_rollback(
    repository: OperatorSpotRecoveryRepository,
) -> None:
    client_order_id, portfolio_id = _insert_order(
        repository,
        status=OrderStatus.OPEN,
    )
    case = repository.create_case(
        client_order_id=client_order_id,
        product_id="BTC-USDC",
        portfolio_id_sha256=hashlib.sha256(portfolio_id.encode()).hexdigest(),
        actor_id="operator",
        operator_reason="terminal correction",
        correlation_id="correlation-create",
    )
    claimed = repository.begin_refresh(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="correlation-refresh",
    )
    ready = repository.complete_refresh(
        case_id=case["case_id"],
        expected_revision=claimed["revision"],
        plan=_plan(
            client_order_id=client_order_id,
            portfolio_id=portfolio_id,
            local_status=OrderStatus.OPEN,
            exchange_status=OrderStatus.FILLED,
        ),
        order_read_page_count=1,
        fill_read_page_count=1,
        diagnostic_code="recovery_plan_ready",
        actor_id="operator",
        correlation_id="correlation-refresh",
    )
    applied = repository.apply_plan(
        case_id=case["case_id"],
        expected_revision=ready["revision"],
        actor_id="operator",
        operator_reason="apply reviewed terminal correction",
        correlation_id="correlation-apply",
    )

    with pytest.raises(ValueError, match="recovery_rollback_unsafe"):
        repository.rollback_plan(
            case_id=case["case_id"],
            expected_revision=applied["revision"],
            actor_id="operator",
            operator_reason="unsafe rollback attempt",
            correlation_id="correlation-rollback",
        )

    assert repository.read_local_order(client_order_id)["status"] == "FILLED"


class _RecoveryRestClient:
    def __init__(self, *, order_status: str = "FILLED") -> None:
        self.order_status = order_status
        self.get_order_calls: list[str] = []
        self.fill_calls: list[dict] = []

    def get_order(self, exchange_order_id: str):
        self.get_order_calls.append(exchange_order_id)
        return {
            "order": {
                "client_order_id": self.client_order_id,
                "order_id": exchange_order_id,
                "product_id": "BTC-USDC",
                "status": self.order_status,
                "retail_portfolio_id": self.portfolio_id,
            }
        }

    def list_fills(self, **kwargs):
        self.fill_calls.append(dict(kwargs))
        if len(self.fill_calls) == 1:
            return {
                "fills": [
                    {
                        "order_id": kwargs["order_id"],
                        "product_id": kwargs["product_id"],
                    }
                ],
                "cursor": "page-2",
                "has_next": True,
            }
        return {
            "fills": [
                {
                    "order_id": kwargs["order_id"],
                    "product_id": kwargs["product_id"],
                }
            ],
            "has_next": False,
        }


def test_service_refresh_uses_one_logical_order_and_fill_read(
    repository: OperatorSpotRecoveryRepository,
) -> None:
    client_order_id, portfolio_id = _insert_order(
        repository,
        status=OrderStatus.OPEN,
    )
    rest_client = _RecoveryRestClient()
    rest_client.client_order_id = client_order_id
    rest_client.portfolio_id = portfolio_id
    service = OperatorSpotRecoveryService(
        repository=repository,
        rest_client=rest_client,
        rest_client_available=True,
        configured_portfolio_id=portfolio_id,
    )
    case = service.create_case(
        client_order_id=client_order_id,
        actor_id="operator",
        operator_reason="review exact root",
        correlation_id="correlation-create",
    )

    refreshed = service.refresh_case(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="correlation-refresh",
        manual_live_acknowledgement=True,
    )

    assert refreshed["state"] == SpotRecoveryCaseState.PLAN_READY.value
    assert refreshed["plan"]["kind"] == "SET_LOCAL_STATUS"
    assert refreshed["plan"]["fill_count"] == 2
    assert refreshed["refresh_count"] == 1
    assert refreshed["order_read_logical_count"] == 1
    assert refreshed["fill_read_logical_count"] == 1
    assert len(rest_client.get_order_calls) == 1
    assert len(rest_client.fill_calls) == 2


def test_service_never_persists_transport_exception_text(
    repository: OperatorSpotRecoveryRepository,
) -> None:
    client_order_id, portfolio_id = _insert_order(
        repository,
        status=OrderStatus.OPEN,
    )

    class _FailingRestClient:
        def get_order(self, _exchange_order_id: str):
            raise RuntimeError("TOP-SECRET-TRANSPORT-TEXT")

    service = OperatorSpotRecoveryService(
        repository=repository,
        rest_client=_FailingRestClient(),
        rest_client_available=True,
        configured_portfolio_id=portfolio_id,
    )
    case = service.create_case(
        client_order_id=client_order_id,
        actor_id="operator",
        operator_reason="review exact root",
        correlation_id="correlation-create",
    )

    failed = service.refresh_case(
        case_id=case["case_id"],
        expected_revision=case["revision"],
        actor_id="operator",
        correlation_id="correlation-refresh",
        manual_live_acknowledgement=True,
    )

    assert failed["state"] == SpotRecoveryCaseState.BLOCKED.value
    assert failed["diagnostic_code"] == "order_read_failed"
    rows = repository.database.execute_query(
        f"""
        SELECT
            row_to_json(recovery_case)::text AS case_text
        FROM {repository.prefix}operator_spot_recovery_case AS recovery_case
        WHERE case_id = %s::uuid
        """,
        (case["case_id"],),
    )
    assert "TOP-SECRET-TRANSPORT-TEXT" not in rows[0]["case_text"]
