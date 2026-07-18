"""Serial PostgreSQL safety tests for operator follow-up-intent persistence.

Every test is pinned to ``coinbase-test-postgres:9876`` and creates a random,
test-owned schema.  No query addresses the operator database on port 5432 and
no Coinbase client is imported or called.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import os
import re
import threading
import time
import uuid

import psycopg2
from psycopg2 import sql
import pytest

from database.database import PostgresDB
from database.order_follow_up_intent import (
    FollowUpIntentCommand,
    FollowUpIntentStoreConflict,
    OperatorFollowUpIntentRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]


TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_NAME = "postgres"
TEST_DB_USER = "postgres"
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
PORTFOLIO_ID = "11111111-2222-4333-8444-555555555555"
KNOWN_PRODUCT_ID = "BTC-USDC"
UNKNOWN_PRODUCT_ID = "FOLLOW-UP-UNKNOWN-PRODUCT"
_SCHEMA_PATTERN = re.compile(r"^test_follow_up_intent_[0-9a-f]{32}$")


def _new_database() -> PostgresDB:
    # Keep these explicit: inheriting a developer shell's DB environment could
    # otherwise turn a synthetic integration test into an operator-data write.
    assert TEST_DB_HOST == "coinbase-test-postgres"
    assert TEST_DB_PORT == 9876
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )


def _raw_connection():
    assert TEST_DB_HOST == "coinbase-test-postgres"
    assert TEST_DB_PORT == 9876
    return psycopg2.connect(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )


@dataclass
class _RepositoryHarness:
    schema: str
    databases: list[PostgresDB] = field(default_factory=list)

    def repository(self) -> OperatorFollowUpIntentRepository:
        database = _new_database()
        self.databases.append(database)
        repository = OperatorFollowUpIntentRepository(
            database,
            configured_spot_portfolio_id=PORTFOLIO_ID,
            schema=self.schema,
        )
        repository.ensure_schema()
        return repository

    @property
    def database(self) -> PostgresDB:
        return self.databases[0]

    def execute(self, query: str, params: tuple = ()) -> None:
        with self.database.get_cursor() as cursor:
            cursor.execute(query, params)

    def scalar(self, query: str, params: tuple = ()) -> int:
        with self.database.get_cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
        return int(row[0])


@pytest.fixture
def repository_harness() -> _RepositoryHarness:
    schema = f"test_follow_up_intent_{uuid.uuid4().hex}"
    assert _SCHEMA_PATTERN.fullmatch(schema)
    admin_database = _new_database()
    admin_database.connect()
    with admin_database.get_cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_parent (
                    id BIGSERIAL PRIMARY KEY,
                    client_order_id VARCHAR(128) UNIQUE NOT NULL,
                    product_id VARCHAR(255) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    size NUMERIC NOT NULL DEFAULT 1,
                    price NUMERIC NOT NULL DEFAULT 1,
                    status VARCHAR(20) NOT NULL,
                    parent_order_id VARCHAR(128),
                    ownership_provenance VARCHAR(64),
                    retail_portfolio_id UUID,
                    correlation_id VARCHAR(255),
                    audit_id VARCHAR(255),
                    exchange_order_id VARCHAR(128),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.fill_ledger (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    derived_trade_key UUID UNIQUE,
                    exchange_trade_id TEXT,
                    exchange_entry_id VARCHAR(80),
                    instrument VARCHAR(32),
                    side VARCHAR(10),
                    quantity NUMERIC NOT NULL DEFAULT 0,
                    price NUMERIC NOT NULL DEFAULT 0,
                    timestamp TIMESTAMPTZ,
                    fees NUMERIC NOT NULL DEFAULT 0,
                    commission_percentage NUMERIC NOT NULL DEFAULT 0,
                    client_order_id VARCHAR(128)
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_match_audit (
                    client_order_id VARCHAR(128),
                    cumulative_quantity NUMERIC NOT NULL DEFAULT 0,
                    derived_size_delta NUMERIC NOT NULL DEFAULT 0,
                    number_of_fills INTEGER NOT NULL DEFAULT 0
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.order_event_stream (
                    client_order_id VARCHAR(128),
                    cumulative_filled_size NUMERIC NOT NULL DEFAULT 0
                )
                """
            ).format(sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.partial_fill_progress (
                    client_order_id VARCHAR(128),
                    last_cumulative_qty_processed NUMERIC NOT NULL DEFAULT 0,
                    carry_remainder_qty NUMERIC NOT NULL DEFAULT 0,
                    last_number_of_fills_seen INTEGER NOT NULL DEFAULT 0,
                    last_completion_pct_seen NUMERIC NOT NULL DEFAULT 0,
                    partial_follow_ups_created INTEGER NOT NULL DEFAULT 0
                )
                """
            ).format(sql.Identifier(schema))
        )

    harness = _RepositoryHarness(schema=schema, databases=[admin_database])
    harness.repository()
    try:
        yield harness
    finally:
        for database in harness.databases[1:]:
            database.disconnect()
        try:
            with admin_database.get_cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )
        finally:
            admin_database.disconnect()


def _insert_order(
    harness: _RepositoryHarness,
    *,
    client_order_id: str,
    product_id: str,
    side: str,
    status: str,
    parent_order_id: str | None,
    ownership_provenance: str,
) -> None:
    harness.execute(
        f"""
        INSERT INTO \"{harness.schema}\".order_parent (
            client_order_id, product_id, side, status, parent_order_id,
            ownership_provenance, retail_portfolio_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            client_order_id,
            product_id,
            side,
            status,
            parent_order_id,
            ownership_provenance,
            PORTFOLIO_ID,
        ),
    )


def _insert_chain(
    harness: _RepositoryHarness,
    *,
    product_id: str = KNOWN_PRODUCT_ID,
) -> tuple[str, str]:
    root_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    _insert_order(
        harness,
        client_order_id=root_id,
        product_id=product_id,
        side="BUY",
        status="OPEN",
        parent_order_id=None,
        ownership_provenance="ADMIN_MANUAL_ROOT",
    )
    _insert_order(
        harness,
        client_order_id=source_id,
        product_id=product_id,
        side="BUY",
        status="OPEN",
        parent_order_id=root_id,
        ownership_provenance="ADMIN_FILL_FOLLOW_UP",
    )
    return root_id, source_id


def _command(
    source_client_order_id: str,
    *,
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
    payload_seed: str = "same-payload",
) -> FollowUpIntentCommand:
    return FollowUpIntentCommand(
        source_client_order_id=source_client_order_id,
        actor_id="operator-test-001",
        roles=("trader",),
        environment="local",
        idempotency_key=idempotency_key or f"idem-{uuid.uuid4()}",
        correlation_id=correlation_id or f"corr-{uuid.uuid4()}",
        operator_intent="attach_single_follow_up_intent",
        payload_sha256=hashlib.sha256(payload_seed.encode("ascii")).hexdigest(),
    )


def test_unknown_product_is_rejected_by_the_default_repository(
    repository_harness: _RepositoryHarness,
):
    """Unknown identifiers must not inherit the permissive Spot default."""

    _root_id, source_id = _insert_chain(
        repository_harness,
        product_id=UNKNOWN_PRODUCT_ID,
    )
    repository = repository_harness.repository()

    with pytest.raises(FollowUpIntentStoreConflict) as exc_info:
        repository.attach(_command(source_id))

    assert exc_info.value.code == "source_product_unknown"
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".operator_follow_up_intent'
    ) == 0


def test_flat_chain_sibling_is_reported_as_attribution_ambiguity(
    repository_harness: _RepositoryHarness,
):
    """A flat-root sibling alone cannot identify the source it followed."""

    root_id, source_id = _insert_chain(repository_harness)
    _insert_order(
        repository_harness,
        client_order_id=str(uuid.uuid4()),
        product_id=KNOWN_PRODUCT_ID,
        side="SELL",
        status="OPEN",
        parent_order_id=root_id,
        ownership_provenance="ADMIN_FILL_FOLLOW_UP",
    )

    eligibility = repository_harness.repository().read(source_id).eligibility

    assert eligibility.eligible is False
    assert eligibility.source_follow_up_child_absent is False
    assert "source_follow_up_child_attribution_ambiguous" in eligibility.blockers
    assert "source_follow_up_child_already_exists" not in eligibility.blockers


@pytest.mark.parametrize("claim_kind", ["OPERATOR_INTENT", "UNKNOWN_ACTIVE_KIND"])
def test_orphan_or_unknown_active_claim_fails_closed(
    repository_harness: _RepositoryHarness,
    claim_kind: str,
):
    _root_id, source_id = _insert_chain(repository_harness)
    repository_harness.execute(
        f"""
        INSERT INTO \"{repository_harness.schema}\".order_follow_up_semantic_claim (
            claim_id, source_client_order_id, claim_kind, trigger, state
        ) VALUES (%s, %s, %s, 'FILLED', 'COMPLETED')
        """,
        (str(uuid.uuid4()), source_id, claim_kind),
    )

    eligibility = repository_harness.repository().read(source_id).eligibility

    assert eligibility.eligible is False
    assert eligibility.automatic_semantic_claim_absent is False
    assert eligibility.blockers
    assert any("claim" in blocker for blocker in eligibility.blockers)


def test_same_idempotency_key_replays_the_same_durable_intent(
    repository_harness: _RepositoryHarness,
):
    _root_id, source_id = _insert_chain(repository_harness)
    repository = repository_harness.repository()
    command = _command(
        source_id,
        idempotency_key="same-key-replay",
        correlation_id="same-key-correlation",
    )

    first = repository.attach(command)
    replay = repository.attach(command)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.record.follow_up_intent_id == first.record.follow_up_intent_id
    assert replay.record.claim_id == first.record.claim_id
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".operator_follow_up_intent'
    ) == 1
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".order_follow_up_semantic_claim'
    ) == 1


def test_distinct_concurrent_requests_use_only_one_source_slot(
    repository_harness: _RepositoryHarness,
):
    _root_id, source_id = _insert_chain(repository_harness)
    repositories = [repository_harness.repository(), repository_harness.repository()]
    commands = [
        _command(
            source_id,
            idempotency_key=f"distinct-concurrent-{index}",
            payload_seed=f"distinct-payload-{index}",
        )
        for index in range(2)
    ]
    barrier = threading.Barrier(2)
    successes = []
    conflicts: list[FollowUpIntentStoreConflict] = []
    unexpected: list[BaseException] = []
    result_lock = threading.Lock()

    def attach(index: int) -> None:
        barrier.wait()
        try:
            result = repositories[index].attach(commands[index])
            with result_lock:
                successes.append(result)
        except FollowUpIntentStoreConflict as exc:
            with result_lock:
                conflicts.append(exc)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            with result_lock:
                unexpected.append(exc)

    threads = [threading.Thread(target=attach, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert unexpected == []
    assert len(successes) == 1
    assert len(conflicts) == 1
    assert conflicts[0].code == "follow_up_intent_already_attached"
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".operator_follow_up_intent'
    ) == 1
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".order_follow_up_semantic_claim'
    ) == 1


def test_status_transition_that_locks_first_serializes_before_attach(
    repository_harness: _RepositoryHarness,
):
    """An earlier authoritative status write wins over an attachment race."""

    _root_id, source_id = _insert_chain(repository_harness)
    repository = repository_harness.repository()
    status_connection = _raw_connection()
    status_cursor = status_connection.cursor()
    status_cursor.execute(
        f'UPDATE "{repository_harness.schema}".order_parent '
        "SET status = 'FILLED' WHERE client_order_id = %s",
        (source_id,),
    )
    started = threading.Event()
    conflicts: list[FollowUpIntentStoreConflict] = []
    unexpected: list[BaseException] = []

    def attach() -> None:
        started.set()
        try:
            repository.attach(_command(source_id))
        except FollowUpIntentStoreConflict as exc:
            conflicts.append(exc)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            unexpected.append(exc)

    thread = threading.Thread(target=attach)
    try:
        thread.start()
        assert started.wait(timeout=2)
        time.sleep(0.15)
        blocked_before_status_commit = thread.is_alive()
        status_connection.commit()
        thread.join(timeout=10)
    finally:
        if not status_connection.closed:
            status_connection.rollback()
        status_cursor.close()
        status_connection.close()

    assert blocked_before_status_commit is True
    assert thread.is_alive() is False
    assert unexpected == []
    assert [conflict.code for conflict in conflicts] == ["source_status_not_open"]
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".operator_follow_up_intent'
    ) == 0


class _PauseBeforeCommitDatabase(PostgresDB):
    """Hold a fill insert transaction open after SQL and before commit."""

    def __init__(self) -> None:
        super().__init__(
            host=TEST_DB_HOST,
            port=TEST_DB_PORT,
            database=TEST_DB_NAME,
            user=TEST_DB_USER,
            password=TEST_DB_PASSWORD,
        )
        self.pause_enabled = False
        self.statement_executed = threading.Event()
        self.allow_commit = threading.Event()

    @contextmanager
    def get_cursor(self):
        with super().get_cursor() as cursor:
            yield cursor
            if self.pause_enabled:
                self.statement_executed.set()
                if not self.allow_commit.wait(timeout=10):
                    raise TimeoutError("test fill writer was not released")


def test_fill_writer_that_starts_first_cannot_race_an_attachment(
    repository_harness: _RepositoryHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    """Positive fill persistence and slot attachment must serialize per source."""

    from database import order as order_database

    _root_id, source_id = _insert_chain(repository_harness)
    repository = repository_harness.repository()
    fill_database = _PauseBeforeCommitDatabase()
    fill_database.connect()
    with fill_database.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("SET search_path TO {}").format(
                sql.Identifier(repository_harness.schema)
            )
        )
    fill_database.pause_enabled = True
    monkeypatch.setattr(order_database, "DB_CLIENT", fill_database)

    fill_results: list[int | None] = []
    attach_results = []
    attach_conflicts: list[FollowUpIntentStoreConflict] = []
    unexpected: list[BaseException] = []

    def write_fill() -> None:
        try:
            fill_results.append(
                order_database.insert_fill_record(
                    derived_trade_key=str(uuid.uuid4()),
                    instrument=KNOWN_PRODUCT_ID,
                    side="BUY",
                    quantity=0.25,
                    price=100,
                    timestamp=datetime.now(timezone.utc),
                    client_order_id=source_id,
                )
            )
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            unexpected.append(exc)

    def attach() -> None:
        try:
            attach_results.append(repository.attach(_command(source_id)))
        except FollowUpIntentStoreConflict as exc:
            attach_conflicts.append(exc)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            unexpected.append(exc)

    fill_thread = threading.Thread(target=write_fill)
    attach_thread = threading.Thread(target=attach)
    try:
        fill_thread.start()
        assert fill_database.statement_executed.wait(timeout=5)
        attach_thread.start()
        # A correct implementation may either block on the source lock or
        # immediately observe a committed semantic fill marker.  Release the
        # held transaction after allowing either path to establish itself.
        time.sleep(0.15)
        fill_database.allow_commit.set()
        fill_thread.join(timeout=10)
        attach_thread.join(timeout=10)
    finally:
        fill_database.allow_commit.set()
        fill_database.disconnect()

    assert fill_thread.is_alive() is False
    assert attach_thread.is_alive() is False
    assert unexpected == []
    assert len(fill_results) == 1
    assert fill_results[0] is not None
    assert attach_results == []
    assert len(attach_conflicts) == 1
    assert attach_conflicts[0].code in {
        "source_has_positive_fill_evidence",
        "source_has_positive_fill_activity",
    }
    assert repository_harness.scalar(
        f'SELECT COUNT(*) FROM "{repository_harness.schema}".operator_follow_up_intent'
    ) == 0
