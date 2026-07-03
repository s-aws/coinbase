"""Run the local Admin MVP HTTP API.

Usage:
    py -3.13 tools/run_admin_api.py --host 127.0.0.1 --port 8010
"""

from __future__ import annotations

import argparse
from collections.abc import MutableMapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.mvp_service import (
    AdminMvpRequestContext,
    SPOT_CANCEL_ORDER_PROOF_CHAIN_ROUTE,
    SPOT_MANUAL_ORDER_PROOF_CHAIN_ROUTE,
    get_admin_mvp_service,
)


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_CORS_ORIGIN = "http://127.0.0.1:3000"
AUTH_TOKEN_ENV = "COINBASE_ADMIN_API_BEARER_TOKEN"
CORS_ORIGINS_ENV = "COINBASE_ADMIN_API_CORS_ORIGINS"
ENVIRONMENT_ENV = "COINBASE_ADMIN_API_ENVIRONMENT"
DEPLOYMENT_TIER_ENV = "COINBASE_BACKEND_DEPLOYMENT_TIER"
OS_TRUSTSTORE_ENV = "COINBASE_ADMIN_API_OS_TRUSTSTORE"
DISABLED_ENV_VALUES = {"0", "false", "no", "off", "disabled"}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Admin MVP API.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="HTTP bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP bind port.")
    parser.add_argument(
        "--dev-token",
        help=(
            "Local-only bearer token to export for frontend BFF compatibility. "
            "The MVP runner still delegates authorization evidence to the "
            "backend Admin service."
        ),
    )
    parser.add_argument(
        "--cors-origin",
        action="append",
        dest="cors_origins",
        help=(
            "Allowed browser origin. Can be repeated. Defaults to "
            f"{DEFAULT_CORS_ORIGIN}."
        ),
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Accepted for compatibility with the full Admin API runner.",
    )
    args = parser.parse_args(argv)
    args.cors_origins = tuple(args.cors_origins or (DEFAULT_CORS_ORIGIN,))
    return args


def apply_local_environment(
    args: argparse.Namespace,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    target = environ if environ is not None else os.environ
    applied: dict[str, str] = {}
    if target.get(OS_TRUSTSTORE_ENV, "").strip().lower() in DISABLED_ENV_VALUES:
        applied[OS_TRUSTSTORE_ENV] = "disabled"
    else:
        truststore_status = enable_os_truststore()
        target[OS_TRUSTSTORE_ENV] = truststore_status
        applied[OS_TRUSTSTORE_ENV] = truststore_status
    if args.dev_token and not target.get(AUTH_TOKEN_ENV, "").strip():
        target[AUTH_TOKEN_ENV] = args.dev_token
        applied[AUTH_TOKEN_ENV] = "set_from_dev_token"
    if args.cors_origins:
        target[CORS_ORIGINS_ENV] = ",".join(args.cors_origins)
        applied[CORS_ORIGINS_ENV] = target[CORS_ORIGINS_ENV]
    if not target.get(ENVIRONMENT_ENV, "").strip():
        environment = target.get(DEPLOYMENT_TIER_ENV, "").strip() or "local"
        target[ENVIRONMENT_ENV] = environment
        applied[ENVIRONMENT_ENV] = environment
    return applied


def enable_os_truststore() -> str:
    """Enable OS certificate verification for local Coinbase REST reads."""

    try:
        import truststore
    except Exception:
        return "unavailable"
    try:
        truststore.inject_into_ssl()
    except Exception:
        return "failed"
    return "enabled"


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
    write_cors_headers(handler)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


def write_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    origin = handler.headers.get("Origin") or ""
    allowed_origins = {
        item.strip()
        for item in os.environ.get(CORS_ORIGINS_ENV, DEFAULT_CORS_ORIGIN).split(",")
        if item.strip()
    }
    if "*" in allowed_origins:
        handler.send_header("Access-Control-Allow-Origin", "*")
    elif origin in allowed_origins:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
    handler.send_header(
        "Access-Control-Allow-Headers",
        "Authorization,Content-Type,Idempotency-Key,X-Admin-Actor,"
        "X-Admin-Roles,X-Correlation-Id,X-Operator-Intent,X-Request-Id",
    )
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")


class AdminMvpRequestHandler(BaseHTTPRequestHandler):
    server_version = "CoinbaseAdminMvp/0.1"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        write_cors_headers(self)
        self.send_header("Content-Length", "0")
        self.end_headers()

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
        elif path == "/api/v1/admin/live-execution/adapter-decisions":
            result = service.record_live_adapter_decision(body, context)
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
        elif path == SPOT_MANUAL_ORDER_PROOF_CHAIN_ROUTE:
            result = service.record_spot_manual_order_proof_chain(body, context)
        elif path == SPOT_CANCEL_ORDER_PROOF_CHAIN_ROUTE:
            result = service.record_spot_cancel_order_proof_chain(body, context)
        elif path == "/api/v1/futures/orders":
            result = service.submit_futures_command(path, body, context)
        elif path.startswith("/api/v1/futures/positions/") and (
            path.endswith("/close-reduce") or path.endswith("/reconciliation")
        ):
            result = service.submit_futures_command(path, body, context)
        elif path.startswith("/api/v1/futures/orders/") and path.endswith("/cancel"):
            result = service.submit_futures_command(path, body, context)
        elif path == "/api/v1/futures/risk-proofs":
            result = service.record_futures_risk_proof(body, context)
        else:
            result = service._error(404, f"Admin MVP mutation route not found: {path}", context)
        write_json(self, result)

    def log_message(self, format: str, *args: Any) -> None:
        return None


def main() -> None:
    args = parse_args()
    apply_local_environment(args)
    server = ThreadingHTTPServer((args.host, args.port), AdminMvpRequestHandler)
    print(f"Admin MVP API listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
