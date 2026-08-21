"""One-shot REST lookup: fetch order details + fills for a given id and
print fees / commission so we can compare actual exchange charges
against the validator's projection.

Accepts either an exchange ``order_id`` or our ``client_order_id`` —
list_fills(order_id=...) takes the exchange id; if that returns empty
we retry treating the input as a client_order_id via the historical
list_orders endpoint.

Usage (from repo root):
    .\\.venv\\Scripts\\python.exe genai_tools\\lookup_order_fees.py <id>
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict

from configuration import REST_CLIENT as client
from external.coinbase_client import coinbase_sdk_response_to_dict


def _dump(label: str, payload: Any) -> None:
    print(f"\n===== {label} =====")
    print(json.dumps(payload, indent=2, default=str))


def main(order_id_input: str) -> int:
    # 1) Try as exchange order_id via the SDK directly (no thin wrapper).
    try:
        sdk_order = client._client.get_order(order_id=order_id_input)
        order_dict = coinbase_sdk_response_to_dict(sdk_order)
    except Exception as exc:
        order_dict = {"error": f"{type(exc).__name__}: {exc}"}
    _dump("get_order(order_id) [treats input as exchange order_id]", order_dict)

    # 2) Pull fills for the same id (best-effort).
    fills_dict: Dict[str, Any]
    try:
        fills_dict = client.list_fills(order_id=order_id_input, limit=100)
    except Exception as exc:
        fills_dict = {"error": f"{type(exc).__name__}: {exc}"}
    _dump("list_fills(order_id=...)", fills_dict)

    # 3) Aggregate from fills if present.
    fills = fills_dict.get("fills") if isinstance(fills_dict, dict) else None
    if fills:
        total_size = 0.0
        total_notional = 0.0
        total_commission = 0.0
        for f in fills:
            try:
                size = float(f.get("size") or 0)
                price = float(f.get("price") or 0)
                commission = float(f.get("commission") or 0)
            except (TypeError, ValueError):
                continue
            total_size += size
            total_notional += size * price
            total_commission += commission
        avg_price = (total_notional / total_size) if total_size else 0.0
        _dump(
            "AGGREGATE FROM FILLS",
            {
                "fill_count": len(fills),
                "total_size_contracts": total_size,
                "avg_fill_price": avg_price,
                "total_notional": total_notional,
                "sum_commission_field": total_commission,
                "implied_commission_per_contract": (
                    total_commission / total_size if total_size else None
                ),
                "implied_commission_bps_of_notional": (
                    (total_commission / total_notional) * 10_000
                    if total_notional
                    else None
                ),
            },
        )

    # 4) Whatever the order endpoint returned, surface the fee fields
    #    explicitly so we don't have to scan the full dump.
    order = order_dict.get("order") if isinstance(order_dict, dict) else None
    if isinstance(order, dict):
        _dump(
            "ORDER FEE-RELEVANT FIELDS",
            {
                "client_order_id": order.get("client_order_id"),
                "order_id": order.get("order_id"),
                "product_id": order.get("product_id"),
                "side": order.get("side"),
                "status": order.get("status"),
                "filled_size": order.get("filled_size"),
                "average_filled_price": order.get("average_filled_price"),
                "total_fees": order.get("total_fees"),
                "total_value_after_fees": order.get("total_value_after_fees"),
                "outstanding_hold_amount": order.get("outstanding_hold_amount"),
                "is_liquidation": order.get("is_liquidation"),
                "fee_summary": {
                    k: order.get(k)
                    for k in (
                        "total_fees",
                        "filled_value",
                        "trigger_status",
                    )
                    if k in order
                },
            },
        )

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: lookup_order_fees.py <order_id>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
