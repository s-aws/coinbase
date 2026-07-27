"""Backend-owned local coordinator for the Goal 16 Cancel-only sweep."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Mapping

from application.admin_api.operator_spot_safe_closeout_sweep_models import (
    LIVE_AUTHORITY_BLOCKER,
    OperatorSpotSafeCloseoutAllowance,
    OperatorSpotSafeCloseoutCandidate,
    OperatorSpotSafeCloseoutCandidatePage,
    OperatorSpotSafeCloseoutSweepActionRequest,
    OperatorSpotSafeCloseoutSweepCreateRequest,
    OperatorSpotSafeCloseoutSweepReadback,
)
from application.admin_api.operator_spot_safe_closeout_sweep_policy import (
    OperatorSpotSafeCloseoutSweepPolicyError,
    build_operator_spot_safe_closeout_sweep_plan,
)


_OPERATOR_ROLES = frozenset({"admin", "trader"})
_EVIDENCE_ID = re.compile(r"^[A-Za-z0-9._:@|/-]{1,255}$")
_SAFE_CODE = re.compile(r"^operator_spot_sweep_[a-z0-9_]{1,75}$")
_ALLOWANCE_CATEGORIES = (
    "API_KEY_PERMISSIONS",
    "PORTFOLIO_CATALOG",
    "PRE_CANCEL_EXACT_ORDER_READ",
    "CANCEL",
    "POST_CANCEL_EXACT_ORDER_READ",
)
_METHODS = {
    "CREATE": "create_safe_closeout_sweep",
    "PAUSE": "pause_safe_closeout_sweep",
    "RESUME": "resume_safe_closeout_sweep",
    "ABORT": "abort_safe_closeout_sweep",
}
_INTENTS = {
    "CREATE": "create_operator_spot_safe_closeout_sweep",
    "PAUSE": "pause_operator_spot_safe_closeout_sweep",
    "RESUME": "resume_operator_spot_safe_closeout_sweep",
    "ABORT": "abort_operator_spot_safe_closeout_sweep",
}


class OperatorSpotSafeCloseoutSweepError(ValueError):
    """Fixed-code Goal 16 service rejection."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OperatorSpotSafeCloseoutSweepConflict(
    OperatorSpotSafeCloseoutSweepError
):
    """Stale evidence, singleton, lifecycle, or idempotency conflict."""


@dataclass(frozen=True, slots=True)
class OperatorSpotSafeCloseoutSweepCommandContext:
    actor_id: str
    roles: tuple[str, ...]
    correlation_id: str
    idempotency_key: str
    operator_intent: str


class OperatorSpotSafeCloseoutSweepService:
    """Coordinate local-only planning/control; expose no exchange method."""

    def __init__(self, *, repository: Any, candidate_resolver: Any) -> None:
        self.repository = repository
        self.candidate_resolver = candidate_resolver

    def list_safe_closeout_candidates(
        self,
        *,
        limit: int,
        offset: int,
        status_filter: str | None,
        ownership_provenance_filter: str | None,
        can_mutate: bool,
    ) -> OperatorSpotSafeCloseoutCandidatePage:
        candidates, total = self.candidate_resolver.list_candidates(
            limit=limit,
            offset=offset,
            status_filter=status_filter,
            ownership_provenance_filter=(
                ownership_provenance_filter
            ),
        )
        public_candidates = [
            OperatorSpotSafeCloseoutCandidate(
                **_public_candidate(candidate)
            )
            for candidate in candidates
        ]
        goal_bound = bool(self.repository.goal_is_bound())
        return OperatorSpotSafeCloseoutCandidatePage(
            items=public_candidates,
            total=total,
            limit=limit,
            offset=offset,
            status_filter=status_filter,
            ownership_provenance_filter=(
                ownership_provenance_filter
            ),
            configured_portfolio_scope_sha256=(
                self.candidate_resolver
                .configured_portfolio_scope_sha256
            ),
            diagnostic_code=(
                "operator_spot_sweep_goal_already_bound"
                if goal_bound
                else (
                    "operator_spot_sweep_candidates_ready"
                    if total
                    else "operator_spot_sweep_candidates_empty"
                )
            ),
            allowed_actions=(
                ["CREATE_SWEEP"]
                if can_mutate
                and not goal_bound
                and total > 0
                and public_candidates
                else []
            ),
        )

    def get_safe_closeout_sweep(
        self,
        *,
        sweep_id: str,
        can_mutate: bool,
    ) -> OperatorSpotSafeCloseoutSweepReadback:
        row = self.repository.get_plan(sweep_id=sweep_id)
        if row is None:
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_not_found"
            )
        return self._readback(
            row,
            command_service_method="get_safe_closeout_sweep",
            operator_intent=None,
            can_mutate=can_mutate,
        )

    def get_current_safe_closeout_sweep(
        self,
        *,
        can_mutate: bool,
    ) -> OperatorSpotSafeCloseoutSweepReadback:
        row = self.repository.get_current_plan()
        if row is None:
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_not_found"
            )
        return self._readback(
            row,
            command_service_method="get_current_safe_closeout_sweep",
            operator_intent=None,
            can_mutate=can_mutate,
        )

    def create_safe_closeout_sweep(
        self,
        *,
        body: OperatorSpotSafeCloseoutSweepCreateRequest,
        context: OperatorSpotSafeCloseoutSweepCommandContext,
    ) -> OperatorSpotSafeCloseoutSweepReadback:
        self._require_context(context, action="CREATE")
        payload_sha256 = _payload_hash(
            route="/api/v1/spot/safe-closeout-sweeps",
            action="CREATE",
            sweep_id=None,
            body=body.model_dump(mode="json"),
            operator_intent=context.operator_intent,
        )
        with self.repository.command_lock():
            replay = self.repository.get_command_replay(
                action="CREATE",
                sweep_id=None,
                actor_id=context.actor_id,
                correlation_id=context.correlation_id,
                idempotency_key=context.idempotency_key,
                payload_sha256=payload_sha256,
            )
            if replay is not None:
                return self._readback(
                    replay,
                    command_service_method=_METHODS["CREATE"],
                    operator_intent=context.operator_intent,
                )
            selections = [
                (
                    item.client_order_id,
                    item.expected_candidate_evidence_sha256,
                )
                for item in body.items
            ]
            candidates = self.candidate_resolver.resolve_selected(
                selections
            )
            try:
                plan = build_operator_spot_safe_closeout_sweep_plan(
                    candidates=candidates,
                    configured_portfolio_scope_sha256=(
                        self.candidate_resolver
                        .configured_portfolio_scope_sha256
                    ),
                )
            except OperatorSpotSafeCloseoutSweepPolicyError as exc:
                raise OperatorSpotSafeCloseoutSweepConflict(
                    exc.code
                ) from None
            row = self.repository.create_plan(
                plan=plan.to_persisted_payload(),
                plan_sha256=plan.plan_sha256,
                private_exchange_bindings=dict(
                    plan.private_exchange_bindings
                ),
                actor_id=context.actor_id,
                correlation_id=context.correlation_id,
                idempotency_key=context.idempotency_key,
                payload_sha256=payload_sha256,
                operator_reason_sha256=_sha(body.operator_reason),
                operator_intent=context.operator_intent,
            )
        return self._readback(
            row,
            command_service_method=_METHODS["CREATE"],
            operator_intent=context.operator_intent,
        )

    def pause_safe_closeout_sweep(
        self,
        *,
        sweep_id: str,
        body: OperatorSpotSafeCloseoutSweepActionRequest,
        context: OperatorSpotSafeCloseoutSweepCommandContext,
    ) -> OperatorSpotSafeCloseoutSweepReadback:
        return self._local_action(
            sweep_id=sweep_id,
            action="PAUSE",
            body=body,
            context=context,
        )

    def resume_safe_closeout_sweep(
        self,
        *,
        sweep_id: str,
        body: OperatorSpotSafeCloseoutSweepActionRequest,
        context: OperatorSpotSafeCloseoutSweepCommandContext,
    ) -> OperatorSpotSafeCloseoutSweepReadback:
        return self._local_action(
            sweep_id=sweep_id,
            action="RESUME",
            body=body,
            context=context,
        )

    def abort_safe_closeout_sweep(
        self,
        *,
        sweep_id: str,
        body: OperatorSpotSafeCloseoutSweepActionRequest,
        context: OperatorSpotSafeCloseoutSweepCommandContext,
    ) -> OperatorSpotSafeCloseoutSweepReadback:
        return self._local_action(
            sweep_id=sweep_id,
            action="ABORT",
            body=body,
            context=context,
        )

    def _local_action(
        self,
        *,
        sweep_id: str,
        action: str,
        body: OperatorSpotSafeCloseoutSweepActionRequest,
        context: OperatorSpotSafeCloseoutSweepCommandContext,
    ) -> OperatorSpotSafeCloseoutSweepReadback:
        self._require_context(context, action=action)
        payload_sha256 = _payload_hash(
            route=(
                f"/api/v1/spot/safe-closeout-sweeps/"
                f"{sweep_id}/{action.lower()}"
            ),
            action=action,
            sweep_id=sweep_id,
            body=body.model_dump(mode="json"),
            operator_intent=context.operator_intent,
        )
        with self.repository.command_lock():
            replay = self.repository.get_command_replay(
                action=action,
                sweep_id=sweep_id,
                actor_id=context.actor_id,
                correlation_id=context.correlation_id,
                idempotency_key=context.idempotency_key,
                payload_sha256=payload_sha256,
            )
            if replay is not None:
                return self._readback(
                    replay,
                    command_service_method=_METHODS[action],
                    operator_intent=context.operator_intent,
                )
            row = self.repository.apply_local_action(
                sweep_id=sweep_id,
                action=action,
                expected_revision=body.expected_revision,
                expected_plan_sha256=body.expected_plan_sha256,
                actor_id=context.actor_id,
                correlation_id=context.correlation_id,
                idempotency_key=context.idempotency_key,
                payload_sha256=payload_sha256,
                operator_reason_sha256=_sha(body.operator_reason),
                operator_intent=context.operator_intent,
            )
        return self._readback(
            row,
            command_service_method=_METHODS[action],
            operator_intent=context.operator_intent,
        )

    @staticmethod
    def _require_context(
        context: OperatorSpotSafeCloseoutSweepCommandContext,
        *,
        action: str,
    ) -> None:
        if (
            not context.actor_id
            or not set(context.roles).intersection(_OPERATOR_ROLES)
            or _EVIDENCE_ID.fullmatch(context.actor_id) is None
            or _EVIDENCE_ID.fullmatch(context.correlation_id) is None
            or _EVIDENCE_ID.fullmatch(context.idempotency_key) is None
        ):
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_permission_denied"
            )
        if context.operator_intent != _INTENTS[action]:
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_operator_intent_invalid"
            )

    @staticmethod
    def _readback(
        row: Mapping[str, Any],
        *,
        command_service_method: str,
        operator_intent: str | None,
        can_mutate: bool = True,
    ) -> OperatorSpotSafeCloseoutSweepReadback:
        state = str(row.get("state") or "")
        allowed_actions = {
            "READY": ["PAUSE", "ABORT"],
            "PAUSED": ["RESUME", "ABORT"],
            "IN_PROGRESS": [],
            "COMPLETE": [],
            "ABORTED": [],
            "QUARANTINED": [],
        }.get(state)
        if allowed_actions is None:
            raise OperatorSpotSafeCloseoutSweepConflict(
                "operator_spot_sweep_state_invalid"
            )
        local_cycles_used = int(row["local_cycles_used"])
        if local_cycles_used >= 10:
            allowed_actions = []
        items = [
            {
                **dict(item),
                "cancel_allowance_state": "NOT_GRANTED",
                "cancel_allowance_consumed": False,
                "pre_cancel_exact_read_call_count": 0,
                "cancel_call_count": 0,
                "post_cancel_exact_read_call_count": 0,
            }
            for item in list(row.get("items") or [])
        ]
        return OperatorSpotSafeCloseoutSweepReadback(
            sweep_id=str(row["sweep_id"]),
            revision=int(row["revision"]),
            state=state,
            diagnostic_code=_safe_code(
                row.get("diagnostic_code"),
                fallback="operator_spot_sweep_unknown",
            ),
            plan_sha256=str(row["plan_sha256"]),
            configured_portfolio_scope_sha256=str(
                row["configured_portfolio_scope_sha256"]
            ),
            items=items,
            events=list(row.get("events") or []),
            candidate_count=len(items),
            allowed_actions=allowed_actions if can_mutate else [],
            blocker_codes=[LIVE_AUTHORITY_BLOCKER],
            allowances=[
                OperatorSpotSafeCloseoutAllowance(category=category)
                for category in _ALLOWANCE_CATEGORIES
            ],
            local_cycles_used=local_cycles_used,
            partial_result_quarantine=state == "QUARANTINED",
            latest_idempotency_key_sha256=str(
                row["latest_idempotency_key_sha256"]
            ),
            latest_payload_sha256=str(
                row["latest_payload_sha256"]
            ),
            latest_actor_id_sha256=str(
                row["latest_actor_id_sha256"]
            ),
            latest_evidence_sha256=str(
                row["latest_evidence_sha256"]
            ),
            command_replayed=bool(row.get("command_replayed")),
            correlation_id=str(row["correlation_id"]),
            operator_intent=operator_intent,
            command_service_method=command_service_method,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def _public_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: candidate[key]
        for key in (
            "client_order_id",
            "root_client_order_id",
            "product_id",
            "status",
            "ownership_provenance",
            "portfolio_scope_sha256",
            "predecessor_evidence_sha256",
            "candidate_evidence_sha256",
            "created_at",
        )
    }


def _payload_hash(
    *,
    route: str,
    action: str,
    sweep_id: str | None,
    body: Mapping[str, Any],
    operator_intent: str,
) -> str:
    return _canonical_sha(
        {
            "route": route,
            "action": action,
            "sweep_id": sweep_id,
            "body": dict(body),
            "operator_intent": operator_intent,
        }
    )


def _safe_code(value: Any, *, fallback: str) -> str:
    normalized = str(value or "")
    return (
        normalized
        if _SAFE_CODE.fullmatch(normalized) is not None
        else fallback
    )


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_sha(payload: Mapping[str, Any]) -> str:
    return _sha(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


__all__ = [
    "OperatorSpotSafeCloseoutSweepCommandContext",
    "OperatorSpotSafeCloseoutSweepConflict",
    "OperatorSpotSafeCloseoutSweepError",
    "OperatorSpotSafeCloseoutSweepService",
]
