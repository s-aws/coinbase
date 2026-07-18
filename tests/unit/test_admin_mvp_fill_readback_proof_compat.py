from __future__ import annotations

from application.admin_api.mvp_service import (
    _spot_fill_readback_record_proves_live_fill,
)


def _canonical_proof() -> dict[str, object]:
    return {
        "type": "admin_spot_order_fill_readback",
        "status": "passed",
        "read_only": True,
        "client_order_id": "root-fill-proof",
        "audit_id": "audit-fill-proof",
        "order_status": "FILLED",
        "order_read_attempted": True,
        "order_read_succeeded": True,
        "order_found": True,
        "exchange_order_id_present": True,
        "exchange_order_id_evidence_only": True,
        "fill_read_attempted": True,
        "fill_read_succeeded": True,
        "fill_count": 1,
        "fill_read_status": "filled",
        "fill_order_id_matches_exchange_order_id": True,
        "fill_product_id_matches_order": True,
        "fills_have_more_pages": False,
        "coinbase_read_succeeded": True,
        "live_coinbase_read_ran": True,
        "live_coinbase_orders_ran": False,
    }


def test_fill_readback_proof_accepts_local_projection_of_durable_origin() -> None:
    canonical = _canonical_proof()
    projected = {
        **canonical,
        "live_fill_readback_proof_ref": (
            "spot_fill_readback:root-fill-proof:audit-fill-proof"
        ),
        "route": "/api/v1/orders/{client_order_id}/fill-readback",
        "method": "GET",
        "readback_source": "local_durable_evidence",
        "current_request_coinbase_read_ran": False,
        "current_request_local_state_mutated": False,
        "coinbase_read_succeeded": False,
        "live_coinbase_read_ran": False,
        "proof_origin_live_coinbase_read_ran": True,
        "proof_origin_coinbase_read_succeeded": True,
        "proof_origin_order_read_attempted": True,
        "proof_origin_order_read_succeeded": True,
        "proof_origin_order_found": True,
        "proof_origin_exchange_order_id_present": True,
        "proof_origin_fill_read_attempted": True,
        "proof_origin_fill_read_succeeded": True,
        "proof_origin_fills_have_more_pages": False,
    }

    assert _spot_fill_readback_record_proves_live_fill(projected) is True
    assert (
        _spot_fill_readback_record_proves_live_fill(
            projected,
            canonical_only=True,
        )
        is False
    )
    projected["proof_origin_fill_read_succeeded"] = False
    assert _spot_fill_readback_record_proves_live_fill(projected) is False


def test_fill_readback_proof_accepts_established_durable_summary_shape() -> None:
    legacy = {
        "type": "admin_spot_order_fill_readback",
        "module_id": "spot_operations",
        "route": "/api/v1/orders/{client_order_id}/fill-readback",
        "method": "GET",
        "status": "passed",
        "read_only": True,
        "client_order_id": "root-fill-proof",
        "live_fill_readback_proof_ref": (
            "spot_fill_readback:root-fill-proof:audit-fill-proof"
        ),
        "order_status": "FILLED",
        "order_found": True,
        "exchange_order_id_evidence_only": True,
        "fill_count": 1,
        "fill_read_status": "filled",
        "fill_order_id_matches_exchange_order_id": True,
        "fill_product_id_matches_order": True,
        "coinbase_read_succeeded": True,
        "live_coinbase_read_ran": True,
        "live_coinbase_orders_ran": False,
        "ended_at": "2026-07-10T01:02:30Z",
    }

    assert _spot_fill_readback_record_proves_live_fill(legacy) is True
    assert (
        _spot_fill_readback_record_proves_live_fill(
            legacy,
            canonical_only=True,
        )
        is False
    )
    legacy["live_coinbase_orders_ran"] = True
    assert _spot_fill_readback_record_proves_live_fill(legacy) is False


def test_fill_readback_proof_canonical_shape_remains_recordable() -> None:
    assert (
        _spot_fill_readback_record_proves_live_fill(
            _canonical_proof(),
            canonical_only=True,
        )
        is True
    )
