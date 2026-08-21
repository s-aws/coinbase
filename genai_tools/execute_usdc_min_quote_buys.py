"""Execute Coinbase BUY limit orders from a minimum-quote snapshot.

This tool consumes output from ``calculate_usdc_min_buy_sum.py``. It defaults
to dry-run mode and only places live orders when explicit execution guardrails
are supplied.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_INPUT = Path("genai_tools/output/usdc_min_quote_buy_snapshot.json")
CONFIRM_TEXT = "EXECUTE_MIN_USDC_BUYS"
REQUIRED_ROW_FIELDS = (
    "product_id",
    "side",
    "snapshot_limit_price",
    "order_base_size_at_snapshot_price",
)


@dataclass(frozen=True)
class BuyPlan:
    product_id: str
    side: str
    base_size: Decimal
    limit_price: Decimal
    order_quote_size: Decimal | None
    snapshot_notional: Decimal
    estimated_total_quote_with_taker_fee: Decimal
    post_only: bool
    source_row: dict[str, Any]


def decimal_to_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def decimal_from_value(value: Any, field_name: str) -> Decimal:
    if value is None or value == "":
        raise ValueError(f"Missing required decimal field: {field_name}")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal for {field_name}: {value!r}") from exc


def optional_decimal_from_value(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def bool_from_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def response_to_dict(response: Any) -> Any:
    converter = getattr(response, "to_dict", None)
    if callable(converter):
        return converter()
    return response


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_snapshot_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_snapshot(input_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if input_path.suffix.lower() == ".csv":
        with input_path.open("r", newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        return {"source_file": str(input_path), "format": "csv"}, rows

    data = json.loads(input_path.read_text(encoding="utf-8"))
    rows = data.get("products")
    if not isinstance(rows, list):
        raise ValueError("JSON snapshot must contain a products list")
    return data, rows


def filter_rows(rows: list[dict[str, Any]], product_ids: set[str] | None) -> list[dict[str, Any]]:
    if not product_ids:
        return rows
    return [row for row in rows if str(row.get("product_id")) in product_ids]


def validate_row_shape(row: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_ROW_FIELDS if not row.get(field)]
    if missing:
        product_id = row.get("product_id") or "<unknown>"
        raise ValueError(f"{product_id}: missing required fields: {', '.join(missing)}")


def build_plan(row: dict[str, Any], force_post_only: bool) -> BuyPlan:
    validate_row_shape(row)

    product_id = str(row["product_id"])
    side = str(row.get("side") or "BUY").upper()
    if side != "BUY":
        raise ValueError(f"{product_id}: only BUY rows are supported, got {side!r}")

    base_size = decimal_from_value(row.get("order_base_size_at_snapshot_price"), "order_base_size_at_snapshot_price")
    limit_price = decimal_from_value(row.get("snapshot_limit_price"), "snapshot_limit_price")
    order_quote_size = optional_decimal_from_value(row.get("order_quote_size"))

    if base_size <= 0:
        raise ValueError(f"{product_id}: base size must be positive")
    if limit_price <= 0:
        raise ValueError(f"{product_id}: limit price must be positive")

    snapshot_notional = optional_decimal_from_value(row.get("order_notional_at_snapshot_price"))
    if snapshot_notional is None:
        snapshot_notional = base_size * limit_price

    estimated_total = optional_decimal_from_value(row.get("estimated_total_quote_with_taker_fee"))
    if estimated_total is None:
        estimated_total = snapshot_notional

    return BuyPlan(
        product_id=product_id,
        side=side,
        base_size=base_size,
        limit_price=limit_price,
        order_quote_size=order_quote_size,
        snapshot_notional=snapshot_notional,
        estimated_total_quote_with_taker_fee=estimated_total,
        post_only=force_post_only or bool_from_value(row.get("post_only")),
        source_row=row,
    )


def build_plans(rows: list[dict[str, Any]], force_post_only: bool) -> list[BuyPlan]:
    plans = []
    seen: set[str] = set()
    for row in rows:
        plan = build_plan(row, force_post_only=force_post_only)
        if plan.product_id in seen:
            raise ValueError(f"Duplicate product_id in input: {plan.product_id}")
        seen.add(plan.product_id)
        plans.append(plan)
    return plans


def make_client_order_id(run_id: str, plan: BuyPlan) -> str:
    seed = "|".join(
        [
            run_id,
            plan.product_id,
            plan.side,
            decimal_to_text(plan.base_size),
            decimal_to_text(plan.limit_price),
            str(plan.post_only).lower(),
        ]
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def make_rest_client():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError("COINBASE_API_KEY and COINBASE_API_SECRET must be set for --execute")

    from coinbase.rest import RESTClient
    from external import CoinbaseRestClient

    sdk_client = RESTClient(api_key=api_key, api_secret=api_secret, rate_limit_headers=True)
    return CoinbaseRestClient(sdk_client)


def summarize_plans(plans: list[BuyPlan]) -> dict[str, str | int]:
    snapshot_notional = sum((plan.snapshot_notional for plan in plans), Decimal("0"))
    estimated_total = sum((plan.estimated_total_quote_with_taker_fee for plan in plans), Decimal("0"))
    return {
        "order_count": len(plans),
        "snapshot_notional": decimal_to_text(snapshot_notional),
        "estimated_total_quote_with_taker_fee": decimal_to_text(estimated_total),
    }


def validate_execution_guards(
    *,
    execute: bool,
    confirm: str | None,
    max_total_quote: Decimal | None,
    estimated_total: Decimal,
    max_orders: int | None,
    order_count: int,
) -> None:
    if max_orders is not None and order_count > max_orders:
        raise ValueError(f"Plan has {order_count} orders, above --max-orders {max_orders}")

    if not execute:
        return

    if confirm != CONFIRM_TEXT:
        raise ValueError(f"--execute requires --confirm {CONFIRM_TEXT!r}")
    if max_total_quote is None:
        raise ValueError("--execute requires --max-total-quote")
    if estimated_total > max_total_quote:
        raise ValueError(
            "Estimated total "
            f"{decimal_to_text(estimated_total)} exceeds --max-total-quote {decimal_to_text(max_total_quote)}"
        )


def validate_snapshot_age(snapshot: dict[str, Any], max_age_minutes: Decimal, allow_stale: bool) -> None:
    fetched_at = parse_snapshot_time(snapshot.get("fetched_at"))
    if fetched_at is None:
        if allow_stale:
            return
        raise ValueError("Snapshot has no parseable fetched_at; pass --allow-stale-snapshot to override")

    age_seconds = Decimal(str((datetime.now(timezone.utc) - fetched_at).total_seconds()))
    max_age_seconds = max_age_minutes * Decimal("60")
    if age_seconds > max_age_seconds and not allow_stale:
        raise ValueError(
            "Snapshot is stale: "
            f"{decimal_to_text(age_seconds / Decimal('60'))} minutes old, "
            f"max is {decimal_to_text(max_age_minutes)}"
        )


def submit_plan(rest_client: Any, plan: BuyPlan, client_order_id: str, retail_portfolio_id: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if retail_portfolio_id:
        kwargs["retail_portfolio_id"] = retail_portfolio_id

    response = rest_client.limit_order_gtc(
        product_id=plan.product_id,
        side=plan.side,
        base_size=decimal_to_text(plan.base_size),
        limit_price=decimal_to_text(plan.limit_price),
        client_order_id=client_order_id,
        post_only=plan.post_only,
        **kwargs,
    )
    data = response_to_dict(response)
    status = "submitted"
    if isinstance(data, dict) and data.get("success") is False:
        status = "rejected"
    return {
        "status": status,
        "response": data,
    }


def plan_to_report_row(plan: BuyPlan, client_order_id: str, status: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    row = {
        "product_id": plan.product_id,
        "client_order_id": client_order_id,
        "status": status,
        "request": {
            "order_type": "limit_gtc",
            "side": plan.side,
            "base_size": decimal_to_text(plan.base_size),
            "limit_price": decimal_to_text(plan.limit_price),
            "post_only": plan.post_only,
        },
        "snapshot": {
            "order_quote_size": decimal_to_text(plan.order_quote_size) if plan.order_quote_size is not None else None,
            "snapshot_notional": decimal_to_text(plan.snapshot_notional),
            "estimated_total_quote_with_taker_fee": decimal_to_text(plan.estimated_total_quote_with_taker_fee),
        },
    }
    if extra:
        row.update(extra)
    return row


def write_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def parse_products_arg(value: str | None) -> set[str] | None:
    if not value:
        return None
    products = {item.strip() for item in value.split(",") if item.strip()}
    return products or None


def default_report_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(f"genai_tools/output/usdc_min_quote_buy_execution_report_{stamp}.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or submit Coinbase GTC limit BUY orders from a minimum-quote "
            "snapshot. This tool does not decide whether the market is in a downtrend."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help=f"Snapshot JSON/CSV path. Default: {DEFAULT_INPUT}")
    parser.add_argument("--out", type=Path, help="Execution report path. Default: timestamped file in genai_tools/output.")
    parser.add_argument("--execute", action="store_true", help="Place live orders. Omit for dry-run.")
    parser.add_argument("--confirm", help=f"Required with --execute. Must equal {CONFIRM_TEXT}.")
    parser.add_argument("--max-total-quote", help="Required with --execute. Abort if estimated total exceeds this amount.")
    parser.add_argument("--max-orders", type=int, help="Abort if the snapshot has more orders than this.")
    parser.add_argument("--products", help="Optional comma-separated product allowlist, e.g. BTC-USDC,ETH-USDC.")
    parser.add_argument("--post-only", action="store_true", help="Force all orders to be post-only maker orders.")
    parser.add_argument("--allow-stale-snapshot", action="store_true", help="Allow snapshots older than --max-snapshot-age-minutes.")
    parser.add_argument("--max-snapshot-age-minutes", default="30", help="Maximum snapshot age before aborting. Default: 30.")
    parser.add_argument("--retail-portfolio-id", help="Optional Coinbase retail_portfolio_id passed to order placement.")
    parser.add_argument("--run-id", help="Idempotency seed. Default: snapshot fetched_at or input filename.")
    parser.add_argument("--sleep-seconds", default="0.2", help="Delay between live submissions. Default: 0.2.")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop submitting after the first failed/rejected order.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    max_total_quote = optional_decimal_from_value(args.max_total_quote)
    max_snapshot_age_minutes = decimal_from_value(args.max_snapshot_age_minutes, "max_snapshot_age_minutes")
    sleep_seconds = decimal_from_value(args.sleep_seconds, "sleep_seconds")

    if args.max_orders is not None and args.max_orders <= 0:
        print("--max-orders must be positive", file=sys.stderr)
        return 2
    if max_snapshot_age_minutes <= 0:
        print("--max-snapshot-age-minutes must be positive", file=sys.stderr)
        return 2
    if sleep_seconds < 0:
        print("--sleep-seconds must be non-negative", file=sys.stderr)
        return 2

    try:
        snapshot, rows = load_snapshot(args.input)
        rows = filter_rows(rows, parse_products_arg(args.products))
        validate_snapshot_age(snapshot, max_snapshot_age_minutes, args.allow_stale_snapshot)
        plans = build_plans(rows, force_post_only=args.post_only)
        summary = summarize_plans(plans)
        estimated_total = decimal_from_value(summary["estimated_total_quote_with_taker_fee"], "estimated_total_quote_with_taker_fee")
        validate_execution_guards(
            execute=args.execute,
            confirm=args.confirm,
            max_total_quote=max_total_quote,
            estimated_total=estimated_total,
            max_orders=args.max_orders,
            order_count=len(plans),
        )
    except Exception as exc:
        print(f"Plan validation failed: {exc}", file=sys.stderr)
        return 2

    run_id = args.run_id or str(snapshot.get("fetched_at") or args.input)
    report_path = args.out or default_report_path()
    report_rows: list[dict[str, Any]] = []
    rest_client = None

    if args.execute:
        try:
            rest_client = make_rest_client()
        except Exception as exc:
            print(f"Failed to initialize Coinbase client: {exc}", file=sys.stderr)
            return 2

    started_at = utc_now_text()
    for index, plan in enumerate(plans, start=1):
        client_order_id = make_client_order_id(run_id, plan)

        if not args.execute:
            report_rows.append(plan_to_report_row(plan, client_order_id, "dry_run"))
            continue

        try:
            result = submit_plan(rest_client, plan, client_order_id, args.retail_portfolio_id)
            status = str(result.pop("status"))
            report_rows.append(plan_to_report_row(plan, client_order_id, status, result))
            if args.stop_on_error and status != "submitted":
                break
        except Exception as exc:
            report_rows.append(plan_to_report_row(plan, client_order_id, "failed", {"error": str(exc)}))
            if args.stop_on_error:
                break

        if index < len(plans) and sleep_seconds:
            time.sleep(float(sleep_seconds))

    completed_at = utc_now_text()
    final_report = {
        "started_at": started_at,
        "completed_at": completed_at,
        "mode": "execute" if args.execute else "dry_run",
        "input": str(args.input),
        "run_id": run_id,
        "summary": summary,
        "guardrails": {
            "confirm_required": CONFIRM_TEXT,
            "max_total_quote": decimal_to_text(max_total_quote) if max_total_quote is not None else None,
            "max_orders": args.max_orders,
            "post_only_forced": bool(args.post_only),
            "max_snapshot_age_minutes": decimal_to_text(max_snapshot_age_minutes),
            "allow_stale_snapshot": bool(args.allow_stale_snapshot),
        },
        "orders": report_rows,
    }
    write_report(final_report, report_path)

    print(json.dumps({
        "mode": final_report["mode"],
        "report": str(report_path),
        **summary,
        "submitted_or_planned_orders": len(report_rows),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
