"""Backend-owned Admin MVP command and read service.

The service keeps the local Admin API small: it exposes the read shapes the
current frontend needs, records proof-chain evidence, and performs live Coinbase
submission only when explicit backend gates are satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import unquote
import uuid


class AdminMvpFuturesAccountFamily(str, Enum):
    US_CFM = "coinbase_futures_us_cfm"
    INTX_PERPETUALS = "coinbase_intx_perpetuals"


class AdminMvpFuturesIntxApplicability(str, Enum):
    NOT_APPLICABLE_US_ACCOUNT = "not_applicable_us_account"
    REQUIRES_INTX_ACCOUNT = "requires_intx_account"


class AdminMvpFuturesExecutorStatus(str, Enum):
    PENDING_LIVE_DECISION = "pending_live_decision"
    OBSERVED_LIVE_DISABLED = "observed_live_disabled"
    LIVE_ENABLED = "live_enabled"


ADMIN_API_VERSION = "0.1.0-prod-mvp"
MANUAL_ORDER_ROUTE = "/api/v1/orders"
CANCEL_ORDER_ROUTE = "/api/v1/orders/{client_order_id}/cancel"
ADMIN_RUNTIME_ROUTE = "/api/v1/admin/runtime"
ACCOUNT_MANAGEMENT_ROUTE = "/api/v1/admin/account-management"
ACCOUNT_WALLET_ROUTE = "/api/v1/admin/wallet"
ACCOUNT_PRODUCTS_ROUTE = "/api/v1/admin/products"
ACCOUNT_PRODUCTS_REFRESH_ROUTE = "/api/v1/admin/products/refresh"
ACCOUNT_FEES_ROUTE = "/api/v1/admin/fees"
ACCOUNT_MANAGEMENT_MODULE_ID = "account_management"
PRODUCTS_JSON_PATH_ENV = "COINBASE_ADMIN_PRODUCTS_JSON_PATH"
DEFAULT_PRODUCTS_JSON_PATH = Path(__file__).resolve().parents[2] / "products.json"
FRONTEND_LOCAL_RELEASE_MANIFEST_ENV = "COINBASE_ADMIN_FRONTEND_LOCAL_RELEASE_MANIFEST_PATH"
BACKEND_LOCAL_RELEASE_MANIFEST_ENV = "COINBASE_BACKEND_LOCAL_RELEASE_MANIFEST_PATH"
APPROVAL_LOG_PATH_ENV = "COINBASE_ADMIN_API_APPROVAL_LOG_PATH"
IDEMPOTENCY_LOG_PATH_ENV = "COINBASE_ADMIN_API_IDEMPOTENCY_LOG_PATH"
AUDIT_LOG_PATH_ENV = "COINBASE_ADMIN_API_AUDIT_LOG_PATH"
CAP_GUARD_LOG_PATH_ENV = "COINBASE_ADMIN_API_CAP_GUARD_LOG_PATH"
RECONCILIATION_LOG_PATH_ENV = "COINBASE_ADMIN_API_RECONCILIATION_LOG_PATH"
LIVE_SERVICE_DECISION_LOG_PATH_ENV = "COINBASE_ADMIN_API_LIVE_SERVICE_DECISION_LOG_PATH"
LIVE_ADAPTER_DECISION_LOG_PATH_ENV = "COINBASE_ADMIN_API_LIVE_ADAPTER_DECISION_LOG_PATH"
ACCOUNT_SNAPSHOT_WALLET_SOURCE = "account_management_snapshot"
FUTURES_MARGIN_COLLATERAL_SOURCE = "futures_us_cfm_margin_collateral"
BACKEND_REST_CLIENT_SOURCE = "backend_rest_client"
BACKEND_REST_FRESHNESS = "backend_rest_fresh"
LOCAL_DEFAULT_FRESHNESS = "local_default_not_connected"
SPOT_ADMISSION_QUOTE_CURRENCIES = ("USDC", "USD")
DEFAULT_SPOT_PRODUCT_SCOPE = ("BTC-USDC",)
FUTURES_MODULE_ID = "futures_perpetuals"
FUTURES_ACCOUNT_FAMILY_US_CFM = AdminMvpFuturesAccountFamily.US_CFM.value
FUTURES_INTX_APPLICABILITY_US_ACCOUNT = (
    AdminMvpFuturesIntxApplicability.NOT_APPLICABLE_US_ACCOUNT.value
)
UNSCOPED_LIVE_DECISION_VALUE = "unscoped"
FUTURES_CONFIGURED_PRODUCT_SCOPE = ("AVP-20DEC30-CDE", "BIP-20DEC30-CDE")
FUTURES_CDE_CONTRACT_SIZE_BY_SYMBOL = {
    "AVA": "10",
    "AVP": "10",
    "BIP": "0.01",
    "BIT": "0.01",
    "ET": "0.10",
    "ETP": "0.10",
    "SLP": "5",
    "XPP": "500",
}
FUTURES_READ_ROUTES = (
    "/api/v1/futures/command-suite",
    "/api/v1/futures/account",
    "/api/v1/futures/positions",
    "/api/v1/futures/positions/{position_key}",
    "/api/v1/futures/orders/{client_order_id}/fill-readback",
    "/api/v1/futures/risk-proofs",
    "/api/v1/futures/risk-proofs/{futures_risk_proof_id}",
)
FUTURES_COMMAND_CONTRACTS = (
    "futures_account_scope_contract",
    "futures_margin_collateral_risk_proof",
    "futures_reconciliation_contract",
    "futures_live_adapter_contract",
)
FUTURES_EXECUTOR_BOUNDARY_SOURCE = "admin_api_futures_executor_boundary"
FUTURES_COMMAND_SPECS = (
    {
        "command": "futures_place",
        "action_class": "live_exchange_place",
        "route": "/api/v1/futures/orders",
        "service_method": "place_futures_order",
        "identity_key": "product_id",
        "required_permission": "order:create",
    },
    {
        "command": "futures_close_reduce",
        "action_class": "live_exchange_cancel",
        "route": "/api/v1/futures/positions/{position_key}/close-reduce",
        "service_method": "close_or_reduce_futures_position",
        "identity_key": "position_key",
        "required_permission": "order:cancel",
    },
    {
        "command": "futures_cancel",
        "action_class": "live_exchange_cancel",
        "route": "/api/v1/futures/orders/{client_order_id}/cancel",
        "service_method": "cancel_futures_order",
        "identity_key": "client_order_id",
        "required_permission": "order:cancel",
    },
    {
        "command": "futures_reconcile",
        "action_class": "local_state_mutation",
        "route": "/api/v1/futures/positions/{position_key}/reconciliation",
        "service_method": "reconcile_futures_position",
        "identity_key": "position_key",
        "required_permission": "reconciliation:record",
    },
)
FUTURES_COMMAND_REQUEST_FIELDS = {
    "futures_place": (
        {
            "field": "product_id",
            "payload_key": "product_id",
            "identity_field": True,
            "risk_field": True,
        },
        {"field": "order_side", "payload_key": "side"},
        {"field": "order_type", "payload_key": "order_type"},
        {"field": "limit_price", "payload_key": "limit_price", "risk_field": True},
        {"field": "size", "payload_key": "size", "risk_field": True},
    ),
    "futures_close_reduce": (
        {
            "field": "position_key",
            "payload_key": "position_key",
            "identity_field": True,
            "risk_field": True,
        },
        {"field": "limit_price", "payload_key": "limit_price", "risk_field": True},
        {"field": "size", "payload_key": "size", "risk_field": True},
    ),
    "futures_cancel": (
        {
            "field": "client_order_id",
            "payload_key": "client_order_id",
            "identity_field": True,
        },
    ),
    "futures_reconcile": (
        {
            "field": "position_key",
            "payload_key": "position_key",
            "identity_field": True,
        },
        {"field": "reconciliation_reason", "payload_key": "reconciliation_reason"},
    ),
}
FUTURES_COMMAND_ENABLEMENT_SEQUENCE_STEPS = (
    "resolve_prerequisite_contracts",
    "define_request_payload_contract",
    "define_backend_command_service",
    "register_admin_command_route",
    "bind_live_service_adapter",
)
FUTURES_ACCOUNT_SEMANTIC_ARTIFACTS = ("margin", "collateral", "liquidation")
FUTURES_POSITION_SEMANTIC_ARTIFACTS = ("reduce_only", "close_only")
FUTURES_LIVE_EXCHANGE_COMMANDS = (
    "futures_place",
    "futures_close_reduce",
    "futures_cancel",
)
MANUAL_ORDER_MODULE_ID = "spot_operations"
MANUAL_ORDER_ACTION_CLASS = "live_exchange_place"
MANUAL_ORDER_PERMISSION = "order:create"
MANUAL_ORDER_SERVICE_METHOD = "place_manual_order"
CANCEL_ORDER_ACTION_CLASS = "live_exchange_cancel"
CANCEL_ORDER_PERMISSION = "order:cancel"
CANCEL_ORDER_SERVICE_METHOD = "cancel_order_by_client_order_id"
SPOT_MANUAL_ORDER_PROOF_CHAIN_ROUTE = "/api/v1/spot/manual-order/proof-chain"
SPOT_MANUAL_ORDER_PROOF_CHAIN_PERMISSION = "spot_manual_order_proof:record"
SPOT_MANUAL_ORDER_PROOF_CHAIN_SERVICE_METHOD = "record_spot_manual_order_proof_chain"
SPOT_CANCEL_ORDER_PROOF_CHAIN_ROUTE = "/api/v1/spot/cancel-order/proof-chain"
SPOT_CANCEL_ORDER_PROOF_CHAIN_PERMISSION = "spot_order_cancel_proof:record"
SPOT_CANCEL_ORDER_PROOF_CHAIN_SERVICE_METHOD = "record_spot_cancel_order_proof_chain"
SPOT_MANUAL_PROOF_GATES = (
    "approval_snapshot",
    "admission_audit",
    "cap_guard",
    "reconciliation_plan",
)
SPOT_MANUAL_PROOF_GATE_FIELDS = {
    "approval_snapshot": "approval_snapshot_present",
    "admission_audit": "admission_audit_present",
    "cap_guard": "cap_guard_present",
    "reconciliation_plan": "reconciliation_plan_present",
}
SPOT_CANCEL_PROOF_GATES = ("cancel_proof_chain",)
LIVE_SERVICE_DECISION_ROUTE = "/api/v1/admin/live-execution/service-decisions"
LIVE_SERVICE_DECISION_PERMISSION = "config:update"
LIVE_SERVICE_DECISION_SERVICE_METHOD = "record_live_service_decision"
ACCOUNT_PRODUCTS_REFRESH_PERMISSION = "config:update"
ACCOUNT_PRODUCTS_REFRESH_SERVICE_METHOD = "refresh_admin_products"
LIVE_ADAPTER_DECISION_ROUTE = "/api/v1/admin/live-execution/adapter-decisions"
LIVE_ADAPTER_DECISION_PERMISSION = "config:update"
LIVE_ADAPTER_DECISION_SERVICE_METHOD = "record_live_adapter_decision"
ADMIN_RUNTIME_CONTROL_SPECS = {
    "pause": {
        "route": f"{ADMIN_RUNTIME_ROUTE}/pause",
        "required_permission": "runtime:pause",
        "service_method": "pause_runtime",
        "target_states": {"PAUSED"},
    },
    "resume": {
        "route": f"{ADMIN_RUNTIME_ROUTE}/resume",
        "required_permission": "runtime:resume",
        "service_method": "resume_runtime",
        "target_states": {"RUNNING"},
    },
    "shutdown": {
        "route": f"{ADMIN_RUNTIME_ROUTE}/shutdown",
        "required_permission": "runtime:shutdown",
        "service_method": "request_runtime_shutdown",
        "target_states": {"DRAINING", "STOPPED"},
    },
}
DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC = Decimal("3.10")
DEFAULT_MAX_EXECUTED_NOTIONAL_USDC = Decimal("1.00")
DEFAULT_FUTURES_MAX_SUBMITTED_NOTIONAL_USDC = Decimal("100.00")
DEFAULT_FUTURES_MAX_EXECUTED_NOTIONAL_USDC = Decimal("100.00")
DEFAULT_WALLET_AVAILABLE_NOTIONAL_USDC = Decimal("0")
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
ADMIN_MVP_EVIDENCE_LOG_PATH_ENVS = {
    "approval_requests": APPROVAL_LOG_PATH_ENV,
    "approval_snapshots": APPROVAL_LOG_PATH_ENV,
    "command_identity_by_idempotency_key": IDEMPOTENCY_LOG_PATH_ENV,
    "admission_audits": AUDIT_LOG_PATH_ENV,
    "spot_command_decisions": AUDIT_LOG_PATH_ENV,
    "futures_risk_proofs": AUDIT_LOG_PATH_ENV,
    "futures_command_decisions": AUDIT_LOG_PATH_ENV,
    "futures_executor_decisions": AUDIT_LOG_PATH_ENV,
    "cap_guard_decisions": CAP_GUARD_LOG_PATH_ENV,
    "reconciliation_plans": RECONCILIATION_LOG_PATH_ENV,
    "service_decisions": LIVE_SERVICE_DECISION_LOG_PATH_ENV,
    "live_adapter_decisions": LIVE_ADAPTER_DECISION_LOG_PATH_ENV,
}


class AdminMvpCommandStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NOT_IMPLEMENTED = "not_implemented"


class AdminMvpGateStatus(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"


class AdminMvpLiveServiceStatus(str, Enum):
    APPROVAL_REQUIRED = "approval_required"
    LIVE_DISABLED = "live_disabled"


@dataclass(frozen=True)
class AdminMvpRequestContext:
    """Auditable request context supplied by the BFF or dashboard adapter."""

    idempotency_key: str
    correlation_id: str
    operator_intent: str
    actor_id: str
    roles: tuple[str, ...] = ("operator",)


@dataclass(frozen=True)
class AdminMvpApiResult:
    """HTTP-like result returned by the service and local server."""

    status_code: int
    body: dict[str, Any]
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class AdminMvpStore:
    """MVP evidence store for local deployment."""

    command_identity_by_idempotency_key: dict[str, str] = field(default_factory=dict)
    service_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    approval_requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    approval_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    admission_audits: dict[str, dict[str, Any]] = field(default_factory=dict)
    cap_guard_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    reconciliation_plans: dict[str, dict[str, Any]] = field(default_factory=dict)
    live_adapter_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    spot_command_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    futures_risk_proofs: dict[str, dict[str, Any]] = field(default_factory=dict)
    futures_command_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    futures_executor_decisions: dict[str, dict[str, Any]] = field(default_factory=dict)
    submitted_notional_usdc: Decimal = Decimal("0")
    executed_notional_usdc: Decimal = Decimal("0")
    live_coinbase_orders_ran: bool = False


@dataclass(frozen=True)
class AdminMvpEvidenceLog:
    """Append and load local JSONL evidence entries for restart-safe MVP state."""

    collection_paths: Mapping[str, Path] = field(default_factory=dict)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "AdminMvpEvidenceLog":
        source = os.environ if environ is None else environ
        paths: dict[str, Path] = {}
        for collection, env_name in ADMIN_MVP_EVIDENCE_LOG_PATH_ENVS.items():
            raw_path = str(source.get(env_name) or "").strip()
            if raw_path:
                paths[collection] = Path(raw_path)
        return cls(paths)

    def append(self, collection: str, key: str, record: Any) -> None:
        path = self.collection_paths.get(collection)
        if path is None:
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"collection": collection, "key": key, "record": record}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, default=str))
            handle.write("\n")

    def load_store(self) -> AdminMvpStore:
        store = AdminMvpStore()
        for path in _unique_paths(self.collection_paths.values()):
            for entry in self._read_entries(path):
                _apply_evidence_log_entry(store, entry)
        _refresh_store_live_submission_totals(store)
        return store

    def _read_entries(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []

        entries: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    entries.append(entry)
        return entries


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _unique_texts(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _apply_evidence_log_entry(store: AdminMvpStore, entry: Mapping[str, Any]) -> None:
    collection = str(entry.get("collection") or "")
    key = str(entry.get("key") or "")
    record = entry.get("record")
    if not key:
        return

    if collection == "command_identity_by_idempotency_key":
        if isinstance(record, dict):
            client_order_id = str(record.get("client_order_id") or "")
        else:
            client_order_id = str(record or "")
        if client_order_id:
            store.command_identity_by_idempotency_key[key] = client_order_id
        return

    collection_store = _evidence_collection_store(store, collection)
    if collection_store is None or not isinstance(record, dict):
        return
    collection_store[key] = record


def _evidence_collection_store(
    store: AdminMvpStore,
    collection: str,
) -> dict[str, dict[str, Any]] | None:
    if collection == "service_decisions":
        return store.service_decisions
    if collection == "approval_requests":
        return store.approval_requests
    if collection == "approval_snapshots":
        return store.approval_snapshots
    if collection == "admission_audits":
        return store.admission_audits
    if collection == "cap_guard_decisions":
        return store.cap_guard_decisions
    if collection == "reconciliation_plans":
        return store.reconciliation_plans
    if collection == "live_adapter_decisions":
        return store.live_adapter_decisions
    if collection == "spot_command_decisions":
        return store.spot_command_decisions
    if collection == "futures_risk_proofs":
        return store.futures_risk_proofs
    if collection == "futures_command_decisions":
        return store.futures_command_decisions
    if collection == "futures_executor_decisions":
        return store.futures_executor_decisions
    return None


def _refresh_store_live_submission_totals(store: AdminMvpStore) -> None:
    submitted_notional = Decimal("0")
    executed_notional = Decimal("0")
    live_orders_ran = False
    for record in store.spot_command_decisions.values():
        if not bool(record.get("live_exchange_submitted")):
            continue
        live_orders_ran = True
        submitted_notional += _decimal_value(record.get("notional_usdc"), Decimal("0"))
        executed_notional += _decimal_value(
            record.get("executed_notional_usdc"),
            Decimal("0"),
        )
    for record in store.futures_command_decisions.values():
        if not bool(record.get("live_exchange_submitted")):
            continue
        live_orders_ran = True
        submitted_notional += _decimal_value(
            record.get("submitted_notional_usdc"),
            Decimal("0"),
        )
        executed_notional += _decimal_value(
            record.get("executed_notional_usdc"),
            Decimal("0"),
        )

    store.submitted_notional_usdc = submitted_notional
    store.executed_notional_usdc = executed_notional
    store.live_coinbase_orders_ran = live_orders_ran


@dataclass(frozen=True)
class AdminMvpDependencies:
    """Runtime dependencies for the Admin MVP service."""

    rest_client: Any = None
    rest_client_available: bool = False
    live_coinbase_execution_enabled: bool = False
    runtime_controller_factory: Callable[[], Any] = field(
        default_factory=lambda: _default_runtime_controller_factory
    )
    uuid_factory: Callable[[], str] = field(default_factory=lambda: lambda: str(uuid.uuid4()))
    now_factory: Callable[[], datetime] = field(
        default_factory=lambda: lambda: datetime.now(timezone.utc)
    )


def live_coinbase_execution_enabled_from_env() -> bool:
    """Return True when local backend live execution is explicitly enabled."""

    for name in (
        "COINBASE_ADMIN_LIVE_COINBASE_EXECUTION",
        "COINBASE_ADMIN_API_LIVE_COINBASE_EXECUTION_ENABLED",
    ):
        value = os.environ.get(name, "")
        if value.strip().lower() in TRUTHY_ENV_VALUES:
            return True
    return False


def _default_runtime_controller_factory() -> Any:
    from core.runtime_controller import get_runtime_controller

    return get_runtime_controller()


class AdminMvpService:
    """Small backend Admin API service for the local MVP."""

    def __init__(
        self,
        dependencies: AdminMvpDependencies | None = None,
        store: AdminMvpStore | None = None,
        evidence_log: AdminMvpEvidenceLog | None = None,
    ) -> None:
        self.dependencies = dependencies or AdminMvpDependencies(
            live_coinbase_execution_enabled=live_coinbase_execution_enabled_from_env(),
        )
        self.evidence_log = evidence_log or AdminMvpEvidenceLog.from_env()
        self.store = store or self.evidence_log.load_store()
        self._futures_product_metadata_cache: dict[
            str, tuple[dict[str, Any], str | None]
        ] = {}

    def _persist_record(self, collection: str, key: str, record: Any) -> None:
        self.evidence_log.append(collection, key, record)

    def control_runtime(
        self,
        action: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Request one backend runtime lifecycle transition."""

        normalized_action = action.strip().lower()
        spec = ADMIN_RUNTIME_CONTROL_SPECS.get(normalized_action)
        if spec is None:
            return self._error(
                404,
                f"Admin runtime control action not found: {action}",
                context,
            )

        controller = self.dependencies.runtime_controller_factory()
        before = self._runtime_controller_snapshot(controller)
        transition = self._runtime_transition(controller, normalized_action)
        transition_applied = bool(transition())
        after = self._runtime_controller_snapshot(controller)
        target_states = set(spec["target_states"])
        if transition_applied:
            status = AdminMvpCommandStatus.ACCEPTED.value
            message = "Runtime control transition accepted."
        elif after["runtime_state"] in target_states:
            status = "already_in_requested_state"
            message = "Runtime already reported the requested state."
        else:
            status = AdminMvpCommandStatus.REJECTED.value
            message = "Runtime control transition rejected for the current state."

        runtime_state_mutated = before["runtime_state"] != after["runtime_state"]
        response = {
            "type": "admin_runtime_control",
            "status": status,
            "message": message,
            "route": spec["route"],
            "method": "POST",
            "module_id": "admin_system_health",
            "action_class": "admin_runtime",
            "required_permission": spec["required_permission"],
            "service_method": spec["service_method"],
            "operator": {
                "actor_id": context.actor_id,
                "roles": list(context.roles),
                "operator_intent": context.operator_intent,
            },
            "audit": {
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_surface": spec["route"],
            },
            "runtime_state_before": before["runtime_state"],
            "runtime_state_after": after["runtime_state"],
            "transition_applied": transition_applied,
            "runtime_state_mutated": runtime_state_mutated,
            "local_state_mutated": runtime_state_mutated,
            "order_state_mutated": False,
            "exchange_state_mutated": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "live_exchange_submitted": False,
            "drain_requested": normalized_action == "shutdown",
            "drain_executed": False,
            "read_only": False,
            "frontend_safe": True,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            **after,
            **self._live_outputs(False, Decimal("0")),
        }
        return self._ok(response, context)

    def get_read_response(
        self,
        path: str,
        query: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Return a local read response for one Admin API path."""

        normalized_path = _normalize_path(path)
        if normalized_path == "/api/v1/admin/bootstrap":
            return self._ok(self._admin_bootstrap(context), context)
        if normalized_path == ADMIN_RUNTIME_ROUTE:
            return self._ok(self._admin_runtime_status(context), context)
        if normalized_path == "/api/v1/admin/health":
            return self._ok(self._admin_health(), context)
        if normalized_path == "/api/v1/admin/session":
            return self._ok(self._admin_session(context), context)
        if normalized_path == "/api/v1/admin/oidc-readiness":
            return self._ok(self._oidc_readiness(), context)
        if normalized_path == "/api/v1/admin/capabilities":
            return self._ok(self._capability_registry(), context)
        if normalized_path == "/api/v1/admin/csrf":
            return self._ok(self._csrf_contract(), context)
        if normalized_path == ACCOUNT_MANAGEMENT_ROUTE:
            return self._ok(self._account_management(context), context)
        if normalized_path == ACCOUNT_WALLET_ROUTE:
            return self._ok(self._admin_wallet(context), context)
        if normalized_path == ACCOUNT_PRODUCTS_ROUTE:
            return self._ok(self._admin_products(query, context), context)
        if normalized_path == ACCOUNT_FEES_ROUTE:
            return self._ok(self._admin_fees(context), context)
        if normalized_path == "/api/v1/admin/live-enablement":
            return self._ok(self._live_enablement(), context)
        if normalized_path == "/api/v1/admin/enterprise-readiness":
            return self._ok(self._enterprise_readiness(), context)
        if normalized_path == "/api/v1/admin/release-gate":
            return self._ok(self._simple_gate("admin_release_gate"), context)
        if normalized_path == "/api/v1/admin/recovery-gate":
            return self._ok(self._simple_gate("admin_recovery_gate"), context)
        if normalized_path == "/api/v1/admin/fill-ledger-health":
            return self._ok(self._simple_gate("admin_fill_ledger_health"), context)
        if normalized_path == "/api/v1/admin/frontend-fixtures":
            return self._ok(self._frontend_fixtures(), context)
        if normalized_path == "/api/v1/admin/approvals":
            return self._ok(self._approval_list(), context)
        if normalized_path.startswith("/api/v1/admin/approvals/requests/"):
            return self._ok(
                self._approval_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/admission-audits":
            return self._ok(self._admission_audit_list(), context)
        if normalized_path.startswith("/api/v1/admin/admission-audits/"):
            return self._ok(
                self._admission_audit_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/cap-guard/decisions":
            return self._ok(self._cap_guard_list(), context)
        if normalized_path.startswith("/api/v1/admin/cap-guard/decisions/"):
            return self._ok(
                self._cap_guard_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/reconciliation/plans":
            return self._ok(self._reconciliation_list(), context)
        if normalized_path.startswith("/api/v1/admin/reconciliation/plans/"):
            return self._ok(
                self._reconciliation_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/live-execution/admission-preview":
            return self.preview_admission(query, context)
        if normalized_path == "/api/v1/admin/live-execution/service-decisions":
            return self._ok(self._live_service_decision_list(), context)
        if normalized_path.startswith("/api/v1/admin/live-execution/service-decisions/"):
            return self._ok(
                self._live_service_decision_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/live-execution/adapter-decisions":
            return self._ok(self._live_adapter_decision_list(), context)
        if normalized_path.startswith("/api/v1/admin/live-execution/adapter-decisions/"):
            return self._ok(
                self._live_adapter_decision_detail(_last_path_part(normalized_path)),
                context,
            )
        if normalized_path == "/api/v1/admin/guard-risk-policy":
            return self._ok(self._guard_risk_policy(query), context)
        if normalized_path == "/api/v1/admin/audit-workbench":
            return self._ok(self._audit_workbench(query), context)
        if normalized_path == "/api/v1/orders":
            return self._ok(self._order_list(query), context)
        if normalized_path.startswith("/api/v1/orders/"):
            return self._ok(self._order_detail(_last_path_part(normalized_path)), context)
        if normalized_path == "/api/v1/spot/command-suite":
            return self._ok(self._spot_command_suite(query, context), context)
        if normalized_path.startswith("/api/v1/spot/"):
            return self._ok(self._spot_placeholder(normalized_path, query), context)
        if normalized_path.startswith("/api/v1/stealth/"):
            return self._ok(self._stealth_placeholder(normalized_path, query), context)
        if normalized_path.startswith("/api/v1/movement-repricing/"):
            return self._ok(
                self._movement_repricing_placeholder(normalized_path, query),
                context,
            )
        if normalized_path.startswith("/api/v1/futures/"):
            return self._ok(
                self._futures_placeholder(normalized_path, query, context),
                context,
            )
        return self._error(404, f"Admin MVP route not found: {normalized_path}", context)

    def record_live_service_decision(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record backend live-service posture evidence."""

        decision_id = str(body.get("decision_id") or self.dependencies.uuid_factory())
        record = self._live_service_decision_record(decision_id, body, context)
        self.store.service_decisions[decision_id] = record
        self._persist_record("service_decisions", decision_id, record)
        return self._ok(
            {
                "type": "admin_live_service_decision",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "action_class": "local_state_mutation",
                "required_permission": LIVE_SERVICE_DECISION_PERMISSION,
                "service_method": LIVE_SERVICE_DECISION_SERVICE_METHOD,
                "message": "Live-service decision recorded.",
                "decision": record,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _live_service_decision_record(
        self,
        decision_id: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        requested_status = str(
            body.get("requested_service_status")
            or AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value
        )
        return {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "route": LIVE_SERVICE_DECISION_ROUTE,
            "method": "POST",
            "module_id": "admin_system_health",
            "action_class": "local_state_mutation",
            "required_permission": LIVE_SERVICE_DECISION_PERMISSION,
            "service_method": LIVE_SERVICE_DECISION_SERVICE_METHOD,
            "target_route": str(body.get("target_route") or ""),
            "target_method": str(body.get("target_method") or ""),
            "target_module_id": str(body.get("target_module_id") or "admin_system_health"),
            "target_service_method": str(body.get("target_service_method") or ""),
            "account_family": str(body.get("account_family") or UNSCOPED_LIVE_DECISION_VALUE),
            "venue_scope": str(
                body.get("venue_scope")
                or body.get("account_family")
                or UNSCOPED_LIVE_DECISION_VALUE
            ),
            "intx_applicability": str(
                body.get("intx_applicability") or UNSCOPED_LIVE_DECISION_VALUE
            ),
            "product_scope": _string_list(body.get("product_scope")),
            "status": str(body.get("status") or AdminMvpGateStatus.PASSED.value),
            "requested_service_status": requested_status,
            "live_execution_service_status": requested_status,
            "service_enabled": bool(body.get("service_enabled", True)),
            "source": "admin_api_live_service_decision_log",
            "deployment_ref": str(body.get("deployment_ref") or "coinbase-local"),
            "runtime_configuration_ref": str(
                body.get("runtime_configuration_ref") or "coinbase-local-runtime"
            ),
            "decision_reason": str(
                body.get("decision_reason")
                or "Local MVP backend live-service decision recorded."
            ),
            "live_coinbase_execution_approved": bool(
                body.get("live_coinbase_execution_approved", False)
            ),
            "max_submitted_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_submitted_notional_usdc"),
                    _default_live_max_submitted_notional(body),
                )
            ),
            "max_executed_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_executed_notional_usdc"),
                    _default_live_max_executed_notional(body),
                )
            ),
            "enablement_precondition_required": True,
            "enablement_precondition_resolved": False,
            "enablement_precondition_authority": "backend_only",
            "required_enablement_artifacts": [
                "deployment_ref",
                "runtime_configuration_ref",
                "live_coinbase_execution_approved",
            ],
            "recorded_enablement_artifacts": [
                "deployment_ref",
                "runtime_configuration_ref",
            ],
            "missing_enablement_artifacts": [
                "manual_backend_live_execution_review",
            ],
            "resolver_eligible": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "correlation_id": context.correlation_id,
            "detail": "Backend-owned disabled live-service decision evidence.",
        }

    def record_live_adapter_decision(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record backend live-adapter construction posture evidence."""

        decision_id = str(body.get("decision_id") or self.dependencies.uuid_factory())
        record = self._live_adapter_decision_record(decision_id, body, context)
        self.store.live_adapter_decisions[decision_id] = record
        self._persist_record("live_adapter_decisions", decision_id, record)
        return self._ok(
            {
                "type": "admin_live_adapter_decision",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "action_class": "local_state_mutation",
                "required_permission": LIVE_ADAPTER_DECISION_PERMISSION,
                "service_method": LIVE_ADAPTER_DECISION_SERVICE_METHOD,
                "message": "Live-adapter decision recorded.",
                "decision": record,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _live_adapter_decision_record(
        self,
        decision_id: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        requested_status = str(
            body.get("requested_adapter_status")
            or AdminMvpLiveServiceStatus.LIVE_DISABLED.value
        )
        return {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "route": LIVE_ADAPTER_DECISION_ROUTE,
            "method": "POST",
            "module_id": "admin_system_health",
            "action_class": "local_state_mutation",
            "required_permission": LIVE_ADAPTER_DECISION_PERMISSION,
            "service_method": LIVE_ADAPTER_DECISION_SERVICE_METHOD,
            "status": str(body.get("status") or AdminMvpGateStatus.BLOCKED.value),
            "requested_adapter_status": requested_status,
            "live_execution_adapter_status": requested_status,
            "target_route": str(body.get("target_route") or MANUAL_ORDER_ROUTE),
            "target_method": str(body.get("target_method") or "POST"),
            "target_module_id": str(body.get("target_module_id") or MANUAL_ORDER_MODULE_ID),
            "target_service_method": str(
                body.get("target_service_method") or MANUAL_ORDER_SERVICE_METHOD
            ),
            "account_family": str(body.get("account_family") or UNSCOPED_LIVE_DECISION_VALUE),
            "venue_scope": str(
                body.get("venue_scope")
                or body.get("account_family")
                or UNSCOPED_LIVE_DECISION_VALUE
            ),
            "intx_applicability": str(
                body.get("intx_applicability") or UNSCOPED_LIVE_DECISION_VALUE
            ),
            "product_scope": _string_list(body.get("product_scope")),
            "adapter_reference": str(
                body.get("adapter_reference")
                or f"AdminApiCommandService.{MANUAL_ORDER_SERVICE_METHOD}"
            ),
            "adapter_constructed": bool(body.get("adapter_constructed", False)),
            "adapter_enabled": bool(body.get("adapter_enabled", False)),
            "source": "admin_api_live_adapter_decision_log",
            "construction_review_ref": str(
                body.get("construction_review_ref")
                or "adapter-construction-review-disabled"
            ),
            "decision_reason": str(
                body.get("decision_reason")
                or "Local MVP backend live-adapter decision recorded."
            ),
            "live_coinbase_execution_approved": bool(
                body.get("live_coinbase_execution_approved", False)
            ),
            "max_submitted_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_submitted_notional_usdc"),
                    _default_live_max_submitted_notional(body),
                )
            ),
            "max_executed_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_executed_notional_usdc"),
                    _default_live_max_executed_notional(body),
                )
            ),
            "construction_precondition_required": True,
            "construction_precondition_resolved": False,
            "construction_precondition_authority": "backend_route_binding_only_no_execution",
            "required_construction_artifacts": [
                "route_bound_live_execution_adapter",
                "shared_command_service_adapter",
            ],
            "recorded_construction_artifacts": ["route_bound_live_execution_adapter"],
            "missing_construction_artifacts": ["shared_command_service_adapter"],
            "route_mapping_satisfies_construction": False,
            "adapter_configuration_satisfies_construction": False,
            "resolver_eligible": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "correlation_id": context.correlation_id,
            "detail": "Backend-owned disabled live-adapter decision evidence.",
        }

    def record_spot_manual_order_proof_chain(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record backend-owned proof-chain evidence for one spot manual order."""

        proof_context = _spot_manual_order_context_from_body(body)
        if proof_context is None:
            return self._error(
                400,
                "Spot manual-order proof chain requires route, client_order_id, command idempotency key, and payload hash evidence.",
                context,
            )

        record_ids = self._spot_manual_order_proof_chain_record_ids(body, proof_context)
        snapshot = self._account_snapshot()
        cap_guard_allowed = bool(snapshot["readiness"]["spot_wallet_inventory_ready"])
        evidence = self._record_spot_manual_order_proof_chain_evidence(
            body=body,
            context=context,
            proof_context=proof_context,
            record_ids=record_ids,
            cap_guard_allowed=cap_guard_allowed,
        )

        admission_context = AdminMvpRequestContext(
            idempotency_key=proof_context["command_idempotency_key"],
            correlation_id=context.correlation_id,
            operator_intent=proof_context["operator_intent"],
            actor_id=proof_context["actor_id"],
            roles=context.roles,
        )
        admission = self._admission_decision(
            context=admission_context,
            identity_value=proof_context["identity_value"],
            payload_hash=proof_context["payload_hash"],
        )
        missing_gate_chain = _spot_manual_missing_gates(admission)
        resolved_gate_chain = [
            gate for gate in SPOT_MANUAL_PROOF_GATES if gate not in missing_gate_chain
        ]
        proof_chain_status = (
            AdminMvpGateStatus.PASSED.value
            if not missing_gate_chain
            else AdminMvpGateStatus.BLOCKED.value
        )
        return self._ok(
            {
                "type": "spot_manual_order_proof_chain_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "route": SPOT_MANUAL_ORDER_PROOF_CHAIN_ROUTE,
                "method": "POST",
                "module_id": MANUAL_ORDER_MODULE_ID,
                "action_class": "local_state_mutation",
                "required_permission": SPOT_MANUAL_ORDER_PROOF_CHAIN_PERMISSION,
                "service_method": SPOT_MANUAL_ORDER_PROOF_CHAIN_SERVICE_METHOD,
                "message": "Spot manual-order proof-chain evidence recorded by backend Admin API.",
                "target_route": proof_context["route"],
                "target_method": proof_context["method"],
                "identity_key": proof_context["identity_key"],
                "identity_value": proof_context["identity_value"],
                "command_idempotency_key": proof_context["command_idempotency_key"],
                "payload_hash": proof_context["payload_hash"],
                "proof_chain_status": proof_chain_status,
                "resolved_gate_chain": resolved_gate_chain,
                "missing_gate_chain": missing_gate_chain,
                "approval_request_id": record_ids["approval_request_id"],
                "approval_snapshot_id": record_ids["approval_snapshot_id"],
                "admission_audit_id": record_ids["admission_audit_id"],
                "cap_guard_decision_id": record_ids["cap_guard_decision_id"],
                "reconciliation_plan_id": record_ids["reconciliation_plan_id"],
                "admission_decision": admission,
                "evidence": evidence,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "wallet_check_source": ACCOUNT_SNAPSHOT_WALLET_SOURCE,
                "coinbase_order_submission_allowed": False,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _spot_manual_order_proof_chain_record_ids(
        self,
        body: Mapping[str, Any],
        proof_context: Mapping[str, Any],
    ) -> dict[str, str]:
        suffix = _proof_chain_record_key(proof_context)
        return {
            "approval_request_id": str(
                body.get("approval_request_id") or f"mvp-approval-request-{suffix}"
            ),
            "approval_snapshot_id": str(
                body.get("approval_snapshot_id") or f"mvp-approval-{suffix}"
            ),
            "admission_audit_id": str(
                body.get("admission_audit_id") or f"mvp-admission-audit-{suffix}"
            ),
            "cap_guard_decision_id": str(
                body.get("cap_guard_decision_id") or f"mvp-cap-guard-{suffix}"
            ),
            "reconciliation_plan_id": str(
                body.get("reconciliation_plan_id") or f"mvp-reconciliation-{suffix}"
            ),
        }

    def _record_spot_manual_order_proof_chain_evidence(
        self,
        *,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
        proof_context: Mapping[str, Any],
        record_ids: Mapping[str, str],
        cap_guard_allowed: bool,
    ) -> dict[str, Any]:
        proof_base = {
            "route": proof_context["route"],
            "method": proof_context["method"],
            "module_id": proof_context["module_id"],
            "identity_key": proof_context["identity_key"],
            "identity_value": proof_context["identity_value"],
            "action_class": proof_context["action_class"],
            "required_permission": proof_context["required_permission"],
            "service_method": proof_context["service_method"],
            "actor_id": proof_context["actor_id"],
            "operator_intent": proof_context["operator_intent"],
            "command_idempotency_key": proof_context["command_idempotency_key"],
            "payload_hash": proof_context["payload_hash"],
        }
        max_submitted_notional = _decimal_text(
            _decimal_value(
                body.get("max_submitted_notional_usdc"),
                DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC,
            )
        )
        max_executed_notional = _decimal_text(
            _decimal_value(
                body.get("max_executed_notional_usdc"),
                DEFAULT_MAX_EXECUTED_NOTIONAL_USDC,
            )
        )
        approval_request = self.create_approval_request(
            {
                **proof_base,
                "approval_request_id": record_ids["approval_request_id"],
                "request_reason": str(
                    body.get("request_reason")
                    or "Backend spot manual-order proof-chain request."
                ),
                "cap_guard_decision_ref": record_ids["cap_guard_decision_id"],
                "reconciliation_plan_ref": record_ids["reconciliation_plan_id"],
            },
            self._proof_chain_phase_context(context, "approval-request"),
        )
        approval_decision = self.decide_approval_request(
            record_ids["approval_request_id"],
            {
                "decision": "approved",
                "approval_id": record_ids["approval_snapshot_id"],
                "decision_reason": str(
                    body.get("decision_reason")
                    or "Backend spot manual-order proof-chain approval snapshot."
                ),
                "cap_guard_decision_ref": record_ids["cap_guard_decision_id"],
                "reconciliation_plan_ref": record_ids["reconciliation_plan_id"],
            },
            self._proof_chain_phase_context(context, "approval-decision"),
        )
        admission_audit = self.record_admission_audit(
            {
                **proof_base,
                "admission_audit_id": record_ids["admission_audit_id"],
                "approval_snapshot_id": record_ids["approval_snapshot_id"],
                "allowed": True,
                "status": AdminMvpGateStatus.PASSED.value,
            },
            self._proof_chain_phase_context(context, "admission-audit"),
        )
        cap_guard = self.record_cap_guard_decision(
            {
                **proof_base,
                "decision_id": record_ids["cap_guard_decision_id"],
                "approval_snapshot_id": record_ids["approval_snapshot_id"],
                "admission_audit_id": record_ids["admission_audit_id"],
                "allowed": cap_guard_allowed,
                "status": (
                    AdminMvpGateStatus.PASSED.value
                    if cap_guard_allowed
                    else AdminMvpGateStatus.BLOCKED.value
                ),
                "max_submitted_notional_usdc": max_submitted_notional,
                "max_executed_notional_usdc": max_executed_notional,
                "wallet_check_required": True,
                "wallet_check_source": ACCOUNT_SNAPSHOT_WALLET_SOURCE,
            },
            self._proof_chain_phase_context(context, "cap-guard"),
        )
        reconciliation = self.record_reconciliation_plan(
            {
                **proof_base,
                "plan_id": record_ids["reconciliation_plan_id"],
                "approval_snapshot_id": record_ids["approval_snapshot_id"],
                "admission_audit_id": record_ids["admission_audit_id"],
                "cap_guard_decision_id": record_ids["cap_guard_decision_id"],
                "allowed": cap_guard_allowed,
                "status": (
                    AdminMvpGateStatus.PASSED.value
                    if cap_guard_allowed
                    else AdminMvpGateStatus.BLOCKED.value
                ),
                "exchange_submission_required": True,
                "max_submitted_notional_usdc": max_submitted_notional,
                "max_executed_notional_usdc": max_executed_notional,
            },
            self._proof_chain_phase_context(context, "reconciliation"),
        )
        return {
            "approval_request": approval_request.body.get("approval"),
            "approval_snapshot": approval_decision.body.get("approval"),
            "admission_audit": admission_audit.body.get("admission_audit"),
            "cap_guard": cap_guard.body.get("decision"),
            "reconciliation_plan": reconciliation.body.get("plan"),
        }

    def _proof_chain_phase_context(
        self,
        context: AdminMvpRequestContext,
        phase: str,
    ) -> AdminMvpRequestContext:
        return AdminMvpRequestContext(
            idempotency_key=f"{context.idempotency_key}-{phase}",
            correlation_id=context.correlation_id,
            operator_intent=context.operator_intent,
            actor_id=context.actor_id,
            roles=context.roles,
        )

    def record_spot_cancel_order_proof_chain(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record backend-owned proof-chain evidence for one spot cancel request."""

        proof_context = _spot_cancel_order_context_from_body(body)
        if proof_context is None:
            return self._error(
                400,
                "Spot cancel-order proof chain requires route, client_order_id, command idempotency key, and payload hash evidence.",
                context,
            )

        record_ids = self._spot_cancel_order_proof_chain_record_ids(body, proof_context)
        evidence = self._record_spot_cancel_order_proof_chain_evidence(
            body=body,
            context=context,
            proof_context=proof_context,
            record_ids=record_ids,
        )
        cancel_proof = self._matching_cancel_proof(
            proof_context["identity_value"],
            proof_context["command_idempotency_key"],
            proof_context["payload_hash"],
        )
        missing_gate_chain = [] if cancel_proof else list(SPOT_CANCEL_PROOF_GATES)
        resolved_gate_chain = [
            gate for gate in SPOT_CANCEL_PROOF_GATES if gate not in missing_gate_chain
        ]
        proof_chain_status = (
            AdminMvpGateStatus.PASSED.value
            if not missing_gate_chain
            else AdminMvpGateStatus.BLOCKED.value
        )
        return self._ok(
            {
                "type": "spot_cancel_order_proof_chain_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "route": SPOT_CANCEL_ORDER_PROOF_CHAIN_ROUTE,
                "method": "POST",
                "module_id": MANUAL_ORDER_MODULE_ID,
                "action_class": "local_state_mutation",
                "required_permission": SPOT_CANCEL_ORDER_PROOF_CHAIN_PERMISSION,
                "service_method": SPOT_CANCEL_ORDER_PROOF_CHAIN_SERVICE_METHOD,
                "message": "Spot cancel-order proof-chain evidence recorded by backend Admin API.",
                "target_route": proof_context["route"],
                "target_method": proof_context["method"],
                "identity_key": proof_context["identity_key"],
                "identity_value": proof_context["identity_value"],
                "command_idempotency_key": proof_context["command_idempotency_key"],
                "payload_hash": proof_context["payload_hash"],
                "proof_chain_status": proof_chain_status,
                "resolved_gate_chain": resolved_gate_chain,
                "missing_gate_chain": missing_gate_chain,
                "admission_audit_id": record_ids["admission_audit_id"],
                "cancel_proof_chain_id": record_ids["cancel_proof_chain_id"],
                "evidence": evidence,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "coinbase_cancel_submission_allowed": False,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _spot_cancel_order_proof_chain_record_ids(
        self,
        body: Mapping[str, Any],
        proof_context: Mapping[str, Any],
    ) -> dict[str, str]:
        suffix = _proof_chain_record_key(proof_context)
        return {
            "admission_audit_id": str(
                body.get("admission_audit_id") or f"mvp-cancel-admission-audit-{suffix}"
            ),
            "cancel_proof_chain_id": str(
                body.get("cancel_proof_chain_id") or f"mvp-cancel-proof-chain-{suffix}"
            ),
        }

    def _record_spot_cancel_order_proof_chain_evidence(
        self,
        *,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
        proof_context: Mapping[str, Any],
        record_ids: Mapping[str, str],
    ) -> dict[str, Any]:
        proof_base = {
            "route": proof_context["route"],
            "method": proof_context["method"],
            "module_id": proof_context["module_id"],
            "identity_key": proof_context["identity_key"],
            "identity_value": proof_context["identity_value"],
            "action_class": proof_context["action_class"],
            "required_permission": proof_context["required_permission"],
            "service_method": proof_context["service_method"],
            "actor_id": proof_context["actor_id"],
            "operator_intent": proof_context["operator_intent"],
            "command_idempotency_key": proof_context["command_idempotency_key"],
            "payload_hash": proof_context["payload_hash"],
        }
        admission_audit = self.record_admission_audit(
            {
                **proof_base,
                "admission_audit_id": record_ids["admission_audit_id"],
                "allowed": True,
                "status": AdminMvpGateStatus.PASSED.value,
            },
            self._proof_chain_phase_context(context, "cancel-admission-audit"),
        )
        cancel_proof = self.record_reconciliation_plan(
            {
                **proof_base,
                "plan_id": record_ids["cancel_proof_chain_id"],
                "admission_audit_id": record_ids["admission_audit_id"],
                "allowed": True,
                "status": AdminMvpGateStatus.PASSED.value,
                "exchange_submission_required": False,
                "max_submitted_notional_usdc": "0",
                "max_executed_notional_usdc": "0",
                "cancel_proof_reason": str(
                    body.get("cancel_proof_reason")
                    or "Backend spot cancel proof-chain evidence."
                ),
            },
            self._proof_chain_phase_context(context, "cancel-proof-chain"),
        )
        return {
            "admission_audit": admission_audit.body.get("admission_audit"),
            "cancel_proof_chain": cancel_proof.body.get("plan"),
        }

    def submit_manual_order(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Submit a manual order through backend admission and execution gates."""

        client_order_id = self._client_order_id(context.idempotency_key)
        payload_hash = _payload_hash(body)
        notional = _manual_order_notional(body)
        admission = self._admission_decision(
            context=context,
            identity_value=client_order_id,
            payload_hash=payload_hash,
        )
        if not admission["allowed"]:
            return self._manual_order_blocked_response(
                status_code=501,
                command_status=AdminMvpCommandStatus.NOT_IMPLEMENTED,
                message="Manual order requires approval, audit, cap, and reconciliation evidence before Coinbase execution.",
                failure_stage="approval_required",
                client_order_id=client_order_id,
                notional=notional,
                admission=admission,
                context=context,
            )

        pre_coinbase_failure = self._pre_coinbase_failure(body, notional, admission)
        if pre_coinbase_failure:
            return self._manual_order_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message=pre_coinbase_failure["message"],
                failure_stage=pre_coinbase_failure["failure_stage"],
                client_order_id=client_order_id,
                notional=notional,
                admission=admission,
                context=context,
            )

        return self._execute_manual_order(
            body=body,
            context=context,
            client_order_id=client_order_id,
            notional=notional,
            admission=admission,
        )

    def cancel_order_by_client_order_id(
        self,
        client_order_id: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Cancel one spot order through backend proof and live-execution gates."""

        proof_context = _spot_cancel_order_context_from_cancel_request(
            client_order_id,
            body,
            context,
        )
        cancel_proof = self._matching_cancel_proof(
            proof_context["identity_value"],
            proof_context["command_idempotency_key"],
            proof_context["payload_hash"],
        )
        pre_coinbase_failure = self._spot_cancel_pre_coinbase_failure(
            body=body,
            cancel_proof=cancel_proof,
        )
        if pre_coinbase_failure is not None:
            status_code = int(pre_coinbase_failure["status_code"])
            return self._spot_cancel_blocked_response(
                status_code=status_code,
                command_status=(
                    AdminMvpCommandStatus.NOT_IMPLEMENTED
                    if status_code == 501
                    else AdminMvpCommandStatus.REJECTED
                ),
                message=str(pre_coinbase_failure["message"]),
                failure_stage=str(pre_coinbase_failure["failure_stage"]),
                client_order_id=client_order_id,
                proof_context=proof_context,
                cancel_proof=cancel_proof,
                context=context,
            )

        return self._execute_spot_cancel_order(
            client_order_id=client_order_id,
            proof_context=proof_context,
            cancel_proof=cancel_proof,
            context=context,
        )

    def _execute_spot_cancel_order(
        self,
        *,
        client_order_id: str,
        proof_context: Mapping[str, Any],
        cancel_proof: Mapping[str, Any] | None,
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        if not self.dependencies.live_coinbase_execution_enabled:
            return self._spot_cancel_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message="Live Coinbase execution is not enabled for this local backend process.",
                failure_stage="action_condition_guard",
                client_order_id=client_order_id,
                proof_context=proof_context,
                cancel_proof=cancel_proof,
                context=context,
            )
        try:
            controller = self.dependencies.runtime_controller_factory()
            _check_runtime_cancel_admission(controller)
            with _track_runtime_cancel(controller):
                result = self.dependencies.rest_client.cancel_orders(
                    order_ids=[client_order_id],
                )
        except Exception as exc:
            return self._spot_cancel_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message=f"Coinbase order cancel failed: {exc}",
                failure_stage="coinbase_rest",
                client_order_id=client_order_id,
                proof_context=proof_context,
                cancel_proof=cancel_proof,
                context=context,
            )

        cancel_result = _coinbase_cancel_orders_result_data(result)
        if not _coinbase_cancel_order_succeeded(cancel_result):
            return self._spot_cancel_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message=(
                    "Coinbase order cancel was not accepted: "
                    f"{_coinbase_cancel_order_error_message(cancel_result)}"
                ),
                failure_stage="coinbase_rest",
                client_order_id=client_order_id,
                proof_context=proof_context,
                cancel_proof=cancel_proof,
                context=context,
            )

        self.store.live_coinbase_orders_ran = True
        runtime_evidence = self._runtime_evidence()
        command_record = self._record_spot_cancel_command_decision(
            status=AdminMvpCommandStatus.ACCEPTED.value,
            message="Spot cancel submitted to Coinbase by backend Admin API.",
            client_order_id=client_order_id,
            proof_context=proof_context,
            cancel_proof=cancel_proof,
            context=context,
            live_exchange_submitted=True,
            coinbase_cancel_result=cancel_result,
            failure_stage=None,
            runtime_evidence=runtime_evidence,
        )
        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.ACCEPTED.value,
            "action_class": CANCEL_ORDER_ACTION_CLASS,
            "required_permission": CANCEL_ORDER_PERMISSION,
            "service_method": CANCEL_ORDER_SERVICE_METHOD,
            "message": "Spot cancel submitted to Coinbase by backend Admin API.",
            "client_order_id": client_order_id,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "proof_context": proof_context,
            "cancel_proof": _spot_cancel_proof_summary(cancel_proof),
            "failure_stage": None,
            "coinbase_cancel_submission_allowed": True,
            "coinbase_cancel_result": cancel_result,
            "live_exchange_submitted": True,
            "cancel_event_recorded": True,
            "submission_event_recorded": True,
            "submission_event_id": command_record["decision_id"],
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            **self._runtime_evidence(),
            **self._live_outputs(True, Decimal("0")),
        }
        return self._result(200, response, context, live_execution_enabled=True)

    def _spot_cancel_pre_coinbase_failure(
        self,
        *,
        body: Mapping[str, Any],
        cancel_proof: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if cancel_proof is None:
            return {
                "status_code": 501,
                "failure_stage": "cancel_proof_chain_required",
                "message": (
                    "Spot cancel requires backend cancel proof-chain evidence before "
                    "Coinbase execution."
                ),
            }
        if not _manual_live_acknowledged(body):
            return {
                "status_code": 400,
                "failure_stage": "manual_live_acknowledgement",
                "message": "Manual live acknowledgement is required.",
            }
        if not self.dependencies.rest_client_available or self.dependencies.rest_client is None:
            return {
                "status_code": 400,
                "failure_stage": "product_capability",
                "message": "Coinbase REST client is not available to the backend.",
            }
        if not self._latest_service_decision_allows_live():
            return {
                "status_code": 400,
                "failure_stage": "durable_audit_required",
                "message": "Backend live-service decision has not approved live execution.",
            }
        return None

    def _spot_cancel_blocked_response(
        self,
        *,
        status_code: int,
        command_status: AdminMvpCommandStatus,
        message: str,
        failure_stage: str,
        client_order_id: str,
        proof_context: Mapping[str, Any],
        cancel_proof: Mapping[str, Any] | None,
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        runtime_evidence = self._runtime_evidence()
        self._record_spot_cancel_command_decision(
            status=command_status.value,
            message=message,
            client_order_id=client_order_id,
            proof_context=proof_context,
            cancel_proof=cancel_proof,
            context=context,
            live_exchange_submitted=False,
            coinbase_cancel_result={},
            failure_stage=failure_stage,
            runtime_evidence=runtime_evidence,
        )
        response = {
            "type": "admin_api_command_result",
            "status": command_status.value,
            "action_class": CANCEL_ORDER_ACTION_CLASS,
            "required_permission": CANCEL_ORDER_PERMISSION,
            "service_method": CANCEL_ORDER_SERVICE_METHOD,
            "message": message,
            "client_order_id": client_order_id,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "proof_context": dict(proof_context),
            "cancel_proof": _spot_cancel_proof_summary(cancel_proof),
            "failure_stage": failure_stage,
            "coinbase_cancel_submission_allowed": False,
            "live_exchange_submitted": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            **runtime_evidence,
            **self._live_outputs(False, Decimal("0")),
        }
        return self._result(status_code, response, context)

    def create_approval_request(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record an approval request bound to one command identity."""

        approval_request_id = str(
            body.get("approval_request_id") or f"approval-request-{self.dependencies.uuid_factory()}"
        )
        record = {
            "approval_request_id": approval_request_id,
            "approval_id": None,
            "status": "requested",
            "lifecycle_status": "requested",
            "requested_by_actor_id": context.actor_id,
            "requested_at": self._now_iso(),
            "decided_at": None,
            "revoked_at": None,
            "expires_at": None,
            "expired": False,
            **_command_evidence_from_body(body),
            "decision_actor_id": None,
            "revoked_by_actor_id": None,
            "cap_guard_decision_ref": body.get("cap_guard_decision_ref"),
            "reconciliation_plan_ref": body.get("reconciliation_plan_ref"),
            "request_reason": body.get("request_reason"),
            "decision_reason": None,
            "revoke_reason": None,
            "snapshot_linked": False,
            "live_execution_authority": False,
            "live_exchange_submitted": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": "Backend-owned approval request awaiting decision.",
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
        }
        self.store.approval_requests[approval_request_id] = record
        self._persist_record("approval_requests", approval_request_id, record)
        return self._ok(
            {
                "type": "admin_approval_lifecycle",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "action_class": "local_state_mutation",
                "required_permission": "approval:request",
                "service_method": "create_approval_request",
                "message": "Approval request recorded.",
                "approval": record,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def decide_approval_request(
        self,
        approval_request_id: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record an approval decision for a requested command."""

        request = self.store.approval_requests.get(approval_request_id)
        if request is None:
            return self._error(404, "Approval request not found.", context)
        decision = str(body.get("decision") or "").strip().lower()
        if decision != "approved":
            return self._error(400, "Only approved decisions are supported in the MVP.", context)
        approval_id = str(body.get("approval_id") or f"approval-{self.dependencies.uuid_factory()}")
        record = {
            **request,
            "approval_id": approval_id,
            "approval_request_id": approval_request_id,
            "status": "approved",
            "lifecycle_status": "approved",
            "decision": "approved",
            "decision_reason": body.get("decision_reason"),
            "decision_actor_id": context.actor_id,
            "decided_at": self._now_iso(),
            "expires_at": body.get("expires_at"),
            "cap_guard_decision_ref": body.get("cap_guard_decision_ref"),
            "reconciliation_plan_ref": body.get("reconciliation_plan_ref"),
            "snapshot_linked": True,
            "decision_correlation_id": context.correlation_id,
            "decision_idempotency_key": context.idempotency_key,
            "detail": "Backend-owned approval snapshot recorded.",
        }
        self.store.approval_requests[approval_request_id] = record
        self.store.approval_snapshots[approval_id] = record
        self._persist_record("approval_requests", approval_request_id, record)
        self._persist_record("approval_snapshots", approval_id, record)
        return self._ok(
            {
                "type": "admin_approval_lifecycle",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "action_class": "local_state_mutation",
                "required_permission": "approval:manage",
                "service_method": "decide_approval_request",
                "message": "Approval decision recorded.",
                "approval": record,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_id": f"audit-{context.idempotency_key}",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def record_admission_audit(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record durable admission audit evidence for a command."""

        audit_id = str(
            body.get("admission_audit_id") or f"admission-audit-{self.dependencies.uuid_factory()}"
        )
        record = {
            "admission_audit_id": audit_id,
            "recorded_at": self._now_iso(),
            "allowed": bool(body.get("allowed", False)),
            "status": str(body.get("status") or AdminMvpGateStatus.BLOCKED.value),
            **_command_evidence_from_body(body),
            "approval_snapshot_id": body.get("approval_snapshot_id"),
            "actor_id": body.get("actor_id") or context.actor_id,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
        }
        self.store.admission_audits[audit_id] = record
        self._persist_record("admission_audits", audit_id, record)
        return self._ok(
            {
                "type": "admin_admission_audit_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "admission_audit": record,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def record_cap_guard_decision(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record cap and guard evidence for a command."""

        decision_id = str(body.get("decision_id") or f"cap-guard-{self.dependencies.uuid_factory()}")
        wallet_evidence = self._cap_guard_wallet_evidence(body)
        record = {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "allowed": bool(body.get("allowed", False)),
            "status": str(body.get("status") or AdminMvpGateStatus.BLOCKED.value),
            **_command_evidence_from_body(body),
            "approval_snapshot_id": body.get("approval_snapshot_id"),
            "admission_audit_id": body.get("admission_audit_id"),
            "max_submitted_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_submitted_notional_usdc"),
                    _default_live_max_submitted_notional(body),
                )
            ),
            "max_executed_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_executed_notional_usdc"),
                    _default_live_max_executed_notional(body),
                )
            ),
            "wallet_check_required": bool(body.get("wallet_check_required", True)),
            **wallet_evidence,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
        }
        self.store.cap_guard_decisions[decision_id] = record
        self._persist_record("cap_guard_decisions", decision_id, record)
        return self._ok(
            {
                "type": "admin_cap_guard_decision_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "decision": record,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _cap_guard_wallet_evidence(self, body: Mapping[str, Any]) -> dict[str, Any]:
        source = str(body.get("wallet_check_source") or "missing")
        if source != ACCOUNT_SNAPSHOT_WALLET_SOURCE:
            return {
                "wallet_check_status": str(
                    body.get("wallet_check_status") or AdminMvpGateStatus.BLOCKED.value
                ),
                "wallet_available_notional_usdc": _decimal_text(
                    _decimal_value(
                        body.get("wallet_available_notional_usdc"),
                        DEFAULT_WALLET_AVAILABLE_NOTIONAL_USDC,
                    )
                ),
                "wallet_check_source": source,
            }

        snapshot = self._account_snapshot()
        wallet = snapshot["wallet_inventory"]
        ready = bool(snapshot["readiness"]["spot_wallet_inventory_ready"])
        return {
            "wallet_check_status": (
                AdminMvpGateStatus.PASSED.value if ready else AdminMvpGateStatus.BLOCKED.value
            ),
            "wallet_available_notional_usdc": wallet["available_notional_usdc"],
            "wallet_check_source": ACCOUNT_SNAPSHOT_WALLET_SOURCE,
            "account_snapshot_status": snapshot["account_reality"]["status"],
            "account_snapshot_source": snapshot["account_reality"]["source"],
            "account_snapshot_proof_id": snapshot["account_reality"]["proof_id"],
        }

    def record_reconciliation_plan(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record post-submit reconciliation plan evidence for a command."""

        plan_id = str(body.get("plan_id") or f"reconciliation-{self.dependencies.uuid_factory()}")
        record = {
            "plan_id": plan_id,
            "recorded_at": self._now_iso(),
            "allowed": bool(body.get("allowed", False)),
            "status": str(body.get("status") or AdminMvpGateStatus.BLOCKED.value),
            **_command_evidence_from_body(body),
            "approval_snapshot_id": body.get("approval_snapshot_id"),
            "admission_audit_id": body.get("admission_audit_id"),
            "cap_guard_decision_id": body.get("cap_guard_decision_id"),
            "position_key": body.get("position_key"),
            "futures_risk_proof_id": body.get("futures_risk_proof_id"),
            "reconciliation_reason": str(body.get("reconciliation_reason") or ""),
            "exchange_submission_required": bool(
                body.get("exchange_submission_required", True)
            ),
            "max_submitted_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_submitted_notional_usdc"),
                    _default_live_max_submitted_notional(body),
                )
            ),
            "max_executed_notional_usdc": _decimal_text(
                _decimal_value(
                    body.get("max_executed_notional_usdc"),
                    _default_live_max_executed_notional(body),
                )
            ),
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
        }
        self.store.reconciliation_plans[plan_id] = record
        self._persist_record("reconciliation_plans", plan_id, record)
        return self._ok(
            {
                "type": "admin_reconciliation_plan_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "plan": record,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def record_futures_risk_proof(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record append-only futures risk proof evidence without executing orders."""

        command = str(body.get("command") or "futures_place")
        proof_kind = str(body.get("proof_kind") or "margin_collateral")
        proof_id = str(
            body.get("futures_risk_proof_id")
            or f"futures-risk-proof-{self.dependencies.uuid_factory()}"
        )
        record = self._futures_risk_proof_record(
            proof_id=proof_id,
            command=command,
            proof_kind=proof_kind,
            recorded_at=self._now_iso(),
            source="admin_api_futures_risk_proof_log",
            product_id=body.get("product_id"),
            position_key=body.get("position_key"),
            evidence_ref=str(body.get("evidence_ref") or "operator_recorded_futures_risk_proof"),
            verified=bool(body.get("risk_proof_verified", False)),
            accepted=bool(body.get("risk_proof_accepted", False)),
            context=context,
        )
        self.store.futures_risk_proofs[proof_id] = record
        self._persist_record("futures_risk_proofs", proof_id, record)
        return self._ok(
            {
                "type": "admin_futures_risk_proof_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "risk_proof": record,
                "proof_record_created": True,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def submit_futures_command(
        self,
        path: str,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Return an auditable fail-closed Futures command draft response."""

        route_match = _futures_command_route_match(path)
        if route_match is None:
            return self._error(404, f"Futures command route not found: {path}", context)

        spec = route_match["spec"]
        command = str(spec["command"])
        route = str(spec["route"])
        identity_key = str(spec["identity_key"])
        identity_value = str(
            route_match.get("identity_value") or body.get(identity_key) or ""
        )
        payload_hash = _payload_hash(body)
        command_suite = self._futures_command_suite()
        command_evidence = next(
            (
                item
                for item in command_suite["commands"]
                if item.get("command") == command
            ),
            {},
        )
        readiness_decision = dict(command_evidence.get("readiness_decision") or {})
        first_blocker = str(readiness_decision.get("first_blocker") or "execution_disabled")
        payload_validation = _validate_futures_command_payload(
            command=command,
            identity_key=identity_key,
            identity_value=identity_value,
            body=body,
        )
        payload_validation_failed = (
            str(payload_validation["status"]) == AdminMvpGateStatus.BLOCKED.value
        )
        admission_decision = self._futures_admission_decision(
            command=command,
            route=route,
            service_method=str(spec["service_method"]),
            identity_key=identity_key,
            identity_value=identity_value,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            payload_validation=payload_validation,
            risk_proof_id=command_evidence.get("risk_proof_id"),
            context=context,
        )
        if payload_validation_failed:
            command_record = self._record_futures_command_decision(
                status=AdminMvpCommandStatus.REJECTED.value,
                message=(
                    "Futures/Perpetual command payload failed backend validation; "
                    "no executor boundary or Coinbase call was reached."
                ),
                command=command,
                mutation_family="futures_payload_validation",
                action_class=str(spec["action_class"]),
                route=route,
                service_method=str(spec["service_method"]),
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=str(spec["required_permission"]),
                payload_hash=payload_hash,
                readiness_decision=readiness_decision,
                admission_decision=admission_decision,
                payload_validation=payload_validation,
                risk_proof_id=command_evidence.get("risk_proof_id"),
                failure_stage="futures_payload_validation_failed",
                context=context,
            )
            response = {
                "type": "admin_api_command_result",
                "status": AdminMvpCommandStatus.REJECTED.value,
                "module_id": FUTURES_MODULE_ID,
                "command": command,
                "mutation_family": "futures_payload_validation",
                "action_class": str(spec["action_class"]),
                "route": route,
                "method": "POST",
                "required_permission": str(spec["required_permission"]),
                "service_method": str(spec["service_method"]),
                "identity_key": identity_key,
                "identity_value": identity_value,
                "message": (
                    "Futures/Perpetual command payload failed backend validation; "
                    "no executor boundary or Coinbase call was reached."
                ),
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "operator_intent": context.operator_intent,
                "actor_id": context.actor_id,
                "payload_hash": payload_hash,
                "payload_validation": payload_validation,
                "command_suite_status": command_suite["status"],
                "readiness_decision": readiness_decision,
                "admission_decision": admission_decision,
                "executor_decision_id": None,
                "submission_event_recorded": True,
                "submission_event_id": command_record["decision_id"],
                "required_evidence_refs": [
                    ref
                    for blocker in command_suite["command_enablement_blocker_summaries"]
                    for ref in blocker.get("required_evidence_refs", [])
                ],
                "risk_proof_id": command_evidence.get("risk_proof_id"),
                "failure_stage": "futures_payload_validation_failed",
                "command_route_registered": True,
                "command_draft_allowed": True,
                "execution_allowed": False,
                "local_state_mutated": False,
                "exchange_state_mutated": False,
                "live_exchange_submitted": False,
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
                "spot_rule_authority": False,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                **self._runtime_evidence(),
                **self._live_outputs(False, Decimal("0")),
            }
            return self._result(400, response, context)
        if (
            command == "futures_reconcile"
            and readiness_decision.get("execution_allowed") is True
        ):
            return self._execute_futures_reconciliation(
                command=command,
                action_class=str(spec["action_class"]),
                route=route,
                service_method=str(spec["service_method"]),
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=str(spec["required_permission"]),
                payload_hash=payload_hash,
                readiness_decision=readiness_decision,
                admission_decision=admission_decision,
                payload_validation=payload_validation,
                risk_proof_id=command_evidence.get("risk_proof_id"),
                context=context,
            )
        if (
            command == "futures_reconcile"
            and first_blocker == "futures_reconciliation_execution_disabled"
        ):
            return self._futures_reconciliation_execution_boundary_response(
                command=command,
                action_class=str(spec["action_class"]),
                route=route,
                service_method=str(spec["service_method"]),
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=str(spec["required_permission"]),
                payload_hash=payload_hash,
                readiness_decision=readiness_decision,
                admission_decision=admission_decision,
                payload_validation=payload_validation,
                risk_proof_id=command_evidence.get("risk_proof_id"),
                context=context,
            )
        if first_blocker in {"futures_executor_live_disabled", "none"}:
            if _futures_live_place_requested(command, body):
                return self._execute_futures_place_order(
                    body=body,
                    context=context,
                    command=command,
                    action_class=str(spec["action_class"]),
                    route=route,
                    service_method=str(spec["service_method"]),
                    identity_key=identity_key,
                    identity_value=identity_value,
                    required_permission=str(spec["required_permission"]),
                    payload_hash=payload_hash,
                    payload_validation=payload_validation,
                    readiness_decision=readiness_decision,
                    admission_decision=admission_decision,
                    risk_proof_id=command_evidence.get("risk_proof_id"),
                )
            if _futures_live_close_reduce_requested(command, body):
                return self._execute_futures_close_reduce_position(
                    body=body,
                    context=context,
                    command=command,
                    action_class=str(spec["action_class"]),
                    route=route,
                    service_method=str(spec["service_method"]),
                    identity_key=identity_key,
                    identity_value=identity_value,
                    required_permission=str(spec["required_permission"]),
                    payload_hash=payload_hash,
                    payload_validation=payload_validation,
                    readiness_decision=readiness_decision,
                    admission_decision=admission_decision,
                    risk_proof_id=command_evidence.get("risk_proof_id"),
                )
            if _futures_live_cancel_requested(command, body):
                return self._execute_futures_cancel_order(
                    body=body,
                    context=context,
                    command=command,
                    action_class=str(spec["action_class"]),
                    route=route,
                    service_method=str(spec["service_method"]),
                    identity_key=identity_key,
                    identity_value=identity_value,
                    required_permission=str(spec["required_permission"]),
                    payload_hash=payload_hash,
                    payload_validation=payload_validation,
                    readiness_decision=readiness_decision,
                    admission_decision=admission_decision,
                    risk_proof_id=command_evidence.get("risk_proof_id"),
                )
            if first_blocker == "none":
                return self._futures_live_acknowledgement_required_response(
                    command=command,
                    action_class=str(spec["action_class"]),
                    route=route,
                    service_method=str(spec["service_method"]),
                    identity_key=identity_key,
                    identity_value=identity_value,
                    required_permission=str(spec["required_permission"]),
                    payload_hash=payload_hash,
                    readiness_decision=readiness_decision,
                    admission_decision=admission_decision,
                    payload_validation=payload_validation,
                    risk_proof_id=command_evidence.get("risk_proof_id"),
                    context=context,
                )
            executor_decision = self._record_futures_executor_decision(
                command=command,
                action_class=str(spec["action_class"]),
                route=route,
                service_method=str(spec["service_method"]),
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=str(spec["required_permission"]),
                payload_hash=payload_hash,
                readiness_decision=readiness_decision,
                admission_decision=admission_decision,
                risk_proof_id=command_evidence.get("risk_proof_id"),
                context=context,
            )
            response = {
                "type": "admin_api_command_result",
                "status": AdminMvpCommandStatus.REJECTED.value,
                "module_id": FUTURES_MODULE_ID,
                "command": command,
                "mutation_family": "futures_executor_live_disabled",
                "action_class": str(spec["action_class"]),
                "route": route,
                "method": "POST",
                "required_permission": str(spec["required_permission"]),
                "service_method": str(spec["service_method"]),
                "identity_key": identity_key,
                "identity_value": identity_value,
                "message": (
                    "Backend Futures executor boundary was reached for US CFM "
                    "and rejected before Coinbase because live Futures execution "
                    "remains disabled."
                ),
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "operator_intent": context.operator_intent,
                "actor_id": context.actor_id,
                "payload_hash": payload_hash,
                "payload_validation": payload_validation,
                "command_suite_status": command_suite["status"],
                "readiness_decision": readiness_decision,
                "admission_decision": admission_decision,
                "executor_decision_id": executor_decision["decision_id"],
                "executor_decision": executor_decision,
                "submission_event_recorded": True,
                "submission_event_id": executor_decision["decision_id"],
                "required_evidence_refs": [
                    ref
                    for blocker in command_suite["command_enablement_blocker_summaries"]
                    for ref in blocker.get("required_evidence_refs", [])
                ],
                "risk_proof_id": command_evidence.get("risk_proof_id"),
                "failure_stage": first_blocker,
                "command_route_registered": True,
                "command_draft_allowed": True,
                "execution_allowed": False,
                "local_state_mutated": False,
                "exchange_state_mutated": False,
                "live_exchange_submitted": False,
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
                "spot_rule_authority": False,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                **self._runtime_evidence(),
                **self._live_outputs(False, Decimal("0")),
            }
            return self._result(400, response, context)
        command_record = self._record_futures_command_decision(
            status=AdminMvpCommandStatus.NOT_IMPLEMENTED.value,
            message=(
                "Futures/Perpetual command drafts are backend-owned and "
                "auditable; live execution remains disabled."
            ),
            command=command,
            mutation_family="futures_contract_required",
            action_class=str(spec["action_class"]),
            route=route,
            service_method=str(spec["service_method"]),
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=str(spec["required_permission"]),
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=admission_decision,
            payload_validation=payload_validation,
            risk_proof_id=command_evidence.get("risk_proof_id"),
            failure_stage=first_blocker,
            context=context,
        )
        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.NOT_IMPLEMENTED.value,
            "module_id": FUTURES_MODULE_ID,
            "command": command,
            "mutation_family": "futures_contract_required",
            "action_class": str(spec["action_class"]),
            "route": route,
            "method": "POST",
            "required_permission": str(spec["required_permission"]),
            "service_method": str(spec["service_method"]),
            "identity_key": identity_key,
            "identity_value": identity_value,
            "message": (
                "Futures/Perpetual command drafts are backend-owned and "
                "auditable; live execution remains disabled."
            ),
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "operator_intent": context.operator_intent,
            "actor_id": context.actor_id,
            "payload_hash": payload_hash,
            "payload_validation": payload_validation,
            "command_suite_status": command_suite["status"],
            "readiness_decision": readiness_decision,
            "admission_decision": admission_decision,
            "required_evidence_refs": [
                ref
                for blocker in command_suite["command_enablement_blocker_summaries"]
                for ref in blocker.get("required_evidence_refs", [])
            ],
            "risk_proof_id": command_evidence.get("risk_proof_id"),
            "failure_stage": first_blocker,
            "submission_event_recorded": True,
            "submission_event_id": command_record["decision_id"],
            "command_route_registered": True,
            "command_draft_allowed": True,
            "execution_allowed": False,
            "local_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            **self._runtime_evidence(),
            **self._live_outputs(False, Decimal("0")),
        }
        return self._result(501, response, context)

    def _execute_futures_reconciliation(
        self,
        *,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        payload_validation: Mapping[str, Any],
        risk_proof_id: Any,
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Record Futures reconciliation as backend local evidence only."""

        plan_result = self.record_reconciliation_plan(
            {
                "plan_id": f"futures-reconciliation-{self.dependencies.uuid_factory()}",
                "route": route,
                "method": "POST",
                "module_id": FUTURES_MODULE_ID,
                "identity_key": identity_key,
                "identity_value": identity_value,
                "position_key": identity_value,
                "action_class": action_class,
                "required_permission": required_permission,
                "service_method": service_method,
                "operator_intent": context.operator_intent,
                "command_idempotency_key": context.idempotency_key,
                "payload_hash": payload_hash,
                "allowed": True,
                "status": AdminMvpGateStatus.PASSED.value,
                "exchange_submission_required": False,
                "futures_risk_proof_id": risk_proof_id,
                "reconciliation_reason": (
                    payload_validation.get("reconciliation_reason")
                    or "futures_reconciliation_execution"
                ),
                "max_submitted_notional_usdc": "0",
                "max_executed_notional_usdc": "0",
            },
            context,
        )
        plan = dict(plan_result.body.get("plan") or {})
        local_admission = {
            **dict(admission_decision),
            "status": AdminMvpGateStatus.PASSED.value,
            "allowed": True,
            "failure_stage": None,
            "execution_allowed": True,
            "reconciliation_execution_allowed": True,
            "reconciliation_plan_id": plan.get("plan_id"),
            "detail": (
                "Backend Futures reconciliation execution records local "
                "plan evidence only; no Coinbase or exchange mutation is run."
            ),
        }
        command_record = self._record_futures_command_decision(
            status=AdminMvpCommandStatus.ACCEPTED.value,
            message=(
                "Futures/Perpetual reconciliation recorded as backend local "
                "evidence; no Coinbase or exchange mutation was performed."
            ),
            command=command,
            mutation_family="futures_reconciliation_execution",
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=local_admission,
            payload_validation=payload_validation,
            risk_proof_id=risk_proof_id,
            failure_stage=None,
            context=context,
            submitted_notional=Decimal("0"),
            executed_notional=Decimal("0"),
            execution_allowed=True,
            local_state_mutated=True,
            exchange_state_mutated=False,
            runtime_evidence=self._runtime_evidence(),
        )
        return self._result(
            200,
            {
                "type": "admin_api_command_result",
                "status": AdminMvpCommandStatus.ACCEPTED.value,
                "module_id": FUTURES_MODULE_ID,
                "command": command,
                "mutation_family": "futures_reconciliation_execution",
                "action_class": action_class,
                "route": route,
                "method": "POST",
                "required_permission": required_permission,
                "service_method": service_method,
                "identity_key": identity_key,
                "identity_value": identity_value,
                "message": (
                    "Futures/Perpetual reconciliation recorded as backend local "
                    "evidence; no Coinbase or exchange mutation was performed."
                ),
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "operator_intent": context.operator_intent,
                "actor_id": context.actor_id,
                "payload_hash": payload_hash,
                "payload_validation": dict(payload_validation),
                "command_suite_status": "evidence_ready",
                "readiness_decision": dict(readiness_decision),
                "admission_decision": local_admission,
                "risk_proof_id": risk_proof_id,
                "failure_stage": None,
                "submission_event_recorded": True,
                "submission_event_id": command_record["decision_id"],
                "futures_reconciliation_execution_id": command_record["decision_id"],
                "reconciliation_plan_id": plan.get("plan_id"),
                "reconciliation_plan": plan,
                "reconciliation_plan_created": bool(plan),
                "reconciliation_execution_allowed": True,
                "reconciliation_execution_ran": True,
                "reconciliation_plan_required": False,
                "command_route_registered": True,
                "command_draft_allowed": True,
                "execution_allowed": True,
                "local_state_mutated": True,
                "exchange_state_mutated": False,
                "live_exchange_submitted": False,
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
                "spot_rule_authority": False,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                **self._runtime_evidence(),
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _futures_reconciliation_execution_boundary_response(
        self,
        *,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        payload_validation: Mapping[str, Any],
        risk_proof_id: Any,
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Reject Futures reconciliation as an explicit fail-closed boundary."""

        failure_stage = "futures_reconciliation_execution_disabled"
        message = (
            "Futures/Perpetual reconciliation execution remains backend "
            "evidence-only; no local state mutation, exchange mutation, or "
            "Coinbase call was performed."
        )
        command_record = self._record_futures_command_decision(
            status=AdminMvpCommandStatus.NOT_IMPLEMENTED.value,
            message=message,
            command=command,
            mutation_family="futures_reconciliation_execution_boundary",
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=admission_decision,
            payload_validation=payload_validation,
            risk_proof_id=risk_proof_id,
            failure_stage=failure_stage,
            context=context,
        )
        return self._result(
            501,
            {
                "type": "admin_api_command_result",
                "status": AdminMvpCommandStatus.NOT_IMPLEMENTED.value,
                "module_id": FUTURES_MODULE_ID,
                "command": command,
                "mutation_family": "futures_reconciliation_execution_boundary",
                "action_class": action_class,
                "route": route,
                "method": "POST",
                "required_permission": required_permission,
                "service_method": service_method,
                "identity_key": identity_key,
                "identity_value": identity_value,
                "message": message,
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "operator_intent": context.operator_intent,
                "actor_id": context.actor_id,
                "payload_hash": payload_hash,
                "payload_validation": payload_validation,
                "command_suite_status": "evidence_ready",
                "readiness_decision": readiness_decision,
                "admission_decision": admission_decision,
                "risk_proof_id": risk_proof_id,
                "failure_stage": failure_stage,
                "submission_event_recorded": True,
                "submission_event_id": command_record["decision_id"],
                "futures_reconciliation_execution_boundary_id": command_record[
                    "decision_id"
                ],
                "reconciliation_execution_allowed": False,
                "reconciliation_execution_ran": False,
                "reconciliation_plan_required": True,
                "command_route_registered": True,
                "command_draft_allowed": True,
                "execution_allowed": False,
                "local_state_mutated": False,
                "exchange_state_mutated": False,
                "live_exchange_submitted": False,
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
                "spot_rule_authority": False,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                **self._runtime_evidence(),
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _futures_live_acknowledgement_required_response(
        self,
        *,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        payload_validation: Mapping[str, Any],
        risk_proof_id: Any,
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Reject a live-ready Futures command that lacks explicit acknowledgement."""

        failure_stage = "futures_live_acknowledgement_required"
        message = (
            "Futures/Perpetual live command requires dry_run=false and manual "
            "live acknowledgement before Coinbase submission."
        )
        acknowledgement_admission = {
            **dict(admission_decision),
            "failure_stage": failure_stage,
            "detail": (
                "Backend Futures live execution is available, but this request "
                "did not include explicit live acknowledgement."
            ),
        }
        command_record = self._record_futures_command_decision(
            status=AdminMvpCommandStatus.REJECTED.value,
            message=message,
            command=command,
            mutation_family="futures_live_acknowledgement_required",
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=acknowledgement_admission,
            payload_validation=payload_validation,
            risk_proof_id=risk_proof_id,
            failure_stage=failure_stage,
            context=context,
        )
        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.REJECTED.value,
            "module_id": FUTURES_MODULE_ID,
            "command": command,
            "mutation_family": "futures_live_acknowledgement_required",
            "action_class": action_class,
            "route": route,
            "method": "POST",
            "required_permission": required_permission,
            "service_method": service_method,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "message": message,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "operator_intent": context.operator_intent,
            "actor_id": context.actor_id,
            "payload_hash": payload_hash,
            "payload_validation": payload_validation,
            "command_suite_status": "evidence_ready",
            "readiness_decision": readiness_decision,
            "admission_decision": acknowledgement_admission,
            "risk_proof_id": risk_proof_id,
            "failure_stage": failure_stage,
            "submission_event_recorded": True,
            "submission_event_id": command_record["decision_id"],
            "command_route_registered": True,
            "command_draft_allowed": True,
            "execution_allowed": False,
            "manual_live_acknowledgement_required": True,
            "local_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            **self._runtime_evidence(),
            **self._live_outputs(False, Decimal("0")),
        }
        return self._result(400, response, context)

    def _execute_futures_place_order(
        self,
        *,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        payload_validation: Mapping[str, Any],
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        risk_proof_id: Any,
    ) -> AdminMvpApiResult:
        """Execute a confirmed, capped US CFM Futures place order via backend REST."""

        notional = _futures_place_notional(body)
        client_order_id = _futures_client_order_id(body, context)
        live_admission = self._futures_live_admission_decision(
            admission_decision,
            client_order_id=client_order_id,
            notional=notional,
            action_label="place",
        )
        pre_coinbase_failure = self._futures_pre_coinbase_failure(
            command=command,
            body=body,
            notional=notional,
            readiness_decision=readiness_decision,
        )
        if pre_coinbase_failure is not None:
            return self._futures_place_blocked_response(
                status_code=400,
                message=pre_coinbase_failure["message"],
                failure_stage=pre_coinbase_failure["failure_stage"],
                command=command,
                action_class=action_class,
                route=route,
                service_method=service_method,
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=required_permission,
                payload_hash=payload_hash,
                payload_validation=payload_validation,
                readiness_decision=readiness_decision,
                admission_decision=live_admission,
                risk_proof_id=risk_proof_id,
                client_order_id=client_order_id,
                notional=notional,
                context=context,
            )

        proof_chain = self._record_futures_live_proof_chain(
            command=command,
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=live_admission,
            risk_proof_id=risk_proof_id,
            context=context,
        )
        live_admission = {
            **live_admission,
            "cap_guard_present": proof_chain["cap_guard_present"],
            "cap_guard_decision_id": proof_chain["cap_guard_decision_id"],
            "reconciliation_plan_present": proof_chain["reconciliation_plan_present"],
            "reconciliation_plan_id": proof_chain["reconciliation_plan_id"],
        }
        order_configuration = _futures_place_order_configuration(body)
        try:
            controller = self.dependencies.runtime_controller_factory()
            _check_runtime_admission(controller)
            with _track_runtime_place(controller):
                result = self.dependencies.rest_client.create_order(
                    client_order_id=client_order_id,
                    product_id=str(body.get("product_id") or ""),
                    side=str(body.get("side") or "").upper(),
                    order_configuration=order_configuration,
                    **_futures_create_order_kwargs(body),
                )
        except Exception as exc:
            return self._futures_place_blocked_response(
                status_code=400,
                message=f"Coinbase Futures order submission failed: {exc}",
                failure_stage="coinbase_rest",
                command=command,
                action_class=action_class,
                route=route,
                service_method=service_method,
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=required_permission,
                payload_hash=payload_hash,
                payload_validation=payload_validation,
                readiness_decision=readiness_decision,
                admission_decision=live_admission,
                risk_proof_id=risk_proof_id,
                client_order_id=client_order_id,
                notional=notional,
                context=context,
                proof_chain=proof_chain,
            )

        result_data = _object_to_dict(result)
        if not _coinbase_create_order_succeeded(result_data):
            return self._futures_place_blocked_response(
                status_code=400,
                message=(
                    "Coinbase Futures order submission was not accepted: "
                    f"{_coinbase_create_order_error_message(result_data)}"
                ),
                failure_stage="coinbase_rest",
                command=command,
                action_class=action_class,
                route=route,
                service_method=service_method,
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=required_permission,
                payload_hash=payload_hash,
                payload_validation=payload_validation,
                readiness_decision=readiness_decision,
                admission_decision=live_admission,
                risk_proof_id=risk_proof_id,
                client_order_id=client_order_id,
                notional=notional,
                context=context,
                proof_chain=proof_chain,
            )

        order_id = _coinbase_order_id_from_create_order_result(result_data)
        self.store.submitted_notional_usdc += notional
        self.store.live_coinbase_orders_ran = True
        runtime_evidence = self._runtime_evidence()
        command_record = self._record_futures_command_decision(
            status=AdminMvpCommandStatus.ACCEPTED.value,
            message="Futures/Perpetual order submitted to Coinbase by backend Admin API.",
            command=command,
            mutation_family="futures_live_place",
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=live_admission,
            payload_validation=payload_validation,
            risk_proof_id=risk_proof_id,
            failure_stage=None,
            context=context,
            client_order_id=client_order_id,
            coinbase_order_id=order_id or None,
            live_exchange_submitted=True,
            submitted_notional=notional,
            execution_allowed=True,
            local_state_mutated=True,
            exchange_state_mutated=True,
            runtime_evidence=runtime_evidence,
            cap_guard_decision_id=proof_chain["cap_guard_decision_id"],
            reconciliation_plan_id=proof_chain["reconciliation_plan_id"],
        )
        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.ACCEPTED.value,
            "module_id": FUTURES_MODULE_ID,
            "command": command,
            "mutation_family": "futures_live_place",
            "action_class": action_class,
            "route": route,
            "method": "POST",
            "required_permission": required_permission,
            "service_method": service_method,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "client_order_id": client_order_id,
            "coinbase_order_id": order_id or None,
            "exchange_order_id": order_id or None,
            "exchange_order_id_evidence_only": True,
            "message": "Futures/Perpetual order submitted to Coinbase by backend Admin API.",
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "operator_intent": context.operator_intent,
            "actor_id": context.actor_id,
            "payload_hash": payload_hash,
            "payload_validation": dict(payload_validation),
            "readiness_decision": dict(readiness_decision),
            "admission_decision": live_admission,
            "failure_stage": None,
            "submission_event_recorded": True,
            "submission_event_id": command_record["decision_id"],
            "command_route_registered": True,
            "command_draft_allowed": True,
            "execution_allowed": True,
            "local_state_mutated": True,
            "exchange_state_mutated": True,
            "live_exchange_submitted": True,
            "submitted_notional_usdc": _decimal_text(notional),
            "executed_notional_usdc": "0",
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            **proof_chain,
            **runtime_evidence,
            **self._live_outputs(True, notional),
        }
        return self._result(200, response, context, live_execution_enabled=True)

    def _execute_futures_close_reduce_position(
        self,
        *,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        payload_validation: Mapping[str, Any],
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        risk_proof_id: Any,
    ) -> AdminMvpApiResult:
        """Execute a confirmed US CFM Futures close/reduce through backend REST."""

        product_id = _futures_close_reduce_product_id(identity_value, body)
        close_body = {**dict(body), "product_id": product_id}
        notional = futures_place_notional_usdc(close_body)
        client_order_id = _futures_client_order_id(body, context)
        live_admission = self._futures_live_admission_decision(
            admission_decision,
            client_order_id=client_order_id,
            notional=notional,
            action_label="close/reduce",
        )
        pre_coinbase_failure = self._futures_close_reduce_pre_coinbase_failure(
            command=command,
            product_id=product_id,
            notional=notional,
            readiness_decision=readiness_decision,
        )
        if pre_coinbase_failure is not None:
            return self._futures_place_blocked_response(
                status_code=400,
                message=pre_coinbase_failure["message"],
                failure_stage=pre_coinbase_failure["failure_stage"],
                command=command,
                action_class=action_class,
                route=route,
                service_method=service_method,
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=required_permission,
                payload_hash=payload_hash,
                payload_validation=payload_validation,
                readiness_decision=readiness_decision,
                admission_decision=live_admission,
                risk_proof_id=risk_proof_id,
                client_order_id=client_order_id,
                notional=notional,
                context=context,
            )

        proof_chain = self._record_futures_live_proof_chain(
            command=command,
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=live_admission,
            risk_proof_id=risk_proof_id,
            context=context,
        )
        live_admission = {
            **live_admission,
            "cap_guard_present": proof_chain["cap_guard_present"],
            "cap_guard_decision_id": proof_chain["cap_guard_decision_id"],
            "reconciliation_plan_present": proof_chain["reconciliation_plan_present"],
            "reconciliation_plan_id": proof_chain["reconciliation_plan_id"],
        }
        try:
            controller = self.dependencies.runtime_controller_factory()
            _check_runtime_cancel_admission(controller)
            with _track_runtime_cancel(controller):
                result = self.dependencies.rest_client.close_position(
                    client_order_id=client_order_id,
                    product_id=product_id,
                    **_futures_close_position_kwargs(body),
                )
        except Exception as exc:
            return self._futures_place_blocked_response(
                status_code=400,
                message=f"Coinbase Futures close/reduce submission failed: {exc}",
                failure_stage="coinbase_rest",
                command=command,
                action_class=action_class,
                route=route,
                service_method=service_method,
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=required_permission,
                payload_hash=payload_hash,
                payload_validation=payload_validation,
                readiness_decision=readiness_decision,
                admission_decision=live_admission,
                risk_proof_id=risk_proof_id,
                client_order_id=client_order_id,
                notional=notional,
                context=context,
                proof_chain=proof_chain,
            )

        result_data = _object_to_dict(result)
        if not _coinbase_create_order_succeeded(result_data):
            return self._futures_place_blocked_response(
                status_code=400,
                message=(
                    "Coinbase Futures close/reduce was not accepted: "
                    f"{_coinbase_create_order_error_message(result_data)}"
                ),
                failure_stage="coinbase_rest",
                command=command,
                action_class=action_class,
                route=route,
                service_method=service_method,
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=required_permission,
                payload_hash=payload_hash,
                payload_validation=payload_validation,
                readiness_decision=readiness_decision,
                admission_decision=live_admission,
                risk_proof_id=risk_proof_id,
                client_order_id=client_order_id,
                notional=notional,
                context=context,
                proof_chain=proof_chain,
            )

        order_id = _coinbase_order_id_from_create_order_result(result_data)
        self.store.submitted_notional_usdc += notional
        self.store.live_coinbase_orders_ran = True
        runtime_evidence = self._runtime_evidence()
        command_record = self._record_futures_command_decision(
            status=AdminMvpCommandStatus.ACCEPTED.value,
            message="Futures/Perpetual close/reduce submitted to Coinbase by backend Admin API.",
            command=command,
            mutation_family="futures_live_close_reduce",
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=live_admission,
            payload_validation=payload_validation,
            risk_proof_id=risk_proof_id,
            failure_stage=None,
            context=context,
            client_order_id=client_order_id,
            coinbase_order_id=order_id or None,
            live_exchange_submitted=True,
            submitted_notional=notional,
            execution_allowed=True,
            local_state_mutated=True,
            exchange_state_mutated=True,
            runtime_evidence=runtime_evidence,
            cap_guard_decision_id=proof_chain["cap_guard_decision_id"],
            reconciliation_plan_id=proof_chain["reconciliation_plan_id"],
        )
        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.ACCEPTED.value,
            "module_id": FUTURES_MODULE_ID,
            "command": command,
            "mutation_family": "futures_live_close_reduce",
            "action_class": action_class,
            "route": route,
            "method": "POST",
            "required_permission": required_permission,
            "service_method": service_method,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "product_id": product_id,
            "client_order_id": client_order_id,
            "coinbase_order_id": order_id or None,
            "exchange_order_id": order_id or None,
            "exchange_order_id_evidence_only": True,
            "message": "Futures/Perpetual close/reduce submitted to Coinbase by backend Admin API.",
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "operator_intent": context.operator_intent,
            "actor_id": context.actor_id,
            "payload_hash": payload_hash,
            "payload_validation": dict(payload_validation),
            "readiness_decision": dict(readiness_decision),
            "admission_decision": live_admission,
            "failure_stage": None,
            "coinbase_close_position_submission_allowed": True,
            "coinbase_close_position_result": result_data,
            "submission_event_recorded": True,
            "submission_event_id": command_record["decision_id"],
            "command_route_registered": True,
            "command_draft_allowed": True,
            "execution_allowed": True,
            "local_state_mutated": True,
            "exchange_state_mutated": True,
            "live_exchange_submitted": True,
            "submitted_notional_usdc": _decimal_text(notional),
            "executed_notional_usdc": "0",
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            **proof_chain,
            **runtime_evidence,
            **self._live_outputs(True, notional),
        }
        return self._result(200, response, context, live_execution_enabled=True)

    def _execute_futures_cancel_order(
        self,
        *,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        payload_validation: Mapping[str, Any],
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        risk_proof_id: Any,
    ) -> AdminMvpApiResult:
        """Cancel one US CFM Futures order through backend live execution gates."""

        client_order_id = identity_value
        live_admission = self._futures_live_admission_decision(
            admission_decision,
            client_order_id=client_order_id,
            notional=Decimal("0"),
            action_label="cancel",
        )
        pre_coinbase_failure = self._futures_cancel_pre_coinbase_failure(
            command=command,
        )
        if pre_coinbase_failure is not None:
            return self._futures_place_blocked_response(
                status_code=400,
                message=pre_coinbase_failure["message"],
                failure_stage=pre_coinbase_failure["failure_stage"],
                command=command,
                action_class=action_class,
                route=route,
                service_method=service_method,
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=required_permission,
                payload_hash=payload_hash,
                payload_validation=payload_validation,
                readiness_decision=readiness_decision,
                admission_decision=live_admission,
                risk_proof_id=risk_proof_id,
                client_order_id=client_order_id,
                notional=Decimal("0"),
                context=context,
            )

        proof_chain = self._record_futures_live_proof_chain(
            command=command,
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=live_admission,
            risk_proof_id=risk_proof_id,
            context=context,
        )
        live_admission = {
            **live_admission,
            "cap_guard_present": proof_chain["cap_guard_present"],
            "cap_guard_decision_id": proof_chain["cap_guard_decision_id"],
            "reconciliation_plan_present": proof_chain["reconciliation_plan_present"],
            "reconciliation_plan_id": proof_chain["reconciliation_plan_id"],
        }
        try:
            controller = self.dependencies.runtime_controller_factory()
            _check_runtime_cancel_admission(controller)
            with _track_runtime_cancel(controller):
                cancel_attempt = _cancel_futures_order_by_client_order_id(
                    self.dependencies.rest_client,
                    client_order_id=client_order_id,
                )
        except Exception as exc:
            return self._futures_place_blocked_response(
                status_code=400,
                message=f"Coinbase Futures order cancel failed: {exc}",
                failure_stage="coinbase_rest",
                command=command,
                action_class=action_class,
                route=route,
                service_method=service_method,
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=required_permission,
                payload_hash=payload_hash,
                payload_validation=payload_validation,
                readiness_decision=readiness_decision,
                admission_decision=live_admission,
                risk_proof_id=risk_proof_id,
                client_order_id=client_order_id,
                notional=Decimal("0"),
                context=context,
                proof_chain=proof_chain,
            )

        cancel_result = _mapping(cancel_attempt.get("cancel_result"))
        if not _coinbase_cancel_order_succeeded(cancel_result):
            return self._futures_place_blocked_response(
                status_code=400,
                message=(
                    "Coinbase Futures order cancel was not accepted: "
                    f"{_coinbase_cancel_order_error_message(cancel_result)}"
                ),
                failure_stage="coinbase_rest",
                command=command,
                action_class=action_class,
                route=route,
                service_method=service_method,
                identity_key=identity_key,
                identity_value=identity_value,
                required_permission=required_permission,
                payload_hash=payload_hash,
                payload_validation=payload_validation,
                readiness_decision=readiness_decision,
                admission_decision=live_admission,
                risk_proof_id=risk_proof_id,
                client_order_id=client_order_id,
                notional=Decimal("0"),
                context=context,
                proof_chain=proof_chain,
            )

        self.store.live_coinbase_orders_ran = True
        runtime_evidence = self._runtime_evidence()
        command_record = self._record_futures_command_decision(
            status=AdminMvpCommandStatus.ACCEPTED.value,
            message="Futures/Perpetual order cancel submitted to Coinbase by backend Admin API.",
            command=command,
            mutation_family="futures_live_cancel",
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=live_admission,
            payload_validation=payload_validation,
            risk_proof_id=risk_proof_id,
            failure_stage=None,
            context=context,
            client_order_id=client_order_id,
            coinbase_order_id=_optional_text(cancel_attempt.get("exchange_order_id")),
            live_exchange_submitted=True,
            submitted_notional=Decimal("0"),
            execution_allowed=True,
            local_state_mutated=True,
            exchange_state_mutated=True,
            runtime_evidence=runtime_evidence,
            coinbase_order_cancel_submitted=True,
            cap_guard_decision_id=proof_chain["cap_guard_decision_id"],
            reconciliation_plan_id=proof_chain["reconciliation_plan_id"],
        )
        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.ACCEPTED.value,
            "module_id": FUTURES_MODULE_ID,
            "command": command,
            "mutation_family": "futures_live_cancel",
            "action_class": action_class,
            "route": route,
            "method": "POST",
            "required_permission": required_permission,
            "service_method": service_method,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "client_order_id": client_order_id,
            "operator_identity_key": cancel_attempt.get(
                "operator_identity_key", "client_order_id"
            ),
            "exchange_order_id_evidence_only": True,
            "message": "Futures/Perpetual order cancel submitted to Coinbase by backend Admin API.",
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "operator_intent": context.operator_intent,
            "actor_id": context.actor_id,
            "payload_hash": payload_hash,
            "payload_validation": dict(payload_validation),
            "readiness_decision": dict(readiness_decision),
            "admission_decision": live_admission,
            "failure_stage": None,
            "coinbase_cancel_submission_allowed": True,
            "coinbase_cancel_result": cancel_result,
            "coinbase_cancel_identity_used": cancel_attempt.get("identity_used"),
            "coinbase_cancel_initial_identity_used": cancel_attempt.get(
                "initial_identity_used"
            ),
            "coinbase_cancel_initial_result": _mapping(
                cancel_attempt.get("initial_cancel_result")
            ),
            "coinbase_cancel_initial_result_success": bool(
                cancel_attempt.get("initial_cancel_succeeded")
            ),
            "coinbase_cancel_fallback_attempted": bool(
                cancel_attempt.get("fallback_attempted")
            ),
            "coinbase_cancel_fallback_reason": cancel_attempt.get("fallback_reason"),
            "coinbase_cancel_fallback_identity_used": cancel_attempt.get(
                "fallback_identity_used"
            ),
            "coinbase_cancel_order_read_attempted": bool(
                cancel_attempt.get("order_read_attempted")
            ),
            "coinbase_cancel_order_read_succeeded": bool(
                cancel_attempt.get("order_read_succeeded")
            ),
            "exchange_order_id_present": bool(cancel_attempt.get("exchange_order_id")),
            "submission_event_recorded": True,
            "submission_event_id": command_record["decision_id"],
            "command_route_registered": True,
            "command_draft_allowed": True,
            "execution_allowed": True,
            "local_state_mutated": True,
            "exchange_state_mutated": True,
            "live_exchange_submitted": True,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            **proof_chain,
            **runtime_evidence,
            **self._live_outputs(True, Decimal("0")),
        }
        return self._result(200, response, context, live_execution_enabled=True)

    def _futures_place_blocked_response(
        self,
        *,
        status_code: int,
        message: str,
        failure_stage: str,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        payload_validation: Mapping[str, Any],
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        risk_proof_id: Any,
        client_order_id: str,
        notional: Decimal,
        context: AdminMvpRequestContext,
        proof_chain: Mapping[str, Any] | None = None,
    ) -> AdminMvpApiResult:
        mutation_family = (
            "futures_live_cancel"
            if command == "futures_cancel"
            else "futures_live_close_reduce"
            if command == "futures_close_reduce"
            else "futures_live_place"
        )
        runtime_evidence = self._runtime_evidence()
        proof_chain_fields = dict(proof_chain or {})
        command_record = self._record_futures_command_decision(
            status=AdminMvpCommandStatus.REJECTED.value,
            message=message,
            command=command,
            mutation_family=mutation_family,
            action_class=action_class,
            route=route,
            service_method=service_method,
            identity_key=identity_key,
            identity_value=identity_value,
            required_permission=required_permission,
            payload_hash=payload_hash,
            readiness_decision=readiness_decision,
            admission_decision=admission_decision,
            payload_validation=payload_validation,
            risk_proof_id=risk_proof_id,
            failure_stage=failure_stage,
            context=context,
            client_order_id=client_order_id,
            submitted_notional=Decimal("0"),
            runtime_evidence=runtime_evidence,
            cap_guard_decision_id=proof_chain_fields.get("cap_guard_decision_id"),
            reconciliation_plan_id=proof_chain_fields.get("reconciliation_plan_id"),
        )
        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.REJECTED.value,
            "module_id": FUTURES_MODULE_ID,
            "command": command,
            "mutation_family": mutation_family,
            "action_class": action_class,
            "route": route,
            "method": "POST",
            "required_permission": required_permission,
            "service_method": service_method,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "client_order_id": client_order_id,
            "message": message,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "operator_intent": context.operator_intent,
            "actor_id": context.actor_id,
            "payload_hash": payload_hash,
            "payload_validation": dict(payload_validation),
            "readiness_decision": dict(readiness_decision),
            "admission_decision": dict(admission_decision),
            "failure_stage": failure_stage,
            "submission_event_recorded": True,
            "submission_event_id": command_record["decision_id"],
            "command_route_registered": True,
            "command_draft_allowed": True,
            "execution_allowed": False,
            "local_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            **proof_chain_fields,
            **runtime_evidence,
            **self._live_outputs(False, notional),
        }
        return self._result(status_code, response, context)

    def _futures_pre_coinbase_failure(
        self,
        *,
        command: str,
        body: Mapping[str, Any],
        notional: Decimal,
        readiness_decision: Mapping[str, Any],
    ) -> dict[str, str] | None:
        if command != "futures_place":
            return {
                "failure_stage": "futures_executor_not_implemented",
                "message": "Only Futures/Perpetual place has a live executor adapter.",
            }
        if str(body.get("order_type") or "").upper() != "LIMIT":
            return {
                "failure_stage": "futures_limit_order_required",
                "message": "Futures/Perpetual live place currently requires a limit order.",
            }
        if not self.dependencies.live_coinbase_execution_enabled:
            return {
                "failure_stage": "futures_live_runtime_disabled",
                "message": "Live Futures/Perpetual execution is not enabled for this backend process.",
            }
        if not self.dependencies.rest_client_available or self.dependencies.rest_client is None:
            return {
                "failure_stage": "futures_rest_client_unavailable",
                "message": "Coinbase REST client is not available to the backend.",
            }
        cap = self._futures_live_max_submitted_notional(readiness_decision)
        if notional > cap:
            return {
                "failure_stage": "futures_cap_required",
                "message": "Futures/Perpetual order notional exceeds backend cap evidence.",
            }
        return None

    def _futures_cancel_pre_coinbase_failure(
        self,
        *,
        command: str,
    ) -> dict[str, str] | None:
        if command != "futures_cancel":
            return {
                "failure_stage": "futures_executor_not_implemented",
                "message": "Only Futures/Perpetual cancel has a live cancel adapter.",
            }
        if not self.dependencies.live_coinbase_execution_enabled:
            return {
                "failure_stage": "futures_live_runtime_disabled",
                "message": "Live Futures/Perpetual execution is not enabled for this backend process.",
            }
        if not self.dependencies.rest_client_available or self.dependencies.rest_client is None:
            return {
                "failure_stage": "futures_rest_client_unavailable",
                "message": "Coinbase REST client is not available to the backend.",
            }
        return None

    def _futures_close_reduce_pre_coinbase_failure(
        self,
        *,
        command: str,
        product_id: str,
        notional: Decimal,
        readiness_decision: Mapping[str, Any],
    ) -> dict[str, str] | None:
        if command != "futures_close_reduce":
            return {
                "failure_stage": "futures_executor_not_implemented",
                "message": "Only Futures/Perpetual close/reduce has this live adapter.",
            }
        if product_id not in FUTURES_CONFIGURED_PRODUCT_SCOPE:
            return {
                "failure_stage": "unsupported_product_scope",
                "message": "Futures/Perpetual close/reduce product is outside backend scope.",
            }
        if not self.dependencies.live_coinbase_execution_enabled:
            return {
                "failure_stage": "futures_live_runtime_disabled",
                "message": "Live Futures/Perpetual execution is not enabled for this backend process.",
            }
        if not self.dependencies.rest_client_available or self.dependencies.rest_client is None:
            return {
                "failure_stage": "futures_rest_client_unavailable",
                "message": "Coinbase REST client is not available to the backend.",
            }
        cap = self._futures_live_max_submitted_notional(readiness_decision)
        if notional > cap:
            return {
                "failure_stage": "futures_cap_required",
                "message": "Futures/Perpetual close/reduce notional exceeds backend cap evidence.",
            }
        return None

    def _futures_live_max_submitted_notional(
        self,
        readiness_decision: Mapping[str, Any],
    ) -> Decimal:
        live_decision = dict(readiness_decision.get("live_decision_evidence") or {})
        caps = [DEFAULT_FUTURES_MAX_SUBMITTED_NOTIONAL_USDC]
        service_decision_id = str(live_decision.get("matching_service_decision_id") or "")
        if service_decision_id in self.store.service_decisions:
            caps.append(
                _decimal_value(
                    self.store.service_decisions[service_decision_id].get(
                        "max_submitted_notional_usdc"
                    ),
                    DEFAULT_FUTURES_MAX_SUBMITTED_NOTIONAL_USDC,
                )
            )
        adapter_decision_id = str(live_decision.get("matching_adapter_decision_id") or "")
        if adapter_decision_id in self.store.live_adapter_decisions:
            caps.append(
                _decimal_value(
                    self.store.live_adapter_decisions[adapter_decision_id].get(
                        "max_submitted_notional_usdc"
                    ),
                    DEFAULT_FUTURES_MAX_SUBMITTED_NOTIONAL_USDC,
                )
            )
        return min(caps)

    def _futures_product_exposure_evidence(
        self,
        live_decision_summary: Mapping[str, Any],
        latest_live_submit_failure: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return configured Futures product exposure versus backend cap evidence."""

        cap = self._futures_live_max_submitted_notional(
            {"live_decision_evidence": live_decision_summary}
        )
        items = [
            self._futures_product_exposure_item(
                product_id,
                cap,
                latest_live_submit_failure,
            )
            for product_id in FUTURES_CONFIGURED_PRODUCT_SCOPE
        ]
        any_within_cap = any(bool(item["within_backend_cap"]) for item in items)
        return {
            "status": "ready" if any_within_cap else AdminMvpGateStatus.BLOCKED.value,
            "account_family": FUTURES_ACCOUNT_FAMILY_US_CFM,
            "intx_applicability": FUTURES_INTX_APPLICABILITY_US_ACCOUNT,
            "product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
            "max_submitted_notional_usdc": _decimal_text(cap),
            "product_count": len(items),
            "product_within_backend_cap_count": sum(
                1 for item in items if bool(item["within_backend_cap"])
            ),
            "any_product_within_backend_cap": any_within_cap,
            "items": items,
            "next_required_operator_decision": (
                "select_configured_us_cfm_product_within_cap"
                if any_within_cap
                else "configure_lower_exposure_us_cfm_product_or_raise_futures_cap"
            ),
            "execution_allowed": False,
            "live_coinbase_orders_ran": False,
            "backend_owned": True,
            "read_only": True,
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": (
                "Backend-owned Futures/Perpetual product exposure evidence compares "
                "one configured US CFM contract against the active backend cap."
            ),
        }

    def _futures_product_exposure_item(
        self,
        product_id: str,
        cap: Decimal,
        latest_live_submit_failure: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Return one configured Futures product exposure row."""

        metadata, read_error = self._futures_product_metadata(product_id)
        limit_price = _futures_default_limit_price(metadata, side="BUY")
        price_increment = _first_positive_decimal(
            metadata,
            ("price_increment", "quote_increment"),
        )
        contract_size = futures_contract_size_for_product(product_id, metadata)
        metadata_notional = (
            futures_place_notional_usdc(
                {
                    "product_id": product_id,
                    "limit_price": limit_price,
                    "size": "1",
                },
                metadata,
            )
            if limit_price is not None and contract_size > 0
            else Decimal("0")
        )
        failure_notional = _futures_latest_submit_failure_notional_for_product(
            latest_live_submit_failure,
            product_id,
        )
        if metadata_notional > 0:
            minimum_notional = metadata_notional
            minimum_notional_source = "backend_product_metadata"
        elif failure_notional > 0:
            minimum_notional = failure_notional
            minimum_notional_source = "latest_live_submit_failure"
        else:
            minimum_notional = Decimal("0")
            minimum_notional_source = "unavailable"
        metadata_ready = read_error is None and limit_price is not None and contract_size > 0
        within_cap = minimum_notional > 0 and minimum_notional <= cap
        return {
            "product_id": product_id,
            "status": "ready" if within_cap else AdminMvpGateStatus.BLOCKED.value,
            "metadata_read_status": "ready" if read_error is None else "blocked",
            "metadata_read_error": read_error,
            "source": BACKEND_REST_CLIENT_SOURCE,
            "reference_side": "BUY",
            "reference_limit_price": _decimal_text(limit_price or Decimal("0")),
            "price_increment": (
                _decimal_text(price_increment) if price_increment is not None else None
            ),
            "contract_size": _decimal_text(contract_size),
            "minimum_contracts": "1",
            "minimum_contract_notional_usdc": _decimal_text(minimum_notional),
            "minimum_contract_notional_source": minimum_notional_source,
            "max_submitted_notional_usdc": _decimal_text(cap),
            "within_backend_cap": within_cap,
            "execution_allowed": False,
            "live_coinbase_orders_ran": False,
            "backend_owned": True,
            "read_only": True,
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }

    def _futures_product_metadata(
        self,
        product_id: str,
    ) -> tuple[dict[str, Any], str | None]:
        """Read backend product metadata for one configured Futures product."""

        if product_id in self._futures_product_metadata_cache:
            metadata, read_error = self._futures_product_metadata_cache[product_id]
            return dict(metadata), read_error
        if not self.dependencies.rest_client_available or self.dependencies.rest_client is None:
            result = ({}, "rest_client_unavailable")
            self._futures_product_metadata_cache[product_id] = result
            return result
        method = getattr(self.dependencies.rest_client, "get_product_dict", None)
        if not callable(method):
            result = ({}, "get_product_dict_unavailable")
            self._futures_product_metadata_cache[product_id] = result
            return result
        try:
            value = method(product_id)
        except Exception as exc:  # pragma: no cover - defensive around live SDK failures
            result = ({}, f"get_product_dict_failed:{type(exc).__name__}")
            self._futures_product_metadata_cache[product_id] = result
            return result
        if not isinstance(value, Mapping):
            result = ({}, "product_metadata_missing")
            self._futures_product_metadata_cache[product_id] = result
            return result
        result = (dict(value), None)
        self._futures_product_metadata_cache[product_id] = result
        return result

    def _record_futures_live_proof_chain(
        self,
        *,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        risk_proof_id: Any,
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        """Record backend-local proof-chain evidence for a Futures live submit."""

        cap_guard_decision_id = f"futures-cap-guard-{context.idempotency_key}"
        reconciliation_plan_id = f"futures-reconciliation-{context.idempotency_key}"
        status = AdminMvpGateStatus.PASSED.value
        cap = self._futures_live_max_submitted_notional(readiness_decision)
        command_evidence = {
            "route": route,
            "method": "POST",
            "module_id": FUTURES_MODULE_ID,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "action_class": action_class,
            "required_permission": required_permission,
            "service_method": service_method,
            "operator_intent": context.operator_intent,
            "command_idempotency_key": context.idempotency_key,
            "payload_hash": payload_hash,
        }
        cap_result = self.record_cap_guard_decision(
            {
                **command_evidence,
                "decision_id": cap_guard_decision_id,
                "allowed": True,
                "status": status,
                "admission_audit_id": admission_decision.get("audit_id"),
                "max_submitted_notional_usdc": _decimal_text(cap),
                "max_executed_notional_usdc": _decimal_text(cap),
                "wallet_check_required": False,
                "wallet_check_status": status,
                "wallet_available_notional_usdc": _decimal_text(cap),
                "wallet_check_source": FUTURES_MARGIN_COLLATERAL_SOURCE,
            },
            context,
        )
        reconciliation_result = self.record_reconciliation_plan(
            {
                **command_evidence,
                "plan_id": reconciliation_plan_id,
                "allowed": True,
                "status": status,
                "admission_audit_id": admission_decision.get("audit_id"),
                "cap_guard_decision_id": cap_guard_decision_id,
                "position_key": (
                    identity_value if identity_key == "position_key" else None
                ),
                "futures_risk_proof_id": risk_proof_id,
                "reconciliation_reason": f"{command}_post_submit_reconciliation",
                "exchange_submission_required": True,
                "max_submitted_notional_usdc": _decimal_text(cap),
                "max_executed_notional_usdc": _decimal_text(cap),
            },
            context,
        )
        cap_guard = dict(_mapping(cap_result.body.get("decision")))
        reconciliation = dict(_mapping(reconciliation_result.body.get("plan")))
        return {
            "cap_guard_present": True,
            "cap_guard_decision_id": cap_guard_decision_id,
            "cap_guard_decision": cap_guard,
            "reconciliation_plan_present": True,
            "reconciliation_plan_id": reconciliation_plan_id,
            "reconciliation_plan": reconciliation,
        }

    def _futures_live_admission_decision(
        self,
        admission_decision: Mapping[str, Any],
        *,
        client_order_id: str,
        notional: Decimal,
        action_label: str,
    ) -> dict[str, Any]:
        return {
            **dict(admission_decision),
            "status": AdminMvpGateStatus.PASSED.value,
            "allowed": True,
            "failure_stage": None,
            "client_order_id": client_order_id,
            "submitted_notional_usdc": _decimal_text(notional),
            "live_execution_acknowledged": True,
            "detail": (
                "Backend Futures/Perpetual admission passed for an explicitly "
                f"confirmed, capped live {action_label} request."
            ),
        }

    def _futures_admission_decision(
        self,
        *,
        command: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        payload_hash: str,
        readiness_decision: Mapping[str, Any],
        payload_validation: Mapping[str, Any],
        risk_proof_id: Any,
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        live_decision = dict(readiness_decision.get("live_decision_evidence") or {})
        payload_validation_blocked = (
            str(payload_validation.get("status") or "") == AdminMvpGateStatus.BLOCKED.value
        )
        failure_stage = (
            "futures_payload_validation_failed"
            if payload_validation_blocked
            else str(readiness_decision.get("first_blocker") or "execution_disabled")
        )
        return {
            "decision_id": f"futures-admission-{context.idempotency_key}",
            "recorded_at": self._now_iso(),
            "status": AdminMvpGateStatus.BLOCKED.value,
            "allowed": False,
            "failure_stage": failure_stage,
            "payload_validation_status": payload_validation.get("status"),
            "payload_validation_id": payload_validation.get("validation_id"),
            "payload_validation_blocking_request_field_count": payload_validation.get(
                "blocking_request_field_count",
                0,
            ),
            "module_id": FUTURES_MODULE_ID,
            "command": command,
            "route": route,
            "method": "POST",
            "service_method": service_method,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "payload_hash": payload_hash,
            "account_family": FUTURES_ACCOUNT_FAMILY_US_CFM,
            "intx_applicability": FUTURES_INTX_APPLICABILITY_US_ACCOUNT,
            "product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
            "risk_proof_id": risk_proof_id,
            "service_decision_id": live_decision.get("matching_service_decision_id"),
            "adapter_decision_id": live_decision.get("matching_adapter_decision_id"),
            "executor_boundary_status": live_decision.get("executor_boundary_status"),
            "executor_boundary_ready": bool(live_decision.get("executor_boundary_ready")),
            "readiness_decision": str(readiness_decision.get("decision") or ""),
            "command_route_registered": bool(
                readiness_decision.get("command_route_registered", True)
            ),
            "command_draft_allowed": bool(
                readiness_decision.get("command_draft_allowed", True)
            ),
            "execution_allowed": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "correlation_id": context.correlation_id,
            "audit_id": f"audit-{context.idempotency_key}",
            "detail": (
                "US CFM Futures admission is backend-owned and blocked at the "
                "disabled executor boundary before any Coinbase call."
            ),
        }

    def _record_futures_executor_decision(
        self,
        *,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        risk_proof_id: Any,
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        live_decision = dict(readiness_decision.get("live_decision_evidence") or {})
        decision_id = f"futures-executor-{context.idempotency_key}"
        record = {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "source": FUTURES_EXECUTOR_BOUNDARY_SOURCE,
            "executor_status": AdminMvpFuturesExecutorStatus.OBSERVED_LIVE_DISABLED.value,
            "executor_boundary_ready": True,
            "module_id": FUTURES_MODULE_ID,
            "command": command,
            "mutation_family": "futures_executor_live_disabled",
            "action_class": action_class,
            "route": route,
            "method": "POST",
            "required_permission": required_permission,
            "service_method": service_method,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "payload_hash": payload_hash,
            "account_family": FUTURES_ACCOUNT_FAMILY_US_CFM,
            "intx_applicability": FUTURES_INTX_APPLICABILITY_US_ACCOUNT,
            "product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
            "admission_decision_id": admission_decision.get("decision_id"),
            "admission_allowed": False,
            "risk_proof_id": risk_proof_id,
            "service_decision_id": live_decision.get("matching_service_decision_id"),
            "adapter_decision_id": live_decision.get("matching_adapter_decision_id"),
            "failure_stage": "futures_executor_live_disabled",
            "execution_allowed": False,
            "local_state_mutated": False,
            "exchange_state_mutated": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "correlation_id": context.correlation_id,
            "audit_id": f"audit-{context.idempotency_key}",
            "detail": (
                "Backend Futures executor boundary exists for US CFM but is "
                "live-disabled for the local runtime; no Coinbase order or cancel "
                "request was submitted."
            ),
        }
        self.store.futures_executor_decisions[decision_id] = record
        self._persist_record("futures_executor_decisions", decision_id, record)
        return record

    def _record_futures_command_decision(
        self,
        *,
        status: str,
        message: str,
        command: str,
        mutation_family: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        identity_value: str,
        required_permission: str,
        payload_hash: str,
        readiness_decision: Mapping[str, Any],
        admission_decision: Mapping[str, Any],
        payload_validation: Mapping[str, Any] | None = None,
        risk_proof_id: Any,
        failure_stage: str | None,
        context: AdminMvpRequestContext,
        client_order_id: str | None = None,
        coinbase_order_id: str | None = None,
        live_exchange_submitted: bool = False,
        submitted_notional: Decimal = Decimal("0"),
        executed_notional: Decimal = Decimal("0"),
        execution_allowed: bool = False,
        local_state_mutated: bool = False,
        exchange_state_mutated: bool = False,
        runtime_evidence: Mapping[str, Any] | None = None,
        coinbase_order_cancel_submitted: bool = False,
        cap_guard_decision_id: str | None = None,
        reconciliation_plan_id: str | None = None,
    ) -> dict[str, Any]:
        decision_id = f"futures-command-{self.dependencies.uuid_factory()}"
        runtime = dict(runtime_evidence or {})
        record = {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "source": "admin_api_futures_command_log",
            "status": status,
            "module_id": FUTURES_MODULE_ID,
            "command": command,
            "mutation_family": mutation_family,
            "action_class": action_class,
            "route": route,
            "method": "POST",
            "required_permission": required_permission,
            "service_method": service_method,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "payload_hash": payload_hash,
            "account_family": FUTURES_ACCOUNT_FAMILY_US_CFM,
            "intx_applicability": FUTURES_INTX_APPLICABILITY_US_ACCOUNT,
            "product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
            "client_order_id": client_order_id,
            "admission_decision": dict(admission_decision),
            "readiness_decision": dict(readiness_decision),
            "payload_validation": dict(payload_validation or {}),
            "risk_proof_id": risk_proof_id,
            "cap_guard_present": cap_guard_decision_id is not None,
            "cap_guard_decision_id": cap_guard_decision_id,
            "reconciliation_plan_present": reconciliation_plan_id is not None,
            "reconciliation_plan_id": reconciliation_plan_id,
            "failure_stage": failure_stage,
            "execution_allowed": execution_allowed,
            "local_state_mutated": local_state_mutated,
            "exchange_state_mutated": exchange_state_mutated,
            "coinbase_order_submitted": (
                live_exchange_submitted and not coinbase_order_cancel_submitted
            ),
            "coinbase_order_cancel_submitted": coinbase_order_cancel_submitted,
            "coinbase_order_id": coinbase_order_id,
            "exchange_order_id": coinbase_order_id,
            "exchange_order_id_evidence_only": True,
            "live_exchange_submitted": live_exchange_submitted,
            "live_coinbase_orders_ran": live_exchange_submitted,
            "submitted_notional_usdc": _decimal_text(submitted_notional),
            "executed_notional_usdc": _decimal_text(executed_notional),
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "command_idempotency_key": context.idempotency_key,
            "correlation_id": context.correlation_id,
            "audit_id": f"audit-{context.idempotency_key}",
            "message": message,
            "detail": (
                "Backend Futures command submission was recorded after a live "
                "Coinbase request."
                if live_exchange_submitted
                else (
                    "Backend Futures command submission was recorded as local "
                    "Admin evidence; no Coinbase request was submitted."
                )
                if local_state_mutated
                else (
                    "Backend Futures command submission was recorded as an "
                    "auditable draft-only event; execution remains disabled and "
                    "no Coinbase request was submitted."
                )
            ),
            **runtime,
        }
        self.store.futures_command_decisions[decision_id] = record
        self._persist_record("futures_command_decisions", decision_id, record)
        return record

    def preview_admission(
        self,
        query: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Preview admission state from persisted backend proof evidence."""

        identity_value = _query_text(query, "identity_value")
        payload_hash = _query_text(query, "payload_hash")
        command_idempotency_key = _query_text(query, "command_idempotency_key")
        preview_context = AdminMvpRequestContext(
            idempotency_key=command_idempotency_key,
            correlation_id=context.correlation_id,
            operator_intent=_query_text(query, "operator_intent"),
            actor_id=_query_text(query, "actor_id"),
            roles=context.roles,
        )
        admission = self._admission_decision(
            context=preview_context,
            identity_value=identity_value,
            payload_hash=payload_hash,
        )
        return self._ok(
            {
                "type": "admin_live_admission_preview",
                "admission_decision": admission,
                "live_exchange_submitted": False,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _execute_manual_order(
        self,
        *,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
        client_order_id: str,
        notional: Decimal,
        admission: dict[str, Any],
    ) -> AdminMvpApiResult:
        if not self.dependencies.live_coinbase_execution_enabled:
            return self._manual_order_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message="Live Coinbase execution is not enabled for this local backend process.",
                failure_stage="action_condition_guard",
                client_order_id=client_order_id,
                notional=notional,
                admission=admission,
                context=context,
            )
        order_configuration = _manual_order_configuration(body)
        try:
            controller = self.dependencies.runtime_controller_factory()
            _check_runtime_admission(controller)
            with _track_runtime_place(controller):
                result = self.dependencies.rest_client.create_order(
                    client_order_id=client_order_id,
                    product_id=str(body.get("product_id") or ""),
                    side=str(body.get("side") or ""),
                    order_configuration=order_configuration,
                )
        except Exception as exc:
            return self._manual_order_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message=f"Coinbase order submission failed: {exc}",
                failure_stage="coinbase_rest",
                client_order_id=client_order_id,
                notional=notional,
                admission=admission,
                context=context,
            )

        result_data = _object_to_dict(result)
        if not _coinbase_create_order_succeeded(result_data):
            return self._manual_order_blocked_response(
                status_code=400,
                command_status=AdminMvpCommandStatus.REJECTED,
                message=(
                    "Coinbase order submission was not accepted: "
                    f"{_coinbase_create_order_error_message(result_data)}"
                ),
                failure_stage="coinbase_rest",
                client_order_id=client_order_id,
                notional=notional,
                admission=admission,
                context=context,
            )

        order_id = _coinbase_order_id_from_create_order_result(result_data)
        self.store.submitted_notional_usdc += notional
        self.store.live_coinbase_orders_ran = True
        runtime_evidence = self._runtime_evidence()
        command_record = self._record_spot_command_decision(
            status=AdminMvpCommandStatus.ACCEPTED.value,
            message="Manual order submitted to Coinbase by backend Admin API.",
            client_order_id=client_order_id,
            product_id=str(body.get("product_id") or ""),
            notional=notional,
            admission=admission,
            context=context,
            live_exchange_submitted=True,
            coinbase_order_id=order_id or None,
            failure_stage=None,
            runtime_evidence=runtime_evidence,
        )
        response = {
            "type": "admin_api_command_result",
            "status": AdminMvpCommandStatus.ACCEPTED.value,
            "action_class": MANUAL_ORDER_ACTION_CLASS,
            "required_permission": MANUAL_ORDER_PERMISSION,
            "service_method": MANUAL_ORDER_SERVICE_METHOD,
            "message": "Manual order submitted to Coinbase by backend Admin API.",
            "client_order_id": client_order_id,
            "coinbase_order_id": order_id or None,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "admission_decision": admission,
            "live_exchange_submitted": True,
            "paired_sell_required": False,
            "submission_event_recorded": True,
            "submission_event_id": command_record["decision_id"],
            **runtime_evidence,
            **self._live_outputs(True, notional),
        }
        return self._result(200, response, context, live_execution_enabled=True)

    def _manual_order_blocked_response(
        self,
        *,
        status_code: int,
        command_status: AdminMvpCommandStatus,
        message: str,
        failure_stage: str,
        client_order_id: str,
        notional: Decimal,
        admission: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        runtime_evidence = self._runtime_evidence()
        self._record_spot_command_decision(
            status=command_status.value,
            message=message,
            client_order_id=client_order_id,
            product_id=str(admission.get("product_id") or ""),
            notional=notional,
            admission=admission,
            context=context,
            live_exchange_submitted=False,
            coinbase_order_id=None,
            failure_stage=failure_stage,
            runtime_evidence=runtime_evidence,
        )
        body = {
            "type": "admin_api_command_result",
            "status": command_status.value,
            "action_class": MANUAL_ORDER_ACTION_CLASS,
            "required_permission": MANUAL_ORDER_PERMISSION,
            "service_method": MANUAL_ORDER_SERVICE_METHOD,
            "message": message,
            "client_order_id": client_order_id,
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "admission_decision": dict(admission),
            "live_exchange_submitted": False,
            "failure_stage": failure_stage,
            **runtime_evidence,
            **self._live_outputs(False, notional),
        }
        return self._result(status_code, body, context)

    def _record_spot_command_decision(
        self,
        *,
        status: str,
        message: str,
        client_order_id: str,
        product_id: str,
        notional: Decimal,
        admission: Mapping[str, Any],
        context: AdminMvpRequestContext,
        live_exchange_submitted: bool,
        coinbase_order_id: str | None,
        failure_stage: str | None,
        runtime_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        decision_id = f"spot-command-{self.dependencies.uuid_factory()}"
        record = {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "route": MANUAL_ORDER_ROUTE,
            "method": "POST",
            "module_id": MANUAL_ORDER_MODULE_ID,
            "identity_key": "client_order_id",
            "identity_value": client_order_id,
            "action_class": MANUAL_ORDER_ACTION_CLASS,
            "required_permission": MANUAL_ORDER_PERMISSION,
            "service_method": MANUAL_ORDER_SERVICE_METHOD,
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "command_idempotency_key": context.idempotency_key,
            "correlation_id": context.correlation_id,
            "audit_id": f"audit-{context.idempotency_key}",
            "payload_hash": admission.get("payload_hash"),
            "client_order_id": client_order_id,
            "product_id": product_id,
            "notional_usdc": _decimal_text(notional),
            "status": status,
            "message": message,
            "failure_stage": failure_stage,
            "coinbase_order_id": coinbase_order_id,
            "exchange_order_id": coinbase_order_id,
            "exchange_order_id_evidence_only": True,
            "live_exchange_submitted": live_exchange_submitted,
            "admission_decision": dict(admission),
            "live_coinbase_orders_ran": live_exchange_submitted,
            **dict(runtime_evidence),
        }
        self.store.spot_command_decisions[decision_id] = record
        self._persist_record("spot_command_decisions", decision_id, record)
        return record

    def _record_spot_cancel_command_decision(
        self,
        *,
        status: str,
        message: str,
        client_order_id: str,
        proof_context: Mapping[str, Any],
        cancel_proof: Mapping[str, Any] | None,
        context: AdminMvpRequestContext,
        live_exchange_submitted: bool,
        coinbase_cancel_result: Mapping[str, Any],
        failure_stage: str | None,
        runtime_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        decision_id = f"spot-cancel-command-{self.dependencies.uuid_factory()}"
        record = {
            "decision_id": decision_id,
            "recorded_at": self._now_iso(),
            "route": CANCEL_ORDER_ROUTE,
            "method": "POST",
            "module_id": MANUAL_ORDER_MODULE_ID,
            "identity_key": "client_order_id",
            "identity_value": client_order_id,
            "action_class": CANCEL_ORDER_ACTION_CLASS,
            "required_permission": CANCEL_ORDER_PERMISSION,
            "service_method": CANCEL_ORDER_SERVICE_METHOD,
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "idempotency_key": context.idempotency_key,
            "command_idempotency_key": context.idempotency_key,
            "correlation_id": context.correlation_id,
            "audit_id": f"audit-{context.idempotency_key}",
            "payload_hash": proof_context.get("payload_hash"),
            "client_order_id": client_order_id,
            "product_id": "",
            "notional_usdc": "0",
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "status": status,
            "message": message,
            "failure_stage": failure_stage,
            "coinbase_order_id": None,
            "exchange_order_id": None,
            "exchange_order_id_evidence_only": True,
            "coinbase_cancel_result": dict(coinbase_cancel_result),
            "coinbase_order_cancel_submitted": live_exchange_submitted,
            "live_exchange_submitted": live_exchange_submitted,
            "admission_decision": _spot_cancel_admission_summary(
                cancel_proof,
                proof_context,
            ),
            "cancel_proof": _spot_cancel_proof_summary(cancel_proof),
            "live_coinbase_orders_ran": live_exchange_submitted,
            **dict(runtime_evidence),
        }
        self.store.spot_command_decisions[decision_id] = record
        self._persist_record("spot_command_decisions", decision_id, record)
        return record

    def _pre_coinbase_failure(
        self,
        body: Mapping[str, Any],
        notional: Decimal,
        admission: Mapping[str, Any],
    ) -> dict[str, str] | None:
        if not _manual_live_acknowledged(body):
            return {
                "failure_stage": "manual_live_acknowledgement",
                "message": "Manual live acknowledgement is required.",
            }
        if not self.dependencies.rest_client_available or self.dependencies.rest_client is None:
            return {
                "failure_stage": "product_capability",
                "message": "Coinbase REST client is not available to the backend.",
            }
        admitted_cap = self._admitted_cap_guard(admission)
        max_submitted = _decimal_value(
            admitted_cap.get("max_submitted_notional_usdc") if admitted_cap else None,
            DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC,
        )
        if notional > max_submitted:
            return {
                "failure_stage": "direct_spot_cap_required",
                "message": "Manual order notional exceeds backend cap evidence.",
            }
        wallet_failure = _wallet_inventory_failure(admitted_cap, notional)
        if wallet_failure is not None:
            return wallet_failure
        if not self._latest_service_decision_allows_live():
            return {
                "failure_stage": "durable_audit_required",
                "message": "Backend live-service decision has not approved live execution.",
            }
        return None

    def _admitted_cap_guard(self, admission: Mapping[str, Any]) -> dict[str, Any] | None:
        decision_id = str(admission.get("cap_guard_decision_id") or "")
        if not decision_id:
            return None
        return self.store.cap_guard_decisions.get(decision_id)

    def _admission_decision(
        self,
        *,
        context: AdminMvpRequestContext,
        identity_value: str,
        payload_hash: str,
    ) -> dict[str, Any]:
        approval = self._matching_approval(identity_value, context.idempotency_key, payload_hash)
        admission_audit = self._matching_admission_audit(
            identity_value,
            context.idempotency_key,
            payload_hash,
        )
        cap_guard = self._matching_cap_guard(identity_value, context.idempotency_key, payload_hash)
        reconciliation = self._matching_reconciliation(
            identity_value,
            context.idempotency_key,
            payload_hash,
        )
        service_status = self._live_service_status()
        service_present = bool(self.store.service_decisions)
        blockers = []
        if approval is None:
            blockers.append("approval_snapshot_missing")
        if admission_audit is None:
            blockers.append("admission_audit_missing")
        if cap_guard is None:
            blockers.append("cap_guard_missing")
        if reconciliation is None:
            blockers.append("reconciliation_plan_missing")
        if service_status != AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value:
            blockers.append("live_execution_service_missing")
        allowed = not blockers
        return {
            "status": (
                AdminMvpGateStatus.PASSED.value
                if allowed
                else AdminMvpGateStatus.BLOCKED.value
            ),
            "allowed": allowed,
            "route": MANUAL_ORDER_ROUTE,
            "method": "POST",
            "module_id": MANUAL_ORDER_MODULE_ID,
            "identity_key": "client_order_id",
            "identity_value": identity_value,
            "action_class": MANUAL_ORDER_ACTION_CLASS,
            "required_permission": MANUAL_ORDER_PERMISSION,
            "service_method": MANUAL_ORDER_SERVICE_METHOD,
            "actor_id": context.actor_id,
            "idempotency_key": context.idempotency_key,
            "operator_intent": context.operator_intent,
            "payload_hash": payload_hash,
            "approval_snapshot_required": True,
            "approval_snapshot_present": approval is not None,
            "approval_snapshot_id": approval.get("approval_id") if approval else None,
            "admission_audit_required": True,
            "admission_audit_present": admission_audit is not None,
            "admission_audit_id": (
                admission_audit.get("admission_audit_id") if admission_audit else None
            ),
            "cap_guard_required": True,
            "cap_guard_present": cap_guard is not None,
            "cap_guard_decision_id": cap_guard.get("decision_id") if cap_guard else None,
            "reconciliation_required": True,
            "reconciliation_plan_present": reconciliation is not None,
            "reconciliation_plan_id": reconciliation.get("plan_id") if reconciliation else None,
            "live_execution_service_required": True,
            "live_execution_service_present": service_present,
            "live_execution_service_status": service_status,
            "live_execution_service_source": "application/admin_api/mvp_service.py",
            "browser_authority": "backend_admin_api" if allowed else "rejected",
            "live_exchange_submitted": False,
            "blockers": blockers,
            "evidence": _evidence_refs(approval, admission_audit, cap_guard, reconciliation),
            "detail": (
                "Backend proof chain admits the manual order."
                if allowed
                else "Backend proof chain is incomplete for manual order admission."
            ),
        }

    def _matching_approval(
        self,
        identity_value: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        return _find_matching_record(
            self.store.approval_snapshots.values(),
            identity_value,
            idempotency_key,
            payload_hash,
            status_field="decision",
            required_status="approved",
        )

    def _matching_admission_audit(
        self,
        identity_value: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        return _find_matching_record(
            self.store.admission_audits.values(),
            identity_value,
            idempotency_key,
            payload_hash,
        )

    def _matching_cap_guard(
        self,
        identity_value: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        return _find_matching_record(
            self.store.cap_guard_decisions.values(),
            identity_value,
            idempotency_key,
            payload_hash,
            required_allowed=True,
        )

    def _matching_reconciliation(
        self,
        identity_value: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        return _find_matching_record(
            self.store.reconciliation_plans.values(),
            identity_value,
            idempotency_key,
            payload_hash,
            required_allowed=True,
        )

    def _matching_cancel_proof(
        self,
        identity_value: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        return _find_matching_record(
            self.store.reconciliation_plans.values(),
            identity_value,
            idempotency_key,
            payload_hash,
            required_allowed=True,
            service_method=CANCEL_ORDER_SERVICE_METHOD,
        )

    def _client_order_id(self, idempotency_key: str) -> str:
        existing = self.store.command_identity_by_idempotency_key.get(idempotency_key)
        if existing:
            return existing
        client_order_id = self.dependencies.uuid_factory()
        self.store.command_identity_by_idempotency_key[idempotency_key] = client_order_id
        self._persist_record(
            "command_identity_by_idempotency_key",
            idempotency_key,
            {
                "idempotency_key": idempotency_key,
                "client_order_id": client_order_id,
            },
        )
        return client_order_id

    def _runtime_evidence(self) -> dict[str, Any]:
        rest_ready = self.dependencies.rest_client_available and self.dependencies.rest_client is not None
        return {
            "live_command_runtime_enabled": True,
            "live_command_rest_client_available": rest_ready,
            "live_command_runtime_ready": rest_ready,
            "live_command_runtime_missing_reason": None if rest_ready else "rest_client_unavailable",
            "live_command_runtime_source": "application/admin_api/mvp_service.py",
        }

    def _live_service_status(self) -> str:
        latest = _latest_record(self.store.service_decisions)
        if latest and latest.get("service_enabled"):
            return str(
                latest.get("requested_service_status")
                or AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value
            )
        return AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value

    def _account_snapshot(self) -> dict[str, Any]:
        generated_at = self._now_iso()
        unavailable = _unavailable_account_snapshot(generated_at)
        if not self.dependencies.rest_client_available or self.dependencies.rest_client is None:
            return unavailable

        rest_client = self.dependencies.rest_client
        wallets, wallets_read, wallet_error = _read_rest_object(
            rest_client,
            "get_account_wallets",
        )
        portfolios, portfolios_read, portfolio_error = _read_rest_object(
            rest_client,
            "list_portfolios",
        )
        positions, positions_read, positions_error = _read_rest_object(
            rest_client,
            "get_futures_positions",
        )
        futures_margin_collateral, futures_margin_collateral_read, futures_margin_collateral_error = (
            _read_rest_object(
                rest_client,
                "get_futures_margin_collateral_snapshot",
            )
        )
        if not any((wallets_read, portfolios_read, positions_read, futures_margin_collateral_read)):
            return unavailable

        wallet_items = _normalize_wallets(wallets)
        portfolio_items = _normalize_portfolios(portfolios)
        position_items = _normalize_futures_positions(positions)
        wallet_inventory = _wallet_inventory_from_wallets(wallet_items)
        futures_margin_inventory = _futures_margin_collateral_from_cfm_snapshot(
            futures_margin_collateral,
            futures_margin_collateral_error,
        )
        portfolio_scope = _portfolio_scope_from_portfolios(portfolio_items)
        futures_position_scope = [
            item["product_id"] for item in position_items if item.get("product_id")
        ]
        read_errors = [
            error
            for error in (
                wallet_error,
                portfolio_error,
                positions_error,
                futures_margin_collateral_error,
            )
            if error is not None
        ]
        spot_wallet_ready = _spot_admission_quote_ready(wallet_inventory)
        futures_scope_ready = positions_read and positions_error is None
        futures_margin_collateral_ready = futures_margin_inventory["status"] == "ready"
        readiness = {
            "spot_account_ready": portfolios_read and portfolio_error is None and spot_wallet_ready,
            "spot_wallet_inventory_ready": spot_wallet_ready,
            "futures_account_scope_ready": futures_scope_ready,
            "futures_observed_position_scope_ready": bool(position_items),
            "futures_margin_collateral_ready": futures_margin_collateral_ready,
            "usable_for_spot_admission": spot_wallet_ready,
            "usable_for_futures_risk": futures_scope_ready and futures_margin_collateral_ready,
        }
        account_status = "ready" if any(readiness.values()) else "unavailable"
        source = (
            BACKEND_REST_CLIENT_SOURCE
            if account_status == "ready"
            else "backend_rest_unavailable"
        )
        freshness = BACKEND_REST_FRESHNESS if account_status == "ready" else LOCAL_DEFAULT_FRESHNESS
        return {
            "account_reality": {
                "status": account_status,
                "source": source,
                "proof_id": f"account-reality-{generated_at}",
                "generated_at": generated_at,
                "coinbase_read_ran": True,
                "read_error": "none" if not read_errors else ";".join(read_errors),
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
            },
            "account_scope": {
                "scope_type": "backend_account_snapshot",
                "scope_id": portfolio_scope["portfolio_id"],
                "source": source,
                "freshness_status": freshness,
                "account_count": len(wallet_items),
                "configured_product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
                "observed_position_scope": futures_position_scope,
            },
            "portfolio_scope": portfolio_scope,
            "wallet_inventory": wallet_inventory,
            "wallets": wallet_items,
            "readiness": readiness,
            "futures_positions": position_items,
            "futures_margin_collateral": futures_margin_inventory,
            "coinbase_read_enabled": True,
            "coinbase_read_ran": True,
        }

    def _latest_service_decision_allows_live(self) -> bool:
        latest = _latest_record(self.store.service_decisions)
        return bool(latest and latest.get("live_coinbase_execution_approved"))

    def _futures_live_service_decision(self) -> dict[str, Any] | None:
        return _latest_matching_record(
            self.store.service_decisions,
            _is_us_cfm_futures_service_decision,
        )

    def _futures_live_adapter_decision_for_spec(
        self,
        spec: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        return _latest_matching_record(
            self.store.live_adapter_decisions,
            lambda record: _is_us_cfm_futures_adapter_decision(
                record,
                target_route=str(spec["route"]),
                target_service_method=str(spec["service_method"]),
            ),
        )

    def _futures_live_runtime_ready(self) -> bool:
        """Return whether this process can submit confirmed Futures live commands."""

        return bool(
            self.dependencies.live_coinbase_execution_enabled
            and self.dependencies.rest_client_available
            and self.dependencies.rest_client is not None
        )

    def _futures_live_decision_evidence(
        self,
        *,
        command: str,
        route: str,
        service_method: str,
        live_service_decision: Mapping[str, Any] | None,
        live_adapter_decision: Mapping[str, Any] | None,
        live_runtime_ready: bool,
    ) -> dict[str, Any]:
        service_ready = live_service_decision is not None
        adapter_ready = live_adapter_decision is not None
        executor_boundary_ready = service_ready and adapter_ready
        live_exchange_command = _futures_live_exchange_command(command)
        local_reconciliation_command = command == "futures_reconcile"
        execution_allowed = bool(
            executor_boundary_ready
            and (
                (live_runtime_ready and live_exchange_command)
                or local_reconciliation_command
            )
        )
        executor_boundary_status = (
            AdminMvpFuturesExecutorStatus.LIVE_ENABLED.value
            if executor_boundary_ready and live_runtime_ready and live_exchange_command
            else AdminMvpFuturesExecutorStatus.OBSERVED_LIVE_DISABLED.value
            if executor_boundary_ready
            else AdminMvpFuturesExecutorStatus.PENDING_LIVE_DECISION.value
        )
        first_blocker = (
            "none"
            if execution_allowed
            else "futures_reconciliation_execution_disabled"
            if executor_boundary_ready and not live_exchange_command
            else "futures_executor_live_disabled"
            if executor_boundary_ready
            else "execution_disabled"
        )
        return {
            "command": command,
            "target_route": route,
            "target_service_method": service_method,
            "account_family": FUTURES_ACCOUNT_FAMILY_US_CFM,
            "intx_applicability": FUTURES_INTX_APPLICABILITY_US_ACCOUNT,
            "product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
            "service_decision_status": (
                "ready" if service_ready else "missing_matching_us_cfm_service_decision"
            ),
            "adapter_decision_status": (
                "ready" if adapter_ready else "missing_matching_us_cfm_adapter_decision"
            ),
            "matching_service_decision_id": (
                str(live_service_decision["decision_id"]) if service_ready else None
            ),
            "matching_adapter_decision_id": (
                str(live_adapter_decision["decision_id"]) if adapter_ready else None
            ),
            "service_decision_source": (
                str(live_service_decision["source"]) if service_ready else None
            ),
            "adapter_decision_source": (
                str(live_adapter_decision["source"]) if adapter_ready else None
            ),
            "live_decision_scope_ready": service_ready and adapter_ready,
            "live_runtime_ready": live_runtime_ready,
            "live_exchange_command": live_exchange_command,
            "local_reconciliation_command": local_reconciliation_command,
            "executor_boundary_status": executor_boundary_status,
            "executor_boundary_ready": executor_boundary_ready,
            "executor_boundary_source": (
                FUTURES_EXECUTOR_BOUNDARY_SOURCE if executor_boundary_ready else None
            ),
            "execution_allowed": execution_allowed,
            "manual_live_acknowledgement_required": live_exchange_command,
            "first_blocker": first_blocker,
            "required_evidence_refs": [
                LIVE_SERVICE_DECISION_ROUTE,
                LIVE_ADAPTER_DECISION_ROUTE,
            ],
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_coinbase_orders_ran": False,
        }

    def _latest_futures_live_submit_failure(self) -> dict[str, Any] | None:
        """Return the latest rejected Futures live-submit attempt evidence."""

        for record in reversed(list(self.store.futures_command_decisions.values())):
            if str(record.get("command") or "") != "futures_place":
                continue
            if str(record.get("mutation_family") or "") != "futures_live_place":
                continue
            failure_stage = str(record.get("failure_stage") or "")
            if not failure_stage:
                continue
            admission_decision = _mapping(record.get("admission_decision"))
            readiness_decision = _mapping(record.get("readiness_decision"))
            attempted_notional = _decimal_value(
                admission_decision.get("submitted_notional_usdc"),
                Decimal("0"),
            )
            cap = self._futures_live_max_submitted_notional(readiness_decision)
            return {
                "status": AdminMvpGateStatus.BLOCKED.value,
                "command": "futures_place",
                "failure_stage": failure_stage,
                "message": str(record.get("message") or ""),
                "detail": (
                    "Latest Futures/Perpetual live submit was rejected before "
                    "Coinbase order mutation by backend Admin cap evidence."
                ),
                "product_id": str(record.get("identity_value") or ""),
                "client_order_id": str(record.get("client_order_id") or ""),
                "attempted_notional_usdc": _decimal_text(attempted_notional),
                "submitted_notional_usdc": _decimal_text(
                    _decimal_value(record.get("submitted_notional_usdc"), Decimal("0"))
                ),
                "max_submitted_notional_usdc": _decimal_text(cap),
                "live_exchange_submitted": False,
                "live_coinbase_orders_ran": False,
                "execution_allowed": False,
                "backend_owned": True,
                "read_only": True,
                "spot_rule_authority": False,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "next_required_operator_decision": (
                    "choose_lower_notional_us_cfm_product_or_raise_futures_cap"
                    if failure_stage == "futures_cap_required"
                    else "review_backend_futures_live_submit_failure"
                ),
            }
        return None

    def _now_iso(self) -> str:
        return self.dependencies.now_factory().astimezone(timezone.utc).isoformat()

    def _ok(
        self,
        body: dict[str, Any],
        context: AdminMvpRequestContext,
        *,
        live_execution_enabled: bool = False,
    ) -> AdminMvpApiResult:
        return self._result(200, body, context, live_execution_enabled=live_execution_enabled)

    def _error(
        self,
        status_code: int,
        message: str,
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        return self._result(
            status_code,
            {
                "type": "admin_mvp_error",
                "code": "request_error",
                "message": message,
                **self._live_outputs(False, Decimal("0")),
            },
            context,
        )

    def _result(
        self,
        status_code: int,
        body: dict[str, Any],
        context: AdminMvpRequestContext,
        *,
        live_execution_enabled: bool = False,
    ) -> AdminMvpApiResult:
        headers = {
            "Content-Type": "application/json",
            "X-Correlation-Id": context.correlation_id,
            "X-Request-Id": context.correlation_id,
            "X-Admin-Api-Version": ADMIN_API_VERSION,
            "X-Live-Execution-Enabled": "true" if live_execution_enabled else "false",
        }
        return AdminMvpApiResult(status_code=status_code, body=body, headers=headers)

    def _live_outputs(self, live_ran: bool, notional: Decimal) -> dict[str, Any]:
        return {
            "live_coinbase_execution": "submitted" if live_ran else "not_run",
            "notional_usdc": _decimal_text(notional),
            "live_coinbase_orders_ran": live_ran,
        }

    def _admin_bootstrap(self, context: AdminMvpRequestContext) -> dict[str, Any]:
        return {
            "type": "admin_bootstrap",
            "status": "ready",
            "actor": {"actor_id": context.actor_id, "roles": list(context.roles)},
            "capabilities_route": "/api/v1/admin/capabilities",
            "session_route": "/api/v1/admin/session",
            "live_coinbase_orders_ran": False,
        }

    def _admin_runtime_status(self, context: AdminMvpRequestContext) -> dict[str, Any]:
        controller = self.dependencies.runtime_controller_factory()
        snapshot = self._runtime_controller_snapshot(controller)
        return {
            "type": "admin_runtime_status",
            "status": str(snapshot["runtime_state"]).lower(),
            "route": ADMIN_RUNTIME_ROUTE,
            "method": "GET",
            "module_id": "admin_system_health",
            "read_only": True,
            "operator": {
                "actor_id": context.actor_id,
                "roles": list(context.roles),
            },
            "audit": {
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "audit_surface": ADMIN_RUNTIME_ROUTE,
            },
            "frontend_safe": True,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "order_state_mutated": False,
            "exchange_state_mutated": False,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "live_exchange_submitted": False,
            **snapshot,
            **self._live_outputs(False, Decimal("0")),
        }

    def _runtime_controller_snapshot(self, controller: Any) -> dict[str, Any]:
        state = self._runtime_state_value(getattr(controller, "state", "UNKNOWN"))
        inflight_snapshot = getattr(controller, "inflight_snapshot", None)
        total_inflight = getattr(controller, "total_inflight", None)
        is_admitting = getattr(controller, "is_admitting", None)
        is_stopping = getattr(controller, "is_stopping", None)
        inflight = inflight_snapshot() if callable(inflight_snapshot) else {}
        return {
            "runtime_state": state,
            "admitting": (
                bool(is_admitting()) if callable(is_admitting) else state == "RUNNING"
            ),
            "stopping": (
                bool(is_stopping())
                if callable(is_stopping)
                else state in {"DRAINING", "STOPPED"}
            ),
            "inflight": dict(inflight),
            "total_inflight": (
                int(total_inflight())
                if callable(total_inflight)
                else sum(int(value) for value in dict(inflight).values())
            ),
            "runtime_source": "core.runtime_controller.RuntimeController",
        }

    def _runtime_transition(self, controller: Any, action: str) -> Callable[[], bool]:
        method_name_by_action = {
            "pause": "request_pause",
            "resume": "resume",
            "shutdown": "request_shutdown",
        }
        transition = getattr(controller, method_name_by_action[action], None)
        if callable(transition):
            return transition
        return lambda: False

    def _runtime_state_value(self, state: Any) -> str:
        return str(getattr(state, "value", state))

    def _admin_health(self) -> dict[str, Any]:
        return {
            "type": "admin_health",
            "status": "ok",
            "service": "coinbase-admin-prod-mvp",
            "version": ADMIN_API_VERSION,
            "deployment_target": "coinbase-local",
            "read_only": True,
            "submitted_notional_usdc": _decimal_text(self.store.submitted_notional_usdc),
            "executed_notional_usdc": _decimal_text(self.store.executed_notional_usdc),
            **self._live_outputs(
                self.store.live_coinbase_orders_ran,
                self.store.submitted_notional_usdc,
            ),
        }

    def _admin_session(self, context: AdminMvpRequestContext) -> dict[str, Any]:
        return {
            "type": "admin_session",
            "status": "authenticated",
            "session_status": "authenticated",
            "actor": {"actor_id": context.actor_id, "roles": list(context.roles)},
            "actor_id": context.actor_id,
            "roles": list(context.roles),
            "auth_mode": "bootstrap_bearer",
            "bearer_token_visible_to_browser": False,
            "live_coinbase_orders_ran": False,
        }

    def _oidc_readiness(self) -> dict[str, Any]:
        return {
            "type": "admin_oidc_jwt_readiness",
            "active_auth_mode": "bootstrap_bearer",
            "mode": "oidc_jwt",
            "status": "blocked",
            "verifier_implemented": False,
            "missing_env_vars": [],
            "live_coinbase_orders_ran": False,
        }

    def _capability_registry(self) -> dict[str, Any]:
        return {
            "type": "admin_capabilities",
            "capabilities": self._capability_items(),
            "live_coinbase_orders_ran": False,
        }

    def _csrf_contract(self) -> dict[str, Any]:
        return {
            "type": "admin_csrf_contract",
            "csrf_required": False,
            "csrf_header_name": "X-CSRF-Token",
            "token_issued_by_backend": False,
            "token_visible_to_browser": False,
            "live_coinbase_orders_ran": False,
        }

    def _account_management(self, context: AdminMvpRequestContext) -> dict[str, Any]:
        snapshot = self._account_snapshot()
        return {
            "type": "admin_account_management",
            "status": "warning",
            "module_id": ACCOUNT_MANAGEMENT_MODULE_ID,
            "environment": self._account_management_environment(),
            "operator": {
                "actor_id": context.actor_id,
                "roles": list(context.roles),
                "required_permission": "analytics:read",
                "auth_mode": "bootstrap_bearer",
            },
            "account_reality": snapshot["account_reality"],
            "account_scope": snapshot["account_scope"],
            "portfolio_scope": snapshot["portfolio_scope"],
            "wallet_inventory": snapshot["wallet_inventory"],
            "readiness": snapshot["readiness"],
            "permissions": self._account_management_permissions(context),
            "command_readiness_prerequisites": self._account_management_prerequisites(snapshot),
            "audit": {
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "operator_intent": context.operator_intent,
                "audit_surface": ACCOUNT_MANAGEMENT_ROUTE,
            },
            "read_only": True,
            "command_routes_mode": "backend_admin_api",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "coinbase_read_enabled": snapshot["coinbase_read_enabled"],
            "live_coinbase_read_ran": snapshot["coinbase_read_ran"],
            **self._live_outputs(False, Decimal("0")),
            "notional_usdc": "0",
        }

    def _admin_wallet(self, context: AdminMvpRequestContext) -> dict[str, Any]:
        snapshot = self._account_snapshot()
        readiness = snapshot["readiness"]
        wallet_inventory = snapshot["wallet_inventory"]
        spot_wallet_ready = bool(readiness["spot_wallet_inventory_ready"])
        futures_risk_ready = bool(readiness["usable_for_futures_risk"])
        futures_risk_input = snapshot["futures_margin_collateral"]["risk_input"]
        spot_admission_input = _spot_admission_input_from_snapshot(snapshot)
        return {
            "type": "admin_wallet",
            "status": "ready" if spot_wallet_ready else "warning",
            "module_id": ACCOUNT_MANAGEMENT_MODULE_ID,
            "account_reality": snapshot["account_reality"],
            "account_scope": snapshot["account_scope"],
            "portfolio_scope": snapshot["portfolio_scope"],
            "wallet_inventory": wallet_inventory,
            "wallets": _wallet_rows_for_admin(snapshot["wallets"]),
            "wallet_count": len(snapshot["wallets"]),
            "readiness": readiness,
            "spot_admission_input": spot_admission_input,
            "futures_risk_input": {
                "status": "ready" if futures_risk_ready else "blocked",
                "wallet_check_source": ACCOUNT_SNAPSHOT_WALLET_SOURCE,
                "currency": futures_risk_input["currency"],
                "available_notional_usdc": futures_risk_input["available_notional_usdc"],
                "proof_id": snapshot["account_reality"]["proof_id"],
                "first_blocker": "none" if futures_risk_ready else futures_risk_input["first_blocker"],
            },
            "audit": {
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "operator_intent": context.operator_intent,
                "audit_surface": ACCOUNT_WALLET_ROUTE,
            },
            "read_only": True,
            "command_routes_mode": "backend_admin_api",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "coinbase_read_enabled": snapshot["coinbase_read_enabled"],
            "live_coinbase_read_ran": snapshot["coinbase_read_ran"],
            **self._live_outputs(False, Decimal("0")),
            "notional_usdc": "0",
        }

    def _admin_products(
        self,
        query: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        product_ids = _admin_product_scope(query)
        rows = [self._admin_product_row(product_id) for product_id in product_ids]
        ready_rows = [row for row in rows if row["read_status"] == "ready"]
        missing_count = len(rows) - len(ready_rows)
        spot_ids = [
            row["product_id"]
            for row in ready_rows
            if row["product_family"] == "spot"
        ]
        derivative_ids = [
            row["product_id"]
            for row in ready_rows
            if row["product_family"] == "futures_perpetuals"
        ]
        rest_client_ready = (
            self.dependencies.rest_client_available
            and self.dependencies.rest_client is not None
        )
        return {
            "type": "admin_products",
            "status": _admin_products_status(len(ready_rows), missing_count),
            "module_id": ACCOUNT_MANAGEMENT_MODULE_ID,
            "route": ACCOUNT_PRODUCTS_ROUTE,
            "source": BACKEND_REST_CLIENT_SOURCE if rest_client_ready else "backend_rest_unavailable",
            "configured_product_scope": product_ids,
            "spot": spot_ids,
            "derivatives": derivative_ids,
            "products": rows,
            "metadata_count": len(ready_rows),
            "missing_metadata_count": missing_count,
            "spot_count": len(spot_ids),
            "derivatives_count": len(derivative_ids),
            "audit": {
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "operator_intent": context.operator_intent,
                "audit_surface": ACCOUNT_PRODUCTS_ROUTE,
            },
            "read_only": True,
            "command_routes_mode": "backend_admin_api",
            "browser_authority": "display_only",
            "bff_authority": "read_only_forward",
            "coinbase_read_enabled": rest_client_ready,
            "live_coinbase_read_ran": rest_client_ready and bool(product_ids),
            **self._live_outputs(False, Decimal("0")),
            "notional_usdc": "0",
        }

    def _admin_product_row(self, product_id: str) -> dict[str, Any]:
        metadata, read_error = self._read_admin_product_metadata(product_id)
        if read_error is not None:
            return _blocked_admin_product_row(product_id, read_error)
        return _admin_product_metadata_row(product_id, metadata)

    def _read_admin_product_metadata(
        self,
        product_id: str,
    ) -> tuple[dict[str, Any], str | None]:
        if not self.dependencies.rest_client_available or self.dependencies.rest_client is None:
            return {}, "rest_client_unavailable"
        method = getattr(self.dependencies.rest_client, "get_product_dict", None)
        if not callable(method):
            return {}, "get_product_dict_unavailable"
        try:
            product = method(product_id)
        except Exception as exc:
            return {}, f"get_product_dict_failed:{type(exc).__name__}"
        metadata = _object_to_dict(product)
        if not metadata:
            return {}, "product_metadata_missing"
        return metadata, None

    def _admin_fees(self, context: AdminMvpRequestContext) -> dict[str, Any]:
        fee_read = self._read_admin_fee_snapshot()
        snapshot = fee_read["snapshot"]
        return {
            "type": "admin_fee_evidence",
            "status": snapshot["status"],
            "module_id": ACCOUNT_MANAGEMENT_MODULE_ID,
            "route": ACCOUNT_FEES_ROUTE,
            "account_family": FUTURES_ACCOUNT_FAMILY_US_CFM,
            "source": snapshot["source"],
            "fee_tier": snapshot["fee_tier"],
            "spot_fee_input": snapshot["spot_fee_input"],
            "futures_fee_input": snapshot["futures_fee_input"],
            "volume_30day": snapshot["volume_30day"],
            "perpetuals_volume_30day": snapshot["perpetuals_volume_30day"],
            "stablecoin_conversions_enabled": snapshot["stablecoin_conversions_enabled"],
            "audit": {
                "correlation_id": context.correlation_id,
                "idempotency_key": context.idempotency_key,
                "operator_intent": context.operator_intent,
                "audit_surface": ACCOUNT_FEES_ROUTE,
            },
            "read_only": True,
            "command_routes_mode": "backend_admin_api_read_only",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "coinbase_read_enabled": fee_read["rest_client_ready"],
            "live_coinbase_read_ran": (
                fee_read["rest_client_ready"]
                and fee_read["summary_read"]
                and fee_read["summary_error"] is None
            ),
            **self._live_outputs(False, Decimal("0")),
            "notional_usdc": "0",
        }

    def _read_admin_fee_snapshot(self) -> dict[str, Any]:
        rest_client_ready = (
            self.dependencies.rest_client_available
            and self.dependencies.rest_client is not None
        )
        summary: Any = {}
        summary_read = False
        summary_error = "rest_client_unavailable"
        if rest_client_ready:
            summary, summary_read, summary_error = _read_rest_object(
                self.dependencies.rest_client,
                "get_transaction_summary",
            )
        return {
            "snapshot": _admin_fee_evidence_snapshot(
                summary,
                summary_read=summary_read,
                read_error=summary_error,
            ),
            "rest_client_ready": rest_client_ready,
            "summary_read": summary_read,
            "summary_error": summary_error,
        }

    def refresh_admin_products(
        self,
        body: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> AdminMvpApiResult:
        """Refresh backend products.json from Coinbase product reads."""

        product_ids = _admin_product_scope(body)
        rows = [self._admin_product_row(product_id) for product_id in product_ids]
        ready_rows = [row for row in rows if row["read_status"] == "ready"]
        missing_rows = [row for row in rows if row["read_status"] != "ready"]
        spot_ids = [
            str(row["product_id"])
            for row in ready_rows
            if row["product_family"] == "spot"
        ]
        derivative_ids = [
            str(row["product_id"])
            for row in ready_rows
            if row["product_family"] == "futures_perpetuals"
        ]
        rest_client_ready = (
            self.dependencies.rest_client_available
            and self.dependencies.rest_client is not None
        )
        products_json_written = False
        write_error: str | None = None
        preserved_ticker_to_trading = False
        if rest_client_ready and product_ids and not missing_rows:
            try:
                document = _write_admin_products_json(ready_rows)
                products_json_written = True
                preserved_ticker_to_trading = "ticker_to_trading" in document
            except Exception as exc:  # pragma: no cover - defensive filesystem boundary
                write_error = f"products_json_write_failed:{type(exc).__name__}"
        status = (
            AdminMvpCommandStatus.ACCEPTED.value
            if products_json_written
            else AdminMvpCommandStatus.REJECTED.value
        )
        return self._ok(
            {
                "type": "admin_products_refresh",
                "status": status,
                "module_id": ACCOUNT_MANAGEMENT_MODULE_ID,
                "route": ACCOUNT_PRODUCTS_REFRESH_ROUTE,
                "method": "POST",
                "action_class": "local_state_mutation",
                "required_permission": ACCOUNT_PRODUCTS_REFRESH_PERMISSION,
                "service_method": ACCOUNT_PRODUCTS_REFRESH_SERVICE_METHOD,
                "configured_product_scope": product_ids,
                "spot": spot_ids,
                "derivatives": derivative_ids,
                "products": rows,
                "metadata_count": len(ready_rows),
                "missing_metadata_count": len(missing_rows),
                "spot_count": len(spot_ids),
                "derivatives_count": len(derivative_ids),
                "products_json_written": products_json_written,
                "products_json_target": "backend_configured_products_json",
                "preserved_ticker_to_trading": preserved_ticker_to_trading,
                "write_error": write_error,
                "coinbase_read_enabled": rest_client_ready,
                "coinbase_read_attempted": rest_client_ready and bool(product_ids),
                "coinbase_read_succeeded": rest_client_ready and bool(product_ids) and not missing_rows,
                "live_coinbase_read_ran": rest_client_ready and bool(product_ids),
                "local_state_mutated": products_json_written,
                "exchange_state_mutated": False,
                "live_exchange_submitted": False,
                "audit": {
                    "correlation_id": context.correlation_id,
                    "idempotency_key": context.idempotency_key,
                    "operator_intent": context.operator_intent,
                    "audit_surface": ACCOUNT_PRODUCTS_REFRESH_ROUTE,
                },
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "command_routes_mode": "backend_admin_api_local_refresh",
                **self._live_outputs(False, Decimal("0")),
                "notional_usdc": "0",
            },
            context,
        )

    def _account_management_environment(self) -> dict[str, Any]:
        frontend_manifest = _read_json_manifest_from_env(FRONTEND_LOCAL_RELEASE_MANIFEST_ENV)
        backend_manifest = _read_json_manifest_from_env(BACKEND_LOCAL_RELEASE_MANIFEST_ENV)
        frontend_commit = _manifest_text(frontend_manifest, "commit")
        backend_commit = _manifest_text(backend_manifest, "commit")
        account_reality_live_read = _account_reality_live_read_manifest_evidence(
            frontend_manifest
        )
        return {
            "environment": "local",
            "deployment_target": "coinbase-local",
            "backend_repository": "s-aws/coinbase",
            "admin_api_version": ADMIN_API_VERSION,
            "deployment_evidence_status": (
                "visible"
                if frontend_commit != "unknown" and backend_commit != "unknown"
                else "local_default_not_connected"
            ),
            "frontend_release_commit": frontend_commit,
            "frontend_current_path": _manifest_text(frontend_manifest, "currentPath"),
            "frontend_release_path": _manifest_text(frontend_manifest, "releasePath"),
            "backend_release_commit": backend_commit,
            "backend_current_path": _manifest_text(backend_manifest, "current_path"),
            "backend_release_path": _manifest_text(backend_manifest, "release_path"),
            "deployment_smoke_status": _nested_manifest_text(
                frontend_manifest,
                "smokeTiming",
                "status",
            ),
            "backend_smoke_status": _nested_manifest_text(
                frontend_manifest,
                "backendControlledLiveSmokeTiming",
                "status",
            ),
            **account_reality_live_read,
            "deployment_live_coinbase_execution": _manifest_text(
                frontend_manifest,
                "liveCoinbaseExecution",
                _manifest_text(backend_manifest, "live_coinbase_execution", "not_run"),
            ),
            "deployment_notional_usdc": _manifest_text(
                frontend_manifest,
                "notionalUsdc",
                _manifest_text(backend_manifest, "notional_usdc", "0"),
            ),
        }

    def _account_management_wallet_inventory(self) -> dict[str, Any]:
        return {
            "currency": "USDC",
            "available_notional_usdc": "0",
            "hold_notional_usdc": "0",
            "total_notional_usdc": "0",
            "source": "backend_admin_mvp_default",
            "freshness_status": "local_default_not_connected",
            "status": "visible",
            "error": "not_applicable",
        }

    def _account_management_permissions(
        self,
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        return {
            "actor_id": context.actor_id,
            "roles": list(context.roles),
            "required_permission": "analytics:read",
            "permission_status": "visible",
            "mutation_permissions_granted": [],
        }

    def _account_management_prerequisites(
        self,
        snapshot: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        readiness = snapshot["readiness"]
        account_reality = snapshot["account_reality"]
        wallet_ready = bool(readiness["spot_wallet_inventory_ready"])
        return [
            {
                "name": "backend_admin_api_contract",
                "status": "visible",
                "detail": "Account management is exposed only through this backend Admin API read route.",
            },
            {
                "name": "rbac",
                "status": "visible",
                "detail": "Read access uses Admin API session and role evidence.",
            },
            {
                "name": "backend_account_reality",
                "status": account_reality["status"],
                "detail": (
                    "Backend account, portfolio, wallet, and futures position scope read evidence is available."
                    if account_reality["status"] == "ready"
                    else "Backend account reality is unavailable; account-dependent gates remain fail-closed."
                ),
            },
            {
                "name": "wallet_inventory_evidence",
                "status": "ready" if wallet_ready else "visible",
                "detail": (
                    "Backend wallet evidence is available for spot admission inputs."
                    if wallet_ready
                    else "Local default wallet evidence is visible; no live Coinbase account read was attempted."
                ),
            },
            {
                "name": "continuous_deployment_local_release",
                "status": "visible",
                "detail": "Account-management evidence is compatible with the local coinbase-local deployment flow.",
            },
            {
                "name": "approval_admission_cap_reconciliation",
                "status": "not_applicable",
                "detail": "This Account Management MVP read route does not initiate account, transfer, or trading mutations.",
            },
        ]

    def _live_enablement(self) -> dict[str, Any]:
        runtime = self._runtime_evidence()
        service_decision_allows_live = self._latest_service_decision_allows_live()
        backend_live_execution_opt_in = bool(
            self.dependencies.live_coinbase_execution_enabled
        )
        manual_path_live_enabled = (
            service_decision_allows_live and backend_live_execution_opt_in
        )
        manual_path_live_executable = (
            manual_path_live_enabled and bool(runtime["live_command_runtime_ready"])
        )
        cancel_path_live_enabled = (
            service_decision_allows_live and backend_live_execution_opt_in
        )
        cancel_path_live_executable = (
            cancel_path_live_enabled and bool(runtime["live_command_runtime_ready"])
        )
        manual_path = self._live_path(
            route=MANUAL_ORDER_ROUTE,
            method="POST",
            live_enabled=manual_path_live_enabled,
            live_eligible=service_decision_allows_live,
        )
        manual_path.update(
            {
                "live_service_decision_enabled": service_decision_allows_live,
                "backend_live_execution_opt_in": backend_live_execution_opt_in,
                "live_executable": manual_path_live_executable,
                "live_blocker": _live_enablement_blocker(
                    service_decision_allows_live=service_decision_allows_live,
                    backend_live_execution_opt_in=backend_live_execution_opt_in,
                    runtime_ready=bool(runtime["live_command_runtime_ready"]),
                ),
            }
        )
        cancel_path = self._live_path(
            route=CANCEL_ORDER_ROUTE,
            method="POST",
            live_enabled=cancel_path_live_enabled,
            live_eligible=service_decision_allows_live,
        )
        cancel_path.update(
            {
                "live_service_decision_enabled": service_decision_allows_live,
                "backend_live_execution_opt_in": backend_live_execution_opt_in,
                "live_executable": cancel_path_live_executable,
                "live_blocker": _live_enablement_blocker(
                    service_decision_allows_live=service_decision_allows_live,
                    backend_live_execution_opt_in=backend_live_execution_opt_in,
                    runtime_ready=bool(runtime["live_command_runtime_ready"]),
                ),
            }
        )
        live_status = (
            self._live_service_status()
            if backend_live_execution_opt_in
            else AdminMvpLiveServiceStatus.LIVE_DISABLED.value
        )
        return {
            "type": "admin_live_enablement",
            "status": live_status,
            "default_live_coinbase_execution": (
                "submitted" if self.store.live_coinbase_orders_ran else "not_run"
            ),
            "submitted_notional_usdc": _decimal_text(self.store.submitted_notional_usdc),
            "executed_notional_usdc": _decimal_text(self.store.executed_notional_usdc),
            "quote_currency": "USDC",
            "max_submitted_notional_usdc": _decimal_text(self._max_submitted_notional()),
            "max_executed_notional_usdc": _decimal_text(DEFAULT_MAX_EXECUTED_NOTIONAL_USDC),
            "live_enabled_path_count": sum(
                1 for enabled in (manual_path_live_enabled, cancel_path_live_enabled) if enabled
            ),
            "live_eligible_path_count": 2 if service_decision_allows_live else 0,
            "live_executable_path_count": sum(
                1
                for executable in (
                    manual_path_live_executable,
                    cancel_path_live_executable,
                )
                if executable
            ),
            "live_service_decision_enabled": service_decision_allows_live,
            "backend_live_execution_opt_in": backend_live_execution_opt_in,
            **runtime,
            "live_command_runtime_ready_path_count": (
                2 if bool(runtime["live_command_runtime_ready"]) else 0
            ),
            "paths": [manual_path, cancel_path],
            "checks": [
                {
                    "name": "backend_admin_service_gate",
                    "status": self._live_service_status(),
                    "detail": "Spot manual order and cancel require backend proof-chain admission before Coinbase execution.",
                },
                {
                    "name": "backend_live_execution_opt_in",
                    "status": (
                        AdminMvpGateStatus.PASSED.value
                        if backend_live_execution_opt_in
                        else AdminMvpGateStatus.BLOCKED.value
                    ),
                    "detail": (
                        "This backend process is opted in for controlled live execution."
                        if backend_live_execution_opt_in
                        else "This backend process is not opted in for controlled live execution."
                    ),
                }
            ],
            "read_only": True,
            "live_coinbase_orders_ran": self.store.live_coinbase_orders_ran,
        }

    def _enterprise_readiness(self) -> dict[str, Any]:
        modules = [
            _module_registry(
                "admin_system_health",
                "Admin / System Health",
                "platform_ready",
                ["/api/v1/admin/health", "/api/v1/admin/session"],
            ),
            _module_registry(
                ACCOUNT_MANAGEMENT_MODULE_ID,
                "Account Management",
                "mvp_read_ready",
                [ACCOUNT_MANAGEMENT_ROUTE, ACCOUNT_WALLET_ROUTE, ACCOUNT_FEES_ROUTE],
            ),
            _module_registry(
                "spot_operations",
                "Spot Operations",
                "mvp_controlled_live_ready",
                ["/api/v1/orders", "/api/v1/spot/command-suite"],
            ),
            _module_registry(
                FUTURES_MODULE_ID,
                "Futures / Perpetuals",
                "mvp_read_ready",
                list(FUTURES_READ_ROUTES),
            ),
        ]
        return {
            "type": "admin_enterprise_readiness",
            "candidate": "prod_admin_mvp",
            "status": "warning",
            "module_count": len(modules),
            "supported_module_count": len(modules),
            "unsupported_module_count": 0,
            "command_gap_count": 0,
            "functionality_inventory": [],
            "mutation_taxonomy": [],
            "modules": modules,
            "security_checks": [],
            "release_checks": [],
            "live_coinbase_orders_ran": False,
        }

    def _simple_gate(self, gate_type: str) -> dict[str, Any]:
        return {
            "type": gate_type,
            "status": "passed",
            "checks": [],
            "read_only": True,
            "live_coinbase_orders_ran": False,
        }

    def _frontend_fixtures(self) -> dict[str, Any]:
        return {
            "type": "admin_frontend_fixtures",
            "fixtures": {},
            "live_coinbase_orders_ran": False,
        }

    def _approval_list(self) -> dict[str, Any]:
        approvals = list(self.store.approval_requests.values())
        pending_count = sum(1 for approval in approvals if approval.get("status") == "requested")
        approved_count = sum(1 for approval in approvals if approval.get("status") == "approved")
        rejected_count = sum(1 for approval in approvals if approval.get("status") == "rejected")
        revoked_count = sum(1 for approval in approvals if approval.get("status") == "revoked")
        expired_count = sum(1 for approval in approvals if approval.get("expired"))
        return {
            "type": "admin_approval_lifecycle_list",
            "approvals": approvals,
            "returned_count": len(approvals),
            "total_count": len(approvals),
            "pending_count": pending_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "revoked_count": revoked_count,
            "expired_count": expired_count,
            "count": len(approvals),
            "pagination": _pagination(len(approvals), len(approvals), 0),
            "live_coinbase_orders_ran": False,
        }

    def _approval_detail(self, approval_request_id: str) -> dict[str, Any]:
        approval = self.store.approval_requests.get(approval_request_id)
        return {
            "type": "admin_approval_lifecycle",
            "status": (
                AdminMvpCommandStatus.ACCEPTED.value
                if approval is not None
                else AdminMvpCommandStatus.REJECTED.value
            ),
            "action_class": "local_state_mutation",
            "required_permission": "approval:read",
            "service_method": "get_approval_request",
            "message": (
                "Approval detail loaded."
                if approval is not None
                else "Approval request was not found."
            ),
            "approval": approval,
            "found": approval is not None,
            "correlation_id": approval.get("correlation_id") if approval else None,
            "idempotency_key": approval.get("idempotency_key") if approval else None,
            "audit_id": (
                f"audit-{approval.get('idempotency_key')}"
                if approval and approval.get("idempotency_key")
                else None
            ),
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
        }

    def _admission_audit_list(self) -> dict[str, Any]:
        records = list(self.store.admission_audits.values())
        return {
            "type": "admin_admission_audit_list",
            "admission_audits": records,
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _admission_audit_detail(self, audit_id: str) -> dict[str, Any]:
        audit = self.store.admission_audits.get(audit_id)
        return {
            "type": "admin_admission_audit_detail",
            "admission_audit": audit,
            "found": audit is not None,
            "live_coinbase_orders_ran": False,
        }

    def _cap_guard_list(self) -> dict[str, Any]:
        records = list(self.store.cap_guard_decisions.values())
        return {
            "type": "admin_cap_guard_decision_list",
            "decisions": records,
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _cap_guard_detail(self, decision_id: str) -> dict[str, Any]:
        decision = self.store.cap_guard_decisions.get(decision_id)
        return {
            "type": "admin_cap_guard_decision_detail",
            "decision": decision,
            "found": decision is not None,
            "live_coinbase_orders_ran": False,
        }

    def _reconciliation_list(self) -> dict[str, Any]:
        records = list(self.store.reconciliation_plans.values())
        return {
            "type": "admin_reconciliation_plan_list",
            "plans": records,
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _reconciliation_detail(self, plan_id: str) -> dict[str, Any]:
        plan = self.store.reconciliation_plans.get(plan_id)
        return {
            "type": "admin_reconciliation_plan_detail",
            "plan": plan,
            "found": plan is not None,
            "live_coinbase_orders_ran": False,
        }

    def _live_service_decision_list(self) -> dict[str, Any]:
        records = list(self.store.service_decisions.values())
        passed_count = sum(
            1 for record in records if record.get("status") == AdminMvpGateStatus.PASSED.value
        )
        blocked_count = sum(
            1 for record in records if record.get("status") == AdminMvpGateStatus.BLOCKED.value
        )
        return {
            "type": "admin_live_service_decision_list",
            "decisions": records,
            "returned_count": len(records),
            "total_count": len(records),
            "passed_count": passed_count,
            "blocked_count": blocked_count,
            "warning_count": 0,
            "resolver_eligible_count": sum(
                1 for record in records if record.get("resolver_eligible")
            ),
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _live_service_decision_detail(self, decision_id: str) -> dict[str, Any]:
        decision = self.store.service_decisions.get(decision_id)
        return {
            "type": "admin_live_service_decision",
            "status": (
                AdminMvpCommandStatus.ACCEPTED.value
                if decision is not None
                else AdminMvpCommandStatus.REJECTED.value
            ),
            "action_class": "local_state_mutation",
            "required_permission": LIVE_SERVICE_DECISION_PERMISSION,
            "service_method": "get_live_service_decision",
            "message": (
                "Live-service decision detail loaded."
                if decision is not None
                else "Live-service decision was not found."
            ),
            "decision": decision,
            "found": decision is not None,
            "correlation_id": decision.get("correlation_id") if decision else None,
            "idempotency_key": decision.get("idempotency_key") if decision else None,
            "audit_id": (
                f"audit-{decision.get('idempotency_key')}"
                if decision and decision.get("idempotency_key")
                else None
            ),
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
        }

    def _live_adapter_decision_list(self) -> dict[str, Any]:
        records = list(self.store.live_adapter_decisions.values())
        passed_count = sum(
            1 for record in records if record.get("status") == AdminMvpGateStatus.PASSED.value
        )
        blocked_count = sum(
            1 for record in records if record.get("status") == AdminMvpGateStatus.BLOCKED.value
        )
        return {
            "type": "admin_live_adapter_decision_list",
            "decisions": records,
            "returned_count": len(records),
            "total_count": len(records),
            "passed_count": passed_count,
            "blocked_count": blocked_count,
            "warning_count": 0,
            "resolver_eligible_count": sum(
                1 for record in records if record.get("resolver_eligible")
            ),
            "constructed_count": sum(
                1 for record in records if record.get("adapter_constructed")
            ),
            "count": len(records),
            "pagination": _pagination(len(records), len(records), 0),
            "live_coinbase_orders_ran": False,
        }

    def _live_adapter_decision_detail(self, decision_id: str) -> dict[str, Any]:
        decision = self.store.live_adapter_decisions.get(decision_id)
        return {
            "type": "admin_live_adapter_decision",
            "status": (
                AdminMvpCommandStatus.ACCEPTED.value
                if decision is not None
                else AdminMvpCommandStatus.REJECTED.value
            ),
            "action_class": "local_state_mutation",
            "required_permission": LIVE_ADAPTER_DECISION_PERMISSION,
            "service_method": "get_live_adapter_decision",
            "message": (
                "Live-adapter decision detail loaded."
                if decision is not None
                else "Live-adapter decision was not found."
            ),
            "decision": decision,
            "found": decision is not None,
            "correlation_id": decision.get("correlation_id") if decision else None,
            "idempotency_key": decision.get("idempotency_key") if decision else None,
            "audit_id": (
                f"audit-{decision.get('idempotency_key')}"
                if decision and decision.get("idempotency_key")
                else None
            ),
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
        }

    def _order_list(self, query: Mapping[str, Any]) -> dict[str, Any]:
        limit = _query_int(query, "limit", 10)
        offset = _query_int(query, "offset", 0)
        return {
            "type": "admin_order_list",
            "count": 0,
            "items": [],
            "pagination": _pagination(limit, 0, offset),
            "read_only": True,
            "live_coinbase_orders_ran": False,
        }

    def _order_detail(self, client_order_id: str) -> dict[str, Any]:
        return {
            "type": "admin_order_detail",
            "client_order_id": client_order_id,
            "found": False,
            "order": None,
            "read_only": True,
            "live_coinbase_orders_ran": False,
        }

    def _spot_command_suite(
        self,
        query: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        proof_context, admission = self._spot_manual_order_admission(query, context)
        runtime_evidence = self._runtime_evidence()
        cap_guard = self._admitted_cap_guard(admission) if admission is not None else None
        manual_readiness = _manual_order_readiness_preconditions(
            admission=admission,
            cap_guard=cap_guard,
            runtime_evidence=runtime_evidence,
            live_coinbase_execution_enabled=(
                self.dependencies.live_coinbase_execution_enabled
            ),
            live_service_decision_allows_live=self._latest_service_decision_allows_live(),
        )
        manual_command = _manual_order_command(
            admission=admission,
            admission_context=proof_context,
            readiness_preconditions=manual_readiness,
        )
        cancel_context, cancel_proof = self._spot_cancel_order_proof(query)
        cancel_readiness = _cancel_order_readiness_preconditions(
            cancel_proof=cancel_proof,
            runtime_evidence=runtime_evidence,
            live_coinbase_execution_enabled=(
                self.dependencies.live_coinbase_execution_enabled
            ),
            live_service_decision_allows_live=self._latest_service_decision_allows_live(),
        )
        cancel_command = _cancel_order_command(
            cancel_context=cancel_context,
            cancel_proof=cancel_proof,
            readiness_preconditions=cancel_readiness,
        )
        commands = [manual_command, cancel_command]
        blocked_command_count = sum(1 for command in commands if command["status"] != "ready")
        executable_command_count = sum(1 for command in commands if command["executable"])
        live_enabled_command_count = sum(1 for command in commands if command["live_enabled"])
        return {
            "type": "spot_command_suite",
            "status": "approval_required",
            "command_count": len(commands),
            "blocked_command_count": blocked_command_count,
            "live_enabled_command_count": live_enabled_command_count,
            "executable_command_count": executable_command_count,
            "coverage_gap_count": 0,
            "manual_order_proof_chain_status": manual_command["proof_chain_status"],
            "manual_order_missing_gate_count": len(manual_command["missing_gate_chain"]),
            "manual_order_resolved_gate_count": len(manual_command["resolved_gate_chain"]),
            "manual_order_admission_context_present": proof_context is not None,
            "cancel_order_proof_chain_status": cancel_command["proof_chain_status"],
            "cancel_order_missing_gate_count": len(cancel_command["missing_gate_chain"]),
            "cancel_order_resolved_gate_count": len(cancel_command["resolved_gate_chain"]),
            "cancel_order_context_present": cancel_context is not None,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "spot_rules_platform_default": False,
            "submitted_notional_usdc": _decimal_text(self.store.submitted_notional_usdc),
            "executed_notional_usdc": _decimal_text(self.store.executed_notional_usdc),
            "commands": commands,
            "coverage_gaps": [],
            "live_coinbase_orders_ran": self.store.live_coinbase_orders_ran,
        }

    def _spot_manual_order_admission(
        self,
        query: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        proof_context = self._spot_manual_order_context_from_query(query)
        if proof_context is None:
            proof_context = self._latest_spot_manual_order_proof_context()
        if proof_context is None:
            return None, None
        admission_context = AdminMvpRequestContext(
            idempotency_key=proof_context["command_idempotency_key"],
            correlation_id=context.correlation_id,
            operator_intent=proof_context["operator_intent"],
            actor_id=proof_context["actor_id"],
            roles=context.roles,
        )
        admission = self._admission_decision(
            context=admission_context,
            identity_value=proof_context["identity_value"],
            payload_hash=proof_context["payload_hash"],
        )
        return proof_context, admission

    def _spot_cancel_order_proof(
        self,
        query: Mapping[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        proof_context = self._spot_cancel_order_context_from_query(query)
        if proof_context is None:
            proof_context = self._latest_spot_cancel_order_proof_context()
        if proof_context is None:
            return None, None
        cancel_proof = self._matching_cancel_proof(
            proof_context["identity_value"],
            proof_context["command_idempotency_key"],
            proof_context["payload_hash"],
        )
        return proof_context, cancel_proof

    def _spot_manual_order_context_from_query(
        self,
        query: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        route = _query_text(query, "route") or MANUAL_ORDER_ROUTE
        identity_key = _query_text(query, "identity_key") or "client_order_id"
        service_method = _query_text(query, "service_method") or MANUAL_ORDER_SERVICE_METHOD
        if route != MANUAL_ORDER_ROUTE:
            return None
        if identity_key != "client_order_id":
            return None
        if service_method != MANUAL_ORDER_SERVICE_METHOD:
            return None
        identity_value = _query_text(query, "identity_value")
        idempotency_key = _query_text(query, "command_idempotency_key") or _query_text(
            query,
            "idempotency_key",
        )
        payload_hash = _query_text(query, "payload_hash")
        if not (identity_value and idempotency_key and payload_hash):
            return None
        return {
            "route": route,
            "method": _query_text(query, "method") or "POST",
            "module_id": _query_text(query, "module_id") or MANUAL_ORDER_MODULE_ID,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "action_class": _query_text(query, "action_class") or MANUAL_ORDER_ACTION_CLASS,
            "required_permission": _query_text(query, "required_permission")
            or MANUAL_ORDER_PERMISSION,
            "service_method": service_method,
            "actor_id": _query_text(query, "actor_id") or "local-operator",
            "operator_intent": _query_text(query, "operator_intent") or "read_admin_api",
            "command_idempotency_key": idempotency_key,
            "payload_hash": payload_hash,
            "source": "query",
        }

    def _latest_spot_manual_order_proof_context(self) -> dict[str, Any] | None:
        for records in (
            self.store.reconciliation_plans,
            self.store.cap_guard_decisions,
            self.store.admission_audits,
            self.store.approval_snapshots,
            self.store.approval_requests,
        ):
            for record in reversed(list(records.values())):
                proof_context = _spot_manual_order_context_from_record(record)
                if proof_context is not None:
                    return proof_context
        return None

    def _spot_cancel_order_context_from_query(
        self,
        query: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        route = _query_text(query, "route") or CANCEL_ORDER_ROUTE
        identity_key = _query_text(query, "identity_key") or "client_order_id"
        service_method = _query_text(query, "service_method") or CANCEL_ORDER_SERVICE_METHOD
        if route != CANCEL_ORDER_ROUTE:
            return None
        if identity_key != "client_order_id":
            return None
        if service_method != CANCEL_ORDER_SERVICE_METHOD:
            return None
        identity_value = _query_text(query, "identity_value")
        idempotency_key = _query_text(query, "command_idempotency_key") or _query_text(
            query,
            "idempotency_key",
        )
        payload_hash = _query_text(query, "payload_hash")
        if not (identity_value and idempotency_key and payload_hash):
            return None
        return {
            "route": route,
            "method": _query_text(query, "method") or "POST",
            "module_id": _query_text(query, "module_id") or MANUAL_ORDER_MODULE_ID,
            "identity_key": identity_key,
            "identity_value": identity_value,
            "action_class": _query_text(query, "action_class") or CANCEL_ORDER_ACTION_CLASS,
            "required_permission": _query_text(query, "required_permission")
            or CANCEL_ORDER_PERMISSION,
            "service_method": service_method,
            "actor_id": _query_text(query, "actor_id") or "local-operator",
            "operator_intent": _query_text(query, "operator_intent") or "read_admin_api",
            "command_idempotency_key": idempotency_key,
            "payload_hash": payload_hash,
            "source": "query",
        }

    def _latest_spot_cancel_order_proof_context(self) -> dict[str, Any] | None:
        for records in (
            self.store.reconciliation_plans,
            self.store.admission_audits,
        ):
            for record in reversed(list(records.values())):
                proof_context = _spot_cancel_order_context_from_record(record)
                if proof_context is not None:
                    return proof_context
        return None

    def _spot_placeholder(
        self,
        path: str,
        query: Mapping[str, Any],
    ) -> dict[str, Any]:
        if path == "/api/v1/spot/readiness":
            return self._spot_readiness(query)
        if path == "/api/v1/spot/sweep/status":
            return _operator_status("spot_sweep_status")
        if path == "/api/v1/spot/sweep/pnl":
            return {"type": "spot_sweep_pnl", "pnl_report": {}, "live_coinbase_orders_ran": False}
        if path == "/api/v1/spot/pnl/checkpoints":
            return {
                "type": "spot_pnl_checkpoint_list",
                "checkpoints": [],
                "count": 0,
                "live_coinbase_orders_ran": False,
            }
        if path.startswith("/api/v1/spot/pnl/checkpoints/"):
            return {
                "type": "spot_pnl_checkpoint_detail",
                "checkpoint_id": _last_path_part(path),
                "found": False,
                "checkpoint": None,
                "live_coinbase_orders_ran": False,
            }
        if path in {"/api/v1/spot/cost-basis/status", "/api/v1/spot/campaign/status"}:
            return _operator_status(_last_path_part(path))
        if "/direct-orders/" in path:
            return {
                "type": "spot_direct_order_audit",
                "status": "missing",
                "client_order_id": path.split("/direct-orders/", 1)[1].split("/", 1)[0],
                "audit": {},
                "message": "No local direct-order audit record exists.",
                "live_coinbase_orders_ran": False,
            }
        return {
            "type": "spot_placeholder",
            "status": "blocked",
            "route": path,
            "read_only": True,
            "items": [],
            "live_coinbase_orders_ran": False,
        }

    def _spot_readiness(self, query: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = self._account_snapshot()
        spot_admission_input = _spot_admission_input_from_snapshot(snapshot)
        product_rows = [
            self._admin_product_row(product_id)
            for product_id in _query_values(query, "product_id")
        ]
        products = _spot_readiness_products(product_rows, snapshot)
        return {
            "type": "spot_readiness",
            "status": _spot_readiness_status(snapshot),
            "module_id": MANUAL_ORDER_MODULE_ID,
            "account_reality": snapshot["account_reality"],
            "account_scope": snapshot["account_scope"],
            "portfolio_scope": snapshot["portfolio_scope"],
            "account_readiness": snapshot["readiness"],
            "spot_admission_input": spot_admission_input,
            "products": products,
            "planned_budget": _spot_readiness_planned_budget(),
            "wallet_snapshot": _spot_readiness_wallet_snapshot(snapshot, spot_admission_input),
            "action_guard_summary": _spot_readiness_guard_summary(
                snapshot,
                products,
                spot_admission_input,
            ),
            "read_only": True,
            "browser_authority": "display_only",
            "bff_authority": "read_only_forward",
            "coinbase_read_enabled": snapshot["coinbase_read_enabled"],
            "live_coinbase_read_ran": snapshot["coinbase_read_ran"],
            "command_routes_mode": "backend_admin_api",
            **self._live_outputs(False, Decimal("0")),
        }

    def _stealth_placeholder(
        self,
        path: str,
        query: Mapping[str, Any],
    ) -> dict[str, Any]:
        if path == "/api/v1/stealth/orders":
            limit = _query_int(query, "limit", 10)
            offset = _query_int(query, "offset", 0)
            return {
                "type": "admin_stealth_order_list",
                "count": 0,
                "items": [],
                "pagination": _pagination(limit, 0, offset),
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "live_coinbase_orders_ran": False,
            }
        if path == "/api/v1/stealth/command-suite":
            return _empty_command_suite("admin_stealth_command_suite")
        if path.count("/") >= 4:
            return {
                "type": "admin_stealth_detail",
                "stealth_order_id": path.split("/stealth/orders/", 1)[-1].split("/", 1)[0],
                "found": False,
                "order": None,
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "live_coinbase_orders_ran": False,
            }
        return _empty_read(path)

    def _movement_repricing_placeholder(
        self,
        path: str,
        query: Mapping[str, Any],
    ) -> dict[str, Any]:
        if path == "/api/v1/movement-repricing/evidence":
            limit = _query_int(query, "limit", 10)
            offset = _query_int(query, "offset", 0)
            return {
                "type": "movement_repricing_evidence_list",
                "count": 0,
                "items": [],
                "pagination": _pagination(limit, 0, offset),
                "read_only": True,
                "command_routes_mode": "backend_admin_api",
                "live_coinbase_orders_ran": False,
            }
        return {
            "type": "movement_repricing_detail",
            "scope": "client_order_id" if "/orders/" in path else "stealth_order_id",
            "client_order_id": _last_path_part(path) if "/orders/" in path else None,
            "stealth_order_id": _last_path_part(path) if "/stealth/" in path else None,
            "found": False,
            "items": [],
            "read_only": True,
            "command_routes_mode": "backend_admin_api",
            "live_coinbase_orders_ran": False,
        }

    def _futures_placeholder(
        self,
        path: str,
        query: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        if path == "/api/v1/futures/command-suite":
            return self._futures_command_suite()
        if path == "/api/v1/futures/account":
            return self._futures_account()
        if path == "/api/v1/futures/positions":
            return self._futures_positions(query)
        if path.startswith("/api/v1/futures/orders/") and path.endswith(
            "/fill-readback"
        ):
            client_order_id = path.split("/api/v1/futures/orders/", 1)[1].rsplit(
                "/fill-readback",
                1,
            )[0]
            return self._futures_order_fill_readback(
                unquote(client_order_id),
                query,
                context,
            )
        if path == "/api/v1/futures/risk-proofs":
            return self._futures_risk_proofs(query)
        if "/risk-proofs/" in path:
            return self._futures_risk_proof_detail(unquote(_last_path_part(path)))
        return self._futures_position_detail(unquote(_last_path_part(path)))

    def _futures_account(self) -> dict[str, Any]:
        snapshot = self._account_snapshot()
        position_scope = [
            item["product_id"] for item in snapshot["futures_positions"] if item.get("product_id")
        ]
        liquidation = self._futures_liquidation_evidence(
            snapshot["futures_margin_collateral"]["margin"]
        )
        funding = self._futures_funding_evidence(
            snapshot["futures_margin_collateral"],
            snapshot["futures_positions"],
        )
        reduce_close = self._futures_reduce_close_evidence(snapshot["futures_positions"])
        return {
            "type": "admin_futures_account",
            "configured_product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
            "observed_position_scope": position_scope,
            "account_reality": snapshot["account_reality"],
            "account_readiness": snapshot["readiness"],
            "collateral": snapshot["futures_margin_collateral"]["collateral"],
            "margin": snapshot["futures_margin_collateral"]["margin"],
            "funding": funding,
            "liquidation": liquidation,
            "reduce_only_close_only": reduce_close,
            "position_pnl": self._futures_evidence(
                "position_pnl",
                "unavailable",
                "runtime_unavailable",
                "Position P/L requires observed futures position evidence.",
            ),
            "position_count": len(snapshot["futures_positions"]),
            "read_only": True,
            "command_routes_mode": "backend_admin_api_blocked",
            "live_coinbase_orders_ran": False,
        }

    def _futures_liquidation_evidence(
        self,
        margin: Mapping[str, Any],
    ) -> dict[str, Any]:
        value = _object_to_dict(margin.get("value"))
        threshold = _object_to_dict(value.get("liquidation_threshold"))
        buffer = _object_to_dict(value.get("liquidation_buffer"))
        threshold_present = bool(str(threshold.get("value") or "").strip())
        buffer_present = bool(str(buffer.get("value") or "").strip())
        if margin.get("status") == "ready" and threshold_present and buffer_present:
            return self._futures_evidence(
                "liquidation",
                "ready",
                BACKEND_REST_CLIENT_SOURCE,
                "US CFM liquidation threshold and buffer are present in the backend margin snapshot.",
                {
                    "liquidation_threshold_present": True,
                    "liquidation_buffer_present": True,
                    "margin_window_type": value.get("margin_window_type"),
                    "source_ref": "/api/v1/futures/account.margin",
                },
            )
        return self._futures_evidence(
            "liquidation",
            "unavailable",
            "runtime_unavailable",
            "Liquidation threshold and buffer require a ready backend CFM margin snapshot.",
        )

    def _futures_funding_evidence(
        self,
        margin_collateral: Mapping[str, Any],
        positions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        collateral = _object_to_dict(margin_collateral.get("collateral"))
        margin = _object_to_dict(margin_collateral.get("margin"))
        collateral_value = _object_to_dict(collateral.get("value"))
        margin_value = _object_to_dict(margin.get("value"))
        account_family = str(
            collateral_value.get("account_family")
            or margin_value.get("account_family")
            or ""
        )
        intx_applicability = str(
            collateral_value.get("intx_applicability")
            or margin_value.get("intx_applicability")
            or ""
        )
        product_scope = [
            item["product_id"] for item in positions if item.get("product_id")
        ] or list(FUTURES_CONFIGURED_PRODUCT_SCOPE)
        funding_value = {
            "funding_applicability": "not_applicable_us_cfm",
            "funding_required": False,
            "account_family": account_family or FUTURES_ACCOUNT_FAMILY_US_CFM,
            "intx_applicability": (
                intx_applicability or FUTURES_INTX_APPLICABILITY_US_ACCOUNT
            ),
            "product_scope": product_scope,
            "source_ref": "/api/v1/futures/account.margin",
        }
        if (
            margin_collateral.get("status") == "ready"
            and collateral.get("status") == "ready"
            and margin.get("status") == "ready"
            and account_family == FUTURES_ACCOUNT_FAMILY_US_CFM
            and intx_applicability == FUTURES_INTX_APPLICABILITY_US_ACCOUNT
        ):
            return self._futures_evidence(
                "funding",
                "ready",
                BACKEND_REST_CLIENT_SOURCE,
                "US CFM futures scope has no INTX perpetual funding requirement; funding applicability is backend-owned evidence.",
                funding_value,
            )
        return self._futures_evidence(
            "funding",
            "unavailable",
            "runtime_unavailable",
            "Funding applicability requires a ready US CFM margin/collateral snapshot.",
            {
                **funding_value,
                "funding_applicability": "unknown",
                "funding_required": None,
            },
        )

    def _futures_reduce_close_evidence(
        self,
        positions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        observed = [
            item
            for item in positions
            if str(item.get("position_side") or "").strip().upper()
            not in {"", "UNKNOWN"}
        ]
        if observed:
            return self._futures_evidence(
                "reduce_only_close_only",
                "ready",
                "runtime_positions",
                "Observed Futures position side is present for backend close/reduce semantics.",
                {
                    "position_side_observed_count": len(observed),
                    "position_size_observed_count": sum(
                        1
                        for item in observed
                        if str(item.get("number_of_contracts") or "").strip()
                    ),
                    "product_scope": [
                        item["product_id"] for item in observed if item.get("product_id")
                    ],
                    "backend_derives_close_reduce_side": True,
                    "source_ref": "/api/v1/futures/positions",
                },
            )
        return self._futures_evidence(
            "reduce_only_close_only",
            "unavailable",
            "runtime_unavailable",
            "Close/reduce sides require an observed futures position side.",
        )

    def _futures_positions(self, query: Mapping[str, Any]) -> dict[str, Any]:
        limit = _query_int(query, "limit", 10)
        offset = _query_int(query, "offset", 0)
        snapshot = self._account_snapshot()
        items = snapshot["futures_positions"][offset : offset + limit]
        return {
            "type": "admin_futures_positions",
            "filters": dict(query),
            "count": len(items),
            "items": items,
            "pagination": _pagination(limit, len(snapshot["futures_positions"]), offset),
            "read_only": True,
            "command_routes_mode": "backend_admin_api_blocked",
            "live_coinbase_orders_ran": False,
        }

    def _futures_order_fill_readback(
        self,
        client_order_id: str,
        query: Mapping[str, Any],
        context: AdminMvpRequestContext,
    ) -> dict[str, Any]:
        """Read filled Futures order evidence by client_order_id without mutation."""

        from tools.run_admin_api_futures_live_fill_readback import (
            FuturesLiveFillReadbackConfig,
            run_futures_live_fill_readback,
        )

        rest_client = (
            self.dependencies.rest_client
            if self.dependencies.rest_client_available
            else None
        )
        summary = run_futures_live_fill_readback(
            rest_client,
            FuturesLiveFillReadbackConfig(
                client_order_id=client_order_id,
                product_id=_query_text(query, "product_id") or None,
                backend_contract_ref=_query_text(query, "backend_contract_ref") or None,
                fill_limit=max(_query_int(query, "fill_limit", 100), 1),
            ),
        )
        return {
            "type": "admin_futures_order_fill_readback",
            "module_id": FUTURES_MODULE_ID,
            "route": "/api/v1/futures/orders/{client_order_id}/fill-readback",
            "method": "GET",
            "action_class": "read_only",
            "required_permission": "analytics:read",
            "service_method": "read_futures_order_fill_readback",
            "identity_key": "client_order_id",
            "identity_value": client_order_id,
            "client_order_id": client_order_id,
            "operator_identity_key": "client_order_id",
            "correlation_id": context.correlation_id,
            "idempotency_key": context.idempotency_key,
            "actor_id": context.actor_id,
            "operator_intent": context.operator_intent,
            "audit_id": f"audit-{context.idempotency_key}",
            "exchange_order_id_evidence_only": True,
            "coinbase_read_attempted": bool(summary.get("live_coinbase_read_ran")),
            "coinbase_read_succeeded": bool(
                summary.get("order_read_succeeded")
                and summary.get("fill_read_succeeded")
            ),
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "local_state_mutated": False,
            "exchange_state_mutated": False,
            "live_exchange_submitted": False,
            "command_routes_mode": "backend_admin_api_confirmed_live_readback",
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            **summary,
        }

    def _futures_position_detail(self, position_key: str) -> dict[str, Any]:
        snapshot = self._account_snapshot()
        position = next(
            (
                item
                for item in snapshot["futures_positions"]
                if item["position_key"] == position_key or item["product_id"] == position_key
            ),
            None,
        )
        return {
            "type": "admin_futures_position_detail",
            "position_key": position_key,
            "found": position is not None,
            "position": position,
            "read_only": True,
            "command_routes_mode": "backend_admin_api_blocked",
            "live_coinbase_orders_ran": False,
        }

    def _futures_risk_proofs(self, query: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = self._account_snapshot()
        records = self._futures_risk_proof_records(snapshot)
        records = _filter_futures_risk_proofs(records, query)
        stored_count = len(self.store.futures_risk_proofs)
        return {
            "type": "admin_futures_risk_proofs",
            "module_id": FUTURES_MODULE_ID,
            "status": "ready" if records else "blocked",
            "filters": dict(query),
            "count": len(records),
            "items": records,
            "proof_records_created": stored_count > 0,
            "proof_records_generated_from_account_snapshot": any(
                record.get("source") == "account_management_snapshot" for record in records
            ),
            "read_only": True,
            "command_routes_mode": (
                "backend_admin_api_draft_only" if records else "backend_admin_api_blocked"
            ),
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_coinbase_orders_ran": False,
        }

    def _futures_risk_proof_detail(self, proof_id: str) -> dict[str, Any]:
        snapshot = self._account_snapshot()
        record = next(
            (
                item
                for item in self._futures_risk_proof_records(snapshot)
                if item["futures_risk_proof_id"] == proof_id
            ),
            None,
        )
        return {
            "type": "admin_futures_risk_proof_detail",
            "module_id": FUTURES_MODULE_ID,
            "futures_risk_proof_id": proof_id,
            "found": record is not None,
            "record": record,
            "proof_record_created": (
                proof_id in self.store.futures_risk_proofs if record is not None else False
            ),
            "read_only": True,
            "command_routes_mode": (
                "backend_admin_api_draft_only" if record is not None else "backend_admin_api_blocked"
            ),
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_coinbase_orders_ran": False,
        }

    def _futures_risk_proof_records(self, snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
        records = list(self.store.futures_risk_proofs.values())
        if bool(snapshot["readiness"]["usable_for_futures_risk"]):
            records.extend(self._account_snapshot_futures_risk_proofs(snapshot))
        return records

    def _account_snapshot_futures_risk_proofs(
        self,
        snapshot: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        position = snapshot["futures_positions"][0] if snapshot["futures_positions"] else {}
        product_id = str(
            position.get("product_id")
            or next(iter(FUTURES_CONFIGURED_PRODUCT_SCOPE), "unknown")
        )
        position_key = position.get("position_key")
        for spec in FUTURES_COMMAND_SPECS:
            command = str(spec["command"])
            records.append(
                self._futures_risk_proof_record(
                    proof_id=f"futures-risk-proof-account-snapshot-{command.replace('_', '-')}",
                    command=command,
                    proof_kind="margin_collateral",
                    recorded_at=snapshot["account_reality"]["generated_at"],
                    source=ACCOUNT_SNAPSHOT_WALLET_SOURCE,
                    product_id=product_id,
                    position_key=position_key,
                    evidence_ref=snapshot["account_reality"]["proof_id"],
                    verified=True,
                    accepted=False,
                    context=None,
                )
            )
        return records

    def _futures_risk_proof_record(
        self,
        *,
        proof_id: str,
        command: str,
        proof_kind: str,
        recorded_at: str,
        source: str,
        product_id: Any,
        position_key: Any,
        evidence_ref: str,
        verified: bool,
        accepted: bool,
        context: AdminMvpRequestContext | None,
    ) -> dict[str, Any]:
        return {
            "futures_risk_proof_id": proof_id,
            "recorded_at": recorded_at,
            "mutation_family": "futures_risk_proof",
            "command": command,
            "proof_kind": proof_kind,
            "proof_contract_ref": f"admin_futures_risk_proof_contracts.{command}.{proof_kind}",
            "evidence_ref": evidence_ref,
            "evidence_source": source,
            "risk_evidence_refs": [
                "/api/v1/futures/account",
                "/api/v1/futures/positions",
            ],
            "product_id": product_id,
            "position_key": position_key,
            "reconciliation_plan_id": None,
            "approval_snapshot_id": None,
            "admission_audit_id": None,
            "cap_guard_decision_id": None,
            "route": "/api/v1/futures/risk-proofs",
            "method": "POST",
            "module_id": FUTURES_MODULE_ID,
            "action_class": "local_state_mutation",
            "required_permission": "futures_risk_proof:record",
            "service_method": "record_futures_risk_proof",
            "actor_id": context.actor_id if context is not None else "backend-account-snapshot",
            "operator_intent": (
                context.operator_intent if context is not None else "derived_futures_risk_input"
            ),
            "idempotency_key": context.idempotency_key if context is not None else proof_id,
            "correlation_id": context.correlation_id if context is not None else proof_id,
            "payload_hash": _payload_hash(
                {"command": command, "proof_kind": proof_kind, "evidence_ref": evidence_ref}
            ),
            "audit_id": f"audit-{proof_id}",
            "dry_run": True,
            "operator_reason": "Backend-owned futures risk proof evidence; no live order execution.",
            "manual_live_acknowledgement": False,
            "source": source,
            "proof_persisted": context is not None,
            "proof_generated_from_account_snapshot": context is None,
            "risk_proof_verified": verified,
            "risk_proof_accepted": accepted,
            "command_route_registered": True,
            "command_draft_created": False,
            "command_execution_allowed": False,
            "margin_validated": verified,
            "collateral_validated": verified,
            "liquidation_validated": verified,
            "funding_validated": verified,
            "reduce_only_validated": command == "futures_close_reduce",
            "close_only_validated": command == "futures_close_reduce",
            "reconciliation_executed": False,
            "order_state_mutated": False,
            "exchange_state_mutated": False,
            "coinbase_read_attempted": context is None,
            "coinbase_read_succeeded": context is None and verified,
            "coinbase_rest_read_ran": context is None,
            "coinbase_order_submitted": False,
            "coinbase_order_cancel_submitted": False,
            "live_exchange_submitted": False,
            "live_coinbase_orders_ran": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }

    def _futures_evidence(
        self,
        name: str,
        status: str,
        source: str,
        detail: str,
        value: Any = None,
    ) -> dict[str, Any]:
        evidence = {
            "name": name,
            "status": status,
            "source": source,
            "detail": detail,
        }
        if value is not None:
            evidence["value"] = value
        return evidence

    def _futures_command_suite(self) -> dict[str, Any]:
        snapshot = self._account_snapshot()
        fee_snapshot = self._read_admin_fee_snapshot()["snapshot"]
        futures_liquidation_evidence = self._futures_liquidation_evidence(
            snapshot["futures_margin_collateral"]["margin"]
        )
        futures_funding_evidence = self._futures_funding_evidence(
            snapshot["futures_margin_collateral"],
            snapshot["futures_positions"],
        )
        futures_reduce_close_evidence = self._futures_reduce_close_evidence(
            snapshot["futures_positions"]
        )
        proofs = self._futures_risk_proof_records(snapshot)
        proof_by_command = {str(proof["command"]): proof for proof in proofs}
        resolved_contracts = _futures_resolved_contracts(snapshot, proofs)
        missing_contracts = [
            contract
            for contract in FUTURES_COMMAND_CONTRACTS
            if contract not in resolved_contracts
        ]
        live_service_decision = self._futures_live_service_decision()
        live_runtime_ready = self._futures_live_runtime_ready()
        request_field_summaries = _futures_request_field_summaries()
        commands: list[dict[str, Any]] = []
        for spec in FUTURES_COMMAND_SPECS:
            live_adapter_decision = self._futures_live_adapter_decision_for_spec(spec)
            live_decision_evidence = self._futures_live_decision_evidence(
                command=str(spec["command"]),
                route=str(spec["route"]),
                service_method=str(spec["service_method"]),
                live_service_decision=live_service_decision,
                live_adapter_decision=live_adapter_decision,
                live_runtime_ready=live_runtime_ready,
            )
            commands.append(
                self._futures_command(
                    command=str(spec["command"]),
                    action_class=str(spec["action_class"]),
                    route=str(spec["route"]),
                    service_method=str(spec["service_method"]),
                    identity_key=str(spec["identity_key"]),
                    required_permission=str(spec["required_permission"]),
                    missing_contracts=missing_contracts,
                    risk_proof=proof_by_command.get(str(spec["command"])),
                    account_ready=bool(snapshot["readiness"]["futures_account_scope_ready"]),
                    live_decision_evidence=live_decision_evidence,
                    futures_margin_collateral=snapshot["futures_margin_collateral"],
                    futures_liquidation_evidence=futures_liquidation_evidence,
                    futures_reduce_close_evidence=futures_reduce_close_evidence,
                    futures_funding_evidence=futures_funding_evidence,
                    futures_fee_input=fee_snapshot["futures_fee_input"],
                )
            )
        semantic_rows = {
            semantic: _futures_semantic_rows_from_commands(commands, semantic)
            for semantic in (
                *FUTURES_ACCOUNT_SEMANTIC_ARTIFACTS,
                *FUTURES_POSITION_SEMANTIC_ARTIFACTS,
            )
        }
        semantic_guard_rows = _futures_semantic_guard_rows_from_commands(commands)
        semantic_guard_summaries = _futures_semantic_guard_summaries(
            commands,
            semantic_guard_rows,
        )
        funding_semantic_rows = _futures_funding_semantic_rows_from_commands(commands)
        live_decision_summary = _futures_live_decision_summary(
            commands,
            live_runtime_ready=live_runtime_ready,
        )
        latest_live_submit_failure = self._latest_futures_live_submit_failure()
        futures_product_exposure_evidence = self._futures_product_exposure_evidence(
            live_decision_summary,
            latest_live_submit_failure,
        )
        live_decision_summary["latest_live_submit_failure"] = latest_live_submit_failure
        live_decision_summary["latest_live_submit_failure_present"] = (
            latest_live_submit_failure is not None
        )
        live_decision_summary["futures_product_exposure_evidence"] = (
            futures_product_exposure_evidence
        )
        blockers = self._futures_command_blockers(
            [command["command"] for command in commands],
            missing_contracts,
            live_decision_summary,
        )
        sequence_steps = _futures_command_enablement_sequence_steps(
            commands,
            missing_contracts,
            live_decision_summary,
        )
        sequence_traces = _futures_command_enablement_sequence_traces(
            commands,
            sequence_steps,
        )
        status = "evidence_ready" if not missing_contracts else "blocked"
        blocked_command_count = sum(
            1
            for command in commands
            if command["status"] != AdminMvpGateStatus.PASSED.value
        )
        executable_command_count = sum(
            1 for command in commands if bool(command["execution_allowed"])
        )
        command_routes_mode = _futures_command_routes_mode(
            missing_contracts=missing_contracts,
            executable_command_count=executable_command_count,
        )
        next_required_operator_decision = (
            _futures_command_suite_next_required_operator_decision(
                missing_contracts=missing_contracts,
                executable_command_count=executable_command_count,
                live_decision_summary=live_decision_summary,
            )
        )
        return {
            "type": "admin_futures_command_suite",
            "module_id": FUTURES_MODULE_ID,
            "approved_phase_range": "futures-perpetuals-read-contract",
            "status": status,
            "command_count": len(commands),
            "blocked_command_count": blocked_command_count,
            "executable_command_count": executable_command_count,
            "command_route_count": len(commands),
            "command_draft_allowed_count": len(commands),
            "prerequisite_count": 4,
            "blocking_prerequisite_count": 0 if not missing_contracts else 2,
            "prerequisite_summary_count": 4,
            "prerequisite_summary_blocking_count": 0 if not missing_contracts else 2,
            "prerequisite_summaries": _futures_prerequisite_summaries(
                missing_contracts,
                bool(snapshot["readiness"]["futures_account_scope_ready"]),
                bool(proofs),
            ),
            "request_field_count": sum(
                len(_futures_request_fields_for_command(str(spec["command"])))
                for spec in FUTURES_COMMAND_SPECS
            ),
            "required_request_field_count": sum(
                len(_futures_request_fields_for_command(str(spec["command"])))
                for spec in FUTURES_COMMAND_SPECS
            ),
            "blocking_request_field_count": 0,
            "request_field_summary_count": len(request_field_summaries),
            "request_field_summary_blocking_count": 0,
            "request_field_summaries": request_field_summaries,
            **_futures_semantic_counts("margin", semantic_rows["margin"]),
            "request_payload_validation_record_margin_semantics": semantic_rows["margin"],
            **_futures_semantic_counts("collateral", semantic_rows["collateral"]),
            "request_payload_validation_record_collateral_semantics": semantic_rows["collateral"],
            **_futures_semantic_counts("liquidation", semantic_rows["liquidation"]),
            "request_payload_validation_record_liquidation_semantics": semantic_rows["liquidation"],
            **_futures_semantic_counts("reduce_only", semantic_rows["reduce_only"]),
            "request_payload_validation_record_reduce_only_semantics": semantic_rows["reduce_only"],
            **_futures_semantic_counts("close_only", semantic_rows["close_only"]),
            "request_payload_validation_record_close_only_semantics": semantic_rows["close_only"],
            **_futures_funding_semantic_counts(funding_semantic_rows),
            "request_payload_validation_record_funding_semantics": funding_semantic_rows,
            **_futures_semantic_guard_counts(semantic_guard_rows),
            "semantic_guard_summary_count": len(semantic_guard_summaries),
            "semantic_guard_summary_blocking_count": sum(
                1 for item in semantic_guard_summaries if bool(item["blocking"])
            ),
            "semantic_guard_summaries": semantic_guard_summaries,
            "command_enablement_blocker_summary_count": len(blockers),
            "command_enablement_blocker_summary_blocking_count": len(blockers),
            "command_enablement_blocker_summaries": blockers,
            "command_enablement_sequence_step_count": len(sequence_steps),
            "command_enablement_sequence_step_blocking_count": sum(
                1 for step in sequence_steps if bool(step["blocking"])
            ),
            "command_enablement_sequence_steps": sequence_steps,
            "command_enablement_sequence_command_trace_count": len(sequence_traces),
            "command_enablement_sequence_command_trace_blocking_count": sum(
                1 for trace in sequence_traces if bool(trace["blocking"])
            ),
            "command_enablement_sequence_command_traces": sequence_traces,
            "commands": commands,
            "futures_live_execution_scope": _futures_live_execution_scope(
                execution_allowed=executable_command_count > 0,
            ),
            "futures_live_decision_evidence": live_decision_summary,
            "futures_product_exposure_evidence": futures_product_exposure_evidence,
            "latest_live_submit_failure": latest_live_submit_failure,
            "latest_live_submit_failure_present": latest_live_submit_failure is not None,
            "account_evidence_routes": ["/api/v1/futures/account"],
            "position_evidence_routes": [
                "/api/v1/futures/positions",
                "/api/v1/futures/positions/{position_key}",
            ],
            "required_backend_contracts": list(FUTURES_COMMAND_CONTRACTS),
            "resolved_backend_contracts": resolved_contracts,
            "missing_backend_contracts": missing_contracts,
            "next_required_operator_decision": next_required_operator_decision,
            "futures_risk_proof_count": len(proofs),
            "futures_risk_proof_ids": [
                str(proof["futures_risk_proof_id"]) for proof in proofs
            ],
            "forbidden_spot_assumptions": [
                "spot_wallet_usdc_only",
                "spot_no_shorting",
                "spot_average_cost_basis",
                "spot_inventory_available_quote",
            ],
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "live_coinbase_orders_ran": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "read_only": True,
            "command_routes_mode": command_routes_mode,
            "message": (
                "Futures command-suite evidence is ready for confirmed backend live exchange commands; reconciliation remains evidence-only."
                if executable_command_count
                else "Futures command-suite evidence is ready for draft review; execution remains disabled."
                if not missing_contracts
                else "Futures command readiness is backend-owned and blocked until futures account and risk-proof evidence exist."
            ),
        }

    def _futures_command(
        self,
        *,
        command: str,
        action_class: str,
        route: str,
        service_method: str,
        identity_key: str,
        required_permission: str,
        missing_contracts: list[str],
        risk_proof: Mapping[str, Any] | None,
        account_ready: bool,
        live_decision_evidence: Mapping[str, Any],
        futures_margin_collateral: Mapping[str, Any],
        futures_liquidation_evidence: Mapping[str, Any],
        futures_reduce_close_evidence: Mapping[str, Any],
        futures_funding_evidence: Mapping[str, Any],
        futures_fee_input: Mapping[str, Any],
    ) -> dict[str, Any]:
        blocking_prerequisite_count = 0 if not missing_contracts else 2
        request_fields = _futures_request_fields_for_command(command)
        semantic_rows = _futures_request_payload_validation_record_semantics(
            command,
            identity_key,
            request_fields,
            futures_margin_collateral,
            futures_liquidation_evidence,
            futures_reduce_close_evidence,
        )
        funding_semantics = _futures_request_payload_validation_record_funding_semantics(
            command,
            identity_key,
            request_fields,
            futures_funding_evidence,
            futures_fee_input,
        )
        semantic_guards = _futures_command_semantic_guards(
            command=command,
            identity_key=identity_key,
            request_fields=request_fields,
            missing_contracts=missing_contracts,
            risk_proof=risk_proof,
            semantic_rows=semantic_rows,
            funding_semantics=funding_semantics,
            live_decision_evidence=live_decision_evidence,
        )
        semantic_guard_counts = _futures_semantic_guard_counts(semantic_guards)
        first_blocker = (
            str(live_decision_evidence["first_blocker"])
            if not missing_contracts
            else "futures_margin_collateral_risk_proof"
        )
        execution_allowed = bool(
            not missing_contracts and live_decision_evidence.get("execution_allowed")
        )
        live_exchange_command = _futures_live_exchange_command(command)
        command_status = (
            AdminMvpGateStatus.PASSED.value
            if execution_allowed
            else AdminMvpGateStatus.BLOCKED.value
        )
        if execution_allowed:
            readiness_decision = "confirmed_live_ready"
        elif not missing_contracts and first_blocker == "futures_executor_live_disabled":
            readiness_decision = "executor_observed_live_disabled"
        elif not missing_contracts:
            readiness_decision = "draft_ready_execution_disabled"
        else:
            readiness_decision = "blocked_backend_contracts_required"
        return {
            "command": command,
            "mutation_family": (
                "futures_confirmed_live_ready"
                if execution_allowed
                else "futures_contract_required"
            ),
            "status": command_status,
            "action_class": action_class,
            "route": route,
            "method": "POST",
            "service_method": service_method,
            "identity_key": identity_key,
            "required_permission": required_permission,
            "prerequisite_count": 4,
            "resolved_prerequisite_count": 4 - blocking_prerequisite_count,
            "blocking_prerequisite_count": blocking_prerequisite_count,
            "prerequisites": self._futures_command_prerequisites(
                command,
                missing_contracts,
                account_ready,
                risk_proof is not None,
            ),
            "request_field_count": len(request_fields),
            "required_request_field_count": len(request_fields),
            "blocking_request_field_count": 0,
            "request_fields": request_fields,
            **_futures_semantic_counts("margin", semantic_rows["margin"]),
            "request_payload_validation_record_margin_semantics": semantic_rows["margin"],
            **_futures_semantic_counts("collateral", semantic_rows["collateral"]),
            "request_payload_validation_record_collateral_semantics": semantic_rows["collateral"],
            **_futures_semantic_counts("liquidation", semantic_rows["liquidation"]),
            "request_payload_validation_record_liquidation_semantics": semantic_rows["liquidation"],
            **_futures_semantic_counts("reduce_only", semantic_rows["reduce_only"]),
            "request_payload_validation_record_reduce_only_semantics": semantic_rows["reduce_only"],
            **_futures_semantic_counts("close_only", semantic_rows["close_only"]),
            "request_payload_validation_record_close_only_semantics": semantic_rows["close_only"],
            **_futures_funding_semantic_counts(funding_semantics),
            "request_payload_validation_record_funding_semantics": funding_semantics,
            **semantic_guard_counts,
            "semantic_guards": semantic_guards,
            "required_backend_contracts": list(FUTURES_COMMAND_CONTRACTS),
            "missing_backend_contracts": missing_contracts,
            "risk_proof_id": (
                str(risk_proof["futures_risk_proof_id"]) if risk_proof is not None else None
            ),
            "forbidden_spot_assumptions": [
                "spot_wallet_usdc_only",
                "spot_no_shorting",
                "spot_average_cost_basis",
            ],
            "readiness_decision": {
                "decision": readiness_decision,
                "status": command_status,
                "ready": execution_allowed,
                "blocker_count": (
                    0
                    if execution_allowed
                    else 1
                    if not missing_contracts
                    else len(missing_contracts)
                ),
                "blocking_prerequisite_count": blocking_prerequisite_count,
                "blocking_request_field_count": 0,
                "blocking_semantic_guard_count": semantic_guard_counts[
                    "blocking_semantic_guard_count"
                ],
                "missing_backend_contract_count": len(missing_contracts),
                "missing_evidence_ref_count": 0 if not missing_contracts else 2,
                "evidence_route_count": 4,
                "first_blocker": first_blocker,
                "next_required_backend_contract": missing_contracts[0] if missing_contracts else None,
                "command_route_registered": True,
                "command_draft_allowed": True,
                "execution_allowed": execution_allowed,
                "manual_live_acknowledgement_required": live_exchange_command,
                "backend_owned": True,
                "read_only": True,
                "spot_rule_authority": False,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "live_decision_evidence": dict(live_decision_evidence),
                "detail": (
                    "Futures live-decision evidence is bound to the US CFM scope; confirmed backend live exchange submission is available only after explicit operator acknowledgement."
                    if execution_allowed
                    else
                    "Futures live-decision evidence is bound to the US CFM scope; the backend executor boundary is present and live-disabled."
                    if first_blocker == "futures_executor_live_disabled"
                    else "Futures reconciliation remains backend evidence-only; no live exchange submission is available for this route."
                    if first_blocker == "futures_reconciliation_execution_disabled"
                    else "Futures command draft evidence is available; live execution remains disabled."
                    if not missing_contracts
                    else "Futures command is visible as a route-bound draft only; execution remains blocked."
                ),
            },
            **_futures_command_readiness_closure(
                command=command,
                route=route,
                service_method=service_method,
                missing_contracts=missing_contracts,
                request_fields=request_fields,
                live_decision_evidence=live_decision_evidence,
            ),
            "command_route_registered": True,
            "command_draft_allowed": True,
            "execution_allowed": execution_allowed,
            "manual_live_acknowledgement_required": live_exchange_command,
            "live_coinbase_orders_ran": False,
            "submitted_notional_usdc": "0",
            "executed_notional_usdc": "0",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": (
                "Backend-owned futures command readiness evidence; confirmed live exchange submission is available only through backend Admin API acknowledgement."
                if execution_allowed
                else "Backend-owned futures command readiness evidence; no Coinbase call, state mutation, or browser/BFF execution authority."
            ),
            "spot_rule_authority": False,
        }

    def _futures_command_prerequisites(
        self,
        command: str,
        missing_contracts: list[str],
        account_ready: bool,
        risk_proof_ready: bool,
    ) -> list[dict[str, Any]]:
        reconciliation_ready = "futures_reconciliation_contract" not in missing_contracts
        live_adapter_ready = "futures_live_adapter_contract" not in missing_contracts
        return [
            {
                "prerequisite": "futures_account_scope",
                "status": "ready" if account_ready else "blocked",
                "source": "backend_contract",
                "resolved": account_ready,
                "blocking": not account_ready,
                "spot_rule_authority": False,
                "evidence_route": "/api/v1/futures/account",
                "detail": f"{command} requires futures account and portfolio scope evidence.",
            },
            {
                "prerequisite": "margin_collateral_risk_proof",
                "status": "ready" if risk_proof_ready else "blocked",
                "source": "backend_contract",
                "resolved": risk_proof_ready,
                "blocking": not risk_proof_ready,
                "spot_rule_authority": False,
                "evidence_route": "/api/v1/futures/risk-proofs",
                "detail": f"{command} requires futures-specific margin, collateral, and liquidation proof.",
            },
            {
                "prerequisite": "audit_idempotency_replay_protection",
                "status": "ready",
                "source": "backend_contract",
                "resolved": True,
                "blocking": False,
                "spot_rule_authority": False,
                "evidence_route": "/api/v1/admin/admission-audits",
                "detail": f"{command} requires audit correlation, idempotency, and replay protection.",
            },
            {
                "prerequisite": "futures_reconciliation",
                "status": "ready" if reconciliation_ready else "blocked",
                "source": "backend_contract",
                "resolved": reconciliation_ready,
                "blocking": not reconciliation_ready,
                "spot_rule_authority": False,
                "evidence_route": "/api/v1/admin/reconciliation/plans",
                "detail": f"{command} requires futures-specific reconciliation proof.",
                "live_adapter_evidence_ready": live_adapter_ready,
            },
        ]

    def _futures_command_blockers(
        self,
        commands: list[str],
        missing_contracts: list[str],
        live_decision_summary: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        if missing_contracts:
            blockers.append({
                "blocker": "unresolved_prerequisites",
                "status": "blocked",
                "blocking": True,
                "command_count": len(commands),
                "affected_commands": commands,
                "evidence_ref_count": 3,
                "required_evidence_refs": [
                    "/api/v1/futures/account",
                    "/api/v1/futures/risk-proofs",
                    "/api/v1/admin/reconciliation/plans",
                ],
                "required_backend_contracts": [
                    "futures_account_scope_contract",
                    "futures_margin_collateral_risk_proof",
                    "futures_reconciliation_contract",
                ],
                "command_route_registered": True,
                "command_draft_allowed": True,
                "execution_allowed": False,
                "live_coinbase_orders_ran": False,
                "backend_owned": True,
                "read_only": True,
                "spot_rule_authority": False,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "detail": "Futures commands remain blocked until futures-specific prerequisites are implemented and proven.",
            })
        execution_blocker = str(live_decision_summary["first_blocker"])
        latest_live_submit_failure = live_decision_summary.get("latest_live_submit_failure")
        if execution_blocker == "none" and not latest_live_submit_failure:
            return blockers
        blocker_detail = (
            "Latest Futures/Perpetual live submit was rejected before Coinbase order mutation by backend cap evidence."
            if latest_live_submit_failure
            else "Futures confirmed live exchange commands can reach the backend executor with explicit operator acknowledgement."
            if execution_blocker == "none"
            else "Futures US CFM live-service and live-adapter decisions are bound; the backend Futures executor boundary is present and live-disabled."
            if execution_blocker == "futures_executor_live_disabled"
            else "Futures command evidence is available, but live futures execution is intentionally disabled."
        )
        blockers.append({
            "blocker": execution_blocker,
            "status": "blocked",
            "blocking": True,
            "command_count": len(commands),
            "affected_commands": commands,
            "evidence_ref_count": 2,
            "required_evidence_refs": [
                "/api/v1/admin/live-execution/service-decisions",
                "/api/v1/admin/live-execution/adapter-decisions",
            ],
            "required_backend_contracts": [],
            "command_route_registered": True,
            "command_draft_allowed": True,
            "execution_allowed": False,
            "live_coinbase_orders_ran": False,
            "backend_owned": True,
            "read_only": True,
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "futures_live_execution_scope": _futures_live_execution_scope(
                execution_allowed=bool(live_decision_summary.get("execution_allowed")),
            ),
            "futures_live_decision_evidence": dict(live_decision_summary),
            "latest_live_submit_failure": latest_live_submit_failure,
            "latest_live_submit_failure_present": latest_live_submit_failure is not None,
            "detail": blocker_detail,
        })
        return blockers

    def _guard_risk_policy(self, query: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "type": "admin_guard_risk_policy",
            "filters": dict(query),
            "action_condition_policy": {},
            "live_execution_gate": {},
            "product_capability_policy": {},
            "profitability_policy": {},
            "configured_limit_rules": [],
            "product_capability_decisions": [],
            "authority_sources": [],
            "rejection_categories": [],
            "read_only": True,
            "command_routes_mode": "backend_admin_api",
            "live_coinbase_orders_ran": False,
            "live_coinbase_read_ran": False,
        }

    def _audit_workbench(self, query: Mapping[str, Any]) -> dict[str, Any]:
        limit = _query_int(query, "limit", 10)
        offset = _query_int(query, "offset", 0)
        events = self._audit_workbench_events(query)
        visible_events = events[offset : offset + limit]
        live_coinbase_orders_ran = any(
            bool(event.get("live_coinbase_orders_ran")) for event in events
        )
        return {
            "type": "admin_audit_workbench",
            "filters": dict(query),
            "items": visible_events,
            "events": visible_events,
            "module_summary": _audit_workbench_module_summary(events),
            "count": len(visible_events),
            "pagination": _page_pagination(
                limit=limit,
                returned_count=len(visible_events),
                total_count=len(events),
                offset=offset,
            ),
            "command_routes_mode": "evidence_only",
            "read_only": True,
            "live_coinbase_orders_ran": live_coinbase_orders_ran,
            "live_coinbase_read_ran": False,
        }

    def _audit_workbench_events(self, query: Mapping[str, Any]) -> list[dict[str, Any]]:
        events = [
            self._spot_command_audit_event(record)
            for record in self.store.spot_command_decisions.values()
        ]
        events.extend(
            [
                self._futures_command_audit_event(record)
                for record in self.store.futures_command_decisions.values()
            ]
        )
        events.extend(
            [
                self._futures_executor_audit_event(record)
                for record in self.store.futures_executor_decisions.values()
            ]
        )
        return _filter_audit_workbench_events(events, query)

    def _spot_command_audit_event(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        admission_decision = dict(_mapping(record.get("admission_decision")))
        return {
            "event_id": record.get("decision_id"),
            "module": "spot",
            "source": "admin_api_audit_log",
            "action_class": record.get("action_class"),
            "endpoint": record.get("route"),
            "status": record.get("status"),
            "actor_id": record.get("actor_id"),
            "permission": record.get("required_permission"),
            "client_order_id": record.get("client_order_id") or record.get("identity_value"),
            "stealth_order_id": None,
            "position_key": None,
            "product_id": record.get("product_id"),
            "correlation_id": record.get("correlation_id"),
            "audit_id": record.get("audit_id"),
            "request_id": record.get("correlation_id"),
            "idempotency_key": record.get("idempotency_key"),
            "exchange_order_id": record.get("exchange_order_id"),
            "exchange_order_id_evidence_only": True,
            "live_exchange_submitted": bool(record.get("live_exchange_submitted")),
            "live_command_runtime_enabled": record.get("live_command_runtime_enabled"),
            "live_command_rest_client_available": record.get(
                "live_command_rest_client_available"
            ),
            "live_command_runtime_ready": record.get("live_command_runtime_ready"),
            "live_command_runtime_missing_reason": record.get(
                "live_command_runtime_missing_reason"
            ),
            "live_command_runtime_source": record.get("live_command_runtime_source"),
            "recorded_at": record.get("recorded_at"),
            "message": record.get("message"),
            "admission_decision": admission_decision,
            "live_coinbase_orders_ran": bool(record.get("live_coinbase_orders_ran")),
            "raw_event": dict(record),
        }

    def _futures_command_audit_event(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        identity_key = str(record.get("identity_key") or "")
        identity_value = str(record.get("identity_value") or "")
        position_key = identity_value if identity_key == "position_key" else None
        product_id = identity_value if identity_key == "product_id" else None
        client_order_id = (
            identity_value
            if identity_key == "client_order_id"
            else record.get("client_order_id")
        )
        admission_decision = dict(_mapping(record.get("admission_decision")))
        cap_guard_decision_id = record.get("cap_guard_decision_id")
        reconciliation_plan_id = record.get("reconciliation_plan_id")
        cap_guard = self.store.cap_guard_decisions.get(str(cap_guard_decision_id or ""))
        reconciliation = self.store.reconciliation_plans.get(str(reconciliation_plan_id or ""))
        cap_guard_present = (
            record.get("cap_guard_present")
            if isinstance(record.get("cap_guard_present"), bool)
            else cap_guard_decision_id is not None
        )
        reconciliation_plan_present = (
            record.get("reconciliation_plan_present")
            if isinstance(record.get("reconciliation_plan_present"), bool)
            else reconciliation_plan_id is not None
        )
        return {
            "event_id": record.get("decision_id"),
            "module": FUTURES_MODULE_ID,
            "source": record.get("source") or "admin_api_futures_command_log",
            "action_class": record.get("action_class"),
            "endpoint": record.get("route"),
            "status": record.get("status"),
            "actor_id": record.get("actor_id"),
            "permission": record.get("required_permission"),
            "client_order_id": client_order_id,
            "stealth_order_id": None,
            "position_key": position_key,
            "product_id": product_id or _first_text(record.get("product_scope")),
            "correlation_id": record.get("correlation_id"),
            "audit_id": record.get("audit_id"),
            "request_id": record.get("correlation_id"),
            "idempotency_key": record.get("idempotency_key"),
            "exchange_order_id": record.get("exchange_order_id"),
            "exchange_order_id_evidence_only": True,
            "live_exchange_submitted": bool(record.get("live_exchange_submitted")),
            "live_command_runtime_enabled": record.get("live_command_runtime_enabled"),
            "live_command_rest_client_available": record.get(
                "live_command_rest_client_available"
            ),
            "live_command_runtime_ready": record.get("live_command_runtime_ready"),
            "live_command_runtime_missing_reason": record.get("failure_stage"),
            "live_command_runtime_source": record.get("source"),
            "recorded_at": record.get("recorded_at"),
            "message": record.get("message") or record.get("detail"),
            "admission_decision": admission_decision,
            "readiness_decision": dict(_mapping(record.get("readiness_decision"))),
            "cap_guard_present": cap_guard_present,
            "cap_guard_decision_id": cap_guard_decision_id,
            "cap_guard_source": "admin_api_cap_guard_log" if cap_guard else None,
            "cap_guard_recorded_at": cap_guard.get("recorded_at") if cap_guard else None,
            "cap_guard_missing_reason": (
                None if cap_guard_present else "cap_guard_decision_missing"
            ),
            "reconciliation_plan_present": reconciliation_plan_present,
            "reconciliation_plan_id": reconciliation_plan_id,
            "reconciliation_plan_source": (
                "admin_api_reconciliation_plan_log" if reconciliation else None
            ),
            "reconciliation_plan_recorded_at": (
                reconciliation.get("recorded_at") if reconciliation else None
            ),
            "reconciliation_plan_missing_reason": (
                None if reconciliation_plan_present else "reconciliation_plan_missing"
            ),
            "live_coinbase_orders_ran": bool(record.get("live_coinbase_orders_ran")),
            "raw_event": dict(record),
        }

    def _futures_executor_audit_event(
        self,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        identity_key = str(record.get("identity_key") or "")
        identity_value = str(record.get("identity_value") or "")
        position_key = identity_value if identity_key == "position_key" else None
        product_id = identity_value if identity_key == "product_id" else None
        client_order_id = identity_value if identity_key == "client_order_id" else None
        status = AdminMvpCommandStatus.REJECTED.value
        admission_decision = {
            "decision_id": record.get("admission_decision_id"),
            "status": AdminMvpGateStatus.BLOCKED.value,
            "allowed": False,
            "route": record.get("route"),
            "method": record.get("method"),
            "module_id": record.get("module_id"),
            "identity_key": identity_key,
            "identity_value": identity_value,
            "action_class": record.get("action_class"),
            "required_permission": record.get("required_permission"),
            "service_method": record.get("service_method"),
            "actor_id": record.get("actor_id"),
            "idempotency_key": record.get("idempotency_key"),
            "operator_intent": record.get("operator_intent"),
            "payload_hash": record.get("payload_hash"),
            "account_family": record.get("account_family"),
            "intx_applicability": record.get("intx_applicability"),
            "product_scope": record.get("product_scope"),
            "risk_proof_id": record.get("risk_proof_id"),
            "executor_boundary_status": record.get("executor_status"),
            "executor_boundary_ready": record.get("executor_boundary_ready"),
            "browser_authority": record.get("browser_authority"),
            "bff_authority": record.get("bff_authority"),
            "live_exchange_submitted": False,
            "blockers": [record.get("failure_stage") or "futures_executor_live_disabled"],
            "evidence": [record.get("source") or FUTURES_EXECUTOR_BOUNDARY_SOURCE],
            "detail": record.get("detail"),
        }
        return {
            "event_id": record.get("decision_id"),
            "module": FUTURES_MODULE_ID,
            "source": record.get("source") or FUTURES_EXECUTOR_BOUNDARY_SOURCE,
            "action_class": record.get("action_class"),
            "endpoint": record.get("route"),
            "status": status,
            "actor_id": record.get("actor_id"),
            "permission": record.get("required_permission"),
            "client_order_id": client_order_id,
            "stealth_order_id": None,
            "position_key": position_key,
            "product_id": product_id or _first_text(record.get("product_scope")),
            "correlation_id": record.get("correlation_id"),
            "audit_id": record.get("audit_id"),
            "request_id": record.get("correlation_id"),
            "idempotency_key": record.get("idempotency_key"),
            "exchange_order_id": None,
            "exchange_order_id_evidence_only": True,
            "live_exchange_submitted": False,
            "live_command_runtime_enabled": False,
            "live_command_rest_client_available": False,
            "live_command_runtime_ready": False,
            "live_command_runtime_missing_reason": record.get("failure_stage"),
            "live_command_runtime_source": record.get("source"),
            "recorded_at": record.get("recorded_at"),
            "message": record.get("detail"),
            "admission_decision": admission_decision,
            "executor_decision": dict(record),
            "live_coinbase_orders_ran": False,
            "raw_event": dict(record),
        }

    def _capability_items(self) -> list[dict[str, Any]]:
        read_routes = [
            "/api/v1/admin/bootstrap",
            ADMIN_RUNTIME_ROUTE,
            "/api/v1/admin/health",
            "/api/v1/admin/session",
            "/api/v1/admin/oidc-readiness",
            "/api/v1/admin/capabilities",
            "/api/v1/admin/csrf",
            ACCOUNT_MANAGEMENT_ROUTE,
            ACCOUNT_WALLET_ROUTE,
            ACCOUNT_PRODUCTS_ROUTE,
            ACCOUNT_FEES_ROUTE,
            "/api/v1/admin/live-enablement",
            "/api/v1/admin/enterprise-readiness",
            "/api/v1/admin/release-gate",
            "/api/v1/admin/recovery-gate",
            "/api/v1/admin/fill-ledger-health",
            "/api/v1/admin/frontend-fixtures",
            "/api/v1/orders",
            "/api/v1/spot/command-suite",
            *FUTURES_READ_ROUTES,
        ]
        capabilities = [
            _read_capability(
                route,
                _read_capability_module_id(route),
            )
            for route in read_routes
        ]
        capabilities.extend([
            _command_capability(
                route=MANUAL_ORDER_ROUTE,
                action_class=MANUAL_ORDER_ACTION_CLASS,
                required_permission=MANUAL_ORDER_PERMISSION,
                shared_method=MANUAL_ORDER_SERVICE_METHOD,
                live_enabled=True,
            ),
            _command_capability(
                route=CANCEL_ORDER_ROUTE,
                action_class=CANCEL_ORDER_ACTION_CLASS,
                required_permission=CANCEL_ORDER_PERMISSION,
                shared_method=CANCEL_ORDER_SERVICE_METHOD,
                live_enabled=True,
            ),
            _command_capability(
                route="/api/v1/admin/approvals/requests",
                action_class="local_state_mutation",
                required_permission="approval:request",
                shared_method="create_approval_request",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/approvals/requests/{approval_request_id}/decisions",
                action_class="local_state_mutation",
                required_permission="approval:manage",
                shared_method="decide_approval_request",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/admission-audits",
                action_class="local_state_mutation",
                required_permission="admission_audit:record",
                shared_method="record_admission_audit",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/cap-guard/decisions",
                action_class="local_state_mutation",
                required_permission="cap_guard:record",
                shared_method="record_cap_guard_decision",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/reconciliation/plans",
                action_class="local_state_mutation",
                required_permission="reconciliation:record",
                shared_method="record_reconciliation_plan",
                live_enabled=False,
            ),
            _command_capability(
                route=ACCOUNT_PRODUCTS_REFRESH_ROUTE,
                action_class="local_state_mutation",
                required_permission=ACCOUNT_PRODUCTS_REFRESH_PERMISSION,
                shared_method=ACCOUNT_PRODUCTS_REFRESH_SERVICE_METHOD,
                live_enabled=False,
                module_id=ACCOUNT_MANAGEMENT_MODULE_ID,
            ),
            *(
                _command_capability(
                    route=str(spec["route"]),
                    action_class="admin_runtime",
                    required_permission=str(spec["required_permission"]),
                    shared_method=str(spec["service_method"]),
                    live_enabled=False,
                )
                for spec in ADMIN_RUNTIME_CONTROL_SPECS.values()
            ),
            _command_capability(
                route=SPOT_MANUAL_ORDER_PROOF_CHAIN_ROUTE,
                action_class="local_state_mutation",
                required_permission=SPOT_MANUAL_ORDER_PROOF_CHAIN_PERMISSION,
                shared_method=SPOT_MANUAL_ORDER_PROOF_CHAIN_SERVICE_METHOD,
                live_enabled=False,
                module_id=MANUAL_ORDER_MODULE_ID,
            ),
            _command_capability(
                route=SPOT_CANCEL_ORDER_PROOF_CHAIN_ROUTE,
                action_class="local_state_mutation",
                required_permission=SPOT_CANCEL_ORDER_PROOF_CHAIN_PERMISSION,
                shared_method=SPOT_CANCEL_ORDER_PROOF_CHAIN_SERVICE_METHOD,
                live_enabled=False,
                module_id=MANUAL_ORDER_MODULE_ID,
            ),
            *(
                _command_capability(
                    route=str(spec["route"]),
                    action_class=str(spec["action_class"]),
                    required_permission=str(spec["required_permission"]),
                    shared_method=str(spec["service_method"]),
                    live_enabled=False,
                    module_id=FUTURES_MODULE_ID,
                )
                for spec in FUTURES_COMMAND_SPECS
            ),
            _command_capability(
                route="/api/v1/admin/live-execution/service-decisions",
                action_class="local_state_mutation",
                required_permission="config:update",
                shared_method="record_live_service_decision",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/admin/live-execution/adapter-decisions",
                action_class="local_state_mutation",
                required_permission="config:update",
                shared_method="record_live_adapter_decision",
                live_enabled=False,
            ),
            _command_capability(
                route="/api/v1/futures/risk-proofs",
                action_class="local_state_mutation",
                required_permission="futures_risk_proof:record",
                shared_method="record_futures_risk_proof",
                live_enabled=False,
                module_id=FUTURES_MODULE_ID,
            ),
        ])
        return capabilities

    def _live_path(
        self,
        *,
        route: str,
        method: str,
        live_enabled: bool,
        live_eligible: bool,
    ) -> dict[str, Any]:
        runtime = self._runtime_evidence()
        return {
            "route": route,
            "method": method,
            "module_id": MANUAL_ORDER_MODULE_ID,
            "identity_key": "client_order_id",
            "action_class": (
                MANUAL_ORDER_ACTION_CLASS if route == MANUAL_ORDER_ROUTE else CANCEL_ORDER_ACTION_CLASS
            ),
            "required_permission": (
                MANUAL_ORDER_PERMISSION if route == MANUAL_ORDER_ROUTE else CANCEL_ORDER_PERMISSION
            ),
            "service_method": (
                MANUAL_ORDER_SERVICE_METHOD
                if route == MANUAL_ORDER_ROUTE
                else CANCEL_ORDER_SERVICE_METHOD
            ),
            "live_enabled": live_enabled,
            "live_eligible": live_eligible,
            "live_command_runtime_ready": runtime["live_command_runtime_ready"],
            "live_command_runtime_missing_reason": runtime[
                "live_command_runtime_missing_reason"
            ],
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": "Backend controlled-live route evidence.",
        }

    def _max_submitted_notional(self) -> Decimal:
        latest = _latest_record(self.store.service_decisions)
        if not latest:
            return DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC
        return _decimal_value(
            latest.get("max_submitted_notional_usdc"),
            DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC,
        )


def _live_enablement_blocker(
    *,
    service_decision_allows_live: bool,
    backend_live_execution_opt_in: bool,
    runtime_ready: bool,
) -> str | None:
    if not service_decision_allows_live:
        return "live_service_decision_missing"
    if not backend_live_execution_opt_in:
        return "backend_live_execution_disabled"
    if not runtime_ready:
        return "live_command_runtime_not_ready"
    return None


def _payload_hash(body: Mapping[str, Any]) -> str:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manual_order_notional(body: Mapping[str, Any]) -> Decimal:
    quote_size = _decimal_value(body.get("quote_size"), Decimal("0"))
    if quote_size > 0:
        return quote_size
    base_size = _decimal_value(body.get("base_size"), Decimal("0"))
    limit_price = _decimal_value(body.get("limit_price"), Decimal("0"))
    return base_size * limit_price


def _futures_latest_submit_failure_notional_for_product(
    latest_live_submit_failure: Mapping[str, Any] | None,
    product_id: str,
) -> Decimal:
    """Return latest failed Futures submit notional for one product."""

    if not latest_live_submit_failure:
        return Decimal("0")
    if str(latest_live_submit_failure.get("product_id") or "") != product_id:
        return Decimal("0")
    return _decimal_value(
        latest_live_submit_failure.get("attempted_notional_usdc"),
        Decimal("0"),
    )


def _futures_default_limit_price(
    product_metadata: Mapping[str, Any],
    *,
    side: str,
) -> Decimal | None:
    """Return the backend default Futures limit price for an order side."""

    price = _first_positive_decimal(product_metadata, _futures_price_fields_for_side(side))
    if price is None:
        return None
    increment = _first_positive_decimal(
        product_metadata,
        ("price_increment", "quote_increment"),
    )
    if increment is None:
        return price
    return _quantize_decimal_to_increment(
        price,
        increment,
        direction="down" if side.upper() == "BUY" else "up",
    )


def _futures_price_fields_for_side(side: str) -> tuple[str, ...]:
    """Return metadata price fields for a Futures limit order side."""

    return (
        ("best_bid", "mid_price", "price", "best_ask")
        if side.upper() == "BUY"
        else ("best_ask", "mid_price", "price", "best_bid")
    )


def _first_positive_decimal(
    source: Mapping[str, Any],
    fields: Sequence[str],
) -> Decimal | None:
    """Return the first positive Decimal found in mapped fields."""

    for field in fields:
        value = _decimal_value_or_none(source.get(field))
        if value is not None and value > 0:
            return value
    return None


def _decimal_value_or_none(value: Any) -> Decimal | None:
    """Return Decimal for a numeric value, otherwise None."""

    try:
        number = Decimal(str(value).strip())
    except Exception:
        return None
    return number


def _quantize_decimal_to_increment(
    value: Decimal,
    increment: Decimal,
    *,
    direction: str,
) -> Decimal:
    """Quantize a Decimal value to a positive increment."""

    if increment <= 0:
        return value
    rounding = ROUND_DOWN if direction == "down" else ROUND_UP
    ticks = (value / increment).to_integral_value(rounding=rounding)
    return ticks * increment


def futures_contract_size_for_product(
    product_id: object,
    product_metadata: Mapping[str, Any] | None = None,
) -> Decimal:
    """Return backend-owned contract size for Futures notional calculations."""

    metadata = _object_to_dict(product_metadata)
    future_details = _object_to_dict(metadata.get("future_product_details"))
    for raw_value in (
        future_details.get("contract_size"),
        metadata.get("contract_size"),
    ):
        contract_size = _decimal_value(raw_value, Decimal("0"))
        if contract_size > 0:
            return contract_size

    symbol = str(product_id or "").split("-", 1)[0].upper()
    configured = FUTURES_CDE_CONTRACT_SIZE_BY_SYMBOL.get(symbol)
    if configured is not None:
        return Decimal(configured)
    return Decimal("1")


def futures_place_notional_usdc(
    body: Mapping[str, Any],
    product_metadata: Mapping[str, Any] | None = None,
) -> Decimal:
    """Return Futures order notional as contracts times price times contract size."""

    size = _decimal_value(
        body.get("size", body.get("number_of_contracts")),
        Decimal("0"),
    )
    limit_price = _decimal_value(body.get("limit_price"), Decimal("0"))
    contract_size = futures_contract_size_for_product(
        body.get("product_id"),
        product_metadata,
    )
    return size * limit_price * contract_size


def _futures_place_notional(body: Mapping[str, Any]) -> Decimal:
    return futures_place_notional_usdc(body)


def _futures_live_place_requested(command: str, body: Mapping[str, Any]) -> bool:
    execution_mode = str(body.get("execution_mode") or "").strip().lower()
    live_mode_requested = execution_mode == "live" or body.get("dry_run") is False
    return (
        command == "futures_place"
        and live_mode_requested
        and _futures_live_acknowledged(body)
    )


def _futures_live_cancel_requested(command: str, body: Mapping[str, Any]) -> bool:
    execution_mode = str(body.get("execution_mode") or "").strip().lower()
    live_mode_requested = execution_mode == "live" or body.get("dry_run") is False
    return (
        command == "futures_cancel"
        and live_mode_requested
        and _futures_live_acknowledged(body)
    )


def _futures_live_close_reduce_requested(command: str, body: Mapping[str, Any]) -> bool:
    execution_mode = str(body.get("execution_mode") or "").strip().lower()
    live_mode_requested = execution_mode == "live" or body.get("dry_run") is False
    return (
        command == "futures_close_reduce"
        and live_mode_requested
        and _futures_live_acknowledged(body)
    )


def _futures_live_acknowledged(body: Mapping[str, Any]) -> bool:
    value = body.get(
        "futures_live_acknowledgement",
        body.get(
            "live_execution_acknowledgement",
            body.get("manual_live_acknowledgement"),
        ),
    )
    if isinstance(value, str):
        return value.strip().lower() in TRUTHY_ENV_VALUES
    return bool(value)


def _futures_client_order_id(
    body: Mapping[str, Any],
    context: AdminMvpRequestContext,
) -> str:
    return str(body.get("client_order_id") or context.idempotency_key)


def _futures_close_reduce_product_id(
    identity_value: str,
    body: Mapping[str, Any],
) -> str:
    position_key = str(body.get("position_key") or identity_value or "").strip()
    prefix = "futures_position:runtime:"
    if position_key.startswith(prefix):
        return position_key.removeprefix(prefix)
    if position_key in FUTURES_CONFIGURED_PRODUCT_SCOPE:
        return position_key
    return str(body.get("product_id") or "").strip()


def _futures_place_order_configuration(body: Mapping[str, Any]) -> dict[str, Any]:
    inner = {
        "base_size": str(body.get("size") or body.get("number_of_contracts") or ""),
        "limit_price": str(body.get("limit_price") or ""),
        "post_only": bool(body.get("post_only", False)),
    }
    return {"limit_limit_gtc": {key: value for key, value in inner.items() if value != ""}}


def _futures_create_order_kwargs(body: Mapping[str, Any]) -> dict[str, str]:
    optional_fields = ("leverage", "margin_type", "retail_portfolio_id")
    return {
        field: str(body[field])
        for field in optional_fields
        if str(body.get(field) or "").strip()
    }


def _futures_close_position_kwargs(body: Mapping[str, Any]) -> dict[str, str]:
    size = str(body.get("size") or body.get("number_of_contracts") or "").strip()
    return {"size": size} if size else {}


def _wallet_inventory_failure(
    cap_guard: Mapping[str, Any] | None,
    notional: Decimal,
) -> dict[str, str] | None:
    if cap_guard is None:
        return {
            "failure_stage": "known_inventory_required",
            "message": "Backend wallet/inventory evidence is required before Coinbase execution.",
        }
    if bool(cap_guard.get("wallet_check_required", True)) is False:
        return None
    wallet_status = str(
        cap_guard.get("wallet_check_status") or AdminMvpGateStatus.BLOCKED.value
    )
    if wallet_status != AdminMvpGateStatus.PASSED.value:
        return {
            "failure_stage": "known_inventory_required",
            "message": "Backend wallet/inventory check has not passed.",
        }
    wallet_available = _decimal_value(
        cap_guard.get("wallet_available_notional_usdc"),
        DEFAULT_WALLET_AVAILABLE_NOTIONAL_USDC,
    )
    if notional > wallet_available:
        return {
            "failure_stage": "known_inventory_required",
            "message": "Manual order notional exceeds backend wallet/inventory evidence.",
        }
    return None


def _manual_order_configuration(body: Mapping[str, Any]) -> dict[str, Any]:
    order_type = str(body.get("order_type") or "MARKET").upper()
    if order_type == "LIMIT":
        time_in_force = str(body.get("time_in_force") or "").upper()
        if time_in_force in {"IOC", "IMMEDIATE_OR_CANCEL"}:
            inner = {
                "base_size": str(body.get("base_size") or ""),
                "quote_size": str(body.get("quote_size") or ""),
                "limit_price": str(body.get("limit_price") or ""),
            }
            return {
                "sor_limit_ioc": {
                    key: value for key, value in inner.items() if value != ""
                }
            }
        inner = {
            "base_size": str(body.get("base_size") or ""),
            "limit_price": str(body.get("limit_price") or ""),
            "post_only": bool(body.get("post_only", False)),
        }
        return {"limit_limit_gtc": {key: value for key, value in inner.items() if value != ""}}
    inner: dict[str, str] = {}
    if body.get("base_size"):
        inner["base_size"] = str(body["base_size"])
    if body.get("quote_size"):
        inner["quote_size"] = str(body["quote_size"])
    return {"market_market_ioc": inner}


def _manual_live_acknowledged(body: Mapping[str, Any]) -> bool:
    value = body.get("manual_live_acknowledgement", body.get("manual_live_acknowledged"))
    if isinstance(value, str):
        return value.strip().lower() in TRUTHY_ENV_VALUES
    return bool(value)


def _coinbase_create_order_succeeded(result_data: Mapping[str, Any]) -> bool:
    success = result_data.get("success")
    if success is None:
        return True
    if isinstance(success, str):
        return success.strip().lower() in TRUTHY_ENV_VALUES
    return bool(success)


def _coinbase_order_id_from_create_order_result(result_data: Mapping[str, Any]) -> str:
    success_response = result_data.get("success_response")
    success_data = (
        dict(success_response)
        if isinstance(success_response, Mapping)
        else _object_to_dict(success_response)
    )
    return str(success_data.get("order_id") or result_data.get("order_id") or "")


def _coinbase_create_order_error_message(result_data: Mapping[str, Any]) -> str:
    error_response = result_data.get("error_response")
    error_data = (
        dict(error_response)
        if isinstance(error_response, Mapping)
        else _object_to_dict(error_response)
    )
    details = [
        str(error_data.get(key) or "").strip()
        for key in ("message", "error_details", "error")
        if str(error_data.get(key) or "").strip()
    ]
    if details:
        return "; ".join(details)
    return "Coinbase returned success=false."


def _coinbase_cancel_orders_result_data(result: Any) -> dict[str, Any]:
    if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
        return {"results": [_object_to_dict(item) for item in result]}
    return _object_to_dict(result)


def _cancel_futures_order_by_client_order_id(
    rest_client: Any,
    *,
    client_order_id: str,
) -> dict[str, Any]:
    initial_result = rest_client.cancel_orders(order_ids=[client_order_id])
    initial_data = _coinbase_cancel_orders_result_data(initial_result)
    initial_succeeded = _coinbase_cancel_order_succeeded(initial_data)
    if initial_succeeded:
        return {
            "cancel_result": initial_data,
            "identity_used": "client_order_id",
            "operator_identity_key": "client_order_id",
            "initial_identity_used": "client_order_id",
            "initial_cancel_result": initial_data,
            "initial_cancel_succeeded": True,
            "fallback_attempted": False,
            "fallback_reason": None,
            "fallback_identity_used": None,
            "order_read_attempted": False,
            "order_read_succeeded": False,
            "exchange_order_id": None,
        }

    order_read = _read_open_coinbase_order_by_client_order_id(
        rest_client,
        client_order_id=client_order_id,
    )
    exchange_order_id = _coinbase_exchange_order_id(order_read.get("order"))
    if not exchange_order_id or exchange_order_id == client_order_id:
        return {
            "cancel_result": initial_data,
            "identity_used": "client_order_id",
            "operator_identity_key": "client_order_id",
            "initial_identity_used": "client_order_id",
            "initial_cancel_result": initial_data,
            "initial_cancel_succeeded": False,
            "fallback_attempted": False,
            "fallback_reason": "client_order_id_cancel_not_accepted",
            "fallback_identity_used": None,
            "order_read_attempted": bool(order_read.get("attempted")),
            "order_read_succeeded": bool(order_read.get("succeeded")),
            "exchange_order_id": exchange_order_id or None,
        }

    fallback_result = rest_client.cancel_orders(order_ids=[exchange_order_id])
    return {
        "cancel_result": _coinbase_cancel_orders_result_data(fallback_result),
        "identity_used": "exchange_order_id",
        "operator_identity_key": "client_order_id",
        "initial_identity_used": "client_order_id",
        "initial_cancel_result": initial_data,
        "initial_cancel_succeeded": False,
        "fallback_attempted": True,
        "fallback_reason": "client_order_id_cancel_not_accepted",
        "fallback_identity_used": "exchange_order_id",
        "order_read_attempted": bool(order_read.get("attempted")),
        "order_read_succeeded": bool(order_read.get("succeeded")),
        "exchange_order_id": exchange_order_id,
    }


def _read_open_coinbase_order_by_client_order_id(
    rest_client: Any,
    *,
    client_order_id: str,
) -> dict[str, Any]:
    list_orders = getattr(rest_client, "list_orders", None)
    if not callable(list_orders):
        return {"attempted": False, "succeeded": False, "order": None}
    try:
        response = list_orders(order_status=["OPEN"])
    except Exception:
        return {"attempted": True, "succeeded": False, "order": None}
    order = _find_coinbase_order_by_client_order_id(
        _coinbase_order_records(response),
        client_order_id,
    )
    return {"attempted": True, "succeeded": True, "order": order}


def _coinbase_order_records(response: Any) -> list[dict[str, Any]]:
    data = _object_to_dict(response)
    orders = data.get("orders")
    if not isinstance(orders, Sequence) or isinstance(orders, (str, bytes, bytearray)):
        return []
    return [_object_to_dict(order) for order in orders]


def _find_coinbase_order_by_client_order_id(
    orders: Sequence[Mapping[str, Any]],
    client_order_id: str,
) -> dict[str, Any] | None:
    for order in orders:
        if str(order.get("client_order_id") or "").strip() == client_order_id:
            return dict(order)
    return None


def _coinbase_exchange_order_id(order: Any) -> str:
    data = _mapping(order)
    return str(
        data.get("order_id")
        or data.get("exchange_order_id")
        or data.get("coinbase_order_id")
        or ""
    ).strip()


def _coinbase_cancel_order_succeeded(result_data: Mapping[str, Any]) -> bool:
    success = result_data.get("success")
    if success is not None:
        return _truthy_value(success)
    results = result_data.get("results")
    if isinstance(results, Sequence) and not isinstance(results, (str, bytes, bytearray)):
        if not results:
            return False
        return all(_coinbase_cancel_result_item_succeeded(item) for item in results)
    return bool(result_data)


def _coinbase_cancel_result_item_succeeded(item: Any) -> bool:
    item_data = item if isinstance(item, Mapping) else _object_to_dict(item)
    success = item_data.get("success") if isinstance(item_data, Mapping) else None
    if success is None:
        return bool(item_data)
    return _truthy_value(success)


def _coinbase_cancel_order_error_message(result_data: Mapping[str, Any]) -> str:
    error_response = result_data.get("error_response")
    error_data = (
        dict(error_response)
        if isinstance(error_response, Mapping)
        else _object_to_dict(error_response)
    )
    details = [
        str(error_data.get(key) or "").strip()
        for key in ("message", "error_details", "error")
        if str(error_data.get(key) or "").strip()
    ]
    results = result_data.get("results")
    if not details and isinstance(results, Sequence):
        for item in results:
            item_data = item if isinstance(item, Mapping) else _object_to_dict(item)
            if not isinstance(item_data, Mapping):
                continue
            details.extend(
                str(item_data.get(key) or "").strip()
                for key in ("failure_reason", "message", "error")
                if str(item_data.get(key) or "").strip()
            )
    if details:
        return "; ".join(details)
    return "Coinbase returned cancel success=false."


def _truthy_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in TRUTHY_ENV_VALUES
    return bool(value)


def _object_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    converter = getattr(value, "to_dict", None)
    if callable(converter):
        converted = converter()
        return dict(converted) if isinstance(converted, Mapping) else {}
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _admin_product_scope(query: Mapping[str, Any]) -> list[str]:
    requested = _query_values(query, "product_id")
    if requested:
        return list(dict.fromkeys(requested))
    return list(dict.fromkeys([*DEFAULT_SPOT_PRODUCT_SCOPE, *FUTURES_CONFIGURED_PRODUCT_SCOPE]))


def _admin_products_status(ready_count: int, missing_count: int) -> str:
    if ready_count <= 0:
        return "blocked"
    if missing_count > 0:
        return "warning"
    return "ready"


def _admin_product_metadata_row(
    product_id: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    product_type = _admin_product_type(metadata, product_id)
    future_details = _mapping(metadata.get("future_product_details"))
    return {
        "product_id": str(metadata.get("product_id") or product_id),
        "product_type": product_type,
        "product_family": _admin_product_family(product_type, product_id),
        "base_currency": _optional_text(metadata.get("base_currency")),
        "quote_currency": _optional_text(metadata.get("quote_currency")),
        "base_increment": _optional_text(metadata.get("base_increment")),
        "quote_increment": _optional_text(metadata.get("quote_increment")),
        "price_increment": _optional_text(metadata.get("price_increment")),
        "base_min_size": _optional_text(metadata.get("base_min_size")),
        "quote_min_size": _optional_text(metadata.get("quote_min_size")),
        "display_name": _optional_text(metadata.get("display_name")),
        "status": _optional_text(metadata.get("status")),
        "mid_price": _optional_text(metadata.get("mid_price") or metadata.get("price")),
        "trading_disabled": bool(metadata.get("trading_disabled", False)),
        "contract_size": _optional_text(
            metadata.get("contract_size") or future_details.get("contract_size")
        ),
        "expiry": _optional_text(metadata.get("expiry")),
        "source": BACKEND_REST_CLIENT_SOURCE,
        "read_status": "ready",
        "read_error": None,
        "backend_owned": True,
        "read_only": True,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward",
        "live_coinbase_orders_ran": False,
    }


def _blocked_admin_product_row(product_id: str, read_error: str) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "product_type": "UNKNOWN",
        "product_family": "unknown",
        "base_currency": None,
        "quote_currency": None,
        "base_increment": None,
        "quote_increment": None,
        "price_increment": None,
        "base_min_size": None,
        "quote_min_size": None,
        "display_name": None,
        "status": None,
        "mid_price": None,
        "trading_disabled": False,
        "contract_size": None,
        "expiry": None,
        "source": (
            BACKEND_REST_CLIENT_SOURCE
            if read_error == "product_metadata_missing"
            else "backend_rest_unavailable"
        ),
        "read_status": "blocked",
        "read_error": read_error,
        "backend_owned": True,
        "read_only": True,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward",
        "live_coinbase_orders_ran": False,
    }


def _admin_product_type(metadata: Mapping[str, Any], product_id: str) -> str:
    product_type = str(metadata.get("product_type") or metadata.get("type") or "").upper()
    if product_type in {"SPOT", "FUTURE", "PERPETUAL_FUTURE"}:
        return product_type
    if product_id.endswith("-CDE"):
        return "FUTURE"
    return "UNKNOWN"


def _admin_product_family(product_type: str, product_id: str) -> str:
    if product_type == "SPOT":
        return "spot"
    if product_type in {"FUTURE", "PERPETUAL_FUTURE"} or product_id.endswith("-CDE"):
        return "futures_perpetuals"
    return "unknown"


def _write_admin_products_json(
    product_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    products_path = _admin_products_json_path()
    existing = _read_products_json(products_path)
    document = _admin_products_json_document(product_rows, existing)
    products_path.parent.mkdir(parents=True, exist_ok=True)
    products_path.write_text(
        json.dumps(document, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return document


def _admin_products_json_path() -> Path:
    configured = os.environ.get(PRODUCTS_JSON_PATH_ENV, "").strip()
    return Path(configured) if configured else DEFAULT_PRODUCTS_JSON_PATH


def _read_products_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


def _admin_products_json_document(
    product_rows: Sequence[Mapping[str, Any]],
    existing: Mapping[str, Any],
) -> dict[str, Any]:
    ready_rows = [row for row in product_rows if row.get("read_status") == "ready"]
    spot = sorted(
        str(row["product_id"])
        for row in ready_rows
        if row.get("product_family") == "spot"
    )
    derivatives = sorted(
        str(row["product_id"])
        for row in ready_rows
        if row.get("product_family") == "futures_perpetuals"
    )
    document: dict[str, Any] = {
        "spot": spot,
        "derivatives": derivatives,
    }
    ticker_to_trading = existing.get("ticker_to_trading")
    if isinstance(ticker_to_trading, Mapping):
        document["ticker_to_trading"] = dict(ticker_to_trading)
    document["metadata"] = {
        str(row["product_id"]): _admin_products_json_metadata(row)
        for row in ready_rows
    }
    return document


def _admin_products_json_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": row.get("product_type") or "UNKNOWN",
        "base_currency": row.get("base_currency"),
        "quote_currency": row.get("quote_currency"),
        "base_increment": str(row.get("base_increment") or ""),
        "quote_increment": str(row.get("quote_increment") or ""),
        "price_increment": str(row.get("price_increment") or ""),
        "base_min_size": str(row.get("base_min_size") or ""),
        "quote_min_size": str(row.get("quote_min_size") or ""),
        "display_name": row.get("display_name"),
        "status": row.get("status"),
        "mid_price": row.get("mid_price"),
        "trading_disabled": bool(row.get("trading_disabled", False)),
        "contract_size": row.get("contract_size"),
        "expiry": row.get("expiry"),
    }


def _admin_fee_evidence_snapshot(
    summary: Any,
    *,
    summary_read: bool,
    read_error: str | None,
) -> dict[str, Any]:
    data = _mapping(summary)
    if not summary_read or read_error is not None:
        return _blocked_admin_fee_evidence(read_error or "transaction_summary_unavailable")

    fee_tier = _admin_fee_tier(
        data,
        tier_key="fee_tier",
        source="coinbase_transaction_summary.fee_tier",
    )
    futures_tier = _admin_fee_tier(
        data,
        tier_key="perpetuals_fee_tier",
        source="coinbase_transaction_summary.perpetuals_fee_tier",
    )
    if futures_tier["status"] != "ready":
        futures_tier = {**fee_tier, "source": fee_tier["source"]}
    status = "ready" if fee_tier["status"] == "ready" else "blocked"
    return {
        "status": status,
        "source": BACKEND_REST_CLIENT_SOURCE if status == "ready" else "backend_rest_unavailable",
        "fee_tier": fee_tier,
        "spot_fee_input": _spot_fee_input(fee_tier),
        "futures_fee_input": _futures_fee_input(futures_tier),
        "volume_30day": _admin_fee_money(data.get("volume_30day")),
        "perpetuals_volume_30day": _admin_fee_money(data.get("perpetuals_volume_30day")),
        "stablecoin_conversions_enabled": bool(data.get("stablecoin_conversions_enabled", False)),
    }


def _blocked_admin_fee_evidence(read_error: str) -> dict[str, Any]:
    fee_tier = _blocked_admin_fee_tier(read_error)
    return {
        "status": "blocked",
        "source": "backend_rest_unavailable",
        "fee_tier": fee_tier,
        "spot_fee_input": _spot_fee_input(fee_tier),
        "futures_fee_input": _futures_fee_input(fee_tier),
        "volume_30day": _admin_fee_money(None),
        "perpetuals_volume_30day": _admin_fee_money(None),
        "stablecoin_conversions_enabled": False,
    }


def _admin_fee_tier(
    summary: Mapping[str, Any],
    *,
    tier_key: str,
    source: str,
) -> dict[str, Any]:
    tier = _mapping(summary.get(tier_key))
    source_data = tier if tier else summary
    maker_fee_rate = _optional_text(source_data.get("maker_fee_rate"))
    taker_fee_rate = _optional_text(source_data.get("taker_fee_rate"))
    if not maker_fee_rate or not taker_fee_rate:
        return _blocked_admin_fee_tier(f"{tier_key}_rate_missing")
    return {
        "status": "ready",
        "source": source,
        "name": _optional_text(source_data.get("name")),
        "pricing_tier": _optional_text(source_data.get("pricing_tier")),
        "maker_fee_rate": maker_fee_rate,
        "taker_fee_rate": taker_fee_rate,
        "read_error": "none",
        "backend_owned": True,
        "read_only": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    }


def _blocked_admin_fee_tier(read_error: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "source": "backend_rest_unavailable",
        "name": None,
        "pricing_tier": None,
        "maker_fee_rate": None,
        "taker_fee_rate": None,
        "read_error": read_error,
        "backend_owned": True,
        "read_only": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    }


def _spot_fee_input(fee_tier: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": fee_tier["status"],
        "source": fee_tier["source"],
        "maker_fee_rate": fee_tier.get("maker_fee_rate"),
        "taker_fee_rate": fee_tier.get("taker_fee_rate"),
        "post_only_rate_source": "maker_fee_rate",
        "non_post_only_rate_source": "taker_fee_rate",
        "first_blocker": "none" if fee_tier["status"] == "ready" else fee_tier["read_error"],
        "backend_owned": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    }


def _futures_fee_input(fee_tier: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": fee_tier["status"],
        "source": fee_tier["source"],
        "account_family": FUTURES_ACCOUNT_FAMILY_US_CFM,
        "intx_applicability": FUTURES_INTX_APPLICABILITY_US_ACCOUNT,
        "maker_fee_rate": fee_tier.get("maker_fee_rate"),
        "taker_fee_rate": fee_tier.get("taker_fee_rate"),
        "first_blocker": "none" if fee_tier["status"] == "ready" else fee_tier["read_error"],
        "backend_owned": True,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
    }


def _admin_fee_money(value: Any) -> dict[str, str]:
    data = _mapping(value)
    return {
        "value": str(data.get("value") or "0"),
        "currency": str(data.get("currency") or "USD"),
    }


def _unavailable_account_snapshot(generated_at: str) -> dict[str, Any]:
    readiness = {
        "spot_account_ready": False,
        "spot_wallet_inventory_ready": False,
        "futures_account_scope_ready": False,
        "futures_observed_position_scope_ready": False,
        "futures_margin_collateral_ready": False,
        "usable_for_spot_admission": False,
        "usable_for_futures_risk": False,
    }
    return {
        "account_reality": {
            "status": "unavailable",
            "source": "backend_rest_unavailable",
            "proof_id": f"account-reality-{generated_at}",
            "generated_at": generated_at,
            "coinbase_read_ran": False,
            "read_error": "rest_client_unavailable",
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        },
        "account_scope": {
            "scope_type": "local_admin_portfolio",
            "scope_id": "local-admin-account-scope",
            "source": "backend_admin_mvp",
            "freshness_status": LOCAL_DEFAULT_FRESHNESS,
            "account_count": 0,
            "configured_product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
            "observed_position_scope": [],
        },
        "portfolio_scope": {
            "portfolio_id": "local-admin-portfolio",
            "portfolio_name": "Local Admin Portfolio",
            "source": "backend_admin_mvp",
            "freshness_status": LOCAL_DEFAULT_FRESHNESS,
        },
        "wallet_inventory": {
            "currency": "USDC",
            "available_notional_usdc": "0",
            "hold_notional_usdc": "0",
            "total_notional_usdc": "0",
            "source": "backend_admin_mvp_default",
            "freshness_status": LOCAL_DEFAULT_FRESHNESS,
            "status": "visible",
            "error": "not_applicable",
        },
        "wallets": [],
        "readiness": readiness,
        "futures_positions": [],
        "futures_margin_collateral": _blocked_futures_margin_collateral(
            "rest_client_unavailable",
            "US Coinbase Futures CFM margin/collateral snapshot is unavailable because the REST client is not configured.",
        ),
        "coinbase_read_enabled": False,
        "coinbase_read_ran": False,
    }


def _spot_admission_input_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    readiness = _mapping(snapshot.get("readiness"))
    wallet_inventory = _mapping(snapshot.get("wallet_inventory"))
    account_reality = _mapping(snapshot.get("account_reality"))
    spot_wallet_ready = bool(readiness.get("spot_wallet_inventory_ready"))
    return {
        "status": "ready" if spot_wallet_ready else "blocked",
        "wallet_check_source": ACCOUNT_SNAPSHOT_WALLET_SOURCE,
        "currency": str(wallet_inventory.get("currency") or "USDC"),
        "available_notional_usdc": str(wallet_inventory.get("available_notional_usdc") or "0"),
        "proof_id": str(account_reality.get("proof_id") or "account-reality-unavailable"),
        "first_blocker": (
            "none"
            if spot_wallet_ready
            else str(wallet_inventory.get("quote_wallet_error") or "spot_wallet_inventory_ready")
        ),
    }


def _spot_readiness_status(snapshot: Mapping[str, Any]) -> str:
    readiness = _mapping(snapshot.get("readiness"))
    account_reality = _mapping(snapshot.get("account_reality"))
    if bool(readiness.get("usable_for_spot_admission")):
        return "ready"
    if account_reality.get("status") == "unavailable":
        return "blocked"
    return "warning"


def _spot_readiness_planned_budget() -> dict[str, str]:
    return {}


def _spot_readiness_wallet_snapshot(
    snapshot: Mapping[str, Any],
    spot_admission_input: Mapping[str, Any],
) -> dict[str, Any]:
    wallet_inventory = dict(_mapping(snapshot.get("wallet_inventory")))
    return {
        **wallet_inventory,
        "available": spot_admission_input.get("status") == "ready",
        "reason": spot_admission_input.get("first_blocker"),
        "proof_id": spot_admission_input.get("proof_id"),
        "backend_owned": True,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward",
    }


def _spot_readiness_products(
    product_rows: Sequence[Mapping[str, Any]],
    snapshot: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [_spot_readiness_product(product_row, snapshot) for product_row in product_rows]


def _spot_readiness_product(
    product_row: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    readiness = _mapping(snapshot.get("readiness"))
    wallet_inventory = _mapping(snapshot.get("wallet_inventory"))
    product_id = str(product_row.get("product_id") or "")
    quote_currency = str(
        product_row.get("quote_currency")
        or _product_quote_currency(product_id, str(wallet_inventory.get("currency") or "USDC"))
    )
    quote_supported = quote_currency in SPOT_ADMISSION_QUOTE_CURRENCIES
    wallet_ready = bool(readiness.get("spot_wallet_inventory_ready")) and quote_supported
    product_capability = _spot_product_capability_contract(
        product_row,
        quote_supported,
    )
    return {
        "product_id": product_id,
        "product_type": product_row.get("product_type"),
        "product_family": product_row.get("product_family"),
        "quote_currency": quote_currency,
        "base_currency": product_row.get("base_currency"),
        "base_increment": product_row.get("base_increment"),
        "quote_increment": product_row.get("quote_increment"),
        "price_increment": product_row.get("price_increment"),
        "base_min_size": product_row.get("base_min_size"),
        "quote_min_size": product_row.get("quote_min_size"),
        "display_name": product_row.get("display_name"),
        "trading_disabled": bool(product_row.get("trading_disabled", False)),
        "product_read_status": product_row.get("read_status"),
        "product_read_error": product_row.get("read_error"),
        "product_metadata_source": product_row.get("source"),
        "capabilities": {
            "wallet_inventory": {
                "mode": "enabled" if wallet_ready else "blocked",
                "source": ACCOUNT_SNAPSHOT_WALLET_SOURCE,
                "required": True,
                "detail": (
                    "Backend wallet inventory can be used for this quote currency."
                    if wallet_ready
                    else "Backend wallet inventory is not ready for this quote currency."
                ),
            },
            "spot_admission_input": {
                "mode": (
                    "enabled"
                    if bool(readiness.get("usable_for_spot_admission")) and quote_supported
                    else "blocked"
                ),
                "source": ACCOUNT_SNAPSHOT_WALLET_SOURCE,
                "required": True,
                "detail": "Backend account snapshot is the wallet input for Spot admission.",
            },
            "product_capability_contract": product_capability,
        },
        "inventory": {
            "imported_baselines": {
                "configured": False,
                "known_quantity": "0",
                "unknown_cost_basis_quantity": "0",
                "lots": [],
            },
        },
        "backend_owned": True,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward",
    }


def _spot_product_capability_contract(
    product_row: Mapping[str, Any],
    quote_supported: bool,
) -> dict[str, Any]:
    read_status = str(product_row.get("read_status") or "blocked")
    read_error = str(product_row.get("read_error") or "none")
    product_family = str(product_row.get("product_family") or "unknown")
    source = str(product_row.get("source") or "backend_rest_unavailable")
    trading_disabled = bool(product_row.get("trading_disabled", False))
    enabled = (
        read_status == "ready"
        and product_family == "spot"
        and quote_supported
        and not trading_disabled
    )
    if enabled:
        detail = "Backend Coinbase product metadata is ready for this Spot quote scope."
    elif read_status != "ready":
        detail = f"Backend Coinbase product metadata is blocked: {read_error}."
    elif product_family != "spot":
        detail = "Backend product metadata is not a Spot product."
    elif not quote_supported:
        detail = "Backend product metadata quote currency is not supported for Spot admission."
    else:
        detail = "Backend product metadata reports trading disabled for this product."
    return {
        "mode": "enabled" if enabled else "blocked",
        "source": source,
        "required": True,
        "detail": detail,
        "read_status": read_status,
        "read_error": None if read_error == "none" else read_error,
        "product_family": product_family,
        "backend_owned": True,
        "browser_authority": "display_only",
        "bff_authority": "read_only_forward",
    }


def _spot_readiness_guard_summary(
    snapshot: Mapping[str, Any],
    products: list[dict[str, Any]],
    spot_admission_input: Mapping[str, Any],
) -> list[dict[str, Any]]:
    readiness = _mapping(snapshot.get("readiness"))
    account_reality = _mapping(snapshot.get("account_reality"))
    wallet_inventory = _mapping(snapshot.get("wallet_inventory"))
    product_scope_detail = (
        f"{len(products)} requested product scope row(s) are visible."
        if products
        else "No product_id filter was supplied; product capability checks remain backend pending."
    )
    product_contract = _spot_readiness_product_contract_summary(products)
    return [
        {
            "condition": "backend_account_reality",
            "label": "Backend account reality",
            "mode": "enabled" if account_reality.get("status") == "ready" else "blocked",
            "reason": str(account_reality.get("read_error") or "none"),
            "source": str(account_reality.get("source") or "backend_rest_unavailable"),
            "backend_owned": True,
        },
        {
            "condition": "spot_wallet_inventory",
            "label": "Spot wallet inventory",
            "mode": "enabled" if bool(readiness.get("spot_wallet_inventory_ready")) else "blocked",
            "reason": (
                f"{wallet_inventory.get('currency', 'USDC')} available "
                f"{wallet_inventory.get('available_notional_usdc', '0')} USDC"
            ),
            "source": ACCOUNT_SNAPSHOT_WALLET_SOURCE,
            "backend_owned": True,
        },
        {
            "condition": "spot_admission_input",
            "label": "Spot admission input",
            "mode": "enabled" if spot_admission_input.get("status") == "ready" else "blocked",
            "reason": str(spot_admission_input.get("first_blocker") or "none"),
            "source": ACCOUNT_SNAPSHOT_WALLET_SOURCE,
            "backend_owned": True,
        },
        {
            "condition": "product_capability_contract",
            "label": "Product capability contract",
            "mode": product_contract["mode"],
            "reason": product_contract["reason"] or product_scope_detail,
            "source": product_contract["source"],
            "backend_owned": True,
        },
    ]


def _spot_readiness_product_contract_summary(
    products: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    if not products:
        return {
            "mode": "pending",
            "reason": "No product_id filter was supplied; product capability checks remain backend pending.",
            "source": "coinbase_product_capability_contract_pending",
        }
    capability_rows = [
        _mapping(_mapping(product.get("capabilities")).get("product_capability_contract"))
        for product in products
    ]
    blocked_rows = [
        row
        for row in capability_rows
        if str(row.get("mode") or "blocked") != "enabled"
    ]
    if blocked_rows:
        first_blocker = blocked_rows[0]
        return {
            "mode": "blocked",
            "reason": str(first_blocker.get("detail") or "Backend product capability is blocked."),
            "source": str(first_blocker.get("source") or "backend_rest_unavailable"),
        }
    return {
        "mode": "enabled",
        "reason": f"{len(products)} requested product capability row(s) are backend-ready.",
        "source": BACKEND_REST_CLIENT_SOURCE,
    }


def _product_quote_currency(product_id: str, default_currency: str) -> str:
    if "-" not in product_id:
        return default_currency
    quote = product_id.rsplit("-", 1)[-1].strip().upper()
    return quote or default_currency


def _read_rest_object(rest_client: Any, method_name: str) -> tuple[Any, bool, str | None]:
    method = getattr(rest_client, method_name, None)
    if not callable(method):
        return None, False, f"{method_name}_unavailable"
    try:
        return method(), True, None
    except Exception as exc:  # pragma: no cover - defensive around live SDK failures
        return None, True, f"{method_name}_failed:{type(exc).__name__}"


def _normalize_wallets(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        candidates = value.values()
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    wallets: list[dict[str, Any]] = []
    for item in candidates:
        data = _object_to_dict(item)
        currency = str(data.get("currency") or "").upper()
        if not currency:
            continue
        wallets.append(
            {
                "currency": currency,
                "available_balance": _decimal_text(
                    _decimal_value(data.get("available_balance"), Decimal("0"))
                ),
                "total_balance": _decimal_text(
                    _decimal_value(data.get("total_balance"), Decimal("0"))
                ),
                "hold_balance": _decimal_text(
                    _wallet_hold_balance(data),
                ),
                "updated_at": data.get("updated_at"),
            }
        )
    return wallets


def _normalize_portfolios(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        candidates = value.get("portfolios") if isinstance(value.get("portfolios"), list) else value.values()
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    portfolios = []
    for item in candidates:
        data = _object_to_dict(item)
        portfolio_id = data.get("portfolio_id") or data.get("uuid") or data.get("id")
        if not portfolio_id:
            continue
        portfolios.append(
            {
                "portfolio_id": str(portfolio_id),
                "portfolio_name": str(data.get("name") or data.get("portfolio_name") or portfolio_id),
                "source": BACKEND_REST_CLIENT_SOURCE,
                "freshness_status": BACKEND_REST_FRESHNESS,
            }
        )
    return portfolios


def _normalize_futures_positions(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        candidates = value.values()
    elif isinstance(value, list):
        candidates = value
    else:
        candidates = []
    positions: list[dict[str, Any]] = []
    for item in candidates:
        data = _object_to_dict(item)
        product_id = str(data.get("product_id") or "")
        if not product_id:
            continue
        positions.append(
            {
                "position_key": f"futures_position:runtime:{product_id}",
                "product_id": product_id,
                "position_side": str(data.get("position_side") or data.get("side") or "UNKNOWN"),
                "number_of_contracts": str(data.get("number_of_contracts") or "0"),
                "current_price": str(data.get("current_price") or ""),
                "entry_price": str(data.get("entry_price") or ""),
                "raw_position": data,
                "source": "runtime_positions",
                "updated_at": data.get("updated_at"),
            }
        )
    return positions


def _futures_margin_collateral_from_cfm_snapshot(
    value: Any,
    read_error: str | None,
) -> dict[str, Any]:
    if read_error is not None:
        return _blocked_futures_margin_collateral(
            "futures_margin_collateral_read_failed",
            "US Coinbase Futures CFM margin/collateral snapshot could not be read.",
            {"read_error": read_error},
        )

    data = _object_to_dict(value)
    if not data:
        return _blocked_futures_margin_collateral(
            "futures_margin_collateral_missing",
            "US Coinbase Futures CFM margin/collateral snapshot returned no data.",
        )

    if str(data.get("status") or "").lower() == "blocked":
        return _blocked_futures_margin_collateral(
            _first_cfm_error_blocker(data),
            "US Coinbase Futures CFM balance summary is blocked by the Coinbase REST reader.",
            data,
        )

    balance_summary = _object_to_dict(data.get("balance_summary"))
    if not balance_summary:
        return _blocked_futures_margin_collateral(
            "futures_margin_collateral_missing_balance_summary",
            "US Coinbase Futures CFM balance summary is missing from the backend snapshot.",
            data,
        )

    available_margin = _money_field(balance_summary, "available_margin")
    if available_margin is None:
        return _blocked_futures_margin_collateral(
            "futures_available_margin_missing",
            "US Coinbase Futures CFM available margin is missing from the balance summary.",
            data,
        )

    currency = available_margin["currency"]
    total_usd_balance = _money_field(balance_summary, "total_usd_balance", currency)
    cfm_usd_balance = _money_field(balance_summary, "cfm_usd_balance", currency)
    futures_buying_power = _money_field(balance_summary, "futures_buying_power", currency)
    initial_margin = _money_field(balance_summary, "initial_margin", currency)
    liquidation_threshold = _money_field(balance_summary, "liquidation_threshold", currency)
    margin_window_measure = _active_cfm_margin_window_measure(balance_summary)
    maintenance_margin = _decimal_text(
        _decimal_value(margin_window_measure.get("maintenance_margin"), Decimal("0"))
    )
    liquidation_buffer = _decimal_text(
        _decimal_value(margin_window_measure.get("liquidation_buffer"), Decimal("0"))
    )
    margin_window_type = str(
        margin_window_measure.get("margin_window_type") or "FCM_MARGIN_WINDOW_TYPE_UNKNOWN"
    )
    account_family = str(data.get("account_family") or "coinbase_futures_us_cfm")
    intx_applicability = str(data.get("intx_applicability") or "not_applicable_us_account")
    errors = data.get("errors") if isinstance(data.get("errors"), list) else []
    collateral_value = {
        "account_family": account_family,
        "collateral_source": "cfm_balance_summary",
        "available_margin": available_margin,
        "total_usd_balance": total_usd_balance,
        "cfm_usd_balance": cfm_usd_balance,
        "futures_buying_power": futures_buying_power,
        "intx_applicability": intx_applicability,
        "errors": errors,
    }
    margin_value = {
        "account_family": account_family,
        "margin_source": "cfm_balance_summary",
        "initial_margin": initial_margin,
        "maintenance_margin": {"value": maintenance_margin, "currency": currency},
        "liquidation_threshold": liquidation_threshold,
        "liquidation_buffer": {"value": liquidation_buffer, "currency": currency},
        "margin_window_type": margin_window_type,
        "intraday_margin_setting": _object_to_dict(data.get("intraday_margin_setting")),
        "current_margin_windows": data.get("current_margin_windows")
        if isinstance(data.get("current_margin_windows"), list)
        else [],
        "intx_applicability": intx_applicability,
        "errors": errors,
    }
    return {
        "status": "ready",
        "source": BACKEND_REST_CLIENT_SOURCE,
        "blocker": "none",
        "risk_input": {
            "status": "ready",
            "currency": currency,
            "available_notional_usdc": available_margin["value"],
            "first_blocker": "none",
        },
        "collateral": _futures_evidence_item(
            "collateral",
            "ready",
            BACKEND_REST_CLIENT_SOURCE,
            "US Coinbase Futures CFM balance summary is available for backend futures risk input.",
            collateral_value,
        ),
        "margin": _futures_evidence_item(
            "margin",
            "ready",
            BACKEND_REST_CLIENT_SOURCE,
            "US Coinbase Futures CFM margin summary is available for backend futures risk input.",
            margin_value,
        ),
    }


def _blocked_futures_margin_collateral(
    blocker: str,
    detail: str,
    raw_value: Any = None,
) -> dict[str, Any]:
    value = {
        "account_family": "coinbase_futures_us_cfm",
        "collateral_source": "cfm_balance_summary",
        "intx_applicability": "not_applicable_us_account",
        "blocker": blocker,
    }
    if raw_value is not None:
        value["raw_status"] = _object_to_dict(raw_value)
    return {
        "status": "blocked",
        "source": BACKEND_REST_CLIENT_SOURCE,
        "blocker": blocker,
        "risk_input": {
            "status": "blocked",
            "currency": "USD",
            "available_notional_usdc": "0",
            "first_blocker": blocker,
        },
        "collateral": _futures_evidence_item(
            "collateral",
            "blocked",
            BACKEND_REST_CLIENT_SOURCE,
            detail,
            value,
        ),
        "margin": _futures_evidence_item(
            "margin",
            "blocked",
            BACKEND_REST_CLIENT_SOURCE,
            detail,
            value,
        ),
    }


def _futures_evidence_item(
    name: str,
    status: str,
    source: str,
    detail: str,
    value: Any = None,
) -> dict[str, Any]:
    evidence = {
        "name": name,
        "status": status,
        "source": source,
        "detail": detail,
    }
    if value is not None:
        evidence["value"] = value
    return evidence


def _first_cfm_error_blocker(data: Mapping[str, Any]) -> str:
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        first = _object_to_dict(errors[0])
        method = str(first.get("method") or "futures_margin_collateral")
        return f"{method}_blocked"
    return "futures_margin_collateral_ready"


def _futures_resolved_contracts(
    snapshot: Mapping[str, Any],
    proofs: list[dict[str, Any]],
) -> list[str]:
    readiness = snapshot["readiness"]
    resolved: list[str] = []
    if bool(readiness["futures_account_scope_ready"]):
        resolved.append("futures_account_scope_contract")
    if bool(readiness["usable_for_futures_risk"]) and proofs:
        resolved.append("futures_margin_collateral_risk_proof")
    resolved.extend([
        "futures_reconciliation_contract",
        "futures_live_adapter_contract",
    ])
    return [contract for contract in FUTURES_COMMAND_CONTRACTS if contract in resolved]


def _futures_prerequisite_summaries(
    missing_contracts: list[str],
    account_ready: bool,
    risk_proof_ready: bool,
) -> list[dict[str, Any]]:
    rows = [
        (
            "futures_account_scope",
            account_ready,
            "/api/v1/futures/account",
            "Backend futures account and observed position scope evidence.",
        ),
        (
            "margin_collateral_risk_proof",
            risk_proof_ready,
            "/api/v1/futures/risk-proofs",
            "Backend-generated futures margin and collateral risk proof evidence.",
        ),
        (
            "audit_idempotency_replay_protection",
            True,
            "/api/v1/admin/admission-audits",
            "Backend admission audit and idempotency evidence route.",
        ),
        (
            "futures_reconciliation",
            "futures_reconciliation_contract" not in missing_contracts,
            "/api/v1/admin/reconciliation/plans",
            "Backend reconciliation plan evidence route.",
        ),
    ]
    return [
        {
            "prerequisite": name,
            "status": "ready" if ready else "blocked",
            "blocking": not ready,
            "resolved": ready,
            "evidence_route": route,
            "detail": detail,
            "backend_owned": True,
            "read_only": True,
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        }
        for name, ready, route, detail in rows
    ]


def _futures_request_fields_for_command(command: str) -> list[dict[str, Any]]:
    return [
        _futures_request_field_item(command, field_spec)
        for field_spec in FUTURES_COMMAND_REQUEST_FIELDS.get(command, ())
    ]


def _futures_request_payload_validation_record_semantics(
    command: str,
    identity_key: str,
    request_fields: Sequence[Mapping[str, Any]],
    margin_collateral: Mapping[str, Any],
    liquidation_evidence: Mapping[str, Any],
    reduce_close_evidence: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    rows = {
        semantic: []
        for semantic in (
            *FUTURES_ACCOUNT_SEMANTIC_ARTIFACTS,
            *FUTURES_POSITION_SEMANTIC_ARTIFACTS,
        )
    }
    field = _futures_funding_semantic_field(identity_key, request_fields)
    if field is None:
        return rows
    account_readiness = {
        "margin": _futures_margin_semantic_readiness(margin_collateral),
        "collateral": _futures_collateral_semantic_readiness(margin_collateral),
        "liquidation": _futures_liquidation_semantic_readiness(liquidation_evidence),
    }
    for semantic, readiness in account_readiness.items():
        rows[semantic].append(
            _futures_request_payload_validation_record_semantic(
                command,
                field,
                semantic,
                readiness,
            )
        )
    if command == "futures_close_reduce":
        for semantic in FUTURES_POSITION_SEMANTIC_ARTIFACTS:
            rows[semantic].append(
                _futures_request_payload_validation_record_semantic(
                    command,
                    field,
                    semantic,
                    _futures_reduce_close_semantic_readiness(
                        reduce_close_evidence,
                        semantic,
                    ),
                )
            )
    return rows


def _futures_margin_semantic_readiness(
    margin_collateral: Mapping[str, Any],
) -> dict[str, Any]:
    margin = _object_to_dict(margin_collateral.get("margin"))
    value = _object_to_dict(margin.get("value"))
    flags = {
        "margin_account_bound": _futures_us_cfm_account_bound(value),
        "margin_requirement_bound": (
            _futures_money_value_present(value, "initial_margin")
            and _futures_money_value_present(value, "maintenance_margin")
        ),
        "margin_mode_bound": bool(
            str(value.get("margin_window_type") or "").strip()
            or str(value.get("intraday_margin_setting") or "").strip()
            or value.get("current_margin_windows")
        ),
        "margin_buffer_bound": _futures_money_value_present(
            value,
            "liquidation_buffer",
        ),
    }
    return _futures_semantic_readiness(
        semantic="margin",
        runtime_observed=str(margin.get("status") or "") == "ready",
        flags=flags,
        missing_reason="backend_owned_margin_evidence_missing",
        detail_ready=(
            "backend-owned US CFM margin account, requirement, mode, and buffer "
            "evidence are bound"
        ),
        detail_blocked=(
            "backend-owned US CFM margin evidence must include account, "
            "requirement, mode, and buffer fields"
        ),
        required_evidence_refs=[
            "/api/v1/futures/account.margin",
            "/api/v1/futures/risk-proofs",
        ],
        evidence_routes=[
            "/api/v1/futures/account",
            "/api/v1/futures/risk-proofs",
        ],
    )


def _futures_collateral_semantic_readiness(
    margin_collateral: Mapping[str, Any],
) -> dict[str, Any]:
    collateral = _object_to_dict(margin_collateral.get("collateral"))
    value = _object_to_dict(collateral.get("value"))
    flags = {
        "collateral_balance_bound": (
            _futures_money_value_present(value, "cfm_usd_balance")
            or _futures_money_value_present(value, "total_usd_balance")
        ),
        "collateral_currency_bound": _futures_money_currency_present(
            value,
            ("cfm_usd_balance", "total_usd_balance", "available_margin"),
        ),
        "collateral_requirement_bound": (
            _futures_money_value_present(value, "available_margin")
            or _futures_money_value_present(value, "futures_buying_power")
        ),
        "collateral_source_bound": bool(
            str(value.get("collateral_source") or "").strip()
        ),
    }
    return _futures_semantic_readiness(
        semantic="collateral",
        runtime_observed=str(collateral.get("status") or "") == "ready",
        flags=flags,
        missing_reason="backend_owned_collateral_evidence_missing",
        detail_ready=(
            "backend-owned US CFM collateral balance, currency, requirement, "
            "and source evidence are bound"
        ),
        detail_blocked=(
            "backend-owned US CFM collateral evidence must include balance, "
            "currency, requirement, and source fields"
        ),
        required_evidence_refs=[
            "/api/v1/futures/account.collateral",
            "/api/v1/futures/risk-proofs",
        ],
        evidence_routes=[
            "/api/v1/futures/account",
            "/api/v1/futures/risk-proofs",
        ],
    )


def _futures_liquidation_semantic_readiness(
    liquidation_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    value = _object_to_dict(liquidation_evidence.get("value"))
    threshold_bound = bool(value.get("liquidation_threshold_present"))
    buffer_bound = bool(value.get("liquidation_buffer_present"))
    flags = {
        "liquidation_buffer_bound": buffer_bound,
        "liquidation_price_bound": threshold_bound,
        "liquidation_distance_bound": buffer_bound,
        "liquidation_threshold_bound": threshold_bound,
    }
    return _futures_semantic_readiness(
        semantic="liquidation",
        runtime_observed=str(liquidation_evidence.get("status") or "") == "ready",
        flags=flags,
        missing_reason="backend_owned_liquidation_evidence_missing",
        detail_ready=(
            "backend-owned US CFM liquidation threshold and buffer evidence are "
            "bound"
        ),
        detail_blocked=(
            "backend-owned US CFM liquidation evidence must include threshold "
            "and buffer fields"
        ),
        required_evidence_refs=[
            "/api/v1/futures/account.liquidation",
            "/api/v1/futures/risk-proofs",
        ],
        evidence_routes=[
            "/api/v1/futures/account",
            "/api/v1/futures/risk-proofs",
        ],
    )


def _futures_reduce_close_semantic_readiness(
    reduce_close_evidence: Mapping[str, Any],
    semantic: str,
) -> dict[str, Any]:
    value = _object_to_dict(reduce_close_evidence.get("value"))
    position_side_bound = _int_value(value.get("position_side_observed_count")) > 0
    position_size_bound = _int_value(value.get("position_size_observed_count")) > 0
    side_derivation_bound = bool(value.get("backend_derives_close_reduce_side"))
    flags = {
        f"{semantic}_flag_bound": side_derivation_bound,
        f"{semantic}_position_side_bound": position_side_bound,
        f"{semantic}_position_size_bound": position_size_bound,
        f"{semantic}_order_side_bound": side_derivation_bound,
    }
    return _futures_semantic_readiness(
        semantic=semantic,
        runtime_observed=str(reduce_close_evidence.get("status") or "") == "ready",
        flags=flags,
        missing_reason=f"backend_owned_{semantic}_evidence_missing",
        detail_ready=(
            "backend-owned Futures position side and size evidence are bound for "
            f"{semantic.replace('_', '-')} command semantics"
        ),
        detail_blocked=(
            "backend-owned Futures close/reduce evidence must include observed "
            f"position side, size, and derived order side for {semantic.replace('_', '-')}"
        ),
        required_evidence_refs=[
            "/api/v1/futures/account.reduce_only_close_only",
            "/api/v1/futures/positions",
            "/api/v1/futures/risk-proofs",
        ],
        evidence_routes=[
            "/api/v1/futures/account",
            "/api/v1/futures/positions",
            "/api/v1/futures/risk-proofs",
        ],
    )


def _futures_semantic_readiness(
    *,
    semantic: str,
    runtime_observed: bool,
    flags: Mapping[str, bool],
    missing_reason: str,
    detail_ready: str,
    detail_blocked: str,
    required_evidence_refs: Sequence[str],
    evidence_routes: Sequence[str],
) -> dict[str, Any]:
    ready = runtime_observed and all(bool(value) for value in flags.values())
    return {
        "ready": ready,
        "runtime_observed": runtime_observed,
        "flags": dict(flags),
        "missing_reason": "none" if ready else missing_reason,
        "detail": detail_ready if ready else detail_blocked,
        "required_evidence_refs": list(required_evidence_refs),
        "evidence_routes": list(evidence_routes),
        "runtime_key": f"runtime_{semantic}_evidence_observed",
        "runtime_satisfies_key": f"runtime_evidence_satisfies_{semantic}_semantics",
        "validation_ready_key": f"validation_record_{semantic}_semantics_ready",
    }


def _futures_us_cfm_account_bound(value: Mapping[str, Any]) -> bool:
    return (
        str(value.get("account_family") or "") == FUTURES_ACCOUNT_FAMILY_US_CFM
        and str(value.get("intx_applicability") or "")
        == FUTURES_INTX_APPLICABILITY_US_ACCOUNT
    )


def _futures_money_value_present(
    value: Mapping[str, Any],
    key: str,
) -> bool:
    item = _object_to_dict(value.get(key))
    return bool(str(item.get("value") or "").strip())


def _futures_money_currency_present(
    value: Mapping[str, Any],
    keys: Sequence[str],
) -> bool:
    return any(
        bool(str(_object_to_dict(value.get(key)).get("currency") or "").strip())
        for key in keys
    )


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _futures_request_payload_validation_record_semantic(
    command: str,
    field: str,
    semantic: str,
    readiness: Mapping[str, Any],
) -> dict[str, Any]:
    ready = bool(readiness["ready"])
    eligibility_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_execution_eligibilities.py::{command}_{field}"
    )
    semantic_ref = f"{eligibility_ref}_{semantic}_semantics"
    contract_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_{semantic}_semantics.py::{command}_{field}_{semantic}_semantics_contract"
    )
    artifact_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifacts.py::{command}_{field}_{semantic}_semantics"
    )
    definition_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifact_definitions.py::{command}_{field}_{semantic}_semantics_definition"
    )
    review_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifact_definition_reviews.py::{command}_{field}_{semantic}_semantics_definition_review"
    )
    runtime_evidence_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifact_runtime_evidences.py::{command}_{field}_{semantic}_semantics_runtime_evidence"
    )
    acceptance_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py::{command}_{field}_{semantic}_semantics_runtime_evidence_acceptance"
    )
    required_evidence_refs = [
        semantic_ref,
        contract_ref,
        *list(readiness["required_evidence_refs"]),
    ]
    missing_evidence_refs = [] if ready else required_evidence_refs
    forbidden_execution_claims = [
        "validation_record_execution_eligible",
        "command_execution_allowed",
        "live_coinbase_orders_ran",
        "browser_execution_authority",
        "bff_execution_authority",
        "spot_rule_authority",
    ]
    runtime_key = str(readiness["runtime_key"])
    runtime_satisfies_key = str(readiness["runtime_satisfies_key"])
    validation_ready_key = str(readiness["validation_ready_key"])
    return {
        "field": field,
        "blocker": f"{semantic}_semantics_missing",
        "semantic_artifact": f"{semantic}_semantics",
        "status": (
            AdminMvpGateStatus.PASSED.value
            if ready
            else AdminMvpGateStatus.BLOCKED.value
        ),
        "source": "backend_contract",
        "required": True,
        "blocking": not ready,
        "validation_record_execution_eligibility_contract_ref": eligibility_ref,
        "validation_record_execution_eligibility_blocker_ref": semantic_ref,
        "semantic_ref": semantic_ref,
        "semantic_artifact_ref": artifact_ref,
        "semantic_artifact_contract_ref": f"{artifact_ref}_contract",
        "semantic_artifact_definition_ref": definition_ref,
        "semantic_artifact_definition_contract_ref": f"{definition_ref}_contract",
        "semantic_artifact_definition_review_ref": review_ref,
        "semantic_artifact_definition_review_contract_ref": f"{review_ref}_contract",
        "semantic_artifact_runtime_evidence_ref": runtime_evidence_ref,
        "semantic_artifact_runtime_evidence_contract_ref": f"{runtime_evidence_ref}_contract",
        "semantic_artifact_runtime_evidence_acceptance_ref": acceptance_ref,
        "semantic_artifact_runtime_evidence_acceptance_contract_ref": f"{acceptance_ref}_contract",
        f"{semantic}_semantics_ref": semantic_ref,
        f"{semantic}_semantics_contract_ref": contract_ref,
        "evidence_routes": list(readiness["evidence_routes"]),
        "evidence_route_count": len(readiness["evidence_routes"]),
        "required_backend_contract": contract_ref,
        "missing_backend_contract": "none" if ready else contract_ref,
        "missing_reason": str(readiness["missing_reason"]),
        "required_evidence_refs": required_evidence_refs,
        "required_evidence_count": len(required_evidence_refs),
        "missing_evidence_refs": missing_evidence_refs,
        "missing_evidence_count": len(missing_evidence_refs),
        "forbidden_execution_claims": forbidden_execution_claims,
        "forbidden_execution_claim_count": len(forbidden_execution_claims),
        "backend_owned": True,
        "read_only": True,
        "contextless_review_required": False,
        "spot_rule_authority": False,
        f"{semantic}_semantics_contract_available": ready,
        f"{semantic}_semantics_contract_ready": ready,
        **dict(readiness["flags"]),
        runtime_key: bool(readiness["runtime_observed"]),
        runtime_satisfies_key: ready,
        "semantic_artifact_runtime_evidence_acceptance_available": ready,
        "semantic_artifact_runtime_evidence_acceptance_accepted": ready,
        validation_ready_key: ready,
        "validation_record_execution_eligible": False,
        "execution_allowed": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            f"{command}.{field}: {readiness['detail']}; command execution remains controlled by separate live enablement gates."
        ),
    }


def _futures_semantic_rows_from_commands(
    commands: Sequence[Mapping[str, Any]],
    semantic: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    key = f"request_payload_validation_record_{semantic}_semantics"
    for command in commands:
        rows.extend([dict(item) for item in command.get(key, [])])
    return rows


def _futures_semantic_counts(
    semantic: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    runtime_key = f"runtime_{semantic}_evidence_observed"
    return {
        f"request_payload_validation_record_{semantic}_semantic_count": len(rows),
        f"blocking_request_payload_validation_record_{semantic}_semantic_count": sum(
            1 for row in rows if bool(row.get("blocking"))
        ),
        f"ready_request_payload_validation_record_{semantic}_semantic_count": sum(
            1 for row in rows if str(row.get("status") or "") == AdminMvpGateStatus.PASSED.value
        ),
        f"runtime_observed_request_payload_validation_record_{semantic}_semantic_count": sum(
            1 for row in rows if bool(row.get(runtime_key))
        ),
    }


def _futures_command_semantic_guards(
    *,
    command: str,
    identity_key: str,
    request_fields: Sequence[Mapping[str, Any]],
    missing_contracts: Sequence[str],
    risk_proof: Mapping[str, Any] | None,
    semantic_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_semantics: Sequence[Mapping[str, Any]],
    live_decision_evidence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    fields = [str(item.get("field") or "") for item in request_fields]
    identity_fields = [identity_key] if identity_key in fields else fields[:1]
    risk_ready = risk_proof is not None and not missing_contracts
    margin_ready = _futures_semantic_family_ready(semantic_rows.get("margin", []))
    collateral_ready = _futures_semantic_family_ready(
        semantic_rows.get("collateral", [])
    )
    liquidation_ready = _futures_semantic_family_ready(
        semantic_rows.get("liquidation", [])
    )
    funding_ready = _futures_semantic_family_ready(funding_semantics)
    reduce_only_ready = _futures_semantic_family_ready(
        semantic_rows.get("reduce_only", [])
    )
    close_only_ready = _futures_semantic_family_ready(
        semantic_rows.get("close_only", [])
    )
    product_scope_ready = risk_ready and command == "futures_place"
    position_scope_ready = risk_ready and command in {
        "futures_close_reduce",
        "futures_reconcile",
    }
    live_execution_ready = bool(live_decision_evidence.get("execution_allowed"))
    live_missing_refs = _futures_live_execution_boundary_missing_refs(
        live_decision_evidence
    )
    guards: list[dict[str, Any]] = []
    if command == "futures_place":
        guards.append(
            _futures_semantic_guard(
                semantic_guard="product_scope",
                ready=product_scope_ready,
                applies_to_fields=["product_id"],
                evidence_routes=["/api/v1/futures/account", "/api/v1/futures/positions"],
                required_evidence_refs=[
                    "futures_product_scope_readback",
                    "futures_command_product_scope_contract",
                ],
                identity_semantic=True,
                risk_semantic=True,
                detail=(
                    "Backend Futures product scope is bound to the configured US CFM "
                    "product set before live placement."
                ),
            )
        )
    if command in {"futures_close_reduce", "futures_reconcile"}:
        guards.append(
            _futures_semantic_guard(
                semantic_guard="position_scope",
                ready=position_scope_ready,
                applies_to_fields=["position_key"],
                evidence_routes=[
                    "/api/v1/futures/positions",
                    "/api/v1/futures/positions/{position_key}",
                ],
                required_evidence_refs=[
                    "futures_position_scope_readback",
                    "futures_command_position_scope_contract",
                ],
                identity_semantic=True,
                risk_semantic=True,
                detail=(
                    "Backend Futures position scope is bound before close/reduce or "
                    "reconciliation commands."
                ),
            )
        )
    if command in {"futures_place", "futures_close_reduce", "futures_reconcile"}:
        guards.extend(
            [
                _futures_semantic_guard(
                    semantic_guard="margin_collateral",
                    ready=margin_ready and collateral_ready,
                    applies_to_fields=_futures_risk_fields(fields),
                    evidence_routes=[
                        "/api/v1/futures/account",
                        "/api/v1/futures/risk-proofs",
                    ],
                    required_evidence_refs=[
                        "futures_margin_collateral_risk_contract",
                        "futures_account_margin_collateral_readback",
                    ],
                    risk_semantic=True,
                    detail=(
                        "Backend Futures margin and collateral evidence are bound "
                        "to the command risk proof."
                    ),
                ),
                _futures_semantic_guard(
                    semantic_guard="liquidation_buffer",
                    ready=liquidation_ready,
                    applies_to_fields=_futures_risk_fields(fields),
                    evidence_routes=[
                        "/api/v1/futures/account",
                        "/api/v1/futures/risk-proofs",
                    ],
                    required_evidence_refs=[
                        "futures_liquidation_buffer_risk_contract",
                        "futures_account_liquidation_readback",
                    ],
                    risk_semantic=True,
                    detail=(
                        "Backend Futures liquidation threshold and buffer evidence "
                        "are bound to risk admission."
                    ),
                ),
                _futures_semantic_guard(
                    semantic_guard="funding_fee",
                    ready=funding_ready,
                    applies_to_fields=_futures_risk_fields(fields),
                    evidence_routes=[
                        "/api/v1/futures/account",
                        ACCOUNT_FEES_ROUTE,
                        "/api/v1/futures/risk-proofs",
                    ],
                    required_evidence_refs=[
                        "futures_funding_fee_risk_contract",
                        "futures_fee_tier_readback",
                    ],
                    risk_semantic=True,
                    detail=(
                        "Backend Futures funding applicability and fee-tier "
                        "evidence are bound to risk admission."
                    ),
                ),
            ]
        )
    if command == "futures_close_reduce":
        guards.extend(
            [
                _futures_semantic_guard(
                    semantic_guard="reduce_only",
                    ready=reduce_only_ready,
                    applies_to_fields=["position_key", "size"],
                    evidence_routes=[
                        "/api/v1/futures/account",
                        "/api/v1/futures/positions",
                        "/api/v1/futures/risk-proofs",
                    ],
                    required_evidence_refs=[
                        "futures_reduce_only_position_contract",
                        "futures_position_side_readback",
                    ],
                    risk_semantic=True,
                    detail=(
                        "Backend derives reduce-only side from observed Futures "
                        "position evidence."
                    ),
                ),
                _futures_semantic_guard(
                    semantic_guard="close_only",
                    ready=close_only_ready,
                    applies_to_fields=["position_key", "size"],
                    evidence_routes=[
                        "/api/v1/futures/account",
                        "/api/v1/futures/positions",
                        "/api/v1/futures/risk-proofs",
                    ],
                    required_evidence_refs=[
                        "futures_close_only_position_contract",
                        "futures_position_side_readback",
                    ],
                    risk_semantic=True,
                    detail=(
                        "Backend derives close-only side from observed Futures "
                        "position evidence."
                    ),
                ),
            ]
        )
    guards.append(
        _futures_semantic_guard(
            semantic_guard="idempotency",
            ready=bool(identity_fields),
            applies_to_fields=identity_fields,
            evidence_routes=["/api/v1/admin/admission-audits"],
            required_evidence_refs=[
                "futures_client_order_id_idempotency_contract",
                "futures_payload_hash_admission_audit_link",
            ],
            identity_semantic=True,
            audit_semantic=True,
            proof_writer_enabled=True,
            detail=(
                "Backend command identity, payload hash, idempotency key, and "
                "correlation id are bound before command admission."
            ),
        )
    )
    if command in {"futures_place", "futures_close_reduce"}:
        guards.append(
            _futures_semantic_guard(
                semantic_guard="cap_guard",
                ready=risk_ready,
                applies_to_fields=_futures_risk_fields(fields),
                evidence_routes=[
                    "/api/v1/futures/account",
                    "/api/v1/admin/cap-guard/decisions",
                ],
                required_evidence_refs=[
                    "futures_cap_guard_decision_contract",
                    "futures_cap_guard_notional_limit",
                ],
                risk_semantic=True,
                audit_semantic=True,
                proof_writer_enabled=True,
                detail=(
                    "Backend Futures cap evidence is available before live "
                    "notional admission."
                ),
            )
        )
    guards.extend(
        [
            _futures_semantic_guard(
                semantic_guard="admission_audit",
                ready=True,
                applies_to_fields=identity_fields,
                evidence_routes=["/api/v1/admin/admission-audits"],
                required_evidence_refs=["futures_admission_audit_contract"],
                audit_semantic=True,
                proof_writer_enabled=True,
                detail=(
                    "Backend Futures admission audit evidence is recorded with "
                    "operator intent and request correlation."
                ),
            ),
            _futures_semantic_guard(
                semantic_guard="reconciliation_plan",
                ready=risk_ready,
                applies_to_fields=identity_fields,
                evidence_routes=["/api/v1/admin/reconciliation/plans"],
                required_evidence_refs=["futures_reconciliation_plan_contract"],
                execution_semantic=True,
                proof_writer_enabled=True,
                detail=(
                    "Backend Futures reconciliation evidence route is bound for "
                    "post-command local evidence."
                ),
            ),
            _futures_semantic_guard(
                semantic_guard="live_execution_boundary",
                ready=live_execution_ready,
                applies_to_fields=identity_fields,
                evidence_routes=[
                    "/api/v1/admin/live-enablement",
                    LIVE_SERVICE_DECISION_ROUTE,
                    LIVE_ADAPTER_DECISION_ROUTE,
                ],
                required_evidence_refs=[
                    LIVE_SERVICE_DECISION_ROUTE,
                    LIVE_ADAPTER_DECISION_ROUTE,
                ],
                missing_evidence_refs=live_missing_refs,
                execution_semantic=True,
                proof_writer_enabled=True,
                detail=(
                    "Backend Futures live-service, live-adapter, runtime opt-in, "
                    "and explicit acknowledgement gates control exchange submission."
                ),
            ),
        ]
    )
    return guards


def _futures_risk_fields(fields: Sequence[str]) -> list[str]:
    risk_fields = [
        field
        for field in fields
        if field
        in {
            "product_id",
            "position_key",
            "limit_price",
            "size",
            "order_side",
            "order_type",
        }
    ]
    return risk_fields or [field for field in fields if field]


def _futures_semantic_family_ready(rows: Sequence[Mapping[str, Any]]) -> bool:
    return bool(rows) and all(
        str(row.get("status") or "") == AdminMvpGateStatus.PASSED.value
        and not bool(row.get("blocking"))
        for row in rows
    )


def _futures_live_execution_boundary_missing_refs(
    live_decision_evidence: Mapping[str, Any],
) -> list[str]:
    if bool(live_decision_evidence.get("execution_allowed")):
        return []
    missing: list[str] = []
    if str(live_decision_evidence.get("service_decision_status") or "") != "ready":
        missing.append(LIVE_SERVICE_DECISION_ROUTE)
    if str(live_decision_evidence.get("adapter_decision_status") or "") != "ready":
        missing.append(LIVE_ADAPTER_DECISION_ROUTE)
    if (
        bool(live_decision_evidence.get("executor_boundary_ready"))
        and not bool(live_decision_evidence.get("live_runtime_ready"))
        and bool(live_decision_evidence.get("live_exchange_command"))
    ):
        missing.append("COINBASE_ADMIN_LIVE_COINBASE_EXECUTION")
    return missing


def _futures_semantic_guard(
    *,
    semantic_guard: str,
    ready: bool,
    applies_to_fields: Sequence[str],
    evidence_routes: Sequence[str],
    required_evidence_refs: Sequence[str],
    detail: str,
    missing_evidence_refs: Sequence[str] | None = None,
    identity_semantic: bool = False,
    risk_semantic: bool = False,
    audit_semantic: bool = False,
    execution_semantic: bool = False,
    proof_writer_enabled: bool = False,
) -> dict[str, Any]:
    missing_refs = list(missing_evidence_refs) if missing_evidence_refs is not None else (
        [] if ready else list(required_evidence_refs)
    )
    routes = _unique_texts(evidence_routes)
    required_refs = _unique_texts(required_evidence_refs)
    missing_refs = _unique_texts(missing_refs)
    return {
        "semantic_guard": semantic_guard,
        "status": (
            AdminMvpGateStatus.PASSED.value
            if ready
            else AdminMvpGateStatus.BLOCKED.value
        ),
        "source": "backend_contract",
        "applies_to_fields": _unique_texts(applies_to_fields),
        "evidence_routes": routes,
        "evidence_route_count": len(routes),
        "required_evidence_refs": required_refs,
        "required_evidence_count": len(required_refs),
        "missing_evidence_refs": missing_refs,
        "missing_evidence_count": len(missing_refs),
        "required": True,
        "identity_semantic": identity_semantic,
        "risk_semantic": risk_semantic,
        "audit_semantic": audit_semantic,
        "execution_semantic": execution_semantic,
        "evidence_backend_owned": True,
        "evidence_read_only": True,
        "proof_route_required": True,
        "proof_route_registered": True,
        "proof_writer_enabled": proof_writer_enabled,
        "proof_evidence_only": True,
        "backend_owned": True,
        "spot_rule_authority": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": detail,
    }


def _futures_semantic_guard_counts(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    return {
        "semantic_guard_count": len(rows),
        "blocking_semantic_guard_count": sum(
            1 for row in rows if str(row.get("status") or "") != AdminMvpGateStatus.PASSED.value
        ),
        "risk_semantic_guard_count": sum(
            1 for row in rows if bool(row.get("risk_semantic"))
        ),
    }


def _futures_semantic_guard_rows_from_commands(
    commands: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for command in commands:
        command_name = str(command.get("command") or "")
        for row in command.get("semantic_guards", []):
            rows.append({"command": command_name, **dict(row)})
    return rows


def _futures_semantic_guard_summaries(
    commands: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    ordered_guards = _unique_texts(row.get("semantic_guard") for row in rows)
    summaries: list[dict[str, Any]] = []
    command_ids = [str(command.get("command") or "") for command in commands]
    for semantic_guard in ordered_guards:
        guard_rows = [
            row for row in rows if str(row.get("semantic_guard") or "") == semantic_guard
        ]
        affected_commands = _unique_texts(row.get("command") for row in guard_rows)
        blocking_rows = [
            row
            for row in guard_rows
            if str(row.get("status") or "") != AdminMvpGateStatus.PASSED.value
        ]
        applies_to_fields = _unique_texts(
            field
            for row in guard_rows
            for field in row.get("applies_to_fields", [])
        )
        evidence_routes = _unique_texts(
            route
            for row in guard_rows
            for route in row.get("evidence_routes", [])
        )
        required_refs = _unique_texts(
            ref
            for row in guard_rows
            for ref in row.get("required_evidence_refs", [])
        )
        missing_refs = _unique_texts(
            ref
            for row in guard_rows
            for ref in row.get("missing_evidence_refs", [])
        )
        summaries.append({
            "semantic_guard": semantic_guard,
            "status": (
                AdminMvpGateStatus.BLOCKED.value
                if blocking_rows
                else AdminMvpGateStatus.PASSED.value
            ),
            "blocking": bool(blocking_rows),
            "command_count": len(affected_commands),
            "affected_commands": [
                command for command in command_ids if command in affected_commands
            ],
            "blocking_command_count": len(
                _unique_texts(row.get("command") for row in blocking_rows)
            ),
            "identity_semantic_command_count": len(
                _unique_texts(
                    row.get("command") for row in guard_rows if row.get("identity_semantic")
                )
            ),
            "risk_semantic_command_count": len(
                _unique_texts(
                    row.get("command") for row in guard_rows if row.get("risk_semantic")
                )
            ),
            "audit_semantic_command_count": len(
                _unique_texts(
                    row.get("command") for row in guard_rows if row.get("audit_semantic")
                )
            ),
            "execution_semantic_command_count": len(
                _unique_texts(
                    row.get("command") for row in guard_rows if row.get("execution_semantic")
                )
            ),
            "applies_to_field_count": len(applies_to_fields),
            "applies_to_fields": applies_to_fields,
            "evidence_route_count": len(evidence_routes),
            "evidence_routes": evidence_routes,
            "required_evidence_ref_count": len(required_refs),
            "required_evidence_refs": required_refs,
            "missing_evidence_ref_count": len(missing_refs),
            "missing_evidence_refs": missing_refs,
            "proof_route_required_count": sum(
                1 for row in guard_rows if bool(row.get("proof_route_required"))
            ),
            "proof_route_registered_count": sum(
                1 for row in guard_rows if bool(row.get("proof_route_registered"))
            ),
            "proof_writer_enabled_count": sum(
                1 for row in guard_rows if bool(row.get("proof_writer_enabled"))
            ),
            "proof_evidence_only_count": sum(
                1 for row in guard_rows if bool(row.get("proof_evidence_only"))
            ),
            "backend_owned": True,
            "read_only": True,
            "spot_rule_authority": False,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
            "detail": (
                f"{semantic_guard} guard is backend-owned evidence across "
                f"{len(affected_commands)} Futures/Perpetual command(s)."
            ),
        })
    return summaries


def _futures_request_payload_validation_record_funding_semantics(
    command: str,
    identity_key: str,
    request_fields: Sequence[Mapping[str, Any]],
    funding_evidence: Mapping[str, Any],
    fee_input: Mapping[str, Any],
) -> list[dict[str, Any]]:
    field = _futures_funding_semantic_field(identity_key, request_fields)
    if field is None:
        return []
    return [
        _futures_request_payload_validation_record_funding_semantic(
            command,
            field,
            funding_evidence,
            fee_input,
        )
    ]


def _futures_funding_semantic_field(
    identity_key: str,
    request_fields: Sequence[Mapping[str, Any]],
) -> str | None:
    for item in request_fields:
        if str(item.get("field") or "") == identity_key:
            return identity_key
    if request_fields:
        return str(request_fields[0].get("field") or "") or None
    return None


def _futures_request_payload_validation_record_funding_semantic(
    command: str,
    field: str,
    funding_evidence: Mapping[str, Any],
    fee_input: Mapping[str, Any],
) -> dict[str, Any]:
    funding_ready = str(funding_evidence.get("status") or "") == "ready"
    fee_ready = str(fee_input.get("status") or "") == "ready"
    ready = funding_ready and fee_ready
    eligibility_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_execution_eligibilities.py::{command}_{field}"
    )
    semantic_ref = f"{eligibility_ref}_funding_semantics"
    contract_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_funding_semantics.py::{command}_{field}_funding_semantics_contract"
    )
    artifact_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifacts.py::{command}_{field}_funding_semantics"
    )
    definition_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifact_definitions.py::{command}_{field}_funding_semantics_definition"
    )
    review_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifact_definition_reviews.py::{command}_{field}_funding_semantics_definition_review"
    )
    runtime_evidence_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifact_runtime_evidences.py::{command}_{field}_funding_semantics_runtime_evidence"
    )
    acceptance_ref = (
        "application/admin_api/"
        f"futures_request_payload_validation_record_semantic_artifact_runtime_evidence_acceptances.py::{command}_{field}_funding_semantics_runtime_evidence_acceptance"
    )
    evidence_routes = [
        "/api/v1/futures/account",
        ACCOUNT_FEES_ROUTE,
        "/api/v1/futures/risk-proofs",
    ]
    required_evidence_refs = [
        semantic_ref,
        contract_ref,
        "/api/v1/futures/account.funding",
        f"{ACCOUNT_FEES_ROUTE}.futures_fee_input",
        "/api/v1/futures/risk-proofs",
    ]
    missing_evidence_refs = [] if ready else required_evidence_refs
    forbidden_execution_claims = [
        "validation_record_execution_eligible",
        "command_execution_allowed",
        "live_coinbase_orders_ran",
        "browser_execution_authority",
        "bff_execution_authority",
        "spot_rule_authority",
    ]
    return {
        "field": field,
        "blocker": "funding_semantics_missing",
        "semantic_artifact": "funding_semantics",
        "status": (
            AdminMvpGateStatus.PASSED.value
            if ready
            else AdminMvpGateStatus.BLOCKED.value
        ),
        "source": "backend_contract",
        "required": True,
        "blocking": not ready,
        "validation_record_execution_eligibility_contract_ref": eligibility_ref,
        "validation_record_execution_eligibility_blocker_ref": semantic_ref,
        "semantic_ref": semantic_ref,
        "semantic_artifact_ref": artifact_ref,
        "semantic_artifact_contract_ref": f"{artifact_ref}_contract",
        "semantic_artifact_definition_ref": definition_ref,
        "semantic_artifact_definition_contract_ref": f"{definition_ref}_contract",
        "semantic_artifact_definition_review_ref": review_ref,
        "semantic_artifact_definition_review_contract_ref": f"{review_ref}_contract",
        "semantic_artifact_runtime_evidence_ref": runtime_evidence_ref,
        "semantic_artifact_runtime_evidence_contract_ref": f"{runtime_evidence_ref}_contract",
        "semantic_artifact_runtime_evidence_acceptance_ref": acceptance_ref,
        "semantic_artifact_runtime_evidence_acceptance_contract_ref": f"{acceptance_ref}_contract",
        "funding_semantics_ref": semantic_ref,
        "funding_semantics_contract_ref": contract_ref,
        "evidence_routes": evidence_routes,
        "evidence_route_count": len(evidence_routes),
        "required_backend_contract": contract_ref,
        "missing_backend_contract": "none" if ready else contract_ref,
        "missing_reason": "none" if ready else "backend_owned_funding_or_fee_evidence_missing",
        "required_evidence_refs": required_evidence_refs,
        "required_evidence_count": len(required_evidence_refs),
        "missing_evidence_refs": missing_evidence_refs,
        "missing_evidence_count": len(missing_evidence_refs),
        "forbidden_execution_claims": forbidden_execution_claims,
        "forbidden_execution_claim_count": len(forbidden_execution_claims),
        "backend_owned": True,
        "read_only": True,
        "contextless_review_required": False,
        "spot_rule_authority": False,
        "funding_semantics_contract_available": ready,
        "funding_semantics_contract_ready": ready,
        "funding_rate_bound": funding_ready,
        "funding_fee_bound": fee_ready,
        "funding_interval_bound": funding_ready,
        "funding_cost_bound": funding_ready,
        "runtime_funding_evidence_observed": funding_ready,
        "runtime_evidence_satisfies_funding_semantics": ready,
        "semantic_artifact_runtime_evidence_acceptance_available": ready,
        "semantic_artifact_runtime_evidence_acceptance_accepted": ready,
        "validation_record_funding_semantics_ready": ready,
        "validation_record_execution_eligible": False,
        "execution_allowed": False,
        "live_coinbase_orders_ran": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            f"{command}.{field}: backend-owned US CFM funding applicability and fee-tier evidence are bound for validation-record funding semantics; command execution remains controlled by separate live enablement gates."
            if ready
            else f"{command}.{field}: backend-owned funding semantics require ready US CFM funding applicability and fee-tier evidence before validation-record funding semantics can pass."
        ),
    }


def _futures_funding_semantic_rows_from_commands(
    commands: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for command in commands:
        rows.extend(
            [
                dict(item)
                for item in command.get(
                    "request_payload_validation_record_funding_semantics",
                    [],
                )
            ]
        )
    return rows


def _futures_funding_semantic_counts(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    return {
        "request_payload_validation_record_funding_semantic_count": len(rows),
        "blocking_request_payload_validation_record_funding_semantic_count": sum(
            1 for row in rows if bool(row.get("blocking"))
        ),
        "ready_request_payload_validation_record_funding_semantic_count": sum(
            1 for row in rows if str(row.get("status") or "") == AdminMvpGateStatus.PASSED.value
        ),
        "runtime_observed_request_payload_validation_record_funding_semantic_count": sum(
            1 for row in rows if bool(row.get("runtime_funding_evidence_observed"))
        ),
    }


def _futures_request_field_item(
    command: str,
    field_spec: Mapping[str, Any],
    *,
    status: str = AdminMvpGateStatus.PASSED.value,
    validation_issue: str = "none",
) -> dict[str, Any]:
    field = str(field_spec["field"])
    blocking = status == AdminMvpGateStatus.BLOCKED.value
    return {
        "field": field,
        "status": status,
        "source": "backend_contract",
        "required": True,
        "identity_field": bool(field_spec.get("identity_field", False)),
        "risk_field": bool(field_spec.get("risk_field", False)),
        "payload_field": True,
        "validation_gate_ready": True,
        "validation_gate_passed": not blocking,
        "validator_registered": True,
        "validator_contract_registered": True,
        "validation_registered": True,
        "request_payload_validated": not blocking,
        "request_payload_contract_ref": (
            f"admin_futures_request_payload.{command}.{field}"
        ),
        "validation_evidence_ref": (
            f"admin_futures_payload_validation.{command}.{field}"
        ),
        "validation_gate_ref": (
            f"admin_futures_payload_validation_gate.{command}.{field}"
        ),
        "validator_contract_ref": (
            f"admin_futures_payload_validator_contract.{command}.{field}"
        ),
        "validator_registration_ref": (
            f"admin_futures_payload_validator_registration.{command}.{field}"
        ),
        "backend_owned": True,
        "spot_rule_authority": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": _futures_request_field_detail(command, field, validation_issue),
    }


def _futures_request_field_summaries() -> list[dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for spec in FUTURES_COMMAND_SPECS:
        command = str(spec["command"])
        for field_spec in FUTURES_COMMAND_REQUEST_FIELDS.get(command, ()):
            field = str(field_spec["field"])
            request_field = _futures_request_field_item(command, field_spec)
            summary = summaries.setdefault(
                field,
                {
                    "field": field,
                    "affected_commands": [],
                    "identity_field_command_count": 0,
                    "risk_field_command_count": 0,
                    "payload_field_command_count": 0,
                    "request_payload_contract_refs": [],
                    "validation_gate_refs": [],
                    "validation_evidence_refs": [],
                    "validator_contract_refs": [],
                    "validator_registration_refs": [],
                },
            )
            summary["affected_commands"].append(command)
            if bool(request_field["identity_field"]):
                summary["identity_field_command_count"] += 1
            if bool(request_field["risk_field"]):
                summary["risk_field_command_count"] += 1
            if bool(request_field["payload_field"]):
                summary["payload_field_command_count"] += 1
            summary["request_payload_contract_refs"].append(
                str(request_field["request_payload_contract_ref"])
            )
            summary["validation_gate_refs"].append(str(request_field["validation_gate_ref"]))
            summary["validation_evidence_refs"].append(
                str(request_field["validation_evidence_ref"])
            )
            summary["validator_contract_refs"].append(
                str(request_field["validator_contract_ref"])
            )
            summary["validator_registration_refs"].append(
                str(request_field["validator_registration_ref"])
            )
    return [_futures_request_field_summary_item(summary) for summary in summaries.values()]


def _futures_request_field_summary_item(summary: Mapping[str, Any]) -> dict[str, Any]:
    field = str(summary["field"])
    commands = [str(command) for command in summary["affected_commands"]]
    request_payload_contract_refs = _unique_texts(
        summary["request_payload_contract_refs"]
    )
    validation_gate_refs = _unique_texts(summary["validation_gate_refs"])
    validation_evidence_refs = _unique_texts(summary["validation_evidence_refs"])
    validator_contract_refs = _unique_texts(summary["validator_contract_refs"])
    validator_registration_refs = _unique_texts(
        summary["validator_registration_refs"]
    )
    return {
        "field": field,
        "status": AdminMvpGateStatus.PASSED.value,
        "blocking": False,
        "required": True,
        "command_count": len(commands),
        "affected_commands": commands,
        "required_command_count": len(commands),
        "blocking_command_count": 0,
        "identity_field_command_count": int(summary["identity_field_command_count"]),
        "risk_field_command_count": int(summary["risk_field_command_count"]),
        "payload_field_command_count": int(summary["payload_field_command_count"]),
        "request_payload_contract_ref_count": len(request_payload_contract_refs),
        "request_payload_contract_refs": request_payload_contract_refs,
        "validation_gate_ref_count": len(validation_gate_refs),
        "validation_gate_refs": validation_gate_refs,
        "validation_evidence_ref_count": len(validation_evidence_refs),
        "validation_evidence_refs": validation_evidence_refs,
        "validator_contract_ref_count": len(validator_contract_refs),
        "validator_contract_refs": validator_contract_refs,
        "validator_registration_ref_count": len(validator_registration_refs),
        "validator_registration_refs": validator_registration_refs,
        "backend_owned": True,
        "read_only": True,
        "spot_rule_authority": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            f"{field} is a backend-owned Futures command payload field validated "
            "before executor admission."
        ),
    }


def _validate_futures_command_payload(
    *,
    command: str,
    identity_key: str,
    identity_value: str,
    body: Mapping[str, Any],
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    missing_fields: list[str] = []
    invalid_fields: list[str] = []
    for field_spec in FUTURES_COMMAND_REQUEST_FIELDS.get(command, ()):
        field = str(field_spec["field"])
        value = _futures_payload_field_value(
            field_spec=field_spec,
            identity_key=identity_key,
            identity_value=identity_value,
            body=body,
        )
        validation_issue = _futures_payload_field_issue(field, value)
        status = (
            AdminMvpGateStatus.BLOCKED.value
            if validation_issue != "none"
            else AdminMvpGateStatus.PASSED.value
        )
        if validation_issue == "missing":
            missing_fields.append(field)
        elif validation_issue != "none":
            invalid_fields.append(field)
        item = _futures_request_field_item(
            command,
            field_spec,
            status=status,
            validation_issue=validation_issue,
        )
        item["value_present"] = validation_issue != "missing"
        fields.append(item)

    blocking_count = len(missing_fields) + len(invalid_fields)
    status = (
        AdminMvpGateStatus.BLOCKED.value
        if blocking_count
        else AdminMvpGateStatus.PASSED.value
    )
    return {
        "validation_id": f"futures-payload-validation-{_payload_hash(body)}",
        "command": command,
        "status": status,
        "request_field_count": len(fields),
        "required_request_field_count": len(fields),
        "blocking_request_field_count": blocking_count,
        "missing_request_fields": missing_fields,
        "invalid_request_fields": invalid_fields,
        "request_fields": fields,
        "validation_gate_passed": blocking_count == 0,
        "backend_owned": True,
        "spot_rule_authority": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            "Futures command payload failed backend validation."
            if blocking_count
            else "Futures command payload passed backend validation."
        ),
    }


def _futures_payload_field_value(
    *,
    field_spec: Mapping[str, Any],
    identity_key: str,
    identity_value: str,
    body: Mapping[str, Any],
) -> Any:
    field = str(field_spec["field"])
    payload_key = str(field_spec["payload_key"])
    candidates: list[Any] = []
    if field == identity_key and identity_value.strip():
        candidates.append(identity_value)
    for key in _futures_payload_field_keys(field, payload_key):
        if key in body:
            candidates.append(body.get(key))
    for candidate in candidates:
        if not _futures_payload_value_missing(candidate):
            return candidate
    return candidates[0] if candidates else None


def _futures_payload_field_keys(field: str, payload_key: str) -> list[str]:
    keys = [payload_key]
    if field != payload_key:
        keys.append(field)
    if field == "size":
        keys.append("number_of_contracts")
    return list(dict.fromkeys(keys))


def _futures_payload_field_issue(field: str, value: Any) -> str:
    if _futures_payload_value_missing(value):
        return "missing"
    if field in {"limit_price", "size"}:
        return "none" if _futures_positive_decimal(value) else "must_be_positive_decimal"
    if field == "product_id":
        return (
            "none"
            if str(value).strip() in FUTURES_CONFIGURED_PRODUCT_SCOPE
            else "unsupported_product_scope"
        )
    if field == "order_side":
        return "none" if str(value).strip().upper() in {"BUY", "SELL"} else "invalid_side"
    if field == "order_type":
        return (
            "none"
            if str(value).strip().upper() in {"LIMIT", "MARKET"}
            else "invalid_order_type"
        )
    return "none"


def _futures_payload_value_missing(value: Any) -> bool:
    return value is None or str(value).strip() == ""


def _futures_positive_decimal(value: Any) -> bool:
    try:
        return Decimal(str(value)) > Decimal("0")
    except (InvalidOperation, ValueError, TypeError):
        return False


def _futures_request_field_detail(
    command: str,
    field: str,
    validation_issue: str,
) -> str:
    if validation_issue == "none":
        return f"{command} requires backend validation for {field} before admission."
    if validation_issue == "missing":
        return f"{command} is missing required backend-owned payload field {field}."
    return (
        f"{command} has invalid backend-owned payload field {field}: "
        f"{validation_issue}."
    )


def _futures_command_enablement_sequence_steps(
    commands: Sequence[Mapping[str, Any]],
    missing_contracts: list[str],
    live_decision_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    command_ids = [str(command["command"]) for command in commands]
    rows = [
        _futures_command_enablement_sequence_step(
            step="resolve_prerequisite_contracts",
            sequence=1,
            command_ids=command_ids,
            blocking=bool(missing_contracts),
            source_blockers=["unresolved_prerequisites"] if missing_contracts else [],
            required_backend_contracts=(
                missing_contracts if missing_contracts else list(FUTURES_COMMAND_CONTRACTS)
            ),
            required_evidence_refs=[
                "/api/v1/futures/account",
                "/api/v1/futures/risk-proofs",
                "/api/v1/admin/reconciliation/plans",
            ],
            detail=(
                "Futures prerequisite contracts are still missing; commands remain draft-only."
                if missing_contracts
                else "Futures prerequisite contracts are resolved for draft review."
            ),
        ),
        _futures_command_enablement_sequence_step(
            step="define_request_payload_contract",
            sequence=2,
            command_ids=command_ids,
            blocking=False,
            source_blockers=[],
            required_backend_contracts=["admin_futures_request_payload_contract"],
            required_evidence_refs=[],
            detail=(
                "Backend-owned Futures request payload fields are declared and "
                "validated before admission."
            ),
        ),
        _futures_command_enablement_sequence_step(
            step="define_backend_command_service",
            sequence=3,
            command_ids=command_ids,
            blocking=False,
            source_blockers=[],
            required_backend_contracts=["admin_futures_command_service_contract"],
            required_evidence_refs=[
                str(command.get("service_method") or "")
                for command in commands
            ],
            detail=(
                "Backend Futures command service methods are declared before "
                "route registration or live-adapter binding."
            ),
        ),
        _futures_command_enablement_sequence_step(
            step="register_admin_command_route",
            sequence=4,
            command_ids=command_ids,
            blocking=False,
            source_blockers=[],
            required_backend_contracts=["admin_futures_command_route_registry"],
            required_evidence_refs=[],
            detail=(
                "Backend Admin API routes are registered for Futures command drafts; "
                "browser and BFF authority remain display/forward only."
            ),
        ),
        _futures_command_enablement_sequence_step(
            step="bind_live_service_adapter",
            sequence=5,
            command_ids=command_ids,
            blocking=_futures_live_adapter_sequence_blocking(live_decision_summary),
            source_blockers=(
                ["live_service_adapter"]
                if _futures_live_adapter_sequence_blocking(live_decision_summary)
                else []
            ),
            required_backend_contracts=["futures_live_adapter_contract"],
            required_evidence_refs=[
                "/api/v1/admin/live-execution/service-decisions",
                "/api/v1/admin/live-execution/adapter-decisions",
            ],
            detail=(
                "Futures live-service and adapter evidence are backend-bound; confirmed live exchange commands can reach the backend executor after explicit acknowledgement."
                if not _futures_live_adapter_sequence_blocking(live_decision_summary)
                else "Futures live-service and adapter evidence must remain backend-bound; execution is still disabled for the local runtime."
            ),
        ),
    ]
    return [row for row in rows if row["step"] in FUTURES_COMMAND_ENABLEMENT_SEQUENCE_STEPS]


def _futures_command_readiness_closure(
    *,
    command: str,
    route: str,
    service_method: str,
    missing_contracts: list[str],
    request_fields: Sequence[Mapping[str, Any]],
    live_decision_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    steps = _futures_command_readiness_closure_steps(
        command=command,
        route=route,
        service_method=service_method,
        missing_contracts=missing_contracts,
        request_fields=request_fields,
        live_decision_evidence=live_decision_evidence,
    )
    return {
        "readiness_closure_step_count": len(steps),
        "blocking_readiness_closure_step_count": sum(
            1 for step in steps if bool(step["blocking"])
        ),
        "readiness_closure_steps": steps,
    }


def _futures_command_readiness_closure_steps(
    *,
    command: str,
    route: str,
    service_method: str,
    missing_contracts: list[str],
    request_fields: Sequence[Mapping[str, Any]],
    live_decision_evidence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    request_payload_refs = [
        str(field.get("request_payload_contract_ref") or "")
        for field in request_fields
    ]
    live_blocking = _futures_live_adapter_sequence_blocking(live_decision_evidence)
    return [
        _futures_command_readiness_closure_step(
            step="resolve_prerequisite_contracts",
            sequence=1,
            blocking=bool(missing_contracts),
            required_backend_contract=(
                missing_contracts[0]
                if missing_contracts
                else "futures_command_prerequisite_contracts"
            ),
            required_evidence_refs=[
                "/api/v1/futures/account",
                "/api/v1/futures/risk-proofs",
                "/api/v1/admin/reconciliation/plans",
            ],
            detail=(
                f"{command} prerequisite contracts are still missing."
                if missing_contracts
                else f"{command} prerequisite contracts are resolved for draft review."
            ),
        ),
        _futures_command_readiness_closure_step(
            step="define_request_payload_contract",
            sequence=2,
            blocking=False,
            required_backend_contract=f"admin_futures_request_payload.{command}",
            required_evidence_refs=request_payload_refs,
            detail=f"{command} request payload fields are declared and validated by the backend.",
        ),
        _futures_command_readiness_closure_step(
            step="define_backend_command_service",
            sequence=3,
            blocking=False,
            required_backend_contract=f"admin_futures_command_service.{command}",
            required_evidence_refs=[service_method, route],
            detail=f"{command} is bound to backend service method {service_method}.",
        ),
        _futures_command_readiness_closure_step(
            step="register_admin_command_route",
            sequence=4,
            blocking=False,
            required_backend_contract=f"admin_futures_command_route.{command}",
            required_evidence_refs=[route],
            detail=f"{command} Admin API command route is registered as a backend draft.",
        ),
        _futures_command_readiness_closure_step(
            step="bind_live_service_adapter",
            sequence=5,
            blocking=live_blocking,
            required_backend_contract="futures_live_adapter_contract",
            required_evidence_refs=[
                "/api/v1/admin/live-execution/service-decisions",
                "/api/v1/admin/live-execution/adapter-decisions",
            ],
            detail=(
                f"{command} remains blocked at the backend live-adapter/executor boundary."
                if live_blocking
                else f"{command} has no live-adapter blocker in the current evidence."
            ),
        ),
    ]


def _futures_command_readiness_closure_step(
    *,
    step: str,
    sequence: int,
    blocking: bool,
    required_backend_contract: str,
    required_evidence_refs: list[str],
    detail: str,
) -> dict[str, Any]:
    refs = _unique_texts(required_evidence_refs)
    return {
        "step": step,
        "sequence": sequence,
        "status": (
            AdminMvpGateStatus.BLOCKED.value
            if blocking
            else AdminMvpGateStatus.PASSED.value
        ),
        "blocking": blocking,
        "source": "backend_contract",
        "required_backend_contract": required_backend_contract,
        "required_evidence_refs": refs,
        "required_evidence_count": len(refs),
        "command_route_registered": True,
        "command_draft_allowed": True,
        "execution_allowed": False,
        "proof_writer_enabled": False,
        "backend_owned": True,
        "read_only": True,
        "spot_rule_authority": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": detail,
    }


def _futures_command_enablement_sequence_step(
    *,
    step: str,
    sequence: int,
    command_ids: list[str],
    blocking: bool,
    source_blockers: list[str],
    required_backend_contracts: list[str],
    required_evidence_refs: list[str],
    detail: str,
) -> dict[str, Any]:
    return {
        "step": step,
        "sequence": sequence,
        "status": (
            AdminMvpGateStatus.BLOCKED.value
            if blocking
            else AdminMvpGateStatus.PASSED.value
        ),
        "blocking": blocking,
        "command_count": len(command_ids),
        "affected_commands": command_ids,
        "source_blockers": source_blockers,
        "required_backend_contracts": required_backend_contracts,
        "required_evidence_refs": required_evidence_refs,
        "required_evidence_ref_count": len(required_evidence_refs),
        "command_route_registered": True,
        "command_draft_allowed": True,
        "execution_allowed": False,
        "live_coinbase_orders_ran": False,
        "backend_owned": True,
        "read_only": True,
        "spot_rule_authority": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": detail,
    }


def _futures_command_enablement_sequence_traces(
    commands: Sequence[Mapping[str, Any]],
    sequence_steps: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    traces: list[dict[str, Any]] = []
    for command_sequence, command in enumerate(commands, start=1):
        command_id = str(command["command"])
        for step in sequence_steps:
            traces.append(
                _futures_command_enablement_sequence_trace(
                    command_id=command_id,
                    command_sequence=command_sequence,
                    step=step,
                )
            )
    return traces


def _futures_command_enablement_sequence_trace(
    *,
    command_id: str,
    command_sequence: int,
    step: Mapping[str, Any],
) -> dict[str, Any]:
    required_backend_contracts = [
        str(contract) for contract in step.get("required_backend_contracts", [])
    ]
    required_evidence_refs = [
        str(ref) for ref in step.get("required_evidence_refs", [])
    ]
    return {
        "trace_id": f"{step['step']}::{command_id}",
        "step": str(step["step"]),
        "sequence": int(step["sequence"]),
        "command": command_id,
        "command_sequence": command_sequence,
        "command_step_sequence": int(step["sequence"]),
        "status": str(step["status"]),
        "blocking": bool(step["blocking"]),
        "source_blockers": list(step.get("source_blockers", [])),
        "required_backend_contract": (
            required_backend_contracts[0] if required_backend_contracts else None
        ),
        "required_evidence_refs": required_evidence_refs,
        "required_evidence_ref_count": len(required_evidence_refs),
        "command_route_registered": bool(step["command_route_registered"]),
        "command_draft_allowed": bool(step["command_draft_allowed"]),
        "execution_allowed": False,
        "reconciliation_execution_allowed": False,
        "futures_state_mutation_allowed": False,
        "live_coinbase_orders_ran": False,
        "backend_owned": True,
        "read_only": True,
        "spot_rule_authority": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": (
            f"{command_id} trace for {step['step']} remains read-only evidence; "
            "no Coinbase request or local Futures state mutation is allowed."
        ),
    }


def _futures_live_adapter_sequence_blocking(
    live_decision_summary: Mapping[str, Any],
) -> bool:
    return str(live_decision_summary.get("first_blocker") or "execution_disabled") != "none"


def _filter_futures_risk_proofs(
    records: list[dict[str, Any]],
    query: Mapping[str, Any],
) -> list[dict[str, Any]]:
    command = _query_text(query, "command")
    proof_kind = _query_text(query, "proof_kind")
    limit = _query_int(query, "limit", len(records) or 20)
    offset = _query_int(query, "offset", 0)
    filtered = [
        record
        for record in records
        if (not command or record.get("command") == command)
        and (not proof_kind or record.get("proof_kind") == proof_kind)
    ]
    return filtered[offset : offset + limit]


def _money_field(
    source: Mapping[str, Any],
    key: str,
    default_currency: str = "USD",
) -> dict[str, str] | None:
    value = source.get(key)
    data = _object_to_dict(value)
    if data:
        raw_value = data.get("value")
        if raw_value in (None, ""):
            return None
        return {
            "value": _decimal_text(_decimal_value(raw_value, Decimal("0"))),
            "currency": str(data.get("currency") or default_currency),
        }
    if value in (None, ""):
        return None
    return {
        "value": _decimal_text(_decimal_value(value, Decimal("0"))),
        "currency": default_currency,
    }


def _active_cfm_margin_window_measure(balance_summary: Mapping[str, Any]) -> dict[str, Any]:
    intraday = _object_to_dict(balance_summary.get("intraday_margin_window_measure"))
    if intraday:
        return intraday
    overnight = _object_to_dict(balance_summary.get("overnight_margin_window_measure"))
    if overnight:
        return overnight
    return {}


def _wallet_inventory_from_wallets(wallets: list[dict[str, Any]]) -> dict[str, Any]:
    quote_wallet = _spot_admission_quote_wallet(wallets)
    if quote_wallet is None:
        return {
            "currency": "USDC",
            "available_notional_usdc": "0",
            "hold_notional_usdc": "0",
            "total_notional_usdc": "0",
            "source": BACKEND_REST_CLIENT_SOURCE,
            "freshness_status": BACKEND_REST_FRESHNESS,
            "status": "ready",
            "error": "none",
            "quote_wallet_status": "blocked",
            "quote_wallet_error": "quote_wallet_missing",
        }
    return {
        "currency": quote_wallet["currency"],
        "available_notional_usdc": quote_wallet["available_balance"],
        "hold_notional_usdc": quote_wallet["hold_balance"],
        "total_notional_usdc": quote_wallet["total_balance"],
        "source": BACKEND_REST_CLIENT_SOURCE,
        "freshness_status": BACKEND_REST_FRESHNESS,
        "status": "ready",
        "error": "none",
        "quote_wallet_status": "ready",
        "quote_wallet_error": "none",
    }


def _spot_admission_quote_ready(wallet_inventory: Mapping[str, Any]) -> bool:
    return str(
        wallet_inventory.get("quote_wallet_status") or wallet_inventory.get("status")
    ) == "ready"


def _spot_admission_quote_wallet(
    wallets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for currency in SPOT_ADMISSION_QUOTE_CURRENCIES:
        wallet = next((item for item in wallets if item["currency"] == currency), None)
        if wallet is not None:
            return wallet
    return None


def _wallet_rows_for_admin(wallets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for wallet in wallets:
        admission_asset = wallet["currency"] in SPOT_ADMISSION_QUOTE_CURRENCIES
        admission_ready = admission_asset and _decimal_value(
            wallet["available_balance"],
            Decimal("0"),
        ) > Decimal("0")
        rows.append(
            {
                **wallet,
                "source": BACKEND_REST_CLIENT_SOURCE,
                "freshness_status": BACKEND_REST_FRESHNESS,
                "admission_asset": admission_asset,
                "admission_ready": admission_ready,
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
            }
        )
    return rows


def _portfolio_scope_from_portfolios(portfolios: list[dict[str, Any]]) -> dict[str, Any]:
    if portfolios:
        return portfolios[0]
    return {
        "portfolio_id": "unknown",
        "portfolio_name": "Unknown Backend Portfolio",
        "source": BACKEND_REST_CLIENT_SOURCE,
        "freshness_status": "backend_rest_missing_portfolio",
    }


def _wallet_hold_balance(data: Mapping[str, Any]) -> Decimal:
    explicit_hold = data.get("hold_balance", data.get("hold_notional_usdc"))
    if explicit_hold not in (None, ""):
        return _decimal_value(explicit_hold, Decimal("0"))
    total = _decimal_value(data.get("total_balance"), Decimal("0"))
    available = _decimal_value(data.get("available_balance"), Decimal("0"))
    hold = total - available
    return hold if hold > Decimal("0") else Decimal("0")


def _check_runtime_admission(controller: Any) -> None:
    from core.runtime_controller import INFLIGHT_REST_PLACE

    check_admission = getattr(controller, "check_admission", None)
    if callable(check_admission):
        check_admission(INFLIGHT_REST_PLACE)


def _track_runtime_place(controller: Any):
    from contextlib import nullcontext
    from core.runtime_controller import INFLIGHT_REST_PLACE

    tracker = getattr(controller, "track_inflight", None)
    if callable(tracker):
        return tracker(INFLIGHT_REST_PLACE)
    return nullcontext()


def _check_runtime_cancel_admission(controller: Any) -> None:
    from core.runtime_controller import INFLIGHT_REST_CANCEL

    check_admission = getattr(controller, "check_admission", None)
    if callable(check_admission):
        check_admission(INFLIGHT_REST_CANCEL)


def _track_runtime_cancel(controller: Any):
    from contextlib import nullcontext
    from core.runtime_controller import INFLIGHT_REST_CANCEL

    tracker = getattr(controller, "track_inflight", None)
    if callable(tracker):
        return tracker(INFLIGHT_REST_CANCEL)
    return nullcontext()


def _find_matching_record(
    records: Any,
    identity_value: str,
    idempotency_key: str,
    payload_hash: str,
    *,
    status_field: str | None = None,
    required_status: str | None = None,
    required_allowed: bool | None = None,
    service_method: str | None = None,
) -> dict[str, Any] | None:
    for record in records:
        if record.get("identity_value") != identity_value:
            continue
        if record.get("command_idempotency_key") != idempotency_key:
            continue
        if record.get("payload_hash") != payload_hash:
            continue
        if service_method is not None and record.get("service_method") != service_method:
            continue
        if status_field and str(record.get(status_field)) != required_status:
            continue
        if required_allowed is not None and bool(record.get("allowed")) is not required_allowed:
            continue
        return record
    return None


def _command_evidence_from_body(body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "route": str(body.get("route") or ""),
        "method": str(body.get("method") or ""),
        "module_id": str(body.get("module_id") or ""),
        "identity_key": str(body.get("identity_key") or ""),
        "identity_value": str(body.get("identity_value") or ""),
        "action_class": str(body.get("action_class") or ""),
        "required_permission": str(body.get("required_permission") or ""),
        "service_method": str(body.get("service_method") or MANUAL_ORDER_SERVICE_METHOD),
        "operator_intent": str(body.get("operator_intent") or ""),
        "command_idempotency_key": str(body.get("command_idempotency_key") or ""),
        "payload_hash": str(body.get("payload_hash") or ""),
    }


def _spot_manual_order_context_from_body(
    body: Mapping[str, Any],
) -> dict[str, Any] | None:
    source = body.get("admission_decision")
    if not isinstance(source, Mapping):
        source = body
    route = str(source.get("route") or MANUAL_ORDER_ROUTE)
    identity_key = str(source.get("identity_key") or "client_order_id")
    service_method = str(source.get("service_method") or MANUAL_ORDER_SERVICE_METHOD)
    identity_value = str(source.get("identity_value") or source.get("client_order_id") or "")
    idempotency_key = str(
        source.get("command_idempotency_key") or source.get("idempotency_key") or ""
    )
    payload_hash = str(source.get("payload_hash") or "")
    if route != MANUAL_ORDER_ROUTE:
        return None
    if identity_key != "client_order_id":
        return None
    if service_method != MANUAL_ORDER_SERVICE_METHOD:
        return None
    if not (identity_value and idempotency_key and payload_hash):
        return None
    return {
        "route": route,
        "method": str(source.get("method") or "POST"),
        "module_id": str(source.get("module_id") or MANUAL_ORDER_MODULE_ID),
        "identity_key": identity_key,
        "identity_value": identity_value,
        "action_class": str(source.get("action_class") or MANUAL_ORDER_ACTION_CLASS),
        "required_permission": str(
            source.get("required_permission") or MANUAL_ORDER_PERMISSION
        ),
        "service_method": service_method,
        "actor_id": str(source.get("actor_id") or "local-operator"),
        "operator_intent": str(source.get("operator_intent") or "read_admin_api"),
        "command_idempotency_key": idempotency_key,
        "payload_hash": payload_hash,
        "source": "request_body",
    }


def _spot_cancel_order_context_from_cancel_request(
    client_order_id: str,
    body: Mapping[str, Any],
    context: AdminMvpRequestContext,
) -> dict[str, Any]:
    payload = {"client_order_id": client_order_id, **dict(body)}
    payload_hash = str(body.get("payload_hash") or _payload_hash(payload))
    return {
        "route": CANCEL_ORDER_ROUTE,
        "method": "POST",
        "module_id": MANUAL_ORDER_MODULE_ID,
        "identity_key": "client_order_id",
        "identity_value": client_order_id,
        "action_class": CANCEL_ORDER_ACTION_CLASS,
        "required_permission": CANCEL_ORDER_PERMISSION,
        "service_method": CANCEL_ORDER_SERVICE_METHOD,
        "actor_id": context.actor_id,
        "operator_intent": context.operator_intent,
        "command_idempotency_key": context.idempotency_key,
        "payload_hash": payload_hash,
        "source": "cancel_request",
    }


def _spot_cancel_order_context_from_body(
    body: Mapping[str, Any],
) -> dict[str, Any] | None:
    source = body.get("proof_context")
    if not isinstance(source, Mapping):
        source = body
    route = str(source.get("route") or CANCEL_ORDER_ROUTE)
    identity_key = str(source.get("identity_key") or "client_order_id")
    service_method = str(source.get("service_method") or CANCEL_ORDER_SERVICE_METHOD)
    identity_value = str(source.get("identity_value") or source.get("client_order_id") or "")
    idempotency_key = str(
        source.get("command_idempotency_key") or source.get("idempotency_key") or ""
    )
    payload_hash = str(source.get("payload_hash") or "")
    if route != CANCEL_ORDER_ROUTE:
        return None
    if identity_key != "client_order_id":
        return None
    if service_method != CANCEL_ORDER_SERVICE_METHOD:
        return None
    if not (identity_value and idempotency_key and payload_hash):
        return None
    return {
        "route": route,
        "method": str(source.get("method") or "POST"),
        "module_id": str(source.get("module_id") or MANUAL_ORDER_MODULE_ID),
        "identity_key": identity_key,
        "identity_value": identity_value,
        "action_class": str(source.get("action_class") or CANCEL_ORDER_ACTION_CLASS),
        "required_permission": str(
            source.get("required_permission") or CANCEL_ORDER_PERMISSION
        ),
        "service_method": service_method,
        "actor_id": str(source.get("actor_id") or "local-operator"),
        "operator_intent": str(source.get("operator_intent") or "read_admin_api"),
        "command_idempotency_key": idempotency_key,
        "payload_hash": payload_hash,
        "source": "request_body",
    }


def _proof_chain_record_key(proof_context: Mapping[str, Any]) -> str:
    material = json.dumps(
        {
            "route": proof_context.get("route"),
            "identity_value": proof_context.get("identity_value"),
            "command_idempotency_key": proof_context.get("command_idempotency_key"),
            "payload_hash": proof_context.get("payload_hash"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _spot_manual_missing_gates(admission: Mapping[str, Any]) -> list[str]:
    return [
        gate
        for gate in SPOT_MANUAL_PROOF_GATES
        if not bool(admission.get(SPOT_MANUAL_PROOF_GATE_FIELDS[gate]))
    ]


def _spot_manual_order_context_from_record(
    record: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if record is None:
        return None
    route = str(record.get("route") or "")
    identity_key = str(record.get("identity_key") or "")
    service_method = str(record.get("service_method") or MANUAL_ORDER_SERVICE_METHOD)
    identity_value = str(record.get("identity_value") or "")
    idempotency_key = str(record.get("command_idempotency_key") or "")
    payload_hash = str(record.get("payload_hash") or "")
    if route != MANUAL_ORDER_ROUTE:
        return None
    if identity_key != "client_order_id":
        return None
    if service_method != MANUAL_ORDER_SERVICE_METHOD:
        return None
    if not (identity_value and idempotency_key and payload_hash):
        return None
    return {
        "route": route,
        "method": str(record.get("method") or "POST"),
        "module_id": str(record.get("module_id") or MANUAL_ORDER_MODULE_ID),
        "identity_key": identity_key,
        "identity_value": identity_value,
        "action_class": str(record.get("action_class") or MANUAL_ORDER_ACTION_CLASS),
        "required_permission": str(
            record.get("required_permission") or MANUAL_ORDER_PERMISSION
        ),
        "service_method": service_method,
        "actor_id": str(
            record.get("actor_id")
            or record.get("decision_actor_id")
            or record.get("requested_by_actor_id")
            or "local-operator"
        ),
        "operator_intent": str(record.get("operator_intent") or "read_admin_api"),
        "command_idempotency_key": idempotency_key,
        "payload_hash": payload_hash,
        "source": "latest_backend_proof_record",
    }


def _spot_cancel_order_context_from_record(
    record: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if record is None:
        return None
    route = str(record.get("route") or "")
    identity_key = str(record.get("identity_key") or "")
    service_method = str(record.get("service_method") or "")
    identity_value = str(record.get("identity_value") or "")
    idempotency_key = str(record.get("command_idempotency_key") or "")
    payload_hash = str(record.get("payload_hash") or "")
    if route != CANCEL_ORDER_ROUTE:
        return None
    if identity_key != "client_order_id":
        return None
    if service_method != CANCEL_ORDER_SERVICE_METHOD:
        return None
    if not (identity_value and idempotency_key and payload_hash):
        return None
    return {
        "route": route,
        "method": str(record.get("method") or "POST"),
        "module_id": str(record.get("module_id") or MANUAL_ORDER_MODULE_ID),
        "identity_key": identity_key,
        "identity_value": identity_value,
        "action_class": str(record.get("action_class") or CANCEL_ORDER_ACTION_CLASS),
        "required_permission": str(
            record.get("required_permission") or CANCEL_ORDER_PERMISSION
        ),
        "service_method": service_method,
        "actor_id": str(record.get("actor_id") or "local-operator"),
        "operator_intent": str(record.get("operator_intent") or "read_admin_api"),
        "command_idempotency_key": idempotency_key,
        "payload_hash": payload_hash,
        "source": "latest_backend_proof_record",
    }


def _spot_command_suite_admission_summary(admission: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": admission.get("status"),
        "allowed": bool(admission.get("allowed")),
        "route": admission.get("route"),
        "method": admission.get("method"),
        "module_id": admission.get("module_id"),
        "identity_key": admission.get("identity_key"),
        "identity_value": admission.get("identity_value"),
        "idempotency_key": admission.get("idempotency_key"),
        "payload_hash": admission.get("payload_hash"),
        "approval_snapshot_present": bool(admission.get("approval_snapshot_present")),
        "approval_snapshot_id": admission.get("approval_snapshot_id"),
        "admission_audit_present": bool(admission.get("admission_audit_present")),
        "admission_audit_id": admission.get("admission_audit_id"),
        "cap_guard_present": bool(admission.get("cap_guard_present")),
        "cap_guard_decision_id": admission.get("cap_guard_decision_id"),
        "reconciliation_plan_present": bool(
            admission.get("reconciliation_plan_present")
        ),
        "reconciliation_plan_id": admission.get("reconciliation_plan_id"),
        "live_execution_service_present": bool(
            admission.get("live_execution_service_present")
        ),
        "live_execution_service_status": admission.get("live_execution_service_status"),
        "blockers": list(admission.get("blockers") or []),
        "evidence": list(admission.get("evidence") or []),
        "browser_authority": admission.get("browser_authority"),
        "live_exchange_submitted": False,
    }


def _spot_cancel_admission_summary(
    cancel_proof: Mapping[str, Any] | None,
    proof_context: Mapping[str, Any],
) -> dict[str, Any]:
    proof_passed = bool(cancel_proof and cancel_proof.get("allowed"))
    return {
        "status": (
            AdminMvpGateStatus.PASSED.value
            if proof_passed
            else AdminMvpGateStatus.BLOCKED.value
        ),
        "allowed": proof_passed,
        "route": proof_context.get("route"),
        "method": proof_context.get("method"),
        "module_id": proof_context.get("module_id"),
        "identity_key": proof_context.get("identity_key"),
        "identity_value": proof_context.get("identity_value"),
        "idempotency_key": proof_context.get("command_idempotency_key"),
        "payload_hash": proof_context.get("payload_hash"),
        "cancel_proof_chain_present": cancel_proof is not None,
        "cancel_proof_chain_id": (
            cancel_proof.get("plan_id") if cancel_proof is not None else None
        ),
        "proof_chain_status": (
            AdminMvpGateStatus.PASSED.value
            if proof_passed
            else AdminMvpGateStatus.BLOCKED.value
        ),
    }


def _spot_cancel_proof_summary(
    cancel_proof: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if cancel_proof is None:
        return None
    return {
        "cancel_proof_chain_id": cancel_proof.get("plan_id"),
        "status": cancel_proof.get("status"),
        "allowed": bool(cancel_proof.get("allowed")),
        "exchange_submission_required": bool(
            cancel_proof.get("exchange_submission_required")
        ),
        "payload_hash": cancel_proof.get("payload_hash"),
    }


def _evidence_refs(*records: dict[str, Any] | None) -> list[str]:
    refs: list[str] = []
    for record in records:
        if not record:
            continue
        for key in ("approval_id", "admission_audit_id", "decision_id", "plan_id"):
            value = record.get(key)
            if value:
                refs.append(str(value))
                break
    return refs


def _default_live_max_submitted_notional(body: Mapping[str, Any]) -> Decimal:
    if _live_decision_targets_futures(body):
        return DEFAULT_FUTURES_MAX_SUBMITTED_NOTIONAL_USDC
    return DEFAULT_MAX_SUBMITTED_NOTIONAL_USDC


def _default_live_max_executed_notional(body: Mapping[str, Any]) -> Decimal:
    if _live_decision_targets_futures(body):
        return DEFAULT_FUTURES_MAX_EXECUTED_NOTIONAL_USDC
    return DEFAULT_MAX_EXECUTED_NOTIONAL_USDC


def _live_decision_targets_futures(body: Mapping[str, Any]) -> bool:
    module_id = str(body.get("target_module_id") or body.get("module_id") or "")
    if module_id == FUTURES_MODULE_ID:
        return True
    if str(body.get("account_family") or "") == FUTURES_ACCOUNT_FAMILY_US_CFM:
        return True
    return any(
        product_id in FUTURES_CONFIGURED_PRODUCT_SCOPE
        for product_id in _string_list(body.get("product_scope"))
    )


def _decimal_value(value: Any, default: Decimal) -> Decimal:
    try:
        if value in (None, ""):
            return default
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def _decimal_text(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.01"))
    return format(normalized, "f")


def _latest_record(records: Mapping[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    return next(reversed(records.values()))


def _latest_matching_record(
    records: Mapping[str, dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
) -> dict[str, Any] | None:
    for record in reversed(list(records.values())):
        if predicate(record):
            return record
    return None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    return [text] if text else []


def _futures_command_routes_mode(
    *,
    missing_contracts: Sequence[str],
    executable_command_count: int,
) -> str:
    if missing_contracts:
        return "backend_admin_api_blocked"
    if executable_command_count:
        return "backend_admin_api_confirmed_live"
    return "backend_admin_api_draft_only"


def _futures_command_suite_next_required_operator_decision(
    *,
    missing_contracts: Sequence[str],
    executable_command_count: int,
    live_decision_summary: Mapping[str, Any],
) -> str:
    """Return the next operator action for Futures command-suite evidence."""

    missing = set(missing_contracts)
    if {
        "futures_account_scope_contract",
        "futures_margin_collateral_risk_proof",
    } & missing:
        return (
            "run_backend_account_reality_live_read_smoke_to_refresh_futures_account_and_risk_evidence"
        )
    product_exposure = _mapping(
        live_decision_summary.get("futures_product_exposure_evidence")
    )
    product_decision = str(
        product_exposure.get("next_required_operator_decision") or ""
    ).strip()
    if product_decision:
        return product_decision
    first_blocker = str(live_decision_summary.get("first_blocker") or "").strip()
    if first_blocker == "futures_executor_live_disabled":
        return "enable_futures_live_runtime_before_confirmed_exchange_submission"
    if executable_command_count > 0:
        return "submit_backend_controlled_futures_command_with_explicit_operator_acknowledgement"
    return "review_backend_futures_command_suite_evidence"


def _futures_live_exchange_command(command: str) -> bool:
    return command in FUTURES_LIVE_EXCHANGE_COMMANDS


def _futures_live_execution_scope(execution_allowed: bool = False) -> dict[str, Any]:
    return {
        "account_family": FUTURES_ACCOUNT_FAMILY_US_CFM,
        "intx_applicability": FUTURES_INTX_APPLICABILITY_US_ACCOUNT,
        "product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
        "execution_allowed": execution_allowed,
    }


def _is_us_cfm_futures_service_decision(record: Mapping[str, Any]) -> bool:
    return (
        _has_us_cfm_futures_scope(record)
        and record.get("status") == AdminMvpGateStatus.PASSED.value
        and bool(record.get("service_enabled"))
        and bool(record.get("live_coinbase_execution_approved"))
    )


def _is_us_cfm_futures_adapter_decision(
    record: Mapping[str, Any],
    *,
    target_route: str,
    target_service_method: str,
) -> bool:
    return (
        _has_us_cfm_futures_scope(record)
        and str(record.get("target_route") or "") == target_route
        and str(record.get("target_method") or "") == "POST"
        and str(record.get("target_service_method") or "") == target_service_method
        and record.get("status") == AdminMvpGateStatus.PASSED.value
        and bool(record.get("adapter_constructed"))
        and bool(record.get("adapter_enabled"))
        and bool(record.get("live_coinbase_execution_approved"))
    )


def _has_us_cfm_futures_scope(record: Mapping[str, Any]) -> bool:
    return (
        str(record.get("target_module_id") or "") == FUTURES_MODULE_ID
        and str(record.get("account_family") or "") == FUTURES_ACCOUNT_FAMILY_US_CFM
        and str(record.get("intx_applicability") or "")
        == FUTURES_INTX_APPLICABILITY_US_ACCOUNT
        and _futures_product_scope_matches(record)
    )


def _futures_product_scope_matches(record: Mapping[str, Any]) -> bool:
    product_scope = _string_list(record.get("product_scope"))
    if not product_scope:
        return True
    return any(product_id in FUTURES_CONFIGURED_PRODUCT_SCOPE for product_id in product_scope)


def _futures_live_decision_summary(
    commands: list[Mapping[str, Any]],
    *,
    live_runtime_ready: bool,
) -> dict[str, Any]:
    evidences = [
        command["readiness_decision"]["live_decision_evidence"] for command in commands
    ]
    service_ready = any(
        evidence["service_decision_status"] == "ready" for evidence in evidences
    )
    ready_adapter_count = sum(
        1 for evidence in evidences if evidence["adapter_decision_status"] == "ready"
    )
    missing_adapter_count = len(evidences) - ready_adapter_count
    first_evidence = evidences[0] if evidences else {}
    executor_boundary_ready = service_ready and missing_adapter_count == 0
    execution_allowed = bool(executor_boundary_ready and live_runtime_ready)
    executor_boundary_status = (
        AdminMvpFuturesExecutorStatus.LIVE_ENABLED.value
        if execution_allowed
        else
        AdminMvpFuturesExecutorStatus.OBSERVED_LIVE_DISABLED.value
        if executor_boundary_ready
        else AdminMvpFuturesExecutorStatus.PENDING_LIVE_DECISION.value
    )
    first_blocker = (
        "none"
        if execution_allowed
        else
        "futures_executor_live_disabled"
        if executor_boundary_ready
        else "execution_disabled"
    )
    return {
        "account_family": FUTURES_ACCOUNT_FAMILY_US_CFM,
        "intx_applicability": FUTURES_INTX_APPLICABILITY_US_ACCOUNT,
        "product_scope": list(FUTURES_CONFIGURED_PRODUCT_SCOPE),
        "service_decision_status": (
            "ready" if service_ready else "missing_matching_us_cfm_service_decision"
        ),
        "matching_service_decision_id": first_evidence.get("matching_service_decision_id"),
        "adapter_decision_ready_count": ready_adapter_count,
        "adapter_decision_missing_count": missing_adapter_count,
        "all_command_adapters_ready": missing_adapter_count == 0,
        "executor_boundary_status": executor_boundary_status,
        "executor_boundary_ready": executor_boundary_ready,
        "executor_boundary_source": (
            FUTURES_EXECUTOR_BOUNDARY_SOURCE if executor_boundary_ready else None
        ),
        "first_blocker": first_blocker,
        "required_evidence_refs": [LIVE_SERVICE_DECISION_ROUTE, LIVE_ADAPTER_DECISION_ROUTE],
        "execution_allowed": execution_allowed,
        "manual_live_acknowledgement_required": execution_allowed,
        "live_runtime_ready": live_runtime_ready,
        "spot_rule_authority": False,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "live_coinbase_orders_ran": False,
    }


def _query_text(query: Mapping[str, Any], key: str) -> str:
    value = query.get(key)
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "")


def _query_values(query: Mapping[str, Any], key: str) -> list[str]:
    value = query.get(key)
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item or "").strip()]


def _query_int(query: Mapping[str, Any], key: str, default: int) -> int:
    try:
        return int(_query_text(query, key) or default)
    except ValueError:
        return default


def _pagination(limit: int, count: int, offset: int) -> dict[str, Any]:
    return {
        "limit": limit,
        "offset": offset,
        "returned_count": count,
        "total_matching_count": count,
        "next_offset": None,
        "has_more": False,
    }


def _page_pagination(
    *,
    limit: int,
    returned_count: int,
    total_count: int,
    offset: int,
) -> dict[str, Any]:
    next_offset = offset + returned_count
    has_more = next_offset < total_count
    return {
        "limit": limit,
        "offset": offset,
        "returned_count": returned_count,
        "total_matching_count": total_count,
        "next_offset": next_offset if has_more else None,
        "has_more": has_more,
    }


def _filter_audit_workbench_events(
    events: list[dict[str, Any]],
    query: Mapping[str, Any],
) -> list[dict[str, Any]]:
    module_filter = _query_text(query, "module")
    filters = {
        "product_id": _query_text(query, "product_id"),
        "position_key": _query_text(query, "position_key"),
        "client_order_id": _query_text(query, "client_order_id"),
        "correlation_id": _query_text(query, "correlation_id"),
        "audit_id": _query_text(query, "audit_id"),
    }
    return [
        event
        for event in events
        if _audit_workbench_module_matches(event.get("module"), module_filter)
        and all(
            not expected or str(event.get(key) or "") == expected
            for key, expected in filters.items()
        )
    ]


def _audit_workbench_module_matches(event_module: Any, expected_module: str | None) -> bool:
    if not expected_module:
        return True
    return _audit_workbench_canonical_module(event_module) == _audit_workbench_canonical_module(
        expected_module
    )


def _audit_workbench_canonical_module(value: Any) -> str:
    module = str(value or "").strip().lower()
    if module in {"orders", "spot", MANUAL_ORDER_MODULE_ID}:
        return "spot"
    return module


def _audit_workbench_module_summary(
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    modules: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        modules.setdefault(str(event.get("module") or "unknown"), []).append(event)
    return [
        {
            "module": module,
            "read_route_count": 1,
            "command_route_count": len(
                {str(event.get("endpoint") or "") for event in module_events}
            ),
            "live_enabled": any(
                bool(event.get("live_exchange_submitted")) for event in module_events
            ),
            "primary_identity": (
                "position_key/product_id/client_order_id"
                if module == FUTURES_MODULE_ID
                else "client_order_id"
                if module == "spot"
                else "backend-defined"
            ),
            "evidence_sources": sorted(
                {str(event.get("source") or "unknown") for event in module_events}
            ),
            "routes": sorted(
                {str(event.get("endpoint") or "") for event in module_events}
            ),
            "notes": (
                "Futures command and executor decisions are read-only audit "
                "evidence; live Coinbase execution remains disabled."
                if module == FUTURES_MODULE_ID
                else (
                    "Spot command decisions are backend-recorded audit evidence; "
                    "exchange order_id is evidence only."
                )
                if module == "spot"
                else "Backend audit evidence."
            ),
        }
        for module, module_events in sorted(modules.items())
    ]


def _first_text(value: Any) -> str | None:
    items = _string_list(value)
    return items[0] if items else None


def _normalize_path(path: str) -> str:
    return "/" + path.strip().split("?", 1)[0].strip("/")


def _futures_command_route_match(path: str) -> dict[str, Any] | None:
    normalized_path = _normalize_path(path)
    if normalized_path == "/api/v1/futures/orders":
        return {"spec": _futures_command_spec("futures_place"), "identity_value": None}
    if (
        normalized_path.startswith("/api/v1/futures/positions/")
        and normalized_path.endswith("/close-reduce")
    ):
        position_key = normalized_path.split("/api/v1/futures/positions/", 1)[1].rsplit(
            "/close-reduce",
            1,
        )[0]
        return {
            "spec": _futures_command_spec("futures_close_reduce"),
            "identity_value": unquote(position_key),
        }
    if (
        normalized_path.startswith("/api/v1/futures/orders/")
        and normalized_path.endswith("/cancel")
    ):
        client_order_id = normalized_path.split("/api/v1/futures/orders/", 1)[1].rsplit(
            "/cancel",
            1,
        )[0]
        return {
            "spec": _futures_command_spec("futures_cancel"),
            "identity_value": unquote(client_order_id),
        }
    if (
        normalized_path.startswith("/api/v1/futures/positions/")
        and normalized_path.endswith("/reconciliation")
    ):
        position_key = normalized_path.split("/api/v1/futures/positions/", 1)[1].rsplit(
            "/reconciliation",
            1,
        )[0]
        return {
            "spec": _futures_command_spec("futures_reconcile"),
            "identity_value": unquote(position_key),
        }
    return None


def _futures_command_spec(command: str) -> Mapping[str, Any]:
    return next(spec for spec in FUTURES_COMMAND_SPECS if spec["command"] == command)


def _last_path_part(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def _read_json_manifest_from_env(env_name: str) -> dict[str, Any]:
    path = os.environ.get(env_name, "").strip()
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _account_reality_live_read_manifest_evidence(
    frontend_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = frontend_manifest.get("backendAccountRealityLiveReadSmoke")
    if not isinstance(evidence, Mapping):
        return {
            "backend_account_reality_live_read_status": "unknown",
            "backend_account_reality_live_read_backend_ref": "unknown",
            "backend_account_reality_live_read_check_count": 0,
            "backend_account_reality_live_read_credentials_present": False,
            "backend_account_reality_live_read_truststore_status": "unknown",
            "backend_account_reality_live_read_live_coinbase_execution": "not_run",
            "backend_account_reality_live_read_notional_usdc": "0",
        }
    return {
        "backend_account_reality_live_read_status": _manifest_text(evidence, "status"),
        "backend_account_reality_live_read_backend_ref": _manifest_text(
            evidence,
            "backendContractRef",
        ),
        "backend_account_reality_live_read_check_count": _manifest_int(
            evidence,
            "checkCount",
        ),
        "backend_account_reality_live_read_credentials_present": _manifest_bool(
            evidence,
            "credentialsPresent",
        ),
        "backend_account_reality_live_read_truststore_status": _manifest_text(
            evidence,
            "truststoreStatus",
        ),
        "backend_account_reality_live_read_live_coinbase_execution": _manifest_text(
            evidence,
            "liveCoinbaseExecution",
            "not_run",
        ),
        "backend_account_reality_live_read_notional_usdc": _manifest_text(
            evidence,
            "notionalUsdc",
            "0",
        ),
    }


def _manifest_text(
    manifest: Mapping[str, Any],
    key: str,
    default: str = "unknown",
) -> str:
    value = manifest.get(key)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _manifest_bool(
    manifest: Mapping[str, Any],
    key: str,
    default: bool = False,
) -> bool:
    value = manifest.get(key)
    return value if isinstance(value, bool) else default


def _manifest_int(
    manifest: Mapping[str, Any],
    key: str,
    default: int = 0,
) -> int:
    value = manifest.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    return default


def _nested_manifest_text(
    manifest: Mapping[str, Any],
    section: str,
    key: str,
    default: str = "unknown",
) -> str:
    value = manifest.get(section)
    if not isinstance(value, Mapping):
        return default
    return _manifest_text(value, key, default)


def _read_capability_module_id(route: str) -> str:
    if route in {
        ACCOUNT_MANAGEMENT_ROUTE,
        ACCOUNT_WALLET_ROUTE,
        ACCOUNT_PRODUCTS_ROUTE,
        ACCOUNT_FEES_ROUTE,
    }:
        return ACCOUNT_MANAGEMENT_MODULE_ID
    if route in FUTURES_READ_ROUTES:
        return FUTURES_MODULE_ID
    return "admin_system_health"


def _read_capability(route: str, module_id: str) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "route": route,
        "method": "GET",
        "availability": "available",
        "live_enabled": False,
        "frontend_safe": True,
        "action_class": "read_only",
        "permission": "analytics:read",
        "required_permission": "analytics:read",
        "shared_method": "read_mvp_contract",
        "idempotency": "not_required",
        "approval": "not_required",
        "caps": "not_required",
        "audit": "read_only",
        "command_contract": False,
        "compatibility_mode": "prod_mvp",
        "parity_test": "tests/regression/test_admin_mvp_api.py",
        "detail": "Read-only backend Admin MVP evidence.",
    }


def _command_capability(
    *,
    route: str,
    action_class: str,
    required_permission: str,
    shared_method: str,
    live_enabled: bool,
    module_id: str | None = None,
) -> dict[str, Any]:
    return {
        "module_id": module_id
        or (MANUAL_ORDER_MODULE_ID if route.startswith("/api/v1/orders") else "admin_system_health"),
        "route": route,
        "method": "POST",
        "availability": "available",
        "live_enabled": live_enabled,
        "frontend_safe": True,
        "action_class": action_class,
        "permission": required_permission,
        "required_permission": required_permission,
        "shared_method": shared_method,
        "idempotency": "required",
        "approval": "required",
        "caps": "required",
        "audit": "required",
        "command_contract": True,
        "compatibility_mode": "backend_admin_api_only",
        "parity_test": "tests/regression/test_admin_mvp_api.py",
        "detail": "Mutating route is backend-owned and auditable.",
    }


def _manual_order_readiness_preconditions(
    *,
    admission: Mapping[str, Any] | None,
    cap_guard: Mapping[str, Any] | None,
    runtime_evidence: Mapping[str, Any],
    live_coinbase_execution_enabled: bool,
    live_service_decision_allows_live: bool,
) -> list[dict[str, Any]]:
    proof_chain_passed = bool(admission and admission.get("allowed"))
    runtime_ready = bool(runtime_evidence.get("live_command_runtime_ready"))
    wallet_ready = _cap_guard_wallet_ready(cap_guard)
    return [
        _spot_command_readiness_precondition(
            precondition="manual_order_proof_chain",
            passed=proof_chain_passed,
            source="backend_proof_chain",
            expected_source="approval_audit_cap_reconciliation_records",
            blocker="manual_order_proof_chain_missing",
            evidence=_evidence_refs_from_mapping(admission),
            detail=(
                "Exact manual-order approval, audit, cap, and reconciliation proof chain passed."
                if proof_chain_passed
                else "Exact manual-order proof chain has not passed."
            ),
        ),
        _spot_command_readiness_precondition(
            precondition="live_service_decision",
            passed=live_service_decision_allows_live,
            source="admin_api_live_service_decision_log",
            expected_source="explicit_backend_live_service_decision",
            blocker="live_service_decision_missing",
            evidence=["/api/v1/admin/live-execution/service-decisions"],
            detail=(
                "Latest backend live-service decision explicitly approves live execution."
                if live_service_decision_allows_live
                else "Backend live-service decision has not approved live execution."
            ),
        ),
        _spot_command_readiness_precondition(
            precondition="backend_live_execution_opt_in",
            passed=live_coinbase_execution_enabled,
            source="backend_runtime_environment",
            expected_source="COINBASE_ADMIN_LIVE_COINBASE_EXECUTION",
            blocker="backend_live_execution_disabled",
            evidence=["application/admin_api/mvp_service.py"],
            detail=(
                "This backend process is explicitly opted in for controlled live execution."
                if live_coinbase_execution_enabled
                else "This backend process has not opted in to controlled live execution."
            ),
        ),
        _spot_command_readiness_precondition(
            precondition="live_command_runtime",
            passed=runtime_ready,
            source=str(
                runtime_evidence.get("live_command_runtime_source")
                or "application/admin_api/mvp_service.py"
            ),
            expected_source="coinbase_rest_client_available",
            blocker=str(
                runtime_evidence.get("live_command_runtime_missing_reason")
                or "live_command_runtime_not_ready"
            ),
            evidence=[str(runtime_evidence.get("live_command_runtime_source") or "")],
            detail=(
                "Backend command runtime has a Coinbase REST client available."
                if runtime_ready
                else "Backend command runtime is not ready for Coinbase REST submission."
            ),
        ),
        _spot_command_readiness_precondition(
            precondition="wallet_inventory",
            passed=wallet_ready,
            source=str(
                cap_guard.get("wallet_check_source")
                if cap_guard is not None
                else ACCOUNT_SNAPSHOT_WALLET_SOURCE
            ),
            expected_source=ACCOUNT_SNAPSHOT_WALLET_SOURCE,
            blocker="wallet_inventory_not_passed",
            evidence=[
                str(cap_guard["decision_id"])
                if cap_guard is not None and cap_guard.get("decision_id")
                else ""
            ],
            detail=(
                "Backend cap/guard evidence includes a passed wallet inventory check."
                if wallet_ready
                else "Backend cap/guard evidence does not include a passed wallet inventory check."
            ),
        ),
    ]


def _cancel_order_readiness_preconditions(
    *,
    cancel_proof: Mapping[str, Any] | None,
    runtime_evidence: Mapping[str, Any],
    live_coinbase_execution_enabled: bool,
    live_service_decision_allows_live: bool,
) -> list[dict[str, Any]]:
    proof_chain_passed = bool(cancel_proof and cancel_proof.get("allowed"))
    runtime_ready = bool(runtime_evidence.get("live_command_runtime_ready"))
    return [
        _spot_command_readiness_precondition(
            precondition="cancel_proof_chain",
            passed=proof_chain_passed,
            source="backend_cancel_proof_chain",
            expected_source="cancel_proof_chain_record",
            blocker="cancel_proof_chain_missing",
            evidence=[
                str(cancel_proof["plan_id"])
                if cancel_proof is not None and cancel_proof.get("plan_id")
                else ""
            ],
            detail=(
                "Exact cancel proof-chain record passed for this client_order_id."
                if proof_chain_passed
                else "Exact cancel proof-chain record has not passed."
            ),
        ),
        _spot_command_readiness_precondition(
            precondition="live_service_decision",
            passed=live_service_decision_allows_live,
            source="admin_api_live_service_decision_log",
            expected_source="explicit_backend_live_service_decision",
            blocker="live_service_decision_missing",
            evidence=["/api/v1/admin/live-execution/service-decisions"],
            detail=(
                "Latest backend live-service decision explicitly approves live execution."
                if live_service_decision_allows_live
                else "Backend live-service decision has not approved live execution."
            ),
        ),
        _spot_command_readiness_precondition(
            precondition="backend_live_execution_opt_in",
            passed=live_coinbase_execution_enabled,
            source="backend_runtime_environment",
            expected_source="COINBASE_ADMIN_LIVE_COINBASE_EXECUTION",
            blocker="backend_live_execution_disabled",
            evidence=["application/admin_api/mvp_service.py"],
            detail=(
                "This backend process is explicitly opted in for controlled live execution."
                if live_coinbase_execution_enabled
                else "This backend process has not opted in to controlled live execution."
            ),
        ),
        _spot_command_readiness_precondition(
            precondition="live_command_runtime",
            passed=runtime_ready,
            source=str(
                runtime_evidence.get("live_command_runtime_source")
                or "application/admin_api/mvp_service.py"
            ),
            expected_source="coinbase_rest_client_available",
            blocker=str(
                runtime_evidence.get("live_command_runtime_missing_reason")
                or "live_command_runtime_not_ready"
            ),
            evidence=[str(runtime_evidence.get("live_command_runtime_source") or "")],
            detail=(
                "Backend command runtime has a Coinbase REST client available."
                if runtime_ready
                else "Backend command runtime is not ready for Coinbase REST submission."
            ),
        ),
    ]


def _cap_guard_wallet_ready(cap_guard: Mapping[str, Any] | None) -> bool:
    if cap_guard is None:
        return False
    if bool(cap_guard.get("allowed")) is not True:
        return False
    if bool(cap_guard.get("wallet_check_required", True)) is False:
        return True
    return str(cap_guard.get("wallet_check_status")) == AdminMvpGateStatus.PASSED.value


def _spot_command_readiness_precondition(
    *,
    precondition: str,
    passed: bool,
    source: str,
    expected_source: str,
    blocker: str,
    evidence: Sequence[str] | None,
    detail: str,
) -> dict[str, Any]:
    return {
        "precondition": precondition,
        "status": (
            AdminMvpGateStatus.PASSED.value if passed else AdminMvpGateStatus.BLOCKED.value
        ),
        "required": True,
        "configured": passed,
        "blocking": not passed,
        "backend_owned": True,
        "route_bound": True,
        "source": source,
        "expected_source": expected_source,
        "blocker": None if passed else blocker,
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "evidence": [item for item in (evidence or []) if item],
        "detail": detail,
    }


def _evidence_refs_from_mapping(record: Mapping[str, Any] | None) -> list[str]:
    if record is None:
        return []
    return [
        str(record[key])
        for key in (
            "approval_snapshot_id",
            "admission_audit_id",
            "cap_guard_decision_id",
            "reconciliation_plan_id",
        )
        if record.get(key)
    ]


def _manual_order_command(
    *,
    admission: Mapping[str, Any] | None = None,
    admission_context: Mapping[str, Any] | None = None,
    readiness_preconditions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    readiness_items = [dict(item) for item in (readiness_preconditions or [])]
    readiness_blocker_count = sum(1 for item in readiness_items if bool(item.get("blocking")))
    readiness_passed_count = sum(
        1 for item in readiness_items if item.get("status") == AdminMvpGateStatus.PASSED.value
    )
    if admission is None:
        missing_gate_chain = list(SPOT_MANUAL_PROOF_GATES)
        resolved_gate_chain: list[str] = []
        proof_chain_status = AdminMvpGateStatus.BLOCKED.value
        live_execution_status = AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value
    else:
        missing_gate_chain = [
            gate
            for gate in SPOT_MANUAL_PROOF_GATES
            if not bool(admission.get(SPOT_MANUAL_PROOF_GATE_FIELDS[gate]))
        ]
        resolved_gate_chain = [
            gate for gate in SPOT_MANUAL_PROOF_GATES if gate not in missing_gate_chain
        ]
        proof_chain_status = (
            AdminMvpGateStatus.PASSED.value
            if not missing_gate_chain
            else AdminMvpGateStatus.BLOCKED.value
        )
        live_execution_status = str(
            admission.get("live_execution_service_status")
            or AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value
        )
    executable = bool(readiness_items) and readiness_blocker_count == 0
    return {
        "mutation_family": "spot_manual_order",
        "route": MANUAL_ORDER_ROUTE,
        "method": "POST",
        "identity_key": "client_order_id",
        "shared_method": MANUAL_ORDER_SERVICE_METHOD,
        "status": "ready" if executable else "blocked",
        "live_execution_status": live_execution_status,
        "live_enabled": True,
        "live_eligible": True,
        "executable": executable,
        "live_adapter_configured": True,
        "proof_chain_status": proof_chain_status,
        "proof_chain_blocker_count": len(missing_gate_chain),
        "resolved_gate_chain": resolved_gate_chain,
        "missing_gate_chain": missing_gate_chain,
        "admission_context": dict(admission_context) if admission_context else None,
        "admission_decision": (
            _spot_command_suite_admission_summary(admission) if admission is not None else None
        ),
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "proof_routes": [
            _proof_route("approval", "/api/v1/admin/approvals/requests", "approval_request_id"),
            _proof_route("admission_audit", "/api/v1/admin/admission-audits", "admission_audit_id"),
            _proof_route("cap_guard", "/api/v1/admin/cap-guard/decisions", "decision_id"),
            _proof_route("reconciliation", "/api/v1/admin/reconciliation/plans", "plan_id"),
        ],
        "readiness_preconditions": readiness_items,
        "readiness_precondition_count": len(readiness_items),
        "blocking_readiness_precondition_count": readiness_blocker_count,
        "passed_readiness_precondition_count": readiness_passed_count,
    }


def _cancel_order_command(
    *,
    cancel_context: Mapping[str, Any] | None = None,
    cancel_proof: Mapping[str, Any] | None = None,
    readiness_preconditions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    readiness_items = [dict(item) for item in (readiness_preconditions or [])]
    readiness_blocker_count = sum(1 for item in readiness_items if bool(item.get("blocking")))
    readiness_passed_count = sum(
        1 for item in readiness_items if item.get("status") == AdminMvpGateStatus.PASSED.value
    )
    missing_gate_chain = [] if cancel_proof is not None else list(SPOT_CANCEL_PROOF_GATES)
    resolved_gate_chain = [
        gate for gate in SPOT_CANCEL_PROOF_GATES if gate not in missing_gate_chain
    ]
    proof_chain_status = (
        AdminMvpGateStatus.PASSED.value
        if not missing_gate_chain
        else AdminMvpGateStatus.BLOCKED.value
    )
    executable = bool(readiness_items) and readiness_blocker_count == 0
    return {
        "mutation_family": "spot_order_cancel",
        "route": CANCEL_ORDER_ROUTE,
        "method": "POST",
        "identity_key": "client_order_id",
        "shared_method": CANCEL_ORDER_SERVICE_METHOD,
        "status": "ready" if executable else "blocked",
        "live_execution_status": (
            AdminMvpLiveServiceStatus.APPROVAL_REQUIRED.value
            if cancel_proof is not None
            else AdminMvpLiveServiceStatus.LIVE_DISABLED.value
        ),
        "live_enabled": executable,
        "live_eligible": cancel_proof is not None,
        "executable": executable,
        "live_adapter_configured": any(
            item.get("precondition") == "live_command_runtime"
            and item.get("status") == AdminMvpGateStatus.PASSED.value
            for item in readiness_items
        ),
        "proof_chain_status": proof_chain_status,
        "proof_chain_blocker_count": len(missing_gate_chain),
        "resolved_gate_chain": resolved_gate_chain,
        "missing_gate_chain": missing_gate_chain,
        "cancel_context": dict(cancel_context) if cancel_context else None,
        "cancel_proof": (
            {
                "cancel_proof_chain_id": cancel_proof.get("plan_id"),
                "status": cancel_proof.get("status"),
                "allowed": bool(cancel_proof.get("allowed")),
                "exchange_submission_required": bool(
                    cancel_proof.get("exchange_submission_required")
                ),
                "live_exchange_submitted": False,
            }
            if cancel_proof is not None
            else None
        ),
        "live_exchange_submitted": False,
        "live_coinbase_orders_ran": False,
        "proof_routes": [
            {
                "gate": "cancel_proof_chain",
                "route": SPOT_CANCEL_ORDER_PROOF_CHAIN_ROUTE,
                "method": "POST",
                "identity_key": "cancel_proof_chain_id",
                "command_identity_key": "client_order_id",
                "shared_method": SPOT_CANCEL_ORDER_PROOF_CHAIN_SERVICE_METHOD,
                "status": "available",
                "browser_authority": "display_only",
                "bff_authority": "forward_only_no_execution",
                "detail": "Backend cancel proof-chain evidence route.",
            }
        ],
        "readiness_preconditions": readiness_items,
        "readiness_precondition_count": len(readiness_items),
        "blocking_readiness_precondition_count": readiness_blocker_count,
        "passed_readiness_precondition_count": readiness_passed_count,
    }


def _proof_route(gate: str, route: str, identity_key: str) -> dict[str, Any]:
    return {
        "gate": gate,
        "route": route,
        "method": "POST",
        "identity_key": identity_key,
        "command_identity_key": "client_order_id",
        "shared_method": gate,
        "status": "available",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "detail": "Backend proof-chain evidence route.",
    }


def _module_registry(
    module_id: str,
    module: str,
    support_status: str,
    evidence_routes: list[str],
) -> dict[str, Any]:
    return {
        "module_id": module_id,
        "module": module,
        "support_status": support_status,
        "read_routes": [f"GET {route}" for route in evidence_routes],
        "command_routes": [],
        "live_routes": [f"POST {MANUAL_ORDER_ROUTE}"] if module_id == "spot_operations" else [],
        "unsupported_actions": [],
        "command_gaps": [],
        "identity_keys": ["client_order_id"] if module_id == "spot_operations" else ["correlation_id"],
        "constraints": [],
        "evidence_routes": evidence_routes,
        "verification": ["tests/regression/test_admin_mvp_api.py"],
        "action_posture": {
            "module_id": module_id,
            "status": support_status,
            "browser_authority": "display_only",
            "bff_authority": "forward_only_no_execution",
        },
    }


def _empty_command_suite(response_type: str) -> dict[str, Any]:
    return {
        "type": response_type,
        "status": "blocked",
        "command_count": 0,
        "blocked_command_count": 0,
        "executable_command_count": 0,
        "live_enabled_command_count": 0,
        "command_route_count": 0,
        "commands": [],
        "coverage_gaps": [],
        "read_only": True,
        "command_routes_mode": "backend_admin_api",
        "browser_authority": "display_only",
        "bff_authority": "forward_only_no_execution",
        "live_coinbase_orders_ran": False,
    }


def _operator_status(response_type: str) -> dict[str, Any]:
    return {
        "type": response_type,
        "status": "warning",
        "operator_status": {
            "status": "warning",
            "latest_run_status": "not_configured",
        },
        "read_only": True,
        "live_coinbase_orders_ran": False,
    }


def _empty_read(path: str) -> dict[str, Any]:
    return {
        "type": "admin_mvp_empty_read",
        "route": path,
        "status": "blocked",
        "read_only": True,
        "live_coinbase_orders_ran": False,
    }


_SERVICE_SINGLETON: AdminMvpService | None = None


def get_admin_mvp_service() -> AdminMvpService:
    """Return the process-local Admin MVP service singleton."""

    global _SERVICE_SINGLETON
    if _SERVICE_SINGLETON is None:
        _SERVICE_SINGLETON = AdminMvpService(
            AdminMvpDependencies(
                rest_client=_load_rest_client(),
                rest_client_available=_rest_client_available(),
                live_coinbase_execution_enabled=live_coinbase_execution_enabled_from_env(),
            )
        )
    return _SERVICE_SINGLETON


def _load_rest_client() -> Any:
    try:
        from configuration import REST_CLIENT

        return REST_CLIENT
    except Exception:
        return None


def _rest_client_available() -> bool:
    return _load_rest_client() is not None
