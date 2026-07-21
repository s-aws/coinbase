"""PostgreSQL ledger adapter for the bounded Spot eligibility coordinator."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping

from application.admin_api.automation_models import AutomationMutationContext
from application.admin_api.operator_spot_eligibility import (
    APPROVED_SPOT_ELIGIBILITY_ORDER,
    ApprovedSpotEligibilityCategory,
    SpotEligibilityCategoryClaim,
    SpotEligibilityCategoryResult,
    SpotEligibilityCoordinatorConflict,
    SpotEligibilityCycleClaim,
    SpotEligibilityCycleResult,
    SpotEligibilityReadOutcome,
    SpotEligibilityRunContext,
    derive_spot_eligibility_client_order_id,
)


def _aware_datetime(value: Any, *, code: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(code) from None
    else:
        raise ValueError(code)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(code)
    return parsed.astimezone(timezone.utc)


def _optional_aware_datetime(value: Any, *, code: str) -> datetime | None:
    return None if value is None else _aware_datetime(value, code=code)


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


class PostgresSpotEligibilityLedger:
    """Map coordinator claims onto atomic repository cycle boundaries."""

    def __init__(
        self,
        *,
        repository: Any,
        mutation_context: AutomationMutationContext,
        request_payload: Mapping[str, Any],
        authorization_cycle: bool = False,
    ) -> None:
        if repository is None:
            raise ValueError("spot_eligibility_repository_unavailable")
        if not isinstance(mutation_context, AutomationMutationContext):
            raise ValueError("spot_eligibility_mutation_context_invalid")
        expected_fields = (
            {
                "confirm_single_child_create",
                "confirm_final_eligibility_refresh",
                "confirm_account_wide_active_spot_order_catalog_read",
                "confirm_unknown_consumes_allowance",
                "expected_plan_sha256",
                "reason",
            }
            if authorization_cycle
            else {
                "confirm_approved_eligibility_reads",
                "confirm_account_wide_active_spot_order_catalog_read",
                "confirm_unknown_consumes_cycle",
                "expected_plan_sha256",
                "reason",
            }
        )
        required_confirmations = (
            (
                "confirm_single_child_create",
                "confirm_final_eligibility_refresh",
                "confirm_account_wide_active_spot_order_catalog_read",
                "confirm_unknown_consumes_allowance",
            )
            if authorization_cycle
            else (
                "confirm_approved_eligibility_reads",
                "confirm_account_wide_active_spot_order_catalog_read",
                "confirm_unknown_consumes_cycle",
            )
        )
        if (
            not isinstance(request_payload, Mapping)
            or set(request_payload) != expected_fields
            or any(
                request_payload.get(field_name) is not True
                for field_name in required_confirmations
            )
            or not isinstance(request_payload.get("expected_plan_sha256"), str)
            or not isinstance(request_payload.get("reason"), str)
            or not str(request_payload.get("reason")).strip()
        ):
            raise ValueError("spot_eligibility_request_invalid")
        self._repository = repository
        self._mutation_context = mutation_context
        self._request_payload = dict(request_payload)
        self._authorization_cycle = authorization_cycle

    def _command(
        self,
        *,
        phase: str,
        payload: Mapping[str, Any],
        outer: bool = False,
    ) -> Any:
        from database.operator_automation import AutomationMutationCommand

        if outer:
            idempotency_key = self._mutation_context.idempotency_key
        else:
            digest = hashlib.sha256(
                (
                    f"{self._mutation_context.idempotency_key}:"
                    f"{phase}:{payload.get('run_id', '')}:"
                    f"{payload.get('category', '')}"
                ).encode("utf-8")
            ).hexdigest()
            idempotency_key = f"automation-spot-eligibility-{phase}-{digest}"
        return AutomationMutationCommand(
            idempotency_key=idempotency_key,
            payload_sha256=_payload_sha256(payload),
            actor_id=self._mutation_context.actor_id,
            correlation_id=self._mutation_context.correlation_id,
            operator_intent=self._mutation_context.operator_intent,
        )

    @staticmethod
    def _validate_cycle_binding(
        context: SpotEligibilityRunContext,
        cycle: Any,
    ) -> None:
        expected_client_order_id = derive_spot_eligibility_client_order_id(
            run_id=context.run_id,
            plan_sha256=context.plan_sha256,
            goal_key=context.goal_key,
        )
        if (
            int(getattr(cycle, "cycle_number", 0)) not in range(1, 11)
            or str(getattr(cycle, "run_id", "")) != context.run_id
            or str(getattr(cycle, "definition_id", ""))
            != context.definition_id
            or int(getattr(cycle, "definition_revision", 0))
            != context.definition_revision
            or getattr(cycle, "plan_sha256", None) != context.plan_sha256
            or getattr(cycle, "portfolio_id_sha256", None)
            != context.portfolio_id_sha256
            or getattr(cycle, "product_id", None) != "BTC-USDC"
            or str(getattr(cycle, "client_order_id", ""))
            != expected_client_order_id
        ):
            raise ValueError("spot_eligibility_cycle_binding_invalid")

    def claim_or_resume_cycle(
        self,
        context: SpotEligibilityRunContext,
    ) -> SpotEligibilityCycleClaim:
        if not isinstance(context, SpotEligibilityRunContext):
            raise ValueError("spot_eligibility_context_invalid")
        if self._request_payload["expected_plan_sha256"] != context.plan_sha256:
            raise ValueError("spot_eligibility_request_plan_mismatch")
        payload = {
            "operation": (
                "allocate_automation_spot_authorization_cycle"
                if self._authorization_cycle
                else "resume_automation_spot_source_gated_run"
            ),
            "run_id": context.run_id,
            "expected_plan_sha256": context.plan_sha256,
            "request": self._request_payload,
        }
        allocate_cycle = (
            self._repository.allocate_spot_authorization_cycle
            if self._authorization_cycle
            else self._repository.resume_spot_source_gated_run
        )
        mutation = allocate_cycle(
            context.run_id,
            expected_plan_sha256=context.plan_sha256,
            command=self._command(
                phase="cycle",
                payload=payload,
                outer=True,
            ),
        )
        allocation = getattr(mutation, "entity", None)
        cycle = getattr(allocation, "cycle", None)
        if cycle is None:
            raise ValueError("spot_eligibility_cycle_allocation_invalid")
        self._validate_cycle_binding(context, cycle)

        terminal_result = None
        if bool(getattr(mutation, "replayed", False)):
            if str(cycle.state) != "OPEN":
                attempts = self._repository.list_spot_eligibility_attempts(
                    context.run_id,
                    cycle_number=int(cycle.cycle_number),
                )
                terminal_result = self._terminal_result(
                    context=context,
                    cycle=cycle,
                    attempts=attempts,
                )
        elif str(cycle.state) != "OPEN":
            raise ValueError("spot_eligibility_cycle_allocation_invalid")

        return SpotEligibilityCycleClaim(
            cycle_number=int(cycle.cycle_number),
            client_order_id=str(cycle.client_order_id),
            started_at=_aware_datetime(
                cycle.started_at,
                code="spot_eligibility_cycle_started_at_invalid",
            ),
            replayed=bool(getattr(mutation, "replayed", False)),
            terminal_result=terminal_result,
        )

    def claim_category(
        self,
        context: SpotEligibilityRunContext,
        category: ApprovedSpotEligibilityCategory,
    ) -> SpotEligibilityCategoryClaim:
        if not isinstance(context, SpotEligibilityRunContext) or not isinstance(
            category,
            ApprovedSpotEligibilityCategory,
        ):
            raise ValueError("spot_eligibility_category_claim_invalid")
        payload = {
            "operation": "start_automation_spot_eligibility_category",
            "run_id": context.run_id,
            "category": category.value,
            "plan_sha256": context.plan_sha256,
        }
        mutation = self._repository.start_spot_eligibility_attempt(
            context.run_id,
            category=category.value,
            command=self._command(phase="start", payload=payload),
        )
        if bool(getattr(mutation, "replayed", False)):
            raise SpotEligibilityCoordinatorConflict(
                "automation_spot_eligibility_category_consumed"
            )
        record = getattr(mutation, "entity", None)
        if (
            record is None
            or str(getattr(record, "run_id", "")) != context.run_id
            or getattr(record, "category", None) != category.value
            or not bool(getattr(record, "allowance_consumed", False))
            or getattr(record, "outcome", None) is not None
        ):
            raise ValueError("spot_eligibility_category_claim_invalid")
        return SpotEligibilityCategoryClaim(
            cycle_number=int(record.cycle_number),
            category=category,
            claimed_at=_aware_datetime(
                record.started_at,
                code="spot_eligibility_category_claimed_at_invalid",
            ),
        )

    def finalize_category(
        self,
        context: SpotEligibilityRunContext,
        claim: SpotEligibilityCategoryClaim,
        result: SpotEligibilityCategoryResult,
    ) -> None:
        if (
            not isinstance(context, SpotEligibilityRunContext)
            or not isinstance(claim, SpotEligibilityCategoryClaim)
            or not isinstance(result, SpotEligibilityCategoryResult)
            or claim.category is not result.category
        ):
            raise ValueError("spot_eligibility_category_result_invalid")
        known = result.outcome is not SpotEligibilityReadOutcome.UNKNOWN
        portfolio_id_sha256 = (
            context.portfolio_id_sha256
            if claim.category
            is ApprovedSpotEligibilityCategory.PORTFOLIO_CATALOG
            and result.outcome is SpotEligibilityReadOutcome.SUCCEEDED
            and result.eligible
            else None
        )
        payload = {
            "operation": "finalize_automation_spot_eligibility_category",
            "run_id": context.run_id,
            "cycle_number": claim.cycle_number,
            "category": claim.category.value,
            "outcome": result.outcome.value,
            "eligible": result.eligible,
            "call_count_exact": result.call_count_exact,
            "coinbase_api_call_count": (
                result.http_request_count if known else None
            ),
            "observed_at": (
                result.observed_at.isoformat() if known else None
            ),
            "fresh_until": (
                result.fresh_until.isoformat()
                if known and result.fresh_until is not None
                else None
            ),
            "evidence_sha256": result.evidence_sha256 if known else None,
            "portfolio_id_sha256": portfolio_id_sha256,
        }
        mutation = self._repository.finalize_spot_eligibility_attempt(
            context.run_id,
            category=claim.category.value,
            outcome=result.outcome.value,
            eligible=result.eligible,
            coinbase_api_call_count=(
                result.http_request_count if known else None
            ),
            call_count_exact=result.call_count_exact,
            portfolio_id_sha256=portfolio_id_sha256,
            observed_at=result.observed_at if known else None,
            fresh_until=result.fresh_until if known else None,
            evidence_sha256=result.evidence_sha256 if known else None,
            command=self._command(phase="finalize", payload=payload),
        )
        if bool(getattr(mutation, "replayed", False)):
            raise SpotEligibilityCoordinatorConflict(
                "automation_spot_eligibility_category_consumed"
            )
        record = getattr(mutation, "entity", None)
        recorded_observed_at = (
            _optional_aware_datetime(
                getattr(record, "observed_at", None),
                code="spot_eligibility_category_result_invalid",
            )
            if record is not None
            else None
        )
        recorded_fresh_until = (
            _optional_aware_datetime(
                getattr(record, "fresh_until", None),
                code="spot_eligibility_category_result_invalid",
            )
            if record is not None
            else None
        )
        if (
            record is None
            or str(getattr(record, "run_id", "")) != context.run_id
            or int(getattr(record, "cycle_number", 0)) != claim.cycle_number
            or getattr(record, "category", None) != claim.category.value
            or getattr(record, "outcome", None) != result.outcome.value
            or getattr(record, "eligible", None) is not result.eligible
            or getattr(record, "coinbase_api_call_count", None)
            != (result.http_request_count if known else None)
            or getattr(record, "call_count_exact", None)
            is not result.call_count_exact
            or recorded_observed_at
            != (result.observed_at if known else None)
            or recorded_fresh_until
            != (result.fresh_until if known else None)
            or getattr(record, "evidence_sha256", None)
            != (result.evidence_sha256 if known else None)
            or getattr(record, "portfolio_id_sha256", None)
            != portfolio_id_sha256
        ):
            raise ValueError("spot_eligibility_category_result_invalid")

    @staticmethod
    def _terminal_result(
        *,
        context: SpotEligibilityRunContext,
        cycle: Any,
        attempts: Any,
    ) -> SpotEligibilityCycleResult:
        by_category = {
            str(getattr(item, "category", "")): item for item in attempts
        }
        ordered = tuple(
            by_category[category.value]
            for category in APPROVED_SPOT_ELIGIBILITY_ORDER
            if category.value in by_category
        )
        attempted = tuple(
            ApprovedSpotEligibilityCategory(str(item.category))
            for item in ordered
        )
        if attempted != APPROVED_SPOT_ELIGIBILITY_ORDER[: len(attempted)]:
            raise ValueError("spot_eligibility_attempt_order_invalid")
        completed = tuple(
            ApprovedSpotEligibilityCategory(str(item.category))
            for item in ordered
            if getattr(item, "outcome", None) == "SUCCEEDED"
            and getattr(item, "eligible", None) is True
        )
        state = str(getattr(cycle, "state", ""))
        try:
            outcome = SpotEligibilityReadOutcome(state)
        except ValueError:
            raise ValueError("spot_eligibility_cycle_state_invalid") from None
        if (
            (not ordered and state != "UNKNOWN")
            or any(
            not bool(getattr(item, "allowance_consumed", False))
            or getattr(item, "outcome", None) is None
            for item in ordered
            )
        ):
            raise ValueError("spot_eligibility_cycle_replay_invalid")
        call_count_exact = bool(getattr(cycle, "call_count_exact", False))
        call_count = getattr(cycle, "coinbase_api_call_count", None)
        fresh_until = _optional_aware_datetime(
            getattr(cycle, "fresh_until", None),
            code="spot_eligibility_cycle_fresh_until_invalid",
        )
        return SpotEligibilityCycleResult(
            cycle_number=int(cycle.cycle_number),
            outcome=outcome,
            eligible=outcome is SpotEligibilityReadOutcome.SUCCEEDED,
            attempted_categories=attempted,
            completed_categories=completed,
            logical_call_count=len(attempted),
            coinbase_api_call_count=(int(call_count) if call_count is not None else None),
            call_count_exact=call_count_exact,
            fresh_until=fresh_until,
            client_order_id=str(cycle.client_order_id),
            diagnostic_code=str(cycle.diagnostic_code),
        )
