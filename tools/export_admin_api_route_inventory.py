"""Export the backend-owned Admin API route inventory as JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ROUTE_INVENTORY_EXPORT_PATH = ROOT / "openapi" / "coinbase-admin-api-route-inventory.json"
ROUTE_INVENTORY_EXPORT_SCHEMA_VERSION = "0.1.0"
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ROOT_STR = str(ROOT)
if ROOT_STR in sys.path:
    sys.path.remove(ROOT_STR)
sys.path.insert(0, ROOT_STR)

from application.admin_api.route_inventory import ADMIN_API_ROUTE_INVENTORY
from core.enums import AdminApiActionClass


def _value(item: Any) -> Any:
    return getattr(item, "value", item)


def _http_surface(surface: str) -> tuple[str | None, str | None]:
    pieces = surface.split(" ", 1)
    if len(pieces) != 2 or pieces[0] not in HTTP_METHODS:
        return None, None
    return pieces[0], pieces[1]


def build_admin_api_route_inventory_export() -> dict[str, Any]:
    """Return the route inventory artifact consumed by cross-repo checks."""

    routes: list[dict[str, Any]] = []
    for item in ADMIN_API_ROUTE_INVENTORY:
        method, path = _http_surface(item.surface)
        action_class = _value(item.action_class)
        routes.append(
            {
                "module_id": item.module_id,
                "surface": item.surface,
                "method": method,
                "path": path,
                "action_class": action_class,
                "permission": _value(item.permission),
                "idempotency": item.idempotency,
                "approval": item.approval,
                "caps": item.caps,
                "audit": item.audit,
                "shared_method": item.shared_method,
                "parity_test": item.parity_test,
                "compatibility_mode": item.compatibility_mode,
                "command_contract": method == "POST"
                and action_class != AdminApiActionClass.READ_ONLY.value,
            }
        )
    return {
        "type": "admin_api_route_inventory",
        "schema_version": ROUTE_INVENTORY_EXPORT_SCHEMA_VERSION,
        "routes": routes,
    }


def write_admin_api_route_inventory_export(
    path: Path = ROUTE_INVENTORY_EXPORT_PATH,
) -> dict[str, Any]:
    """Write the route inventory artifact and return its payload."""

    payload = build_admin_api_route_inventory_export()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export the backend-owned Admin API route inventory."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROUTE_INVENTORY_EXPORT_PATH,
        help="Path to write. Defaults to openapi/coinbase-admin-api-route-inventory.json.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write JSON to stdout instead of a file.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_admin_api_route_inventory_export()
    body = json.dumps(payload, indent=2) + "\n"
    if args.stdout:
        sys.stdout.write(body)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
        print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
