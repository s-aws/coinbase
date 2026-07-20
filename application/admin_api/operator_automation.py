"""Operator Automation orchestration and PostgreSQL adaptation.

This module imports no Coinbase SDK, Futures service, or legacy automation
runner. Durable repositories implement the narrow protocol below. The current
adapter is structurally source-gated before every eligibility or exchange
boundary because one canonical read lacks goal authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from typing import Any, Callable, Mapping, Protocol
import uuid

from .automation_models import (
    AutomationControlAction,
    AutomationControlEventItem,
    AutomationControlEventListResponse,
    AutomationControlMutationResponse,
    AutomationControlPlaneItem,
    AutomationControlPlaneResponse,
    AutomationControlRequest,
    AutomationDefinitionCreateRequest,
    AutomationDefinitionDetailResponse,
    AutomationDefinitionEventItem,
    AutomationDefinitionEventListResponse,
    AutomationDefinitionItem,
    AutomationDefinitionLifecycleAction,
    AutomationDefinitionLifecycleRequest,
    AutomationDefinitionListResponse,
    AutomationDefinitionMutationResponse,
    AutomationDefinitionScheduleRequest,
    AutomationDefinitionState,
    AutomationDomain,
    AutomationEligibilityCycleMutationResponse,
    AutomationEligibilityRefreshActivity,
    AutomationEligibilityRefreshRequest,
    AutomationFilters,
    AutomationJobKind,
    AutomationMutationContext,
    AutomationOneShotRunRequest,
    AutomationSingleChildAuthorizationRequest,
    AutomationPagination,
    AutomationRunDetailResponse,
    AutomationRunEventItem,
    AutomationRunEventListResponse,
    AutomationRunFilters,
    AutomationRunItem,
    AutomationRunListResponse,
    AutomationRunMutationActivity,
    AutomationRunMutationResponse,
    AutomationRunState,
    domain_for_job_kind,
)


AUTOMATION_UNAVAILABLE = "automation_control_plane_unavailable"
AUTOMATION_NOT_FOUND = "automation_resource_not_found"


@dataclass(frozen=True)
class AutomationRepositoryPage:
    """One bounded repository page before strict public projection."""

    items: tuple[Mapping[str, Any], ...]
    total_count: int


@dataclass(frozen=True)
class AutomationRepositoryMutation:
    """One authoritative mutation result including replay evidence."""

    entity: Mapping[str, Any]
    audit_id: str
    correlation_id: str
    replayed: bool = False


@dataclass(frozen=True)
class AutomationEligibilityRepositoryMutation(AutomationRepositoryMutation):
    """One run projection plus current-cycle read accounting."""

    coinbase_api_call_count: int | None = 0
    call_count_exact: bool = True


class AutomationRepositoryError(RuntimeError):
    """Fixed repository error; implementations must not include private values."""

    def __init__(self, code: str) -> None:
        self.code = str(code)
        super().__init__(self.code)


class AutomationRepositoryConflict(AutomationRepositoryError):
    pass


class AutomationRepositoryNotFound(AutomationRepositoryError):
    pass


class AutomationRepositoryUnavailable(AutomationRepositoryError):
    pass


class OperatorAutomationRepository(Protocol):
    """Semantic persistence boundary; no route or exchange concepts."""

    def get_control_posture(self) -> Mapping[str, Any]: ...

    def list_definitions(
        self,
        *,
        domain: str | None,
        job_kind: str | None,
        lifecycle_state: str | None,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...

    def get_definition(self, definition_id: str) -> Mapping[str, Any] | None: ...

    def create_definition(
        self,
        *,
        definition: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def transition_definition(
        self,
        *,
        definition_id: str,
        action: AutomationDefinitionLifecycleAction,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def set_schedule(
        self,
        *,
        definition_id: str,
        schedule: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def clear_schedule(
        self,
        *,
        definition_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def transition_control_posture(
        self,
        *,
        action: AutomationControlAction,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def claim_one_shot_run(
        self,
        *,
        definition_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def authorize_single_child(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation: ...

    def refresh_spot_eligibility(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationEligibilityRepositoryMutation: ...

    def list_runs(
        self,
        *,
        definition_id: str | None,
        state: str | None,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...

    def get_run(self, run_id: str) -> Mapping[str, Any] | None: ...

    def list_run_events(
        self,
        *,
        run_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...

    def list_definition_events(
        self,
        *,
        definition_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...

    def list_control_events(
        self,
        *,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage: ...


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _configured_spot_portfolio_hash() -> str:
    from application.admin_api.spot_portfolio_binding import (
        SPOT_PORTFOLIO_ID_ENV,
    )

    portfolio_id = os.environ.get(SPOT_PORTFOLIO_ID_ENV, "").strip()
    if not portfolio_id:
        raise AutomationRepositoryUnavailable(
            "automation_spot_portfolio_not_configured"
        )
    try:
        parsed = uuid.UUID(portfolio_id)
    except (AttributeError, TypeError, ValueError):
        raise AutomationRepositoryUnavailable(
            "automation_spot_portfolio_invalid"
        ) from None
    if str(parsed) != portfolio_id:
        raise AutomationRepositoryUnavailable(
            "automation_spot_portfolio_invalid"
        )
    return hashlib.sha256(portfolio_id.encode("utf-8")).hexdigest()


def _definition_allowed_actions(
    state: AutomationDefinitionState,
) -> list[str]:
    actions: dict[AutomationDefinitionState, list[str]] = {
        AutomationDefinitionState.DRAFT: [
            "ENABLE",
            "DISABLE",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
        ],
        AutomationDefinitionState.ENABLED: [
            "DISABLE",
            "PAUSE",
            "DRAIN",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
            "RUN_ONCE",
        ],
        AutomationDefinitionState.PAUSED: [
            "DISABLE",
            "RESUME",
            "DRAIN",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
        ],
        AutomationDefinitionState.DRAINING: [
            "DISABLE",
            "RESUME",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
        ],
        AutomationDefinitionState.DISABLED: [
            "ENABLE",
            "SET_SCHEDULE",
            "CLEAR_SCHEDULE",
        ],
    }
    return actions[state]


def _control_allowed_actions(posture: Any) -> list[str]:
    actions = {
        "ACTIVE": ["PAUSE", "DRAIN", "SHUTDOWN"],
        "PAUSED": ["RESUME", "DRAIN", "SHUTDOWN"],
        "DRAINING": ["RESUME", "SHUTDOWN"],
        "SHUTDOWN": ["RESUME"],
    }
    return actions[str(getattr(posture, "value", posture))]


class PostgresOperatorAutomationRepositoryAdapter:
    """Adapt typed store records to the narrow Admin API repository protocol."""

    def __init__(
        self,
        repository: Any,
        *,
        spot_eligibility_reader_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.repository = repository
        self._spot_eligibility_reader_factory = spot_eligibility_reader_factory

    @staticmethod
    def _call(operation: Any) -> Any:
        try:
            return operation()
        except Exception as exc:
            from database.operator_automation import (
                AutomationStoreConflict,
                AutomationStoreInvalid,
                AutomationStoreNotFound,
                AutomationStoreUnavailable,
            )

            if isinstance(exc, AutomationStoreConflict):
                raise AutomationRepositoryConflict(exc.code) from None
            if isinstance(exc, AutomationStoreNotFound):
                raise AutomationRepositoryNotFound(exc.code) from None
            if isinstance(
                exc,
                (AutomationStoreInvalid, AutomationStoreUnavailable),
            ):
                raise AutomationRepositoryUnavailable(exc.code) from None
            raise

    @staticmethod
    def _command(
        *,
        context: AutomationMutationContext,
        payload: Mapping[str, Any],
        idempotency_key: str | None = None,
        operator_intent: str | None = None,
    ) -> Any:
        from database.operator_automation import AutomationMutationCommand

        return AutomationMutationCommand(
            idempotency_key=idempotency_key or context.idempotency_key,
            payload_sha256=_payload_sha256(payload),
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            operator_intent=operator_intent or context.operator_intent,
        )

    @staticmethod
    def _control(record: Any) -> Mapping[str, Any]:
        posture = str(getattr(record.posture, "value", record.posture))
        return {
            "posture": posture,
            "local_admission_enabled": posture == "ACTIVE",
            "recurring_worker_started": False,
            "live_scheduler_enabled": False,
            "coinbase_api_call_count": 0,
            "exchange_mutation_count": 0,
            "definition_create_allowed": False,
            "allowed_actions": _control_allowed_actions(record.posture),
            "updated_at": record.updated_at,
        }

    def _definition(
        self,
        record: Any,
        plan: Any | None = None,
        *,
        spot_goal_run_claimed: bool = False,
    ) -> Mapping[str, Any]:
        state = AutomationDefinitionState(
            str(getattr(record.lifecycle_state, "value", record.lifecycle_state))
        )
        schedule_mode = str(
            getattr(record.schedule_kind, "value", record.schedule_kind)
        )
        interval_seconds = record.interval_seconds
        interval_minutes = None
        if interval_seconds is not None:
            if interval_seconds % 60 != 0:
                raise ValueError("automation_schedule_interval_invalid")
            interval_minutes = interval_seconds // 60
        allowed_actions = _definition_allowed_actions(state)
        if record.due_reason == "control_plane_not_active":
            allowed_actions = [
                action for action in allowed_actions if action != "RUN_ONCE"
            ]
        if plan is not None and spot_goal_run_claimed:
            allowed_actions = [
                action for action in allowed_actions if action != "RUN_ONCE"
            ]
        single_child_order = None
        if plan is not None:
            single_child_order = {
                "side": plan.side,
                "base_size": plan.base_size,
                "limit_price": plan.limit_price,
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": plan.post_only,
            }
        return {
            "definition_id": record.definition_id,
            "revision": record.revision,
            "display_name": record.label,
            "domain": str(getattr(record.domain, "value", record.domain)),
            "job_kind": str(getattr(record.job_kind, "value", record.job_kind)),
            "lifecycle_state": state.value,
            "product_ids": list(record.product_ids),
            "single_child_order": single_child_order,
            "schedule": {
                "mode": schedule_mode,
                "interval_minutes": interval_minutes,
                "next_review_at": record.next_review_at,
                "due": record.schedule_due,
            },
            "adapter_status": (
                "UNAVAILABLE"
                if plan is None
                else "SOURCE_GATED"
            ),
            "live_execution_available": False,
            "allowed_actions": allowed_actions,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    def _run(
        self,
        record: Any,
        *,
        eligibility_cycle_number: int | None = None,
    ) -> Mapping[str, Any]:
        plan = None
        attempts: tuple[Any, ...] = ()
        cycles: tuple[Any, ...] = ()
        execution = None
        eligibility_lifetime_call_count: int | None = 0
        eligibility_lifetime_call_count_exact = True
        if (
            str(getattr(record.job_kind, "value", record.job_kind))
            == AutomationJobKind.SPOT_CAMPAIGN.value
            and record.definition_revision is not None
        ):
            plan = self._call(
                lambda: self.repository.get_spot_single_child_plan(
                    record.definition_id,
                    record.definition_revision,
                )
            )
            attempts = self._call(
                lambda: self.repository.list_spot_eligibility_attempts(
                    record.run_id,
                    cycle_number=None,
                )
            )
            cycles = self._call(
                self.repository.list_spot_eligibility_cycles
            )
            execution = self._call(
                lambda: self.repository.get_spot_run_execution(record.run_id)
            )
            eligibility_lifetime_call_count_exact = all(
                attempt.call_count_exact for attempt in attempts
            )
            eligibility_lifetime_call_count = (
                sum(
                    int(attempt.coinbase_api_call_count or 0)
                    for attempt in attempts
                )
                if eligibility_lifetime_call_count_exact
                else None
            )

        run_cycles = tuple(
            cycle
            for cycle in cycles
            if str(getattr(cycle, "run_id", "")) == str(record.run_id)
        )
        if eligibility_cycle_number is None:
            latest_cycle_record = max(
                run_cycles,
                key=lambda cycle: int(cycle.cycle_number),
                default=None,
            )
        else:
            if (
                type(eligibility_cycle_number) is not int
                or not 1 <= eligibility_cycle_number <= 10
            ):
                raise AutomationRepositoryUnavailable(
                    "automation_spot_eligibility_projection_cycle_invalid"
                )
            cycle_matches = tuple(
                cycle
                for cycle in run_cycles
                if int(cycle.cycle_number) == eligibility_cycle_number
            )
            if len(cycle_matches) != 1:
                raise AutomationRepositoryUnavailable(
                    "automation_spot_eligibility_projection_cycle_invalid"
                )
            latest_cycle_record = cycle_matches[0]
        latest_cycle = (
            int(latest_cycle_record.cycle_number)
            if latest_cycle_record is not None
            else None
        )
        current_attempts = tuple(
            attempt
            for attempt in attempts
            if attempt.cycle_number == latest_cycle
        )
        now = datetime.now(timezone.utc)

        def fresh_deadline(value: Any) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                parsed = value
            elif isinstance(value, str):
                try:
                    parsed = datetime.fromisoformat(
                        value.replace("Z", "+00:00")
                    )
                except ValueError:
                    return None
            else:
                return None
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                return None
            return parsed.astimezone(timezone.utc)

        cycle_fresh_until = (
            fresh_deadline(latest_cycle_record.fresh_until)
            if latest_cycle_record is not None
            else None
        )
        current_cycle_fresh = bool(
            latest_cycle_record is not None
            and latest_cycle_record.state == "SUCCEEDED"
            and cycle_fresh_until is not None
            and now < cycle_fresh_until
        )
        plan_readback = None
        if plan is not None:
            portfolio_catalog_proven = any(
                attempt.category == "PORTFOLIO_CATALOG"
                and attempt.allowance_consumed
                and attempt.outcome == "SUCCEEDED"
                and attempt.eligible is True
                and attempt.call_count_exact
                and attempt.coinbase_api_call_count is not None
                and attempt.portfolio_id_sha256
                == plan.portfolio_id_sha256
                and (
                    fresh_deadline(attempt.fresh_until) is not None
                    and now < fresh_deadline(attempt.fresh_until)
                )
                for attempt in current_attempts
            )
            plan_readback = {
                "plan_sha256": plan.plan_sha256,
                "portfolio_scope": (
                    "Test"
                    if portfolio_catalog_proven
                    else "CONFIGURED_UNVERIFIED"
                ),
                "product_id": plan.product_id,
                "side": plan.side,
                "base_size": plan.base_size,
                "limit_price": plan.limit_price,
                "order_type": "LIMIT",
                "time_in_force": "GOOD_UNTIL_CANCELLED",
                "post_only": plan.post_only,
                "submitted_notional_usdc": plan.submitted_notional_usdc,
                "possible_execution_notional_usdc": (
                    plan.possible_execution_notional_usdc
                ),
                "max_submitted_notional_usdc": "3.10",
                "max_possible_execution_notional_usdc": "1.00",
            }

        eligibility = None
        if plan is not None:
            from database.operator_automation import (
                AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES,
            )

            public_category = {
                "API_KEY_PERMISSIONS": "api_key_permissions",
                "PORTFOLIO_CATALOG": "portfolio_catalog",
                "ACCOUNT_WALLET_BALANCES": "wallet_balances",
                "PRODUCT_METADATA": "product_metadata",
                "BEST_BID_ASK": "best_bid_ask",
                "FEE_SUMMARY": "fee_summary",
                "EXACT_ORDER_RECONCILIATION": "exact_order_reconciliation",
            }

            successful_categories = {
                attempt.category
                for attempt in current_attempts
                if attempt.outcome == "SUCCEEDED"
                and attempt.eligible is True
                and attempt.allowance_consumed
                and (
                    attempt.category != "PORTFOLIO_CATALOG"
                    or attempt.portfolio_id_sha256
                    == plan.portfolio_id_sha256
                )
            }
            completed = [
                public_category[category]
                for category in AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
                if category in successful_categories
            ]
            call_count_exact = bool(
                latest_cycle_record is None
                or latest_cycle_record.call_count_exact
            )
            call_count = (
                int(latest_cycle_record.coinbase_api_call_count)
                if latest_cycle_record is not None
                and latest_cycle_record.coinbase_api_call_count is not None
                and call_count_exact
                else (0 if latest_cycle_record is None else None)
            )
            eligible = bool(
                current_attempts
                and successful_categories
                == set(AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES)
                and current_cycle_fresh
            )
            if eligible:
                eligibility_blocker = None
            elif latest_cycle_record is None:
                eligibility_blocker = record.diagnostic_code
            elif latest_cycle_record.state == "OPEN":
                eligibility_blocker = (
                    "automation_spot_eligibility_cycle_in_progress"
                )
            elif (
                latest_cycle_record.state == "SUCCEEDED"
                and not current_cycle_fresh
            ):
                eligibility_blocker = "automation_spot_eligibility_stale"
            else:
                eligibility_blocker = latest_cycle_record.diagnostic_code
            eligibility = {
                "cycle_number": latest_cycle,
                "required_categories": list(
                    public_category[category]
                    for category in AUTOMATION_SPOT_ELIGIBILITY_CATEGORIES
                ),
                "completed_categories": completed,
                "eligible": eligible,
                "blocker_code": eligibility_blocker,
                "coinbase_api_call_count": call_count,
                "call_count_exact": call_count_exact,
            }

        state_value = str(getattr(record.state, "value", record.state))
        adapter_status = {
            AutomationRunState.PREPARING.value: "PREPARING",
            AutomationRunState.AWAITING_OPERATOR_AUTHORIZATION.value: (
                "AWAITING_OPERATOR_AUTHORIZATION"
            ),
            AutomationRunState.BLOCKED.value: "BLOCKED",
            AutomationRunState.INVOCATION_STARTED.value: "INVOCATION_STARTED",
            AutomationRunState.ACTIVE.value: "ACTIVE",
            AutomationRunState.TERMINAL.value: "TERMINAL",
            AutomationRunState.UNKNOWN_CONSUMED.value: "UNKNOWN_CONSUMED",
        }.get(
            state_value,
            "SOURCE_GATED" if plan is not None else "UNAVAILABLE",
        )
        if plan is None:
            adapter_status = "UNAVAILABLE"
        call_count_exact = eligibility_lifetime_call_count_exact
        coinbase_api_call_count: int | None = (
            eligibility_lifetime_call_count
            if plan is not None
            else record.coinbase_api_call_count
        )
        create_call_count: int | None = record.create_call_count
        cancel_call_count: int | None = record.cancel_call_count
        child_terminal = None
        client_order_id = record.client_order_id
        if execution is not None:
            create_call_count = execution.create_call_count
            cancel_call_count = (
                execution.cancel_call_count
                if execution.cancel_allowance_consumed
                else 0
            )
            cancel_call_count_exact = (
                execution.cancel_call_count_exact
                if execution.cancel_allowance_consumed
                else True
            )
            call_count_exact = bool(
                eligibility_lifetime_call_count_exact
                and eligibility_lifetime_call_count is not None
                and execution.create_call_count_exact
                and cancel_call_count_exact
            )
            coinbase_api_call_count = (
                int(eligibility_lifetime_call_count or 0)
                + int(execution.create_call_count or 0)
                + int(execution.cancel_call_count or 0)
                if call_count_exact
                else None
            )
            child_terminal = execution.child_terminal
            client_order_id = execution.client_order_id
        elif (
            record.state is AutomationRunState.UNKNOWN_CONSUMED
            and execution is None
        ):
            call_count_exact = False
            coinbase_api_call_count = None
            create_call_count = None
            cancel_call_count = 0

        live_execution_available = False
        refresh_available = bool(
            plan is not None
            and record.state is AutomationRunState.BLOCKED
            and record.diagnostic_code
            == "automation_active_order_catalog_read_not_authorized"
            and execution is None
            and not record.live_attempt_consumed
            and len(cycles) < 10
            and not any(cycle.state == "OPEN" for cycle in cycles)
        )

        return {
            "run_id": record.run_id,
            "definition_id": record.definition_id,
            "domain": str(getattr(record.domain, "value", record.domain)),
            "job_kind": str(getattr(record.job_kind, "value", record.job_kind)),
            "trigger": "ONE_SHOT",
            "state": state_value,
            "diagnostic_code": record.diagnostic_code,
            "adapter_status": adapter_status,
            "live_execution_available": live_execution_available,
            "live_attempt_consumed": record.live_attempt_consumed,
            "coinbase_api_call_count": coinbase_api_call_count,
            "create_call_count": create_call_count,
            "cancel_call_count": cancel_call_count,
            "call_count_exact": call_count_exact,
            "client_order_id": client_order_id,
            "child_terminal": child_terminal,
            "single_child_plan": plan_readback,
            "eligibility": eligibility,
            "allowed_actions": (
                ["AUTHORIZE_SINGLE_CHILD"]
                if live_execution_available
                else (["REFRESH_ELIGIBILITY"] if refresh_available else [])
            ),
            "audit_id": record.audit_id,
            "correlation_id": record.correlation_id,
            "claimed_at": record.claimed_at,
            "updated_at": record.updated_at,
        }

    @staticmethod
    def _event(record: Any) -> Mapping[str, Any]:
        return {
            "event_id": record.event_id,
            "run_id": record.run_id,
            "sequence": record.sequence,
            "from_state": (
                str(getattr(record.from_state, "value", record.from_state))
                if record.from_state is not None
                else None
            ),
            "state": str(getattr(record.to_state, "value", record.to_state)),
            "diagnostic_code": record.diagnostic_code,
            "audit_id": record.audit_id,
            "correlation_id": record.correlation_id,
            "recorded_at": record.recorded_at,
        }

    @staticmethod
    def _lifecycle_event(record: Any) -> Mapping[str, Any]:
        event = {
            "event_id": record.event_id,
            "from_state": record.from_state,
            "to_state": record.to_state,
            "diagnostic_code": record.diagnostic_code,
            "audit_id": record.audit_id,
            "correlation_id": record.correlation_id,
            "recorded_at": record.recorded_at,
        }
        if record.definition_id is not None:
            event["definition_id"] = record.definition_id
        return event

    @staticmethod
    def _mutation(result: Any, projector: Any) -> AutomationRepositoryMutation:
        return AutomationRepositoryMutation(
            entity=projector(result.entity),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def _spot_plan_for_record(self, record: Any) -> Any | None:
        """Read the exact plan revision already committed with the definition."""

        if record.job_kind is not AutomationJobKind.SPOT_CAMPAIGN:
            return None
        return self._call(
            lambda: self.repository.get_spot_single_child_plan(
                record.definition_id,
                record.revision,
            )
        )

    def _definition_with_plan(
        self,
        record: Any,
        *,
        spot_goal_run_claimed: bool,
    ) -> Mapping[str, Any]:
        plan = None
        if record.job_kind is AutomationJobKind.SPOT_CAMPAIGN:
            plan = self._call(
                lambda: self.repository.get_spot_single_child_plan(
                    record.definition_id,
                    record.revision,
                )
            )
        return self._definition(
            record,
            plan,
            spot_goal_run_claimed=spot_goal_run_claimed,
        )

    def get_control_posture(self) -> Mapping[str, Any]:
        record = self._call(self.repository.get_control_posture)
        return self._control(record)

    def list_definitions(
        self,
        *,
        domain: str | None,
        job_kind: str | None,
        lifecycle_state: str | None,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        spot_goal_run_claimed = self._call(
            self.repository.has_spot_single_child_run
        )
        page = self._call(
            lambda: self.repository.list_definitions(
                domain=AutomationDomain(domain) if domain is not None else None,
                job_kind=(
                    AutomationJobKind(job_kind) if job_kind is not None else None
                ),
                lifecycle_state=(
                    AutomationDefinitionState(lifecycle_state)
                    if lifecycle_state is not None
                    else None
                ),
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(
                self._definition_with_plan(
                    item,
                    spot_goal_run_claimed=spot_goal_run_claimed,
                )
                for item in page.items
            ),
            total_count=page.total_count,
        )

    def get_definition(self, definition_id: str) -> Mapping[str, Any] | None:
        record = self._call(lambda: self.repository.get_definition(definition_id))
        if record is None:
            return None
        return self._definition_with_plan(
            record,
            spot_goal_run_claimed=self._call(
                self.repository.has_spot_single_child_run
            ),
        )

    def create_definition(
        self,
        *,
        definition: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        from database.operator_automation import AutomationDefinitionCreateCommand

        single_child = definition.get("single_child_order")
        portfolio_id_sha256 = (
            _configured_spot_portfolio_hash()
            if single_child is not None
            else None
        )
        command = AutomationDefinitionCreateCommand(
            idempotency_key=context.idempotency_key,
            payload_sha256=_payload_sha256(
                {"operation": "create_definition", "definition": definition}
            ),
            actor_id=context.actor_id,
            correlation_id=context.correlation_id,
            operator_intent=context.operator_intent,
            domain=AutomationDomain(str(definition["domain"])),
            job_kind=AutomationJobKind(str(definition["job_kind"])),
            label=str(definition["display_name"]),
            product_ids=tuple(str(item) for item in definition.get("product_ids", [])),
        )
        plan = None
        if single_child is not None:
            from database.operator_automation import (
                AutomationSpotSingleChildPlanTerms,
            )

            assert portfolio_id_sha256 is not None
            base_size = Decimal(str(single_child["base_size"]))
            limit_price = Decimal(str(single_child["limit_price"]))
            submitted = base_size * limit_price
            plan_terms = AutomationSpotSingleChildPlanTerms(
                portfolio_id_sha256=portfolio_id_sha256,
                product_id="BTC-USDC",
                side=str(single_child["side"]),
                base_size=str(single_child["base_size"]),
                limit_price=str(single_child["limit_price"]),
                submitted_notional_usdc=str(submitted),
                possible_execution_notional_usdc=str(submitted),
                max_submitted_notional_usdc="3.10",
                max_possible_execution_notional_usdc="1.00",
                post_only=bool(single_child["post_only"]),
            )
            result = self._call(
                lambda: self.repository.create_definition(
                    command,
                    spot_single_child_plan=plan_terms,
                )
            )
            plan = self._spot_plan_for_record(result.entity)
        else:
            result = self._call(lambda: self.repository.create_definition(command))
        return AutomationRepositoryMutation(
            entity=self._definition(
                result.entity,
                plan,
                spot_goal_run_claimed=(
                    self._call(self.repository.has_spot_single_child_run)
                    if plan is not None
                    else False
                ),
            ),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def transition_definition(
        self,
        *,
        definition_id: str,
        action: AutomationDefinitionLifecycleAction,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        command = self._command(
            context=context,
            payload={
                "operation": "transition_definition",
                "definition_id": definition_id,
                "action": action.value,
                "request": request,
            },
        )
        result = self._call(
            lambda: self.repository.transition_definition(
                definition_id,
                action.value.lower(),
                command,
            )
        )
        plan = self._spot_plan_for_record(result.entity)
        return AutomationRepositoryMutation(
            entity=self._definition(
                result.entity,
                plan,
                spot_goal_run_claimed=(
                    self._call(self.repository.has_spot_single_child_run)
                    if plan is not None
                    else False
                ),
            ),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def set_schedule(
        self,
        *,
        definition_id: str,
        schedule: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        from core.enums import OperatorAutomationScheduleKind

        mode = OperatorAutomationScheduleKind(str(schedule["mode"]))
        interval_minutes = schedule.get("interval_minutes")
        interval_seconds = (
            int(interval_minutes) * 60 if interval_minutes is not None else None
        )
        command = self._command(
            context=context,
            payload={
                "operation": "set_schedule",
                "definition_id": definition_id,
                "schedule": schedule,
            },
        )
        result = self._call(
            lambda: self.repository.set_schedule(
                definition_id,
                mode,
                interval_seconds=interval_seconds,
                command=command,
            )
        )
        plan = self._spot_plan_for_record(result.entity)
        return AutomationRepositoryMutation(
            entity=self._definition(
                result.entity,
                plan,
                spot_goal_run_claimed=(
                    self._call(self.repository.has_spot_single_child_run)
                    if plan is not None
                    else False
                ),
            ),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def clear_schedule(
        self,
        *,
        definition_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        command = self._command(
            context=context,
            payload={
                "operation": "clear_schedule",
                "definition_id": definition_id,
                "request": request,
            },
        )
        result = self._call(
            lambda: self.repository.clear_schedule(definition_id, command)
        )
        plan = self._spot_plan_for_record(result.entity)
        return AutomationRepositoryMutation(
            entity=self._definition(
                result.entity,
                plan,
                spot_goal_run_claimed=(
                    self._call(self.repository.has_spot_single_child_run)
                    if plan is not None
                    else False
                ),
            ),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def transition_control_posture(
        self,
        *,
        action: AutomationControlAction,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        command = self._command(
            context=context,
            payload={
                "operation": "transition_control_posture",
                "action": action.name,
                "request": request,
            },
        )
        result = self._call(
            lambda: self.repository.transition_control_posture(
                action.name.lower(),
                command,
            )
        )
        return self._mutation(result, self._control)

    def claim_one_shot_run(
        self,
        *,
        definition_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        claim_command = self._command(
            context=context,
            payload={
                "operation": "claim_one_shot_run",
                "definition_id": definition_id,
                "request": request,
            },
        )
        claim = self._call(
            lambda: self.repository.claim_one_shot_run(
                definition_id,
                claim_command,
            )
        )
        current_claim = claim.entity
        if claim.replayed:
            current = self._call(
                lambda: self.repository.get_run(claim.entity.run_id)
            )
            if current is None:
                raise AutomationRepositoryUnavailable(
                    "automation_run_readback_unavailable"
                )
            current_claim = current
            if current.state not in {
                AutomationRunState.CLAIMED,
                AutomationRunState.PREPARING,
            }:
                return AutomationRepositoryMutation(
                    entity=self._run(current),
                    audit_id=current.audit_id,
                    correlation_id=claim.correlation_id,
                    replayed=True,
                )
        if (
            current_claim.job_kind is AutomationJobKind.SPOT_CAMPAIGN
            and current_claim.definition_revision is not None
        ):
            plan = self._call(
                lambda: self.repository.get_spot_single_child_plan(
                    current_claim.definition_id,
                    current_claim.definition_revision,
                )
            )
            if plan is not None:
                prepare_key = "automation-internal-prepare-" + hashlib.sha256(
                    f"{context.idempotency_key}:{current_claim.run_id}".encode(
                        "utf-8"
                    )
                ).hexdigest()
                prepare_command = self._command(
                    context=context,
                    idempotency_key=prepare_key,
                    operator_intent="prepare_automation_single_child_run",
                    payload={
                        "operation": "prepare_automation_single_child_run",
                        "run_id": current_claim.run_id,
                        "plan_sha256": plan.plan_sha256,
                    },
                )
                if current_claim.state is AutomationRunState.CLAIMED:
                    prepared = self._call(
                        lambda: self.repository.transition_run(
                            current_claim.run_id,
                            AutomationRunState.PREPARING,
                            diagnostic_code="preparing",
                            command=prepare_command,
                        )
                    )
                    current_claim = prepared.entity
                diagnostic_code = (
                    "automation_active_order_catalog_read_not_authorized"
                )
            else:
                diagnostic_code = "automation_single_child_plan_missing"
            block_key = "automation-internal-single-child-block-" + hashlib.sha256(
                f"{context.idempotency_key}:{current_claim.run_id}:{diagnostic_code}".encode(
                    "utf-8"
                )
            ).hexdigest()
            block_command = self._command(
                context=context,
                idempotency_key=block_key,
                operator_intent="block_automation_single_child_preflight",
                payload={
                    "operation": "block_automation_single_child_preflight",
                    "run_id": current_claim.run_id,
                    "diagnostic_code": diagnostic_code,
                },
            )
            blocked = self._call(
                lambda: self.repository.transition_run(
                    current_claim.run_id,
                    AutomationRunState.BLOCKED,
                    diagnostic_code=diagnostic_code,
                    command=block_command,
                )
            )
            return AutomationRepositoryMutation(
                entity=self._run(blocked.entity),
                audit_id=blocked.audit_id,
                correlation_id=blocked.correlation_id,
                replayed=claim.replayed,
            )
        internal_key = "automation-internal-block-" + hashlib.sha256(
            f"{context.idempotency_key}:{claim.entity.run_id}".encode("utf-8")
        ).hexdigest()
        block_command = self._command(
            context=context,
            idempotency_key=internal_key,
            operator_intent="finalize_automation_domain_adapter_unavailable",
            payload={
                "operation": "block_unavailable_domain_adapter",
                "run_id": claim.entity.run_id,
            },
        )
        blocked = self._call(
            lambda: self.repository.transition_run(
                claim.entity.run_id,
                AutomationRunState.BLOCKED,
                diagnostic_code="automation_domain_adapter_unavailable",
                command=block_command,
            )
        )
        return AutomationRepositoryMutation(
            entity=self._run(blocked.entity),
            audit_id=blocked.audit_id,
            correlation_id=blocked.correlation_id,
            replayed=claim.replayed,
        )

    def authorize_single_child(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        """Fail closed before any invocation when the canonical read is out of scope.

        The domain-owned Spot placement service retains its account-wide open-order
        guard.  This goal's enumerated read authority does not include that catalog
        read, so an exact authorization can be validated but cannot cross the
        exchange-call boundary.
        """

        record = self._call(lambda: self.repository.get_run(run_id))
        if record is None:
            raise AutomationRepositoryNotFound(AUTOMATION_NOT_FOUND)
        if (
            record.job_kind is not AutomationJobKind.SPOT_CAMPAIGN
            or record.definition_revision is None
        ):
            raise AutomationRepositoryConflict(
                "automation_single_child_run_ineligible"
            )
        plan = self._call(
            lambda: self.repository.get_spot_single_child_plan(
                record.definition_id,
                record.definition_revision,
            )
        )
        if plan is None:
            raise AutomationRepositoryConflict(
                "automation_single_child_plan_missing"
            )
        audit_command = self._command(
            context=context,
            payload={
                "operation": "audit_automation_spot_source_gate_authorization",
                "run_id": run_id,
                "request": request,
            },
        )
        self._call(
            lambda: self.repository.audit_spot_source_gate_authorization(
                run_id,
                expected_plan_sha256=str(
                    request.get("expected_plan_sha256", "")
                ),
                command=audit_command,
            )
        )
        raise AutomationRepositoryConflict(
            "automation_active_order_catalog_read_not_authorized"
        )

    def refresh_spot_eligibility(
        self,
        *,
        run_id: str,
        request: Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationEligibilityRepositoryMutation:
        """Run one exact seven-category cycle and restore the source gate."""

        record = self._call(lambda: self.repository.get_run(run_id))
        if record is None:
            raise AutomationRepositoryNotFound(AUTOMATION_NOT_FOUND)
        source_gate_restored = bool(
            record.state is AutomationRunState.BLOCKED
            and record.diagnostic_code
            == "automation_active_order_catalog_read_not_authorized"
        )
        newer_cycle_in_progress = bool(
            record.state is AutomationRunState.PREPARING
            and record.diagnostic_code == "automation_spot_source_gate_resumed"
        )
        if (
            record.job_kind is not AutomationJobKind.SPOT_CAMPAIGN
            or record.definition_revision is None
            or not (source_gate_restored or newer_cycle_in_progress)
            or record.live_attempt_consumed
        ):
            raise AutomationRepositoryConflict(
                "automation_spot_eligibility_run_ineligible"
            )
        plan = self._call(
            lambda: self.repository.get_spot_single_child_plan(
                record.definition_id,
                record.definition_revision,
            )
        )
        if plan is None:
            raise AutomationRepositoryConflict(
                "automation_single_child_plan_missing"
            )
        if request.get("expected_plan_sha256") != plan.plan_sha256:
            raise AutomationRepositoryConflict(
                "automation_single_child_plan_mismatch"
            )
        from application.admin_api.operator_spot_eligibility import (
            SpotEligibilityCoordinator,
            SpotEligibilityCoordinatorConflict,
            SpotEligibilityRunContext,
        )
        from application.admin_api.operator_spot_eligibility_postgres import (
            PostgresSpotEligibilityLedger,
        )
        from application.admin_api.operator_spot_eligibility_reader import (
            SpotEligibilityPlanTerms,
        )

        run_context = SpotEligibilityRunContext(
            run_id=str(record.run_id),
            definition_id=str(record.definition_id),
            definition_revision=int(record.definition_revision),
            plan_sha256=plan.plan_sha256,
            portfolio_id_sha256=plan.portfolio_id_sha256,
            correlation_id=context.correlation_id,
        )
        plan_terms = SpotEligibilityPlanTerms(
            plan_sha256=plan.plan_sha256,
            product_id=plan.product_id,
            side=plan.side,
            base_size=plan.base_size,
            limit_price=plan.limit_price,
            submitted_notional_usdc=plan.submitted_notional_usdc,
            possible_execution_notional_usdc=(
                plan.possible_execution_notional_usdc
            ),
            max_submitted_notional_usdc=(
                plan.max_submitted_notional_usdc
            ),
            max_possible_execution_notional_usdc=(
                plan.max_possible_execution_notional_usdc
            ),
            post_only=plan.post_only,
        )
        def build_reader() -> Any:
            if self._spot_eligibility_reader_factory is None:
                raise RuntimeError(
                    "automation_spot_eligibility_reader_unavailable"
                )
            return self._spot_eligibility_reader_factory(
                expected_context=run_context,
                plan=plan_terms,
            )
        ledger = PostgresSpotEligibilityLedger(
            repository=self.repository,
            mutation_context=context,
            request_payload=request,
        )
        try:
            cycle_result = self._call(
                lambda: SpotEligibilityCoordinator(
                    ledger=ledger,
                    reader_factory=build_reader,
                ).run(run_context)
            )
        except SpotEligibilityCoordinatorConflict as exc:
            raise AutomationRepositoryConflict(exc.code) from None

        current = self._call(lambda: self.repository.get_run(run_id))
        if current is None:
            raise AutomationRepositoryUnavailable(
                "automation_spot_eligibility_result_unavailable"
            )
        cycles = self._call(self.repository.list_spot_eligibility_cycles)
        matches = tuple(
            cycle
            for cycle in cycles
            if str(cycle.run_id) == run_id
            and int(cycle.cycle_number) == cycle_result.cycle_number
        )
        open_cycles = tuple(
            cycle
            for cycle in cycles
            if cycle.state == "OPEN"
        )
        source_gate_restored = bool(
            current.state is AutomationRunState.BLOCKED
            and current.diagnostic_code
            == "automation_active_order_catalog_read_not_authorized"
        )
        terminal_result_during_newer_cycle = bool(
            current.state is AutomationRunState.PREPARING
            and current.diagnostic_code == "automation_spot_source_gate_resumed"
            and len(open_cycles) == 1
            and str(open_cycles[0].run_id) == run_id
            and int(open_cycles[0].cycle_number) > cycle_result.cycle_number
            and open_cycles[0].plan_sha256 == plan.plan_sha256
        )
        if (
            len(matches) != 1
            or matches[0].state != cycle_result.outcome.value
            or not (source_gate_restored or terminal_result_during_newer_cycle)
        ):
            raise AutomationRepositoryUnavailable(
                "automation_spot_eligibility_result_unavailable"
            )
        cycle = matches[0]
        return AutomationEligibilityRepositoryMutation(
            entity=self._run(
                current,
                eligibility_cycle_number=cycle_result.cycle_number,
            ),
            audit_id=cycle.audit_id,
            correlation_id=cycle.correlation_id,
            replayed=cycle_result.replayed,
            coinbase_api_call_count=cycle_result.coinbase_api_call_count,
            call_count_exact=cycle_result.call_count_exact,
        )

    def resume_spot_source_gated_run(
        self,
        *,
        run_id: str,
        expected_plan_sha256: str,
        context: AutomationMutationContext,
    ) -> AutomationRepositoryMutation:
        """Expose a repository-only continuation primitive to future wiring."""

        command = self._command(
            context=context,
            payload={
                "operation": "resume_automation_spot_source_gated_run",
                "run_id": run_id,
                "expected_plan_sha256": expected_plan_sha256,
            },
        )
        result = self._call(
            lambda: self.repository.resume_spot_source_gated_run(
                run_id,
                expected_plan_sha256=expected_plan_sha256,
                command=command,
            )
        )
        entity = getattr(result.entity, "run", result.entity)
        return AutomationRepositoryMutation(
            entity=self._run(entity),
            audit_id=result.audit_id,
            correlation_id=result.correlation_id,
            replayed=result.replayed,
        )

    def list_runs(
        self,
        *,
        definition_id: str | None,
        state: str | None,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        page = self._call(
            lambda: self.repository.list_runs(
                definition_id=definition_id,
                state=AutomationRunState(state) if state is not None else None,
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(self._run(item) for item in page.items),
            total_count=page.total_count,
        )

    def get_run(self, run_id: str) -> Mapping[str, Any] | None:
        record = self._call(lambda: self.repository.get_run(run_id))
        return self._run(record) if record is not None else None

    def list_run_events(
        self,
        *,
        run_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        page = self._call(
            lambda: self.repository.list_run_events(
                run_id,
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(self._event(item) for item in page.items),
            total_count=page.total_count,
        )

    def list_definition_events(
        self,
        *,
        definition_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        page = self._call(
            lambda: self.repository.list_definition_events(
                definition_id,
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(self._lifecycle_event(item) for item in page.items),
            total_count=page.total_count,
        )

    def list_control_events(
        self,
        *,
        limit: int,
        offset: int,
    ) -> AutomationRepositoryPage:
        page = self._call(
            lambda: self.repository.list_control_events(
                limit=limit,
                offset=offset,
            )
        )
        return AutomationRepositoryPage(
            items=tuple(self._lifecycle_event(item) for item in page.items),
            total_count=page.total_count,
        )


@dataclass(frozen=True)
class OperatorAutomationError(RuntimeError):
    """Value-blind public error classification."""

    code: str
    http_status_code: int

    def __str__(self) -> str:
        return self.code


def _pagination(*, page: AutomationRepositoryPage, limit: int, offset: int) -> AutomationPagination:
    if type(page.total_count) is not int or page.total_count < 0:
        raise ValueError("automation_repository_total_invalid")
    count = len(page.items)
    page_end = offset + count
    if count > limit or page.total_count < page_end:
        raise ValueError("automation_repository_page_invalid")
    has_more = page_end < page.total_count
    if has_more and count != limit:
        raise ValueError("automation_repository_partial_page_invalid")
    return AutomationPagination(
        limit=limit,
        offset=offset,
        returned_count=count,
        total_matching_count=page.total_count,
        next_offset=page_end if has_more else None,
        has_more=has_more,
    )


class OperatorAutomationService:
    """Validate repository evidence and expose fixed, local-only contracts."""

    def __init__(self, repository: OperatorAutomationRepository) -> None:
        self.repository = repository

    @staticmethod
    def _translate_error(exc: BaseException) -> OperatorAutomationError:
        if isinstance(exc, AutomationRepositoryConflict):
            return OperatorAutomationError(exc.code, 409)
        if isinstance(exc, AutomationRepositoryNotFound):
            return OperatorAutomationError(exc.code, 404)
        if isinstance(exc, AutomationRepositoryUnavailable):
            return OperatorAutomationError(exc.code, 503)
        return OperatorAutomationError(AUTOMATION_UNAVAILABLE, 503)

    def get_control_plane(self) -> AutomationControlPlaneResponse:
        try:
            item = AutomationControlPlaneItem.model_validate(
                self.repository.get_control_posture()
            )
            return AutomationControlPlaneResponse(control_plane=item)
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def list_definition_events(
        self,
        *,
        definition_id: str,
        limit: int,
        offset: int,
    ) -> AutomationDefinitionEventListResponse:
        try:
            page = self.repository.list_definition_events(
                definition_id=definition_id,
                limit=limit,
                offset=offset,
            )
            items = [
                AutomationDefinitionEventItem.model_validate(item)
                for item in page.items
            ]
            return AutomationDefinitionEventListResponse(
                definition_id=definition_id,
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def list_control_events(
        self,
        *,
        limit: int,
        offset: int,
    ) -> AutomationControlEventListResponse:
        try:
            page = self.repository.list_control_events(
                limit=limit,
                offset=offset,
            )
            items = [
                AutomationControlEventItem.model_validate(item)
                for item in page.items
            ]
            return AutomationControlEventListResponse(
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def list_definitions(
        self,
        *,
        domain: AutomationDomain | None,
        job_kind: AutomationJobKind | None,
        lifecycle_state: AutomationDefinitionState | None,
        limit: int,
        offset: int,
    ) -> AutomationDefinitionListResponse:
        try:
            if domain is not None and job_kind is not None:
                if domain is not domain_for_job_kind(job_kind):
                    raise OperatorAutomationError(
                        "automation_filter_domain_kind_mismatch",
                        422,
                    )
            page = self.repository.list_definitions(
                domain=domain.value if domain is not None else None,
                job_kind=job_kind.value if job_kind is not None else None,
                lifecycle_state=(
                    lifecycle_state.value if lifecycle_state is not None else None
                ),
                limit=limit,
                offset=offset,
            )
            items = [AutomationDefinitionItem.model_validate(item) for item in page.items]
            return AutomationDefinitionListResponse(
                filters=AutomationFilters(
                    domain=domain,
                    job_kind=job_kind,
                    lifecycle_state=lifecycle_state,
                    limit=limit,
                    offset=offset,
                ),
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def get_definition(self, definition_id: str) -> AutomationDefinitionDetailResponse:
        try:
            record = self.repository.get_definition(definition_id)
            if record is None:
                raise OperatorAutomationError(AUTOMATION_NOT_FOUND, 404)
            return AutomationDefinitionDetailResponse(
                definition=AutomationDefinitionItem.model_validate(record)
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def create_definition(
        self,
        request: AutomationDefinitionCreateRequest,
        context: AutomationMutationContext,
    ) -> AutomationDefinitionMutationResponse:
        definition = request.model_dump(mode="json")
        definition["domain"] = domain_for_job_kind(request.job_kind).value
        return self._definition_mutation(
            lambda: self.repository.create_definition(
                definition=definition,
                context=context,
            )
        )

    def transition_definition(
        self,
        *,
        definition_id: str,
        action: AutomationDefinitionLifecycleAction,
        request: AutomationDefinitionLifecycleRequest,
        context: AutomationMutationContext,
    ) -> AutomationDefinitionMutationResponse:
        return self._definition_mutation(
            lambda: self.repository.transition_definition(
                definition_id=definition_id,
                action=action,
                request=request.model_dump(mode="json"),
                context=context,
            )
        )

    def set_definition_schedule(
        self,
        *,
        definition_id: str,
        request: AutomationDefinitionScheduleRequest,
        context: AutomationMutationContext,
    ) -> AutomationDefinitionMutationResponse:
        return self._definition_mutation(
            lambda: self.repository.set_schedule(
                definition_id=definition_id,
                schedule=request.model_dump(mode="json"),
                context=context,
            )
        )

    def clear_definition_schedule(
        self,
        *,
        definition_id: str,
        request: AutomationDefinitionLifecycleRequest,
        context: AutomationMutationContext,
    ) -> AutomationDefinitionMutationResponse:
        return self._definition_mutation(
            lambda: self.repository.clear_schedule(
                definition_id=definition_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
        )

    def transition_control_posture(
        self,
        *,
        action: AutomationControlAction,
        request: AutomationControlRequest | Mapping[str, Any],
        context: AutomationMutationContext,
    ) -> AutomationControlMutationResponse:
        validated_request = AutomationControlRequest.model_validate(request)
        try:
            result = self.repository.transition_control_posture(
                action=action,
                request=validated_request.model_dump(mode="json"),
                context=context,
            )
            return AutomationControlMutationResponse(
                control_plane=AutomationControlPlaneItem.model_validate(result.entity),
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def claim_one_shot_run(
        self,
        *,
        definition_id: str,
        request: AutomationOneShotRunRequest,
        context: AutomationMutationContext,
    ) -> AutomationRunMutationResponse:
        try:
            result = self.repository.claim_one_shot_run(
                definition_id=definition_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
            return AutomationRunMutationResponse(
                run=AutomationRunItem.model_validate(result.entity),
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def authorize_single_child(
        self,
        *,
        run_id: str,
        request: AutomationSingleChildAuthorizationRequest,
        context: AutomationMutationContext,
    ) -> AutomationRunMutationResponse:
        try:
            result = self.repository.authorize_single_child(
                run_id=run_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
            run = AutomationRunItem.model_validate(result.entity)
            return AutomationRunMutationResponse(
                run=run,
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
                activity=self._run_mutation_activity(
                    run=run,
                    replayed=result.replayed,
                ),
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def refresh_spot_eligibility(
        self,
        *,
        run_id: str,
        request: AutomationEligibilityRefreshRequest,
        context: AutomationMutationContext,
    ) -> AutomationEligibilityCycleMutationResponse:
        try:
            result = self.repository.refresh_spot_eligibility(
                run_id=run_id,
                request=request.model_dump(mode="json"),
                context=context,
            )
            return AutomationEligibilityCycleMutationResponse(
                run=AutomationRunItem.model_validate(result.entity),
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
                activity=AutomationEligibilityRefreshActivity(
                    coinbase_api_call_count=(
                        0 if result.replayed else result.coinbase_api_call_count
                    ),
                    call_count_exact=(
                        True if result.replayed else result.call_count_exact
                    ),
                ),
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    @staticmethod
    def _run_mutation_activity(
        *,
        run: AutomationRunItem,
        replayed: bool,
    ) -> AutomationRunMutationActivity:
        if replayed:
            return AutomationRunMutationActivity()

        create_count = run.create_call_count
        cancel_count = run.cancel_call_count
        if run.call_count_exact:
            exchange_count = (
                None
                if create_count is None or cancel_count is None
                else create_count + cancel_count
            )
            return AutomationRunMutationActivity(
                coinbase_api_call_count=exchange_count,
                exchange_mutation_count=exchange_count,
                create_call_count=create_count,
                cancel_call_count=cancel_count,
                call_count_exact=True,
            )

        exchange_count = (
            None
            if create_count is None or cancel_count is None
            else create_count + cancel_count
        )
        return AutomationRunMutationActivity(
            coinbase_api_call_count=None,
            exchange_mutation_count=exchange_count,
            create_call_count=create_count,
            cancel_call_count=cancel_count,
            call_count_exact=False,
        )

    def list_runs(
        self,
        *,
        definition_id: str | None,
        state: AutomationRunState | None,
        limit: int,
        offset: int,
    ) -> AutomationRunListResponse:
        try:
            page = self.repository.list_runs(
                definition_id=definition_id,
                state=state.value if state is not None else None,
                limit=limit,
                offset=offset,
            )
            items = [AutomationRunItem.model_validate(item) for item in page.items]
            return AutomationRunListResponse(
                filters=AutomationRunFilters(
                    definition_id=definition_id,
                    state=state,
                    limit=limit,
                    offset=offset,
                ),
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def get_run(self, run_id: str) -> AutomationRunDetailResponse:
        try:
            record = self.repository.get_run(run_id)
            if record is None:
                raise OperatorAutomationError(AUTOMATION_NOT_FOUND, 404)
            return AutomationRunDetailResponse(run=AutomationRunItem.model_validate(record))
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def list_run_events(
        self,
        *,
        run_id: str,
        limit: int,
        offset: int,
    ) -> AutomationRunEventListResponse:
        try:
            page = self.repository.list_run_events(
                run_id=run_id,
                limit=limit,
                offset=offset,
            )
            items = [AutomationRunEventItem.model_validate(item) for item in page.items]
            return AutomationRunEventListResponse(
                run_id=run_id,
                count=len(items),
                pagination=_pagination(page=page, limit=limit, offset=offset),
                items=items,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None

    def _definition_mutation(self, operation: Any) -> AutomationDefinitionMutationResponse:
        try:
            result = operation()
            return AutomationDefinitionMutationResponse(
                definition=AutomationDefinitionItem.model_validate(result.entity),
                replayed=result.replayed,
                audit_id=result.audit_id,
                correlation_id=result.correlation_id,
            )
        except OperatorAutomationError:
            raise
        except Exception as exc:
            raise self._translate_error(exc) from None


def _default_spot_eligibility_reader_factory(
    *,
    expected_context: Any,
    plan: Any,
) -> Any:
    """Resolve the canonical client only for an explicit refresh mutation."""

    from application.admin_api.operator_spot_eligibility_reader import (
        CoinbaseApprovedSpotEligibilityReader,
    )
    from configuration import REST_CLIENT

    portfolio_id = str(
        os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID") or ""
    ).strip()
    return CoinbaseApprovedSpotEligibilityReader(
        rest_client=REST_CLIENT,
        expected_context=expected_context,
        approved_portfolio_id=portfolio_id,
        approved_portfolio_label="Test",
        plan=plan,
    )


def get_default_operator_automation_service() -> OperatorAutomationService:
    """Resolve the PostgreSQL repository lazily to keep imports local-only."""

    try:
        from database.operator_automation import (
            get_default_operator_automation_repository,
        )

        repository = get_default_operator_automation_repository()
        return OperatorAutomationService(
            PostgresOperatorAutomationRepositoryAdapter(
                repository,
                spot_eligibility_reader_factory=(
                    _default_spot_eligibility_reader_factory
                ),
            )
        )
    except Exception:
        raise OperatorAutomationError(AUTOMATION_UNAVAILABLE, 503) from None
