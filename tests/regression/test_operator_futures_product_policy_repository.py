from __future__ import annotations

import hashlib
import os
import re
import uuid

import pytest
from psycopg2 import sql
from psycopg2.errors import ObjectNotInPrerequisiteState

from application.admin_api.operator_futures_product_policy import (
    OperatorFuturesProductPolicyError,
)
from database.database import PostgresDB
from database.operator_futures_product_policy import (
    OperatorFuturesProductPolicyRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.integration, pytest.mark.serial]

TEST_DB_HOST = "coinbase-test-postgres"
TEST_DB_PORT = 9876
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA_RE = re.compile(
    r"^test_operator_futures_product_policy_[0-9a-f]{32}$"
)


def _database() -> PostgresDB:
    return PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database="postgres",
        user="postgres",
        password=TEST_DB_PASSWORD,
    )


@pytest.fixture
def repository() -> OperatorFuturesProductPolicyRepository:
    schema = f"test_operator_futures_product_policy_{uuid.uuid4().hex}"
    assert _SCHEMA_RE.fullmatch(schema)
    admin = _database()
    admin.connect()
    with admin.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
    repo_db = _database()
    repository = OperatorFuturesProductPolicyRepository(
        repo_db,
        schema=schema,
    )
    repository.ensure_schema()
    try:
        yield repository
    finally:
        repo_db.disconnect()
        with admin.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        admin.disconnect()


def _command(
    repository: OperatorFuturesProductPolicyRepository,
    *,
    action: str,
    product_id: str,
    expected_revision: int,
    key: str,
):
    return repository.apply(
        action=action,
        product_id=product_id,
        expected_revision=expected_revision,
        actor_id="operator-1",
        roles=("admin", "trader"),
        operator_reason="bounded product policy review",
        operator_intent=(
            f"{action.lower()}_exact_futures_product_for_operator_ticket"
        ),
        confirm_exact_product_policy_action=True,
        correlation_id=f"corr-{key}",
        idempotency_key=key,
    )


def test_policy_lifecycle_and_selection_are_revision_bound_and_durable(
    repository: OperatorFuturesProductPolicyRepository,
) -> None:
    initial = repository.read()
    assert initial.revision == 1
    assert initial.selected_product_id is None
    assert {
        item.product_id: item.lifecycle
        for item in initial.products
    } == {
        "AVP-20DEC30-CDE": "PENDING",
        "BIP-20DEC30-CDE": "PENDING",
    }

    approved = _command(
        repository,
        action="APPROVE",
        product_id="BIP-20DEC30-CDE",
        expected_revision=initial.revision,
        key="approve-bip",
    )
    enabled = _command(
        repository,
        action="ENABLE",
        product_id="BIP-20DEC30-CDE",
        expected_revision=approved.revision,
        key="enable-bip",
    )
    selected = _command(
        repository,
        action="SELECT",
        product_id="BIP-20DEC30-CDE",
        expected_revision=enabled.revision,
        key="select-bip",
    )

    assert selected.selected_product_id == "BIP-20DEC30-CDE"
    assert selected.selection is not None
    assert selected.selection.lifecycle == "ENABLED"
    assert selected.selection.policy_revision == selected.revision
    assert len(selected.selection.policy_sha256) == 64
    assert selected.allowed_actions == [
        "APPROVE",
        "DISABLE",
        "ENABLE",
        "RETIRE",
        "SELECT",
    ]

    replayed = _command(
        repository,
        action="SELECT",
        product_id="BIP-20DEC30-CDE",
        expected_revision=enabled.revision,
        key="select-bip",
    )
    assert replayed == selected

    disabled = _command(
        repository,
        action="DISABLE",
        product_id="BIP-20DEC30-CDE",
        expected_revision=selected.revision,
        key="disable-bip",
    )
    assert disabled.selected_product_id is None
    assert disabled.selection is None
    assert next(
        item
        for item in disabled.products
        if item.product_id == "BIP-20DEC30-CDE"
    ).lifecycle == "DISABLED"


def test_policy_rejects_revision_conflicts_and_idempotency_rebinding(
    repository: OperatorFuturesProductPolicyRepository,
) -> None:
    initial = repository.read()
    _command(
        repository,
        action="APPROVE",
        product_id="AVP-20DEC30-CDE",
        expected_revision=initial.revision,
        key="shared-key",
    )

    with pytest.raises(
        OperatorFuturesProductPolicyError,
        match="operator_futures_product_policy_idempotency_conflict",
    ):
        _command(
            repository,
            action="APPROVE",
            product_id="BIP-20DEC30-CDE",
            expected_revision=initial.revision,
            key="shared-key",
        )

    with pytest.raises(
        OperatorFuturesProductPolicyError,
        match="operator_futures_product_policy_revision_conflict",
    ):
        _command(
            repository,
            action="APPROVE",
            product_id="BIP-20DEC30-CDE",
            expected_revision=initial.revision,
            key="stale-revision",
        )


def test_policy_audit_binds_fixed_operator_intent_and_confirmation(
    repository: OperatorFuturesProductPolicyRepository,
) -> None:
    initial = repository.read()
    approved = _command(
        repository,
        action="APPROVE",
        product_id="AVP-20DEC30-CDE",
        expected_revision=initial.revision,
        key="approve-intent-binding",
    )
    expected_intent_hash = hashlib.sha256(
        b"approve_exact_futures_product_for_operator_ticket"
    ).hexdigest()

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            sql.SQL(
                """
                SELECT operator_intent_sha256, confirmations_json
                FROM {}.operator_futures_product_policy_revision
                WHERE revision = %s
                """
            ).format(sql.Identifier(repository.schema)),
            (approved.revision,),
        )
        revision = cursor.fetchone()
        cursor.execute(
            sql.SQL(
                """
                SELECT operator_intent_sha256, confirmations_json
                FROM {}.operator_futures_product_policy_event
                WHERE revision = %s
                """
            ).format(sql.Identifier(repository.schema)),
            (approved.revision,),
        )
        event = cursor.fetchone()

    for stored in (revision, event):
        assert stored[0] == expected_intent_hash
        assert stored[1] == {
            "confirm_exact_product_policy_action": True
        }


def test_retired_product_cannot_be_reenabled_or_selected(
    repository: OperatorFuturesProductPolicyRepository,
) -> None:
    record = repository.read()
    record = _command(
        repository,
        action="APPROVE",
        product_id="AVP-20DEC30-CDE",
        expected_revision=record.revision,
        key="approve-avp",
    )
    record = _command(
        repository,
        action="RETIRE",
        product_id="AVP-20DEC30-CDE",
        expected_revision=record.revision,
        key="retire-avp",
    )

    for action in ("ENABLE", "SELECT"):
        with pytest.raises(
            OperatorFuturesProductPolicyError,
            match="operator_futures_product_policy_transition_invalid",
        ):
            _command(
                repository,
                action=action,
                product_id="AVP-20DEC30-CDE",
                expected_revision=record.revision,
                key=f"{action.lower()}-retired",
            )


@pytest.mark.parametrize(
    ("table_name", "update_column"),
    [
        ("operator_futures_product_policy_revision", "action"),
        ("operator_futures_product_policy_command", "payload_sha256"),
        ("operator_futures_product_policy_event", "event_type"),
    ],
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_policy_history_tables_are_database_append_only(
    repository: OperatorFuturesProductPolicyRepository,
    table_name: str,
    update_column: str,
    operation: str,
) -> None:
    initial = repository.read()
    _command(
        repository,
        action="APPROVE",
        product_id="AVP-20DEC30-CDE",
        expected_revision=initial.revision,
        key=f"append-only-{table_name}-{operation.lower()}",
    )
    qualified_table = sql.SQL("{}.{}").format(
        sql.Identifier(repository.schema),
        sql.Identifier(table_name),
    )

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS row_count FROM {}").format(
                qualified_table
            )
        )
        before = int(cursor.fetchone()[0])

    with pytest.raises(
        ObjectNotInPrerequisiteState,
        match="operator_futures_product_policy_evidence_append_only",
    ):
        with repository.database.get_cursor() as cursor:
            if operation == "UPDATE":
                cursor.execute(
                    sql.SQL("UPDATE {} SET {} = {}").format(
                        qualified_table,
                        sql.Identifier(update_column),
                        sql.Identifier(update_column),
                    )
                )
            else:
                cursor.execute(
                    sql.SQL("DELETE FROM {}").format(qualified_table)
                )

    with repository.database.get_cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT COUNT(*) AS row_count FROM {}").format(
                qualified_table
            )
        )
        assert int(cursor.fetchone()[0]) == before
