from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid

import pytest
from psycopg2 import sql

from application.admin_api.operator_product_catalog import (
    ProductCatalogReadResult,
    normalize_product_catalog_item,
)
from application.admin_api.operator_stealth_definition import (
    OperatorStealthDefinitionError,
    normalize_stealth_definition_terms,
)
from database.database import PostgresDB
from database.operator_product_catalog import OperatorProductCatalogRepository
from database.operator_stealth_definition import (
    OperatorStealthDefinitionRepository,
)


pytestmark = [pytest.mark.regression, pytest.mark.serial]

TEST_DB_HOST = os.environ.get("COINBASE_DB_HOST", "coinbase-test-postgres")
TEST_DB_PORT = int(os.environ.get("COINBASE_DB_PORT", "9876"))
TEST_DB_NAME = os.environ.get("COINBASE_DB_NAME", "postgres")
TEST_DB_USER = os.environ.get("COINBASE_DB_USER", "postgres")
TEST_DB_PASSWORD = os.environ.get("COINBASE_DB_PASSWORD", "postgres")
_SCHEMA = re.compile(r"^test_operator_stealth_def_[0-9a-f]{32}$")


def _terms(*, threshold: str = "59000", target: str = "0.005"):
    return normalize_stealth_definition_terms(
        name="BTC patient bid",
        product_id="BTC-USDC",
        side="BUY",
        total_size="0.0001",
        limit_price="60000",
        reveal_condition_type="PRICE",
        reveal_price_threshold=threshold,
        reveal_direction="BELOW",
        hold_duration_seconds=5,
        delay_seconds=None,
        reveal_pricing_policy="CONFIGURED_LIMIT",
        sizing_mode="FIXED",
        follow_up_reveal_direction="OPPOSITE",
        target_movement=target,
        target_movement_type="P",
        max_order_replacements=2,
        allow_partial_fills=False,
        post_only=True,
    )


def _seed_catalog(catalog: OperatorProductCatalogRepository) -> None:
    cycle = catalog.begin_refresh(
        expected_active_revision_id=None,
        actor_id="operator",
        operator_reason="seed test product",
        correlation_id="stealth-definition-product-refresh",
        idempotency_key="stealth-definition-product-refresh",
        acknowledgement=True,
    )
    catalog.record_page_call(
        cycle_id=cycle["cycle_id"],
        page_ordinal=1,
        cursor_sha256=None,
    )
    catalog.record_page_returned(
        cycle_id=cycle["cycle_id"],
        page_ordinal=1,
    )
    proposed = catalog.complete_refresh(
        cycle_id=cycle["cycle_id"],
        read_result=ProductCatalogReadResult(
            products=[
                normalize_product_catalog_item(
                    {
                        "product_id": "BTC-USDC",
                        "product_type": "SPOT",
                        "base_currency_id": "BTC",
                        "quote_currency_id": "USDC",
                        "base_increment": "0.00000001",
                        "quote_increment": "0.01",
                        "price_increment": "0.01",
                        "base_min_size": "0.00001",
                        "base_max_size": "10",
                        "quote_min_size": "1",
                        "quote_max_size": "1000000",
                        "display_name": "BTC-USDC",
                        "status": "ONLINE",
                        "is_disabled": False,
                        "trading_disabled": False,
                        "cancel_only": False,
                        "limit_only": False,
                        "post_only": False,
                        "view_only": False,
                    }
                )
            ],
            page_count=1,
            pagination_complete=True,
        ),
        actor_id="operator",
        correlation_id=cycle["correlation_id"],
    )
    approved = catalog.approve_revision(
        revision_id=proposed["revision_id"],
        expected_revision=proposed["revision"],
        snapshot_sha256=proposed["snapshot_sha256"],
        actor_id="operator",
        operator_reason="approve test product",
        correlation_id="stealth-definition-product-approve",
        idempotency_key="stealth-definition-product-approve",
        acknowledgement=True,
    )
    catalog.change_product_lifecycle(
        product_id="BTC-USDC",
        action="ENABLE",
        expected_active_revision_id=approved["revision_id"],
        expected_active_revision=approved["revision"],
        actor_id="operator",
        operator_reason="enable test product",
        correlation_id="stealth-definition-product-enable",
        idempotency_key="stealth-definition-product-enable",
        acknowledgement=True,
    )


@pytest.fixture
def repository() -> OperatorStealthDefinitionRepository:
    schema = f"test_operator_stealth_def_{uuid.uuid4().hex}"
    assert _SCHEMA.fullmatch(schema)
    database = PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )
    database.connect()
    with database.get_cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE {}.stealth_orders (
                    stealth_order_id UUID PRIMARY KEY,
                    status VARCHAR(32) NOT NULL
                )
                """
            ).format(sql.Identifier(schema))
        )
    catalog = OperatorProductCatalogRepository(database, schema=schema)
    catalog.ensure_schema()
    _seed_catalog(catalog)
    repo = OperatorStealthDefinitionRepository(database, schema=schema)
    repo.ensure_schema()
    try:
        yield repo
    finally:
        with database.get_cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(
                    sql.Identifier(schema)
                )
            )
        database.disconnect()


def _create(
    repository: OperatorStealthDefinitionRepository,
    *,
    key: str = "stealth-definition-create",
):
    return repository.create_definition(
        definition_id=None,
        terms=_terms(),
        portfolio_scope_sha256="a" * 64,
        actor_id="operator",
        operator_reason="create reviewed definition",
        correlation_id=f"{key}-correlation",
        idempotency_key=key,
        acknowledgement=True,
    )


def test_create_edit_cancel_are_revision_bound_and_exactly_idempotent(
    repository: OperatorStealthDefinitionRepository,
) -> None:
    created = _create(repository)
    replay = _create(repository)

    assert created["lifecycle_state"] == "DRAFT"
    assert created["runtime_classification"] == "UNMATERIALIZED"
    assert created["allowed_actions"] == ["EDIT", "CANCEL", "EXPORT", "CLEAR"]
    assert replay["definition_id"] == created["definition_id"]
    assert replay["command_replayed"] is True
    assert created["exchange_call_count"] == 0
    assert created["exchange_mutation_count"] == 0

    edited = repository.edit_definition(
        definition_id=created["definition_id"],
        expected_revision=1,
        terms=_terms(threshold="58500", target="0.006"),
        actor_id="operator",
        operator_reason="adjust reviewed threshold",
        correlation_id="stealth-definition-edit-correlation",
        idempotency_key="stealth-definition-edit",
        acknowledgement=True,
    )
    assert edited["revision"] == 2
    assert edited["reveal_price_threshold"] == "58500"
    assert edited["target_movement"] == "0.006"

    cancelled = repository.cancel_definition(
        definition_id=created["definition_id"],
        expected_revision=2,
        actor_id="operator",
        operator_reason="cancel local draft",
        correlation_id="stealth-definition-cancel-correlation",
        idempotency_key="stealth-definition-cancel",
        acknowledgement=True,
    )
    assert cancelled["lifecycle_state"] == "CANCELLED"
    assert cancelled["revision"] == 3
    assert cancelled["allowed_actions"] == []

    events, total = repository.list_events(
        definition_id=created["definition_id"],
        limit=25,
        offset=0,
    )
    assert total == 3
    assert [event["event_type"] for event in reversed(events)] == [
        "STEALTH_DEFINITION_CREATED",
        "STEALTH_DEFINITION_EDITED",
        "STEALTH_DEFINITION_CANCELLED",
    ]


def test_materialized_runtime_row_blocks_every_local_mutation_and_routes(
    repository: OperatorStealthDefinitionRepository,
) -> None:
    created = _create(repository)
    with repository.database.get_cursor() as cursor:
        cursor.execute(
            f"""
            ALTER TABLE {repository.prefix}stealth_orders
            DISABLE TRIGGER operator_stealth_runtime_identity_guard
            """
        )
        cursor.execute(
            f"""
            INSERT INTO {repository.prefix}stealth_orders (
                stealth_order_id, status
            ) VALUES (%s::uuid, 'REVEALED')
            """,
            (created["definition_id"],),
        )
        cursor.execute(
            f"""
            ALTER TABLE {repository.prefix}stealth_orders
            ENABLE TRIGGER operator_stealth_runtime_identity_guard
            """
        )

    detail = repository.get_definition(created["definition_id"])
    assert detail["runtime_classification"] == "REVEALED"
    assert detail["blocked_navigation"] == "MOVEMENT_REPRICING"
    assert detail["allowed_actions"] == []

    with pytest.raises(OperatorStealthDefinitionError) as exc_info:
        repository.cancel_definition(
            definition_id=created["definition_id"],
            expected_revision=1,
            actor_id="operator",
            operator_reason="must fail closed",
            correlation_id="materialized-cancel-correlation",
            idempotency_key="materialized-cancel",
            acknowledgement=True,
        )
    assert exc_info.value.code == "stealth_definition_materialized"


def test_clear_is_atomic_for_an_exact_revision_set(
    repository: OperatorStealthDefinitionRepository,
) -> None:
    first = _create(repository, key="clear-create-one")
    second = _create(repository, key="clear-create-two")

    cleared = repository.clear_definitions(
        selections=[
            (first["definition_id"], 1),
            (second["definition_id"], 1),
        ],
        actor_id="operator",
        operator_reason="clear selected local drafts",
        correlation_id="clear-definitions-correlation",
        idempotency_key="clear-definitions",
        acknowledgement=True,
    )
    assert cleared["cleared_count"] == 2
    assert {
        item["lifecycle_state"] for item in cleared["definitions"]
    } == {"CLEARED"}
    assert cleared["exchange_call_count"] == 0

    third = _create(repository, key="clear-create-three")
    with pytest.raises(OperatorStealthDefinitionError) as exc_info:
        repository.clear_definitions(
            selections=[
                (third["definition_id"], 2),
                (first["definition_id"], 2),
            ],
            actor_id="operator",
            operator_reason="conflicting clear",
            correlation_id="clear-conflict-correlation",
            idempotency_key="clear-conflict",
            acknowledgement=True,
        )
    assert exc_info.value.code == "stealth_definition_revision_conflict"
    assert repository.get_definition(third["definition_id"])[
        "lifecycle_state"
    ] == "DRAFT"


def test_export_and_preview_apply_import_are_durable_and_individually_audited(
    repository: OperatorStealthDefinitionRepository,
) -> None:
    source = _create(repository)
    exported = repository.export_definitions(
        definition_ids=[source["definition_id"]],
        actor_id="operator",
        operator_reason="export selected definition",
        correlation_id="stealth-definition-export-correlation",
        idempotency_key="stealth-definition-export",
        acknowledgement=True,
    )
    assert exported["schema_version"] == "operator-stealth-definition/v1"
    assert exported["item_count"] == 1
    assert exported["manifest_sha256"] == hashlib.sha256(
        json.dumps(
            exported["items"],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    imported_id = str(uuid.uuid4())
    import_item = {
        **exported["items"][0],
        "definition_id": imported_id,
        "name": "Imported BTC patient bid",
    }
    preview = repository.create_import_preview(
        items=[import_item],
        manifest_sha256=hashlib.sha256(
            json.dumps(
                [import_item],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        portfolio_scope_sha256="a" * 64,
        actor_id="operator",
        operator_reason="preview reviewed import",
        correlation_id="stealth-definition-import-preview-correlation",
        idempotency_key="stealth-definition-import-preview",
        acknowledgement=True,
    )
    assert preview["state"] == "PREVIEWED"
    assert preview["all_items_valid"] is True
    assert repository.list_definitions(
        lifecycle_state="DRAFT",
        product_id=None,
        limit=25,
        offset=0,
    )[1] == 1

    applied = repository.apply_import_preview(
        preview_id=preview["preview_id"],
        expected_manifest_sha256=preview["manifest_sha256"],
        portfolio_scope_sha256="a" * 64,
        actor_id="operator",
        operator_reason="apply reviewed import",
        correlation_id="stealth-definition-import-apply-correlation",
        idempotency_key="stealth-definition-import-apply",
        acknowledgement=True,
    )
    assert applied["imported_count"] == 1
    assert applied["definitions"][0]["definition_id"] == imported_id
    assert repository.get_import_preview(preview["preview_id"])["state"] == "APPLIED"
    imported_events, total = repository.list_events(
        definition_id=imported_id,
        limit=25,
        offset=0,
    )
    assert total == 1
    assert imported_events[0]["event_type"] == "STEALTH_DEFINITION_IMPORTED"
    assert (
        imported_events[0]["evidence"]["import_preview_id"]
        == preview["preview_id"]
    )


def test_import_preview_rejects_schema_and_identity_collisions_without_insert(
    repository: OperatorStealthDefinitionRepository,
) -> None:
    source = _create(repository)
    item = {
        "definition_id": source["definition_id"],
        "name": "collision",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": "0.0001",
        "limit_price": "60000",
        "reveal_condition_type": "PRICE",
        "reveal_price_threshold": "59000",
        "reveal_direction": "BELOW",
        "hold_duration_seconds": 5,
        "delay_seconds": None,
        "reveal_pricing_policy": "CONFIGURED_LIMIT",
        "sizing_mode": "FIXED",
        "follow_up_reveal_direction": "OPPOSITE",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "max_order_replacements": 2,
        "allow_partial_fills": False,
        "post_only": True,
    }
    preview = repository.create_import_preview(
        items=[item],
        manifest_sha256=hashlib.sha256(
            json.dumps([item], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        portfolio_scope_sha256="a" * 64,
        actor_id="operator",
        operator_reason="preview collision",
        correlation_id="collision-preview-correlation",
        idempotency_key="collision-preview",
        acknowledgement=True,
    )
    assert preview["state"] == "REJECTED"
    assert preview["all_items_valid"] is False
    assert preview["items"][0]["diagnostic_code"] == (
        "stealth_definition_identity_conflict"
    )

    with pytest.raises(OperatorStealthDefinitionError) as exc_info:
        repository.apply_import_preview(
            preview_id=preview["preview_id"],
            expected_manifest_sha256=preview["manifest_sha256"],
            portfolio_scope_sha256="a" * 64,
            actor_id="operator",
            operator_reason="must not apply",
            correlation_id="collision-apply-correlation",
            idempotency_key="collision-apply",
            acknowledgement=True,
        )
    assert exc_info.value.code == "stealth_definition_import_not_applicable"


def test_import_apply_rejects_a_changed_approved_portfolio_scope(
    repository: OperatorStealthDefinitionRepository,
) -> None:
    item = {
        "definition_id": str(uuid.uuid4()),
        "name": "portfolio-bound import",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "total_size": "0.0001",
        "limit_price": "60000",
        "reveal_condition_type": "PRICE",
        "reveal_price_threshold": "59000",
        "reveal_direction": "BELOW",
        "hold_duration_seconds": 5,
        "delay_seconds": None,
        "reveal_pricing_policy": "CONFIGURED_LIMIT",
        "sizing_mode": "FIXED",
        "follow_up_reveal_direction": "OPPOSITE",
        "target_movement": "0.005",
        "target_movement_type": "P",
        "max_order_replacements": 2,
        "allow_partial_fills": False,
        "post_only": True,
    }
    preview = repository.create_import_preview(
        items=[item],
        manifest_sha256=hashlib.sha256(
            json.dumps([item], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        portfolio_scope_sha256="a" * 64,
        actor_id="operator",
        operator_reason="preview exact portfolio scope",
        correlation_id="portfolio-preview-correlation",
        idempotency_key="portfolio-preview",
        acknowledgement=True,
    )

    with pytest.raises(OperatorStealthDefinitionError) as exc_info:
        repository.apply_import_preview(
            preview_id=preview["preview_id"],
            expected_manifest_sha256=preview["manifest_sha256"],
            portfolio_scope_sha256="b" * 64,
            actor_id="operator",
            operator_reason="reject changed portfolio scope",
            correlation_id="portfolio-apply-correlation",
            idempotency_key="portfolio-apply",
            acknowledgement=True,
        )

    assert exc_info.value.code == "stealth_definition_import_portfolio_changed"
    assert repository.get_import_preview(preview["preview_id"])["state"] == (
        "PREVIEWED"
    )


def test_definition_create_serializes_against_runtime_materialization(
    repository: OperatorStealthDefinitionRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition_id = str(uuid.uuid4())
    admission_entered = threading.Event()
    release_admission = threading.Event()
    original_admission = repository._active_product_admission

    def paused_admission(cursor, product_id):
        admission_entered.set()
        assert release_admission.wait(timeout=5)
        return original_admission(cursor, product_id)

    monkeypatch.setattr(
        repository,
        "_active_product_admission",
        paused_admission,
    )
    create_result: list[dict[str, object]] = []
    create_errors: list[type[BaseException]] = []
    runtime_errors: list[type[BaseException]] = []
    runtime_finished = threading.Event()

    def create_local_definition() -> None:
        try:
            create_result.append(
                repository.create_definition(
                    definition_id=definition_id,
                    terms=_terms(),
                    portfolio_scope_sha256="a" * 64,
                    actor_id="operator",
                    operator_reason="reserve concurrent definition identity",
                    correlation_id="concurrent-create-correlation",
                    idempotency_key="concurrent-create",
                    acknowledgement=True,
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            create_errors.append(type(exc))

    runtime_database = PostgresDB(
        host=TEST_DB_HOST,
        port=TEST_DB_PORT,
        database=TEST_DB_NAME,
        user=TEST_DB_USER,
        password=TEST_DB_PASSWORD,
    )

    def materialize_runtime_identity() -> None:
        try:
            with runtime_database.get_cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO {repository.prefix}stealth_orders (
                        stealth_order_id, status
                    ) VALUES (%s::uuid, 'HIDDEN')
                    """,
                    (definition_id,),
                )
        except BaseException as exc:
            runtime_errors.append(type(exc))
        finally:
            runtime_finished.set()
            runtime_database.disconnect()

    create_thread = threading.Thread(target=create_local_definition)
    runtime_thread = threading.Thread(target=materialize_runtime_identity)
    create_thread.start()
    assert admission_entered.wait(timeout=5)
    runtime_thread.start()
    runtime_finished_while_local_identity_reserved = runtime_finished.wait(
        timeout=0.2
    )
    release_admission.set()
    create_thread.join(timeout=5)
    runtime_thread.join(timeout=5)

    assert runtime_finished_while_local_identity_reserved is False
    assert create_errors == []
    assert len(create_result) == 1
    assert len(runtime_errors) == 1
    assert repository.get_definition(definition_id)[
        "runtime_classification"
    ] == "UNMATERIALIZED"
