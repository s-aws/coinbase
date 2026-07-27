"""Backend-owned local coordinator for one Reprice Now intent."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from application.admin_api.operator_single_order_reprice_now_models import (
    OperatorSingleOrderRepriceNowIntentPlan,
    OperatorSingleOrderRepriceNowIntentRequest,
    OperatorSingleOrderRepriceNowReadback,
    OperatorSingleOrderRepriceNowSourceSelection,
)
from application.admin_api.operator_single_order_reprice_now_policy import (
    OperatorSingleOrderRepriceNowPolicyError,
    build_single_order_reprice_now_intent,
)


_OPERATOR_ROLES = frozenset({"admin", "trader", "operator"})
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:@|/-]{1,255}$")
_SAFE_CODE = re.compile(r"^operator_reprice_now_[a-z0-9_]{1,75}$")


class OperatorSingleOrderRepriceNowError(ValueError):
    """Fixed-code Goal 15 service error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OperatorSingleOrderRepriceNowConflict(
    OperatorSingleOrderRepriceNowError
):
    """Durable identity, evidence, or idempotency conflict."""


@dataclass(frozen=True, slots=True)
class OperatorSingleOrderRepriceNowCommandContext:
    actor_id: str
    roles: tuple[str, ...]
    correlation_id: str
    idempotency_key: str
    operator_intent: str


class OperatorSingleOrderRepriceNowService:
    """Persist a reviewed identity reservation; never call an exchange."""

    def __init__(
        self,
        *,
        definition_repository: Any,
        repository: Any,
        source_resolver: Any,
    ) -> None:
        self.definition_repository = definition_repository
        self.repository = repository
        self.source_resolver = source_resolver

    def get_single_order_reprice_now(
        self,
        *,
        stealth_order_id: str,
        source_client_order_id: str,
        allow_prepare: bool,
    ) -> OperatorSingleOrderRepriceNowReadback:
        row = self.repository.get_intent(
            stealth_order_id=stealth_order_id,
            source_client_order_id=source_client_order_id,
        )
        if row is None:
            selection = self._resolve_source(
                stealth_order_id=stealth_order_id,
                source_client_order_id=source_client_order_id,
            )
            command_service_method = "get_single_order_reprice_now"
            operator_intent = None
        elif row.get("goal_bound_elsewhere") is True:
            selection = self._goal_bound_selection(
                stealth_order_id=stealth_order_id,
                source_client_order_id=source_client_order_id,
            )
            command_service_method = "get_single_order_reprice_now"
            operator_intent = None
        else:
            selection = row["source_selection"]
            command_service_method = "prepare_reprice_now_intent"
            operator_intent = "prepare_single_order_reprice_now"
        return self._response(
            stealth_order_id=stealth_order_id,
            source_client_order_id=source_client_order_id,
            row=row,
            source_selection=selection,
            allow_prepare=allow_prepare,
            command_service_method=command_service_method,
            operator_intent=operator_intent,
        )

    def prepare_reprice_now_intent(
        self,
        *,
        stealth_order_id: str,
        source_client_order_id: str,
        body: OperatorSingleOrderRepriceNowIntentRequest,
        context: OperatorSingleOrderRepriceNowCommandContext,
    ) -> OperatorSingleOrderRepriceNowReadback:
        self._require_context(context)
        payload_sha256 = _hash_payload(
            {
                "stealth_order_id": stealth_order_id,
                "source_client_order_id": source_client_order_id,
                "expected_definition_revision": (
                    body.expected_definition_revision
                ),
                "expected_definition_sha256": (
                    body.expected_definition_sha256
                ),
                "expected_source_evidence_sha256": (
                    body.expected_source_evidence_sha256
                ),
                "operator_reason_sha256": hashlib.sha256(
                    body.operator_reason.encode()
                ).hexdigest(),
                "confirm_prepare_reprice_now_intent": (
                    body.confirm_prepare_reprice_now_intent
                ),
                "operator_intent": context.operator_intent,
            }
        )
        with self.repository.prepare_lock():
            replay = self.repository.get_intent_replay(
                stealth_order_id=stealth_order_id,
                source_client_order_id=source_client_order_id,
                actor_id=context.actor_id,
                correlation_id=context.correlation_id,
                idempotency_key=context.idempotency_key,
                payload_sha256=payload_sha256,
            )
            if replay is not None:
                return self._response(
                    stealth_order_id=stealth_order_id,
                    source_client_order_id=source_client_order_id,
                    row=replay,
                    source_selection=replay["source_selection"],
                    allow_prepare=False,
                    command_service_method="prepare_reprice_now_intent",
                    operator_intent=context.operator_intent,
                )
            if self.repository.goal_is_bound():
                raise OperatorSingleOrderRepriceNowConflict(
                    "operator_reprice_now_goal_already_bound"
                )
            definition = self.definition_repository.get_definition(
                stealth_order_id
            )
            if (
                int(definition.get("revision") or 0)
                != body.expected_definition_revision
                or str(definition.get("definition_sha256") or "")
                != body.expected_definition_sha256
            ):
                raise OperatorSingleOrderRepriceNowConflict(
                    "operator_reprice_now_definition_binding_conflict"
                )
            selection = self.source_resolver.resolve(
                definition=definition,
                stealth_order_id=stealth_order_id,
                source_client_order_id=source_client_order_id,
            )
            if selection.get("eligible") is not True:
                raise OperatorSingleOrderRepriceNowConflict(
                    _safe_code(
                        selection.get("diagnostic_code"),
                        fallback="operator_reprice_now_source_ineligible",
                    )
                )
            if (
                selection.get("source_evidence_sha256")
                != body.expected_source_evidence_sha256
            ):
                raise OperatorSingleOrderRepriceNowConflict(
                    "operator_reprice_now_source_evidence_conflict"
                )
            try:
                intent = build_single_order_reprice_now_intent(
                    source=selection
                )
            except OperatorSingleOrderRepriceNowPolicyError:
                raise
            intent_payload = {
                **intent.to_persisted_payload(),
                "intent_sha256": intent.intent_sha256,
            }
            row = self.repository.create_intent(
                intent=intent_payload,
                source_selection=dict(selection),
                actor_id=context.actor_id,
                correlation_id=context.correlation_id,
                idempotency_key=context.idempotency_key,
                payload_sha256=payload_sha256,
                operator_reason_sha256=hashlib.sha256(
                    body.operator_reason.encode()
                ).hexdigest(),
            )
        return self._response(
            stealth_order_id=stealth_order_id,
            source_client_order_id=source_client_order_id,
            row=row,
            source_selection=row["source_selection"],
            allow_prepare=False,
            command_service_method="prepare_reprice_now_intent",
            operator_intent=context.operator_intent,
        )

    def _resolve_source(
        self,
        *,
        stealth_order_id: str,
        source_client_order_id: str,
    ) -> dict[str, Any]:
        try:
            definition = self.definition_repository.get_definition(
                stealth_order_id
            )
            return dict(
                self.source_resolver.resolve(
                    definition=definition,
                    stealth_order_id=stealth_order_id,
                    source_client_order_id=source_client_order_id,
                )
            )
        except Exception:
            return {
                "stealth_order_id": stealth_order_id,
                "source_client_order_id": source_client_order_id,
                "found": False,
                "eligible": False,
                "diagnostic_code": (
                    "operator_reprice_now_source_unavailable"
                ),
                "definition_revision": None,
                "definition_sha256": None,
                "root_client_order_id": None,
                "source_status": None,
                "zero_fill_proven": False,
                "system_owned": False,
                "direct_parent": False,
                "source_evidence_sha256": None,
            }

    def _response(
        self,
        *,
        stealth_order_id: str,
        source_client_order_id: str,
        row: Mapping[str, Any] | None,
        source_selection: Mapping[str, Any],
        allow_prepare: bool,
        command_service_method: str,
        operator_intent: str | None = None,
    ) -> OperatorSingleOrderRepriceNowReadback:
        selection = OperatorSingleOrderRepriceNowSourceSelection(
            **dict(source_selection)
        )
        if row is None:
            return OperatorSingleOrderRepriceNowReadback(
                state="UNCONSUMED",
                diagnostic_code=selection.diagnostic_code,
                stealth_order_id=stealth_order_id,
                source_client_order_id=source_client_order_id,
                source_client_order_id_sha256=hashlib.sha256(
                    source_client_order_id.encode()
                ).hexdigest(),
                source_selection=selection,
                allowed_actions=(
                    ["PREPARE_REPRICE_NOW"]
                    if allow_prepare and selection.eligible
                    else []
                ),
                local_cycles_used=0,
                execution_authority_enabled=False,
                command_service_method=command_service_method,
            )
        if row.get("goal_bound_elsewhere") is True:
            return OperatorSingleOrderRepriceNowReadback(
                state="GOAL_ALREADY_BOUND",
                diagnostic_code="operator_reprice_now_goal_already_bound",
                stealth_order_id=stealth_order_id,
                source_client_order_id=source_client_order_id,
                source_client_order_id_sha256=hashlib.sha256(
                    source_client_order_id.encode()
                ).hexdigest(),
                source_selection=selection,
                allowed_actions=[],
                local_cycles_used=int(
                    row.get("local_cycles_used") or 1
                ),
                execution_authority_enabled=False,
                command_service_method="get_single_order_reprice_now",
            )
        raw_intent = dict(row["intent"])
        intent_sha256 = str(
            raw_intent.pop(
                "intent_sha256",
                row.get("intent_sha256") or "",
            )
        )
        successor = str(
            raw_intent["reserved_successor_client_order_id"]
        )
        return OperatorSingleOrderRepriceNowReadback(
            state="INTENT_PREPARED",
            diagnostic_code=_safe_code(
                row.get("diagnostic_code"),
                fallback="operator_reprice_now_intent_prepared",
            ),
            stealth_order_id=stealth_order_id,
            source_client_order_id=source_client_order_id,
            source_client_order_id_sha256=hashlib.sha256(
                source_client_order_id.encode()
            ).hexdigest(),
            reserved_successor_client_order_id=successor,
            reserved_successor_client_order_id_sha256=hashlib.sha256(
                successor.encode()
            ).hexdigest(),
            source_selection=selection,
            intent=OperatorSingleOrderRepriceNowIntentPlan(
                **raw_intent
            ),
            intent_sha256=intent_sha256,
            events=list(row.get("events") or []),
            allowed_actions=[],
            local_cycles_used=int(row.get("local_cycles_used") or 0),
            latest_cycle_idempotency_key_sha256=row.get(
                "latest_cycle_idempotency_key_sha256"
            ),
            latest_cycle_payload_sha256=row.get(
                "latest_cycle_payload_sha256"
            ),
            latest_cycle_actor_id_sha256=row.get(
                "latest_cycle_actor_id_sha256"
            ),
            latest_cycle_evidence_sha256=row.get(
                "latest_cycle_evidence_sha256"
            ),
            execution_authority_enabled=False,
            command_replayed=bool(row.get("command_replayed")),
            correlation_id=row.get("correlation_id"),
            operator_intent=operator_intent,
            command_service_method=command_service_method,
        )

    @staticmethod
    def _goal_bound_selection(
        *,
        stealth_order_id: str,
        source_client_order_id: str,
    ) -> dict[str, Any]:
        return {
            "stealth_order_id": stealth_order_id,
            "source_client_order_id": source_client_order_id,
            "found": False,
            "eligible": False,
            "diagnostic_code": (
                "operator_reprice_now_goal_already_bound"
            ),
            "definition_revision": None,
            "definition_sha256": None,
            "root_client_order_id": None,
            "source_status": None,
            "zero_fill_proven": False,
            "system_owned": False,
            "direct_parent": False,
            "source_evidence_sha256": None,
        }

    @staticmethod
    def _require_context(
        context: OperatorSingleOrderRepriceNowCommandContext,
    ) -> None:
        roles = {str(role).strip().lower() for role in context.roles}
        if not roles.intersection(_OPERATOR_ROLES):
            raise OperatorSingleOrderRepriceNowError(
                "operator_reprice_now_permission_denied"
            )
        if (
            context.operator_intent
            != "prepare_single_order_reprice_now"
        ):
            raise OperatorSingleOrderRepriceNowError(
                "operator_reprice_now_intent_invalid"
            )
        if any(
            _EVIDENCE_ID.fullmatch(str(value or "")) is None
            for value in (
                context.actor_id,
                context.correlation_id,
                context.idempotency_key,
            )
        ):
            raise OperatorSingleOrderRepriceNowError(
                "operator_reprice_now_command_identity_invalid"
            )


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _safe_code(value: Any, *, fallback: str) -> str:
    code = str(value or "")
    return code if _SAFE_CODE.fullmatch(code) is not None else fallback


__all__ = [
    "OperatorSingleOrderRepriceNowCommandContext",
    "OperatorSingleOrderRepriceNowConflict",
    "OperatorSingleOrderRepriceNowError",
    "OperatorSingleOrderRepriceNowService",
]
