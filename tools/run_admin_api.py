"""Run the local Admin MVP HTTP API.

Usage:
    py -3.13 tools/run_admin_api.py --host 127.0.0.1 --port 8010
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.mvp_service import (
    AdminMvpRequestContext,
    get_admin_mvp_service,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8010


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Admin MVP API.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP bind port.")
    return parser.parse_args()


def build_request_context(headers: Any) -> AdminMvpRequestContext:
    return AdminMvpRequestContext(
        idempotency_key=headers.get("Idempotency-Key") or "read-only",
        correlation_id=headers.get("X-Correlation-Id") or headers.get("X-Request-Id") or "local-admin-api",
        operator_intent=headers.get("X-Operator-Intent") or "read_admin_api",
        actor_id=headers.get("X-Admin-Actor") or "local-operator",
        roles=tuple(
            role.strip()
            for role in (headers.get("X-Admin-Roles") or "operator").split(",")
            if role.strip()
        ),
    )


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_length = int(handler.headers.get("Content-Length") or "0")
    if content_length <= 0:
        return {}
    raw_body = handler.rfile.read(content_length)
    if not raw_body:
        return {}
    return json.loads(raw_body.decode("utf-8"))


def write_json(handler: BaseHTTPRequestHandler, result) -> None:
    payload = json.dumps(result.body, separators=(",", ":"), default=str).encode("utf-8")
    handler.send_response(result.status_code)
    for name, value in result.headers.items():
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


class AdminMvpRequestHandler(BaseHTTPRequestHandler):
    server_version = "CoinbaseAdminMvp/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = {key: values[0] if len(values) == 1 else values for key, values in parse_qs(parsed.query).items()}
        result = get_admin_mvp_service().get_read_response(
            parsed.path,
            query,
            build_request_context(self.headers),
        )
        write_json(self, result)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        service = get_admin_mvp_service()
        context = build_request_context(self.headers)
        body = read_json_body(self)
        path = parsed.path.rstrip("/")
        if path == "/api/v1/orders":
            result = service.submit_manual_order(body, context)
        elif path.startswith("/api/v1/orders/") and path.endswith("/cancel"):
            client_order_id = path.split("/api/v1/orders/", 1)[1].rsplit("/cancel", 1)[0]
            result = service.cancel_order_by_client_order_id(client_order_id, body, context)
        elif path == "/api/v1/admin/live-execution/service-decisions":
            result = service.record_live_service_decision(body, context)
        elif path == "/api/v1/admin/approvals/requests":
            result = service.create_approval_request(body, context)
        elif path.startswith("/api/v1/admin/approvals/requests/") and path.endswith("/decisions"):
            approval_request_id = path.split("/api/v1/admin/approvals/requests/", 1)[1].rsplit("/decisions", 1)[0]
            result = service.decide_approval_request(approval_request_id, body, context)
        elif path == "/api/v1/admin/admission-audits":
            result = service.record_admission_audit(body, context)
        elif path == "/api/v1/admin/cap-guard/decisions":
            result = service.record_cap_guard_decision(body, context)
        elif path == "/api/v1/admin/reconciliation/plans":
            result = service.record_reconciliation_plan(body, context)
        else:
            result = service._error(404, f"Admin MVP mutation route not found: {path}", context)
        write_json(self, result)

    def log_message(self, format: str, *args: Any) -> None:
        return None


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AdminMvpRequestHandler)
    print(f"Admin MVP API listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
