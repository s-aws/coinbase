"""Regression: PostgresDB.get_cursor() must serialize cursor access across threads.

Bug seen 2026-04-28 (production logs):

    PostgresDB - ERROR - rolling back: ForeignKeyViolation: insert or update on
        table "partial_fill_progress" violates foreign key constraint ...
    PostgresDB - ERROR - rolling back: InFailedSqlTransaction: current
        transaction is aborted, commands ignored until end of transaction block

Two innocent COIDs (``23077e38-...`` and ``bd2123d8-...``) failed with
``InFailedSqlTransaction`` even though their parent rows existed. They were
victims of a sibling thread's earlier ``ForeignKeyViolation``: the global
``DB_CLIENT`` is a single ``PostgresDB`` instance with one underlying
psycopg2 connection, used concurrently by ``user_event_thread_2/5/6/7``.
Thread A's failed statement aborted the transaction *before* Thread B,
mid-execute on the same connection, could acquire its own cursor.

This test pins the contract: **two threads racing on the same PostgresDB
must never observe a cross-thread ``InFailedSqlTransaction``.** The first
thread's bad SQL must complete its rollback before the second thread's
statement sees the connection.

Runs against the test DB on port 9876 (see ``tests/conftest.py``).
"""
import threading
import time

import psycopg2
import pytest

from database.database import PostgresDB
from tests.conftest import _is_production_database_target


pytestmark = [pytest.mark.regression, pytest.mark.serial]


_TABLE_PARENT = "_thread_safety_parent"
_TABLE_CHILD = "_thread_safety_child"


@pytest.mark.parametrize(
    ("host", "port", "expected"),
    [
        ("127.0.0.1", 5432, True),
        ("localhost", 5432, True),
        ("coinbase-stage-postgres", 5432, True),
        ("coinbase-test-postgres", 5432, True),
        ("coinbase-test-postgres", 9876, False),
    ],
)
def test_production_database_target_guard_is_host_alias_independent(
    host,
    port,
    expected,
):
    """Port 5432 is never safe merely because a Docker hostname changed."""

    assert _is_production_database_target(host, port) is expected


@pytest.fixture
def db():
    """Connected PostgresDB pointing at the test instance."""
    db = PostgresDB()
    db.connect()
    # Clean slate.
    with db.get_cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {_TABLE_CHILD};")
        cur.execute(f"DROP TABLE IF EXISTS {_TABLE_PARENT};")
        cur.execute(
            f"CREATE TABLE {_TABLE_PARENT} (id TEXT PRIMARY KEY);"
        )
        cur.execute(
            f"CREATE TABLE {_TABLE_CHILD} ("
            f"  id TEXT PRIMARY KEY,"
            f"  parent_id TEXT NOT NULL REFERENCES {_TABLE_PARENT}(id)"
            f");"
        )
    yield db
    with db.get_cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {_TABLE_CHILD};")
        cur.execute(f"DROP TABLE IF EXISTS {_TABLE_PARENT};")
    db.disconnect()


def test_fk_violation_in_one_thread_does_not_poison_other_threads(db):
    """Reproduces the 2026-04-28 cascade and proves the lock prevents it.

    Strategy:
      * Thread A: insert child referencing a parent that does NOT exist
                   (raises ForeignKeyViolation).
      * Thread B (started concurrently): insert a valid parent row.
        Without the lock, B's INSERT would run on a connection whose
        transaction is in the aborted state from A, raising
        ``InFailedSqlTransaction``.

    The number of iterations + small jitter give the threads many chances
    to interleave; the test fails if even one of B's inserts ever observes
    ``InFailedSqlTransaction``.
    """
    iterations = 30
    errors_a: list[Exception] = []
    errors_b: list[Exception] = []
    successes_b: list[str] = []

    barrier = threading.Barrier(2)

    def thread_a():
        for i in range(iterations):
            barrier.wait()
            try:
                # Parent 'NEVER' is not present -> ForeignKeyViolation.
                db.execute_update(
                    f"INSERT INTO {_TABLE_CHILD} (id, parent_id) VALUES (%s, %s);",
                    (f"a-{i}", "NEVER"),
                )
            except psycopg2.errors.ForeignKeyViolation:
                pass  # expected
            except Exception as e:  # pragma: no cover - any other error is a bug
                errors_a.append(e)

    def thread_b():
        for i in range(iterations):
            barrier.wait()
            try:
                pid = f"b-{i}"
                db.execute_update(
                    f"INSERT INTO {_TABLE_PARENT} (id) VALUES (%s);", (pid,)
                )
                successes_b.append(pid)
            except Exception as e:
                errors_b.append(e)

    t_a = threading.Thread(target=thread_a, name="fk-violator")
    t_b = threading.Thread(target=thread_b, name="innocent-writer")
    t_a.start()
    t_b.start()
    t_a.join(timeout=30)
    t_b.join(timeout=30)

    # Thread B must see no errors at all -- its writes are unrelated to A's bug.
    assert not errors_b, (
        f"Innocent thread saw {len(errors_b)} error(s); "
        f"first: {type(errors_b[0]).__name__}: {errors_b[0]}"
    )
    assert not errors_a, f"Violator thread saw an unexpected error: {errors_a[0]!r}"
    assert len(successes_b) == iterations, (
        f"Innocent thread only completed {len(successes_b)}/{iterations} writes"
    )

    # Sanity-check the data actually landed.
    rows = db.execute_query(f"SELECT COUNT(*) AS n FROM {_TABLE_PARENT};")
    assert rows[0]["n"] == iterations


def test_get_cursor_uses_a_lock_attribute():
    """Pin the implementation: the lock is a class attribute, not a global.

    A future refactor that drops the lock would silently re-introduce the
    cascade — this test makes that change loud.
    """
    db = PostgresDB()
    assert hasattr(db, "_cursor_lock"), (
        "PostgresDB must expose _cursor_lock to serialize cursor access"
    )
    # RLock so nested calls from the same thread are safe.
    lock = db._cursor_lock
    assert lock.acquire(blocking=False)
    assert lock.acquire(blocking=False), "lock must be re-entrant (RLock)"
    lock.release()
    lock.release()
