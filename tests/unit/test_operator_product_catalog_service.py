from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from application.admin_api.operator_product_catalog_service import (
    OperatorProductCatalogService,
)


REVISION_ID = "0d756620-2ce5-4fd3-a24a-a14c4d8bf3c1"


class _Repository:
    def get_revision(self, revision_id: str) -> dict[str, Any]:
        assert revision_id == REVISION_ID
        return {
            "revision_id": REVISION_ID,
            "sequence_number": 1,
            "revision": 1,
            "state": "PROPOSED",
            "source": "COINBASE_CATALOG",
            "source_cycle_id": None,
            "parent_revision_id": None,
            "rollback_of_revision_id": None,
            "snapshot_sha256": "a" * 64,
            "diff_sha256": "b" * 64,
            "product_count": 1,
            "added_count": 1,
            "changed_count": 0,
            "removed_count": 0,
            "unchanged_count": 0,
            "active": False,
            "trading_authority_granted": False,
            "portfolio_scope_expanded": False,
            "exchange_mutation_count": 0,
            "created_at": datetime(2026, 7, 23, tzinfo=UTC),
            "updated_at": datetime(2026, 7, 23, 1, tzinfo=UTC),
        }

    def list_revision_products(
        self,
        revision_id: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "product_id": "BTC-USDC",
                "product_type": "SPOT",
                "base_currency": "BTC",
                "quote_currency": "USDC",
                "base_increment": "0.00000001",
                "quote_increment": "0.01",
                "price_increment": "0.01",
                "base_min_size": "0.00001",
                "base_max_size": "10",
                "quote_min_size": "1",
                "quote_max_size": "1000000",
                "display_name": "BTC-USDC",
                "exchange_status": "ONLINE",
                "exchange_disabled": False,
                "cancel_only": False,
                "limit_only": False,
                "post_only": False,
                "view_only": False,
                "lifecycle": "PENDING",
                "change_type": "ADDED",
            }
        ]

    def list_events(
        self,
        *,
        limit: int,
        offset: int = 0,
        revision_id: str | None = None,
        cycle_id: str | None = None,
    ) -> list[dict[str, Any]]:
        assert limit in {25, 100, 500}
        assert offset == 0
        if cycle_id is not None:
            assert cycle_id == "54fe42bd-1f23-4b42-b83d-949a5184bb3c"
        if revision_id is not None:
            assert revision_id == REVISION_ID
        return [
            {
                "event_id": "e80ef6af-c421-4809-b2d0-f8ca3f3c10ca",
                "event_type": "CATALOG_REFRESH_PROPOSED",
                "revision_id": REVISION_ID,
                "cycle_id": None,
                "product_id": None,
                "correlation_id": "catalog-safe-correlation",
                "evidence": {
                    "product_count": 1,
                    "added_count": 1,
                    "changed_count": 0,
                    "removed_count": 0,
                    "page_count": 1,
                    "raw_response": "must-not-survive",
                    "private_portfolio_id": "must-not-survive",
                },
                "recorded_at": datetime(2026, 7, 23, 2, tzinfo=UTC),
            }
        ]

    def list_revisions(
        self,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        assert limit == 25
        assert offset == 0
        return ([], 0)

    def list_cycles(self) -> list[dict[str, Any]]:
        return [
            {
                "cycle_id": "54fe42bd-1f23-4b42-b83d-949a5184bb3c",
                "cycle_number": 1,
                "state": "FAILED",
                "read_state": "RETURNED_INCOMPLETE",
                "expected_active_revision_id": None,
                "proposed_revision_id": None,
                "logical_read_count": 1,
                "page_count": 1,
                "diagnostic_code":
                    "product_catalog_refresh_interrupted_after_return",
                "correlation_id": "catalog-recovered-cycle",
                "actor_id": "must-not-survive",
                "idempotency_key": "must-not-survive",
                "created_at": datetime(2026, 7, 23, tzinfo=UTC),
                "updated_at": datetime(2026, 7, 23, 1, tzinfo=UTC),
            }
        ]

    def count_events(self) -> int:
        return 1

    def get_goal_budget(self) -> dict[str, Any]:
        return {
            "cycle_count": 1,
            "cycle_limit": 10,
            "logical_read_count": 1,
            "page_count": 1,
            "trading_authority_granted": False,
            "portfolio_scope_expanded": False,
            "exchange_mutation_count": 0,
        }

    def get_active_revision_id(self) -> None:
        return None


def test_service_normalizes_timestamps_and_allowlists_event_evidence() -> None:
    service = OperatorProductCatalogService(
        repository=_Repository(),  # type: ignore[arg-type]
        rest_client=None,
        rest_client_available=False,
    )

    response = service.get_revision(revision_id=REVISION_ID)

    assert response["revision"]["created_at"] == (
        "2026-07-23T00:00:00+00:00"
    )
    assert response["events"][0]["recorded_at"] == (
        "2026-07-23T02:00:00+00:00"
    )
    assert response["events"][0]["evidence"] == {
        "product_count": 1,
        "added_count": 1,
        "changed_count": 0,
        "removed_count": 0,
        "page_count": 1,
    }
    assert "must-not-survive" not in str(response)


def test_catalog_list_exposes_sanitized_terminal_cycle_and_audit_readback() -> None:
    service = OperatorProductCatalogService(
        repository=_Repository(),  # type: ignore[arg-type]
        rest_client=None,
        rest_client_available=False,
    )

    response = service.list_catalog(
        limit=25,
        offset=0,
        event_limit=25,
        event_offset=0,
    )

    assert response["cycles"][0] == {
        "cycle_id": "54fe42bd-1f23-4b42-b83d-949a5184bb3c",
        "cycle_number": 1,
        "state": "FAILED",
        "read_state": "RETURNED_INCOMPLETE",
        "expected_active_revision_id": None,
        "proposed_revision_id": None,
        "logical_read_count": 1,
        "page_count": 1,
        "diagnostic_code":
            "product_catalog_refresh_interrupted_after_return",
        "correlation_id": "catalog-recovered-cycle",
        "events": response["cycles"][0]["events"],
        "created_at": "2026-07-23T00:00:00+00:00",
        "updated_at": "2026-07-23T01:00:00+00:00",
    }
    assert response["event_total_count"] == 1
    assert response["event_returned_count"] == 1
    assert response["event_next_offset"] is None
    assert "must-not-survive" not in str(response)


def test_rejected_command_event_keeps_only_fixed_operation_and_diagnostic() -> None:
    service = OperatorProductCatalogService(
        repository=_Repository(),  # type: ignore[arg-type]
        rest_client=None,
        rest_client_available=False,
    )

    event = service._event_item(
        {
            "event_id": "f80ef6af-c421-4809-b2d0-f8ca3f3c10ca",
            "event_type": "CATALOG_COMMAND_REJECTED",
            "revision_id": None,
            "cycle_id": None,
            "product_id": None,
            "correlation_id": "catalog-rejected-command",
            "evidence": {
                "operation": "approve",
                "diagnostic_code": "product_catalog_approval_conflict",
                "raw_response": "must-not-survive",
            },
            "recorded_at": datetime(2026, 7, 23, 3, tzinfo=UTC),
        }
    ).model_dump(mode="json")

    assert event["evidence"] == {
        "operation": "approve",
        "diagnostic_code": "product_catalog_approval_conflict",
    }
    assert "must-not-survive" not in str(event)
