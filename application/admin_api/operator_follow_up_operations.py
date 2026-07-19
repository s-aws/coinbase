"""Local SQL read model for the operator follow-up operations queue.

This module composes only the durable follow-up repository.  It does not
import the materialization service/runtime, an exchange adapter, or an SDK.
Queue classification grants navigation only and is never live eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.enums import (
    AdminApiPermission,
    AdminOrderFollowUpOperationActionability,
    AdminOrderFollowUpOperationState,
    FollowUpAccountingEvidenceOrigin,
    FollowUpLiveProofOperationKind,
    FollowUpMaterializationState,
)
from database.order_follow_up_intent import (
    FOLLOW_UP_OPERATION_ATTEMPT_CLASSIFICATION,
    OPERATOR_FOLLOW_UP_LIVE_PROOF_GOAL_ID,
    FollowUpLiveProofOperationRecord,
    FollowUpLiveProofOperationSet,
    FollowUpOperationPageItem,
    FollowUpOperationsPage,
    OperatorFollowUpIntentRepository,
    get_default_repository,
)

from .auth import actor_has_permission
from .models import (
    AdminApiActor,
    AdminOrderFollowUpCurrentRequestActivity,
    AdminOrderFollowUpDurableLiveProofActivity,
    AdminOrderFollowUpDurableOperationActivity,
    AdminOrderFollowUpOperationItem,
    AdminOrderFollowUpOperationsQueueResponse,
)


FOLLOW_UP_OPERATIONS_UNAVAILABLE = "follow_up_operations_evidence_unavailable"


def _passive_current_request_activity(
) -> AdminOrderFollowUpCurrentRequestActivity:
    """Return the exact zero activity intrinsic to this local SQL GET."""

    return AdminOrderFollowUpCurrentRequestActivity(
        sdk_mutation_invocation_state="NOT_INVOKED",
        transport_submission_state="NOT_SUBMITTED",
        exchange_mutation_state="NOT_MUTATED",
        read_accounting_state="EXACT",
        observed_read_count=0,
    )


class FollowUpOperationsRepository(Protocol):
    """Narrow repository-only composition required by the passive GET."""

    def list_operations(
        self,
        *,
        product_id: str | None = None,
        state: str | None = None,
        actionability: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> FollowUpOperationsPage: ...


@dataclass(frozen=True)
class OperatorFollowUpOperationsError(RuntimeError):
    """A fixed diagnostic whose cause text is never exposed."""

    code: str
    http_status_code: int

    def __str__(self) -> str:
        return self.code


def _blocker_codes(item: FollowUpOperationPageItem) -> list[str]:
    state = AdminOrderFollowUpOperationState(item.state)
    actionability = AdminOrderFollowUpOperationActionability(
        item.actionability
    )
    if state is AdminOrderFollowUpOperationState.READY_FOR_MATERIALIZATION_AUTHORIZATION:
        return []
    if (
        state is AdminOrderFollowUpOperationState.MATERIALIZED_ACTIVE
        and actionability
        is AdminOrderFollowUpOperationActionability.SAFE_CLOSEOUT_REVIEW
    ):
        return []
    if state is AdminOrderFollowUpOperationState.AWAITING_SOURCE_FILL:
        return ["source_full_fill_not_observed"]
    if state is AdminOrderFollowUpOperationState.MATERIALIZATION_IN_PROGRESS:
        return ["materialization_claim_already_prepared"]
    if state is AdminOrderFollowUpOperationState.MATERIALIZED_TERMINAL:
        return ["materialized_child_terminal"]
    if state is AdminOrderFollowUpOperationState.UNKNOWN_OUTCOME:
        return ["materialization_outcome_unknown"]
    return [item.state_reason_code]


class OperatorFollowUpOperationsService:
    """Map one repository page into the strict public queue contract."""

    def __init__(self, repository: FollowUpOperationsRepository) -> None:
        self.repository = repository

    def list_queue(
        self,
        *,
        actor: AdminApiActor,
        product_id: str | None = None,
        state: AdminOrderFollowUpOperationState | None = None,
        actionability: AdminOrderFollowUpOperationActionability | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> AdminOrderFollowUpOperationsQueueResponse:
        try:
            if not isinstance(actor, AdminApiActor):
                raise ValueError("follow_up_operation_actor_invalid")
            if product_id is not None and (
                not isinstance(product_id, str) or not product_id.strip()
            ):
                raise ValueError("follow_up_operation_product_filter_invalid")
            if state is not None and not isinstance(
                state,
                AdminOrderFollowUpOperationState,
            ):
                raise ValueError("follow_up_operation_state_filter_invalid")
            if actionability is not None and not isinstance(
                actionability,
                AdminOrderFollowUpOperationActionability,
            ):
                raise ValueError(
                    "follow_up_operation_actionability_filter_invalid"
                )
            if type(limit) is not int or not 1 <= limit <= 500:
                raise ValueError("follow_up_operation_limit_invalid")
            if type(offset) is not int or offset < 0:
                raise ValueError("follow_up_operation_offset_invalid")
            normalized_product_id = (
                product_id.strip() if product_id is not None else None
            )
            normalized_limit = limit
            normalized_offset = offset
            page = self.repository.list_operations(
                product_id=normalized_product_id,
                state=state.value if state is not None else None,
                actionability=(
                    actionability.value if actionability is not None else None
                ),
                limit=normalized_limit,
                offset=normalized_offset,
            )
            items = [self._item(record, actor=actor) for record in page.items]
            total_matching_count = page.total_matching_count
            if (
                type(total_matching_count) is not int
                or total_matching_count < len(items)
            ):
                raise ValueError("follow_up_operations_total_invalid")
            next_offset = normalized_offset + len(items)
            if items and total_matching_count < next_offset:
                raise ValueError("follow_up_operations_total_before_page_end")
            if not items and normalized_offset < total_matching_count:
                raise ValueError("follow_up_operations_empty_page_inconsistent")
            has_more = bool(items) and next_offset < total_matching_count
            if has_more and len(items) != normalized_limit:
                raise ValueError("follow_up_operations_partial_page_inconsistent")
            return AdminOrderFollowUpOperationsQueueResponse(
                filters={
                    "product_id": normalized_product_id,
                    "state": state,
                    "actionability": actionability,
                    "limit": normalized_limit,
                    "offset": normalized_offset,
                },
                count=len(items),
                pagination={
                    "limit": normalized_limit,
                    "offset": normalized_offset,
                    "returned_count": len(items),
                    "total_matching_count": total_matching_count,
                    "next_offset": next_offset if has_more else None,
                    "has_more": has_more,
                },
                items=items,
                current_request_activity=_passive_current_request_activity(),
            )
        except OperatorFollowUpOperationsError:
            raise
        except Exception:
            raise OperatorFollowUpOperationsError(
                code=FOLLOW_UP_OPERATIONS_UNAVAILABLE,
                http_status_code=503,
            ) from None

    @staticmethod
    def _item(
        record: FollowUpOperationPageItem,
        *,
        actor: AdminApiActor,
    ) -> AdminOrderFollowUpOperationItem:
        state = AdminOrderFollowUpOperationState(record.state)
        actionability = AdminOrderFollowUpOperationActionability(
            record.actionability
        )
        attempt_classification = (
            FOLLOW_UP_OPERATION_ATTEMPT_CLASSIFICATION[
                FollowUpMaterializationState(
                    record.materialization_attempt_state
                )
            ]
            if record.materialization_attempt_state is not None
            else None
        )
        create_allowance_consumption_count = (
            attempt_classification.create_allowance_consumption_count
            if attempt_classification is not None
            else 0
        )
        cancel_allowance_consumption_count = (
            attempt_classification.cancel_allowance_consumption_count
            if attempt_classification is not None
            else 0
        )
        required_permission = (
            AdminApiPermission.ORDER_CREATE
            if actionability
            is AdminOrderFollowUpOperationActionability.MATERIALIZATION_REVIEW
            else (
                AdminApiPermission.ORDER_CANCEL
                if actionability
                is AdminOrderFollowUpOperationActionability.SAFE_CLOSEOUT_REVIEW
                else None
            )
        )
        actor_authorized = bool(
            required_permission is not None
            and actor_has_permission(actor, required_permission)
        )
        return AdminOrderFollowUpOperationItem(
            follow_up_intent_id=record.follow_up_intent_id,
            source_client_order_id=record.source_client_order_id,
            root_client_order_id=record.root_client_order_id,
            child_client_order_id=record.child_client_order_id,
            product_id=record.product_id,
            source_status=record.source_status,
            derived_follow_up_side=record.derived_follow_up_side,
            operation_state=state,
            state_reason_code=record.state_reason_code,
            blocker_codes=_blocker_codes(record),
            actionability=actionability,
            actionable=actor_authorized,
            review_navigation_available=(
                actionability
                is not AdminOrderFollowUpOperationActionability.NONE
            ),
            materialization_review_available=(
                actionability
                is AdminOrderFollowUpOperationActionability.MATERIALIZATION_REVIEW
            ),
            safe_closeout_review_available=(
                actionability
                is AdminOrderFollowUpOperationActionability.SAFE_CLOSEOUT_REVIEW
            ),
            fresh_authoritative_revalidation_required=(
                actionability
                is not AdminOrderFollowUpOperationActionability.NONE
            ),
            required_permission=required_permission,
            actor_authorized=actor_authorized,
            create_allowance_consumption_count=(
                create_allowance_consumption_count
            ),
            create_allowance_consumed=(
                create_allowance_consumption_count == 1
            ),
            create_call_count=create_allowance_consumption_count,
            create_call_consumed=create_allowance_consumption_count == 1,
            cancel_allowance_consumption_count=(
                cancel_allowance_consumption_count
            ),
            cancel_allowance_consumed=(
                cancel_allowance_consumption_count == 1
            ),
            cancel_call_count=cancel_allowance_consumption_count,
            cancel_call_consumed=cancel_allowance_consumption_count == 1,
            durable_live_proof_activity=(
                OperatorFollowUpOperationsService._durable_live_proof_activity(
                    record
                )
            ),
            materialization_attempt_state=(
                record.materialization_attempt_state
            ),
            correlation_id=record.correlation_id,
            audit_id=record.audit_id,
            recorded_at=record.recorded_at,
            updated_at=record.updated_at,
            detail_href=f"/orders/{record.source_client_order_id}",
        )

    @staticmethod
    def _durable_live_proof_activity(
        item: FollowUpOperationPageItem,
    ) -> AdminOrderFollowUpDurableLiveProofActivity:
        operation_set = item.live_proof_operations
        if operation_set is None:
            operation_set = FollowUpLiveProofOperationSet(
                eligibility_read=None,
                create=None,
                reconciliation_read=None,
                cancel=None,
            )
        slots = {
            "eligibility_read": (
                FollowUpLiveProofOperationKind.ELIGIBILITY_READ,
                operation_set.eligibility_read,
            ),
            "create": (
                FollowUpLiveProofOperationKind.CREATE,
                operation_set.create,
            ),
            "reconciliation_read": (
                FollowUpLiveProofOperationKind.RECONCILIATION_READ,
                operation_set.reconciliation_read,
            ),
            "cancel": (
                FollowUpLiveProofOperationKind.CANCEL,
                operation_set.cancel,
            ),
        }
        projected: dict[str, AdminOrderFollowUpDurableOperationActivity | None] = {}
        for slot_name, (expected_kind, record) in slots.items():
            if record is None:
                projected[slot_name] = None
                continue
            if not OperatorFollowUpOperationsService._live_proof_identity_matches(
                item,
                record,
                expected_kind=expected_kind,
            ):
                raise ValueError("follow_up_operations_live_proof_invalid")
            evidence_origin = {
                FollowUpAccountingEvidenceOrigin.EXPLICIT.value: (
                    "live_proof_journal"
                ),
                FollowUpAccountingEvidenceOrigin.LEGACY_CONSERVATIVE.value: (
                    "conservative_legacy_projection"
                ),
            }.get(record.accounting_evidence_origin)
            if evidence_origin is None:
                raise ValueError("follow_up_operations_live_proof_invalid")
            projected[slot_name] = AdminOrderFollowUpDurableOperationActivity(
                sdk_mutation_invocation_state=(
                    record.sdk_mutation_invocation_state
                ),
                transport_submission_state=record.transport_submission_state,
                exchange_mutation_state=record.exchange_mutation_state,
                read_accounting_state=record.read_accounting_state,
                observed_read_count=record.observed_read_count,
                operation_kind=record.operation_kind,
                event_state=record.event_state,
                terminal_outcome=record.outcome,
                individual_retry_count=record.individual_retry_count,
                evidence_origin=evidence_origin,
                recorded_at=record.recorded_at,
            )
        return AdminOrderFollowUpDurableLiveProofActivity(**projected)

    @staticmethod
    def _live_proof_identity_matches(
        item: FollowUpOperationPageItem,
        record: FollowUpLiveProofOperationRecord,
        *,
        expected_kind: FollowUpLiveProofOperationKind,
    ) -> bool:
        common_identity_matches = bool(
            record.goal_id == OPERATOR_FOLLOW_UP_LIVE_PROOF_GOAL_ID
            and record.operation_kind == expected_kind.value
            and record.source_client_order_id == item.source_client_order_id
            and record.root_client_order_id == item.root_client_order_id
            and record.follow_up_intent_id == item.follow_up_intent_id
        )
        if expected_kind is FollowUpLiveProofOperationKind.ELIGIBILITY_READ:
            binding_matches = bool(
                (
                    record.materialization_id is None
                    and record.child_client_order_id is None
                )
                or (
                    item.materialization_id is not None
                    and item.child_client_order_id is not None
                    and record.materialization_id == item.materialization_id
                    and record.child_client_order_id
                    == item.child_client_order_id
                )
            )
        else:
            binding_matches = bool(
                item.materialization_id is not None
                and item.child_client_order_id is not None
                and record.materialization_id == item.materialization_id
                and record.child_client_order_id == item.child_client_order_id
            )
        return common_identity_matches and binding_matches


def get_default_operator_follow_up_operations_service(
) -> OperatorFollowUpOperationsService:
    """Return the passive queue service over the existing local repository."""

    repository: OperatorFollowUpIntentRepository = get_default_repository()
    return OperatorFollowUpOperationsService(repository)
