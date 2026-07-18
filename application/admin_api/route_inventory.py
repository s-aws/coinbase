"""Admin API route/message inventory."""

from __future__ import annotations

from core.enums import (
    AdminApiActionClass,
    AdminApiCompatibilityMode,
    AdminApiPermission,
)

from .models import AdminApiRouteInventoryItem


ADMIN_API_ROUTE_INVENTORY: tuple[AdminApiRouteInventoryItem, ...] = (
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/orders",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="place_manual_order",
        parity_test="HTTP vs place_order guard/result parity",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/orders",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_order_list",
        parity_test="no Coinbase REST placement",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/orders/{client_order_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_order_detail",
        parity_test="client_order_id identity only",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "GET /api/v1/orders/{source_client_order_id}/follow-up-intent"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not applicable; authoritative local readback only",
        caps="backend-owned one-slot and zero-attachment-notional evidence",
        audit="durable attachment audit binding is returned when present",
        shared_method="read_order_follow_up_intent",
        parity_test=(
            "source/root client_order_id, eligibility, and durable intent "
            "readback only; no Coinbase read, order-engine handler, child "
            "creation, reconciliation execution, or exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/orders/{source_client_order_id}/follow-up-intent"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency=(
            "required; same key and payload replay, changed payload conflicts"
        ),
        approval=(
            "not a live approval; exact operator acknowledgement is required "
            "and later materialization requires fresh authorization"
        ),
        caps=(
            "exactly one durable source slot and zero attachment/submitted "
            "notional; later materialization caps are evaluated separately"
        ),
        audit=(
            "required durable actor, environment, portfolio, source/root, "
            "intent hash, claim, correlation, and terminal-result binding"
        ),
        shared_method="attach_order_follow_up_intent",
        parity_test=(
            "atomic backend eligibility and single-slot CAS for an OPEN, "
            "system-owned, zero-fill Spot source; derives identity, side, "
            "semantic intent, and policy without browser trading fields; no "
            "Coinbase call, order-engine handler, child creation, automatic "
            "fill trigger, reconciliation execution, or exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/orders/{client_order_id}/reconciliation",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required",
        approval="not applicable; exact backend execution authority required",
        caps="not applicable; Coinbase read and local status synchronization only",
        audit="required",
        shared_method="reconcile_order_by_client_order_id",
        parity_test=(
            "exact durable Admin root ownership plus Test portfolio, product, "
            "client_order_id, and stored exchange identity; recognized status "
            "only; a filled root requires bounded exact fill proof persistence; "
            "no create, cancel, or other exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/orders/{client_order_id}/fill-follow-up/replay",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_order_fill_follow_up_replay",
        parity_test=(
            "read-only fill-event replay and follow-up decision evidence; no "
            "OrderEngine.handle_filled_order, claim acquisition, stealth "
            "follow-up creation, Coinbase call, or local/exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/orders/{client_order_id}/fill-follow-up/live-readiness",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_order_fill_follow_up_live_readiness",
        parity_test=(
            "fail-closed fill follow-up live-readiness blockers for "
            "the route-bound order approval carried by legacy-compatible "
            "fill_testing_approval_id, wallet/cap/reconciliation proof, "
            "duplicate-claim protection, and audit correlation; no claim "
            "acquisition, OrderEngine.handle_filled_order, stealth follow-up "
            "creation, Coinbase call, or local/exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/orders/{client_order_id}/fill-follow-up/chain",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_order_fill_follow_up_chain",
        parity_test=(
            "read-only fill follow-up parent/child chain evidence from "
            "order_parent and stealth child rows; no claim acquisition, "
            "OrderEngine.handle_filled_order, stealth follow-up creation, "
            "Coinbase call, or local/exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "GET /api/v1/orders/{root_client_order_id}/fill-follow-up/"
            "child-cancel/readiness"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="historical local V15 plan/marker/handoff evidence only",
        caps="historical local root/child/aggregate plan evidence only",
        audit="historical local route audit evidence only",
        shared_method="build_order_fill_follow_up_child_cancel_readiness",
        parity_test=(
            "display-only historical deterministic-child evidence; always "
            "reports source_disabled_not_implemented and never promotes local "
            "evidence into current exchange revalidation or cancel readiness"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/orders/{root_client_order_id}/fill-follow-up/"
            "child-cancel"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="not_applicable_source_disabled",
        approval="not_applicable_source_disabled",
        caps="not_applicable_source_disabled",
        audit="not_implemented_no_mutation",
        shared_method=(
            "cancel_order_fill_follow_up_child_by_root_client_order_id"
        ),
        parity_test=(
            "fixed source-disabled 501 after authentication and RBAC but "
            "before admission, idempotency, audit, services, stores, Coinbase "
            "reads, local writes, or exchange mutation; restoration requires "
            "separate operator authorization"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "GET /api/v1/orders/{client_order_id}/fill-follow-up/"
            "trigger-preview"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only command admission preview evidence",
        shared_method="preview_fill_follow_up_trigger_admission",
        parity_test=(
            "read-only exact fill follow-up trigger admission preview; computes "
            "the backend POST trigger payload hash for supplied refs without "
            "command execution, idempotency write, audit append, Coinbase call, "
            "claim acquisition, or local/exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/orders/{client_order_id}/fill-follow-up/trigger",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required",
        approval="required before accepted no-live trigger execution",
        caps="required before accepted no-live trigger execution",
        audit="required",
        shared_method="trigger_order_fill_follow_up",
        parity_test=(
            "fail-closed fill follow-up trigger boundary; rejects incomplete "
            "route-bound order approval carried by legacy-compatible "
            "fill_testing_approval_id, wallet/cap/reconciliation proof, "
            "duplicate-claim acknowledgement/readback, audit correlation, "
            "existing child, duplicate chain, or missing execution adapter; "
            "after exact route-bound approval, wallet proof "
            "cap_guard_wallet:<cap_guard_decision_id>, cap/guard, "
            "reconciliation, duplicate-claim, audit-correlation, and "
            "parent/child checks clear, it may invoke the no-live "
            "fill-follow-up executor, require accepted child readback, and "
            "still reports Coinbase submit/cancel and live exchange mutation "
            "remain disallowed"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/orders",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_order_list",
        parity_test="read-only stealth lifecycle evidence; no exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for planning guards before lifecycle writes",
        audit="required",
        shared_method="create_stealth_order",
        parity_test="stealth_order_id identity; no local stealth state mutation until lifecycle-write gates are complete",
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/orders/{stealth_order_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_order_detail",
        parity_test="stealth_order_id identity with exchange ids as evidence only",
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "GET /api/v1/stealth/orders/{stealth_order_id}/active-placement/"
            "exchange-truth-proof"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_active_placement_exchange_truth",
        parity_test=(
            "read-only active-placement exchange-truth evidence; no Coinbase "
            "read, cancel/replace, reconciliation execution, or lifecycle mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "GET /api/v1/stealth/orders/{stealth_order_id}/"
            "lifecycle-write-guard-proof"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_create_lifecycle_write_guard",
        parity_test=(
            "read-only lifecycle-write guard proof evidence; no manager "
            "invocation, local lifecycle mutation, DB write, or Coinbase call"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "GET /api/v1/stealth/orders/{stealth_order_id}/"
            "mutation-claim-proof"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_mutation_claim_snapshot",
        parity_test=(
            "read-only mutation-claim proof evidence; no manager invocation, "
            "claim acquisition/release, Coinbase call, reconciliation "
            "execution, or state mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/orders/{stealth_order_id}/recovery-proof",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_recovery_proof",
        parity_test=(
            "read-only recovery proof evidence; no manager invocation, repair, "
            "rollback, Coinbase call, reconciliation execution, or state mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proof",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_reveal_trigger_proof",
        parity_test=(
            "read-only reveal-trigger proof evidence; no trigger evaluation, "
            "should_trigger_reveal call, reveal_order_slice call, Coinbase "
            "call, reconciliation execution, or lifecycle mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "GET /api/v1/stealth/orders/{stealth_order_id}/"
            "manager-invocation-policy"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_manager_invocation_policy",
        parity_test=(
            "read-only manager-invocation policy evidence; no manager "
            "invocation, Coinbase call, reconciliation execution, or state "
            "mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "GET /api/v1/stealth/orders/{stealth_order_id}/"
            "coinbase-exchange-submission-policy"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_coinbase_exchange_submission_policy",
        parity_test=(
            "read-only Coinbase exchange submission-policy evidence; no "
            "Coinbase submit, cancel, read, manager invocation, "
            "reconciliation execution, or state mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/orders/{stealth_order_id}/state-mutation-policy",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_state_mutation_policy",
        parity_test=(
            "read-only state-mutation policy evidence; no lifecycle/order/"
            "exchange-state mutation, manager invocation, Coinbase call, "
            "active-placement cancel/replace, or reconciliation execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proof",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_reconciliation_proof",
        parity_test=(
            "read-only reconciliation proof evidence; no reconciliation "
            "execution, manager invocation, Coinbase call, active-placement "
            "cancel/replace, exchange-state mutation, or lifecycle mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proof",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_cancel_replace_proof",
        parity_test=(
            "read-only cancel/replace proof evidence; no manager invocation, "
            "Coinbase call, active-placement cancel/replace, exchange-state "
            "mutation, lifecycle mutation, or reconciliation execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "GET /api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-reconciliation-proof"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_post_write_reconciliation_proof",
        parity_test=(
            "read-only post-write reconciliation proof evidence; no manager "
            "invocation, Coinbase call, state mutation, or reconciliation "
            "execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "GET /api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-reconciliation-execution-policy"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method=(
            "build_stealth_post_write_reconciliation_execution_policy"
        ),
        parity_test=(
            "read-only post-write reconciliation execution-policy evidence; "
            "no reconciliation execution, manager invocation, Coinbase call, "
            "active-placement cancel/replace, exchange-state mutation, "
            "lifecycle mutation, or live-execution prerequisite satisfaction"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "GET /api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-execution-journals"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_post_write_execution_journals",
        parity_test=(
            "read-only post-write execution-journal acceptance evidence; no "
            "manager invocation, Coinbase call, state mutation, or "
            "reconciliation execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "GET /api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-reconciliation-verifications"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_stealth_post_write_reconciliation_verifications",
        parity_test=(
            "read-only post-write reconciliation verification evidence; no "
            "manager invocation, Coinbase call, state mutation, or "
            "reconciliation execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/command-suite",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only stealth command-suite evidence",
        audit="optional read audit",
        shared_method="build_stealth_command_suite",
        parity_test="M55 read-only stealth command coverage; no exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders/{stealth_order_id}/reveal",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for trigger, placement, guard, and reconciliation evidence",
        audit="required",
        shared_method="reveal_stealth_order_by_stealth_order_id",
        parity_test=(
            "stealth_order_id identity; no reveal placement or lifecycle "
            "mutation until exchange-submission gates are complete"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-execution-journals"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.RECONCILIATION_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for accepted execution-journal evidence",
        audit="required",
        shared_method="record_stealth_post_write_execution_journal",
        parity_test=(
            "stealth_order_id identity; append-only journal acceptance only, "
            "no manager invocation, Coinbase activity, reconciliation execution, "
            "or lifecycle/order/exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-reconciliation-verifications"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.RECONCILIATION_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for verified post-write reconciliation evidence",
        audit="required",
        shared_method="record_stealth_post_write_reconciliation_verification",
        parity_test=(
            "stealth_order_id identity; append-only verification only after "
            "safe proof and accepted journal, no manager invocation, Coinbase "
            "activity, reconciliation execution, or lifecycle/order/exchange "
            "mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders/{stealth_order_id}/move",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for mutation claims, cancel/replace, guard, and reconciliation evidence",
        audit="required",
        shared_method="move_stealth_order_by_stealth_order_id",
        parity_test=(
            "stealth_order_id identity; no move plan, cancel/replace, or "
            "local lifecycle mutation until exchange-handling gates are complete"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders/{stealth_order_id}/cancel",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for rate/session controls and exchange-reality reconciliation",
        audit="required",
        shared_method="cancel_stealth_order_by_stealth_order_id",
        parity_test="stealth_order_id identity; no active placement mutation until exchange handling is complete",
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders/{stealth_order_id}/recovery",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_RECOVERY_EXECUTE,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for active-placement, repair, rollback, and reconciliation evidence",
        audit="required",
        shared_method="recover_stealth_order_by_stealth_order_id",
        parity_test=(
            "stealth_order_id identity; no recovery repair, rollback, lifecycle "
            "mutation, Coinbase read, or reconciliation execution until stealth "
            "recovery gates are complete"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_RECONCILIATION_EXECUTE,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for reconciliation plan/proof and active-placement exchange-truth evidence",
        audit="required",
        shared_method="reconcile_stealth_order_by_stealth_order_id",
        parity_test=(
            "stealth_order_id identity; no reconciliation execution, lifecycle "
            "mutation, exchange-state mutation, Coinbase read, or proof writer "
            "until stealth reconciliation gates are complete"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/"
            "exchange-truth-snapshots"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_EXCHANGE_TRUTH_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for active-placement evidence record admission",
        audit="required",
        shared_method="record_stealth_active_placement_exchange_truth_snapshot",
        parity_test=(
            "stealth_order_id identity; no Coinbase read, cancel/replace, "
            "reconciliation execution, lifecycle mutation, or exchange-state mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/active-placement/"
            "exchange-truth-proofs"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_EXCHANGE_TRUTH_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for active-placement proof record admission",
        audit="required",
        shared_method="record_stealth_active_placement_exchange_truth_proof",
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not itself verify Coinbase exchange truth"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "lifecycle-write-guard-proofs"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_LIFECYCLE_WRITE_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for lifecycle-write guard proof admission",
        audit="required",
        shared_method="record_stealth_create_lifecycle_write_guard_proof",
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not invoke StealthOrderManager, write local lifecycle state, "
            "write order_parent rows, or submit/read Coinbase"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "mutation-claim-proofs"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_MUTATION_CLAIM_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for mutation-claim snapshot proof admission",
        audit="required",
        shared_method="record_stealth_mutation_claim_snapshot_proof",
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not invoke StealthOrderManager, acquire or release claims, "
            "cancel/replace active placements, execute reconciliation, or "
            "submit/read Coinbase"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders/{stealth_order_id}/recovery-proofs",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_RECOVERY_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for recovery proof admission",
        audit="required",
        shared_method="record_stealth_recovery_proof",
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not repair state, roll back state, invoke managers, call "
            "Coinbase, cancel/replace placements, execute reconciliation, or "
            "mutate state"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders/{stealth_order_id}/reveal-trigger-proofs",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_REVEAL_TRIGGER_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for reveal-trigger proof admission",
        audit="required",
        shared_method="record_stealth_reveal_trigger_proof",
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not evaluate triggers, call should_trigger_reveal, call "
            "reveal_order_slice, invoke managers, submit/read Coinbase, "
            "execute reconciliation, or mutate lifecycle state"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "manager-invocation-policy-proofs"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_MANAGER_POLICY_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for manager-invocation policy proof admission",
        audit="required",
        shared_method="record_stealth_manager_invocation_policy_proof",
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not invoke StealthOrderManager, submit/read/cancel Coinbase, "
            "cancel/replace active placements, execute reconciliation, or "
            "mutate lifecycle/order/exchange state"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "coinbase-exchange-submission-policy-proofs"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_COINBASE_EXCHANGE_POLICY_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for Coinbase exchange policy proof admission",
        audit="required",
        shared_method=(
            "record_stealth_coinbase_exchange_submission_policy_proof"
        ),
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not submit/read/cancel Coinbase orders, invoke managers, "
            "cancel/replace active placements, execute reconciliation, or "
            "mutate lifecycle/order/exchange state"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "state-mutation-policy-proofs"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_STATE_MUTATION_POLICY_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for state-mutation policy proof admission",
        audit="required",
        shared_method="record_stealth_state_mutation_policy_proof",
        parity_test=(
            "stealth_order_id identity; policy proof evidence remains no-live "
            "and does not authorize or perform lifecycle/order/exchange-state "
            "mutation, invoke managers, submit/read/cancel Coinbase, "
            "cancel/replace active placements, or execute reconciliation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders/{stealth_order_id}/reconciliation-proofs",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_RECONCILIATION_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for reconciliation proof admission",
        audit="required",
        shared_method="record_stealth_reconciliation_proof",
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not execute reconciliation, invoke managers, submit/read "
            "Coinbase, cancel/replace active placements, mutate exchange "
            "state, or mutate lifecycle state"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="POST /api/v1/stealth/orders/{stealth_order_id}/cancel-replace-proofs",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.STEALTH_CANCEL_REPLACE_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for cancel/replace proof admission",
        audit="required",
        shared_method="record_stealth_cancel_replace_proof",
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not invoke managers, submit/read/cancel Coinbase, "
            "cancel/replace active placements, mutate exchange state, mutate "
            "lifecycle state, or execute reconciliation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-reconciliation-proofs"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.RECONCILIATION_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for post-write reconciliation proof admission",
        audit="required",
        shared_method="record_stealth_post_write_reconciliation_proof",
        parity_test=(
            "stealth_order_id identity; proof evidence remains no-live and "
            "does not invoke managers, submit/read/cancel Coinbase, mutate "
            "exchange state, mutate lifecycle state, or execute reconciliation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface=(
            "POST /api/v1/stealth/orders/{stealth_order_id}/"
            "post-write-reconciliation-execution-policy-proofs"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=(
            AdminApiPermission.STEALTH_POST_WRITE_RECONCILIATION_POLICY_RECORD
        ),
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for post-write reconciliation policy proof admission",
        audit="required",
        shared_method=(
            "record_stealth_post_write_reconciliation_execution_policy_proof"
        ),
        parity_test=(
            "stealth_order_id identity; policy proof evidence remains "
            "no-live and does not invoke managers, submit/read/cancel "
            "Coinbase, cancel/replace active placements, mutate exchange "
            "state, mutate lifecycle state, or execute reconciliation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface="GET /api/v1/movement-repricing/evidence",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_movement_repricing_evidence",
        parity_test="read-only move/reprice evidence; no exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface="GET /api/v1/movement-repricing/orders/{client_order_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_movement_repricing_order_detail",
        parity_test="client_order_id identity with exchange ids as evidence only",
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface="GET /api/v1/movement-repricing/stealth/{stealth_order_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_movement_repricing_stealth_detail",
        parity_test="stealth_order_id identity with runtime claims as evidence only",
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface="POST /api/v1/movement-repricing/stealth/{stealth_order_id}/reprice",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for rate/session controls, mutation claims, and exchange-reality reconciliation",
        audit="required",
        shared_method="reprice_stealth_order_by_stealth_order_id",
        parity_test="stealth_order_id identity; no cooldown clearing or live repricing until exchange handling is complete",
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/command-suite",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_futures_command_suite",
        parity_test=(
            "read-only Futures source-disabled contract matrix; the four command "
            "POSTs return NOT_IMPLEMENTED and permit no draft, forwarding, gate "
            "progression, spot rules, or exchange execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/orders",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="not_applicable_source_disabled",
        approval="not_applicable_source_disabled",
        caps="not_applicable_source_disabled",
        audit="not_implemented_no_mutation",
        shared_method="place_futures_order",
        parity_test=(
            "product_id identity; source-disabled fixed NOT_IMPLEMENTED response "
            "before replay, admission, audit, service, adapter, or Coinbase code"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/positions/{position_key}/close-reduce",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="not_applicable_source_disabled",
        approval="not_applicable_source_disabled",
        caps="not_applicable_source_disabled",
        audit="not_implemented_no_mutation",
        shared_method="close_or_reduce_futures_position",
        parity_test=(
            "position_key identity; source-disabled fixed NOT_IMPLEMENTED response "
            "before replay, admission, audit, service, adapter, or Coinbase code"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/orders/{client_order_id}/cancel",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="not_applicable_source_disabled",
        approval="not_applicable_source_disabled",
        caps="not_applicable_source_disabled",
        audit="not_implemented_no_mutation",
        shared_method="cancel_futures_order",
        parity_test=(
            "client_order_id identity; source-disabled fixed NOT_IMPLEMENTED "
            "response before replay, admission, audit, service, adapter, or Coinbase code"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/positions/{position_key}/reconciliation",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.RECONCILIATION_RECORD,
        idempotency="not_applicable_source_disabled",
        approval="not_applicable_source_disabled",
        caps="not_applicable_source_disabled",
        audit="not_implemented_no_mutation",
        shared_method="reconcile_futures_position",
        parity_test=(
            "position_key identity; source-disabled fixed NOT_IMPLEMENTED response "
            "before replay, admission, audit, service, reconciliation, or mutation code"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/order-preview",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required for immutable artifact readback",
        approval="producer requires separate backend operator authority",
        caps="fixed slice-local 100 opening / 150 exposure / 300 turnover",
        audit="immutable claim/result artifact",
        shared_method="read_futures_order_preview_artifact",
        parity_test=(
            "disk-only accepted/blocked/unknown Preview readback; GET makes "
            "zero Coinbase calls and grants no create, cancel, close, or reduce authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/account",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_futures_account",
        parity_test="read-only futures account, margin, collateral, liquidation, funding, and P/L evidence",
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/positions",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_futures_positions",
        parity_test="position_key identity and futures close-side semantics; no spot inventory rules",
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/positions/{position_key}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_futures_position_detail",
        parity_test="backend-defined position identity with no order placement or cancellation",
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/risk-proofs",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="list_futures_risk_proofs",
        parity_test=(
            "read-only futures risk-proof record readback; no proof acceptance, "
            "command draft, reconciliation execution, or Coinbase call"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/risk-proofs/{futures_risk_proof_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="get_futures_risk_proof",
        parity_test=(
            "read-only futures risk-proof detail by proof id; no proof "
            "acceptance, command draft, reconciliation execution, or Coinbase call"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/risk-proofs",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.FUTURES_RISK_PROOF_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for futures risk proof record admission",
        audit="required",
        shared_method="record_futures_risk_proof",
        parity_test=(
            "command/proof_kind identity; proof evidence remains no-live and "
            "does not register command routes, create drafts, execute "
            "reconciliation, mutate futures state, or call Coinbase"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="guard_risk_policy",
        surface="GET /api/v1/admin/guard-risk-policy",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only evidence only",
        audit="optional read audit",
        shared_method="build_guard_risk_policy",
        parity_test="read-only guard/risk policy evidence; no browser authority or Coinbase read",
    ),
    AdminApiRouteInventoryItem(
        module_id="audit_workbench",
        surface="GET /api/v1/admin/audit-workbench",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_audit_workbench",
        parity_test="cross-module audit evidence only; no Coinbase read or mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="legacy_dashboard_websocket",
        surface="place_order WebSocket",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission="compatibility policy",
        idempotency="enterprise-gated or compatibility-only",
        approval="enterprise-gated or compatibility-only",
        caps="required",
        audit="required",
        shared_method="place_manual_order",
        parity_test="WebSocket vs HTTP guard/result parity",
        compatibility_mode=AdminApiCompatibilityMode.COMPATIBILITY_ONLY.value,
    ),
    AdminApiRouteInventoryItem(
        module_id="legacy_dashboard_websocket",
        surface="place_hotpoint_test_order WebSocket",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission="compatibility policy",
        idempotency="enterprise-gated or compatibility-only",
        approval="enterprise-gated or compatibility-only",
        caps="required",
        audit="required",
        shared_method="place_hotpoint_test_order",
        parity_test="WebSocket vs shared-service hotpoint guard/result parity",
        compatibility_mode=AdminApiCompatibilityMode.COMPATIBILITY_ONLY.value,
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/orders/{client_order_id}/cancel",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required",
        approval="required by controlled-live request admission",
        caps="required for rate/session controls",
        audit="required",
        shared_method="cancel_order_by_client_order_id",
        parity_test=(
            "controlled-live HTTP vs cancel_order parity with full request "
            "admission and final execution-authority enforcement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/campaign/executions",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="execute_spot_campaign",
        parity_test="campaign execution remains fail-closed until live gates pass",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/sweep/automation-runs",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.SPOT_SWEEP_EXECUTE,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="run_spot_sweep_automation",
        parity_test=(
            "sweep automation remains fail-closed until scheduler, run-limit, "
            "safety, recovery, and reconciliation gates pass"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface="GET /api/v1/automation/usdc-pair-snapshot-runs",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="list_usdc_pair_snapshot_runs",
        parity_test=(
            "M58 read-only durable dry-run snapshot evidence; no Coinbase order "
            "submission, no order payload derivation, no wallet allocation, and "
            "no browser execution authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface="POST /api/v1/automation/usdc-pair-snapshot-runs",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="required",
        approval="not applicable for no-live dry-run evidence",
        caps=(
            "records requested per-product cap only; no order planning or "
            "wallet allocation"
        ),
        audit="required",
        shared_method="record_usdc_pair_snapshot_dry_run",
        parity_test=(
            "M58 backend-owned USDC pair snapshot dry-run; no Coinbase order "
            "submission, no order payload derivation, and no browser execution "
            "authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface="GET /api/v1/automation/usdc-pair-snapshot-order-plans",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="list_usdc_pair_snapshot_order_plans",
        parity_test=(
            "M58 read-only durable order-plan evidence; no Coinbase order "
            "submission, no wallet allocation, and no browser execution "
            "authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "GET /api/v1/automation/usdc-pair-snapshot-order-plan-live-readiness"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="list_usdc_pair_snapshot_order_plan_live_readiness",
        parity_test=(
            "M58 read-only live-readiness preflight evidence; no Coinbase "
            "order submission, no wallet allocation, and no browser execution "
            "authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "GET /api/v1/automation/usdc-pair-snapshot-order-plan-allowlist-readiness"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="list_usdc_pair_snapshot_order_plan_allowlist_readiness",
        parity_test=(
            "M58 read-only allowlist-readiness evidence; no Coinbase order "
            "submission, no fan-out execution, no scheduler, and no browser "
            "execution authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "GET /api/v1/automation/usdc-pair-snapshot-allowlist-run-states"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="list_usdc_pair_snapshot_allowlist_run_states",
        parity_test=(
            "M58 read-only allowlist run-state evidence; no Coinbase order "
            "submission, no fan-out execution, no scheduler, and no browser "
            "execution authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "GET /api/v1/automation/usdc-pair-snapshot-order-plan-live-submissions"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="list_usdc_pair_snapshot_order_plan_live_submissions",
        parity_test=(
            "M58 read-only historical or synthetic submit/cancel evidence; "
            "it does not imply that the source-parked exchange routes are "
            "operator executable"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "POST /api/v1/automation/usdc-pair-snapshot-runs/{run_id}/order-plans"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="required",
        approval="not applicable for no-live dry-run evidence",
        caps=(
            "derives backend-owned limit-order plan evidence with per-product "
            "and run-level notional caps; no wallet allocation"
        ),
        audit="required",
        shared_method="record_usdc_pair_snapshot_order_plan",
        parity_test=(
            "M58 backend-owned limit-order plan evidence derived from durable "
            "USDC snapshot rows; no Coinbase order submission, no wallet "
            "allocation, and no browser execution authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "POST /api/v1/automation/usdc-pair-snapshot-order-plans/"
            "{plan_id}/allowlist-readiness"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="required",
        approval=(
            "records no-live product allowlist readiness from existing "
            "backend-owned order-plan evidence; does not grant Coinbase "
            "submission"
        ),
        caps=(
            "summarizes explicit allowlist product count, run cap exhaustion, "
            "missing order-plan rows, and product evidence blockers; no "
            "wallet allocation"
        ),
        audit="required",
        shared_method=(
            "record_usdc_pair_snapshot_order_plan_allowlist_readiness"
        ),
        parity_test=(
            "M58 backend-owned allowlist-readiness persists no-live "
            "candidate and blocker evidence; no Coinbase order submission, "
            "no fan-out execution, no scheduler, and no browser execution "
            "authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "POST /api/v1/automation/"
            "usdc-pair-snapshot-order-plan-allowlist-readiness/"
            "{readiness_id}/run-state"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="required",
        approval=(
            "records no-live allowlist run-state rehearsal from existing "
            "backend-owned readiness evidence; does not grant Coinbase "
            "submission"
        ),
        caps=(
            "required no-live fan-out testing cap evidence with maximum "
            "fan-out notional <= 100 USDC; no wallet allocation"
        ),
        audit="required",
        shared_method="record_usdc_pair_snapshot_allowlist_run_state",
        parity_test=(
            "M58 backend-owned allowlist run-state persists no-live queued, "
            "blocked, retry, recovery, rate-limit, and cap evidence; no "
            "Coinbase order submission, no fan-out execution, no scheduler, "
            "and no browser execution authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "POST /api/v1/automation/usdc-pair-snapshot-order-plans/"
            "{plan_id}/live-readiness"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="required",
        approval=(
            "offline proof-chain evidence only; source parking cannot grant "
            "Coinbase submission"
        ),
        caps=(
            "required validation for one selected order-plan row, preferred spot live-test "
            "notional cap, exchange minimum size, far-from-bid/non-fill price "
            "distance, and cancel-before-additional-orders plan"
        ),
        audit="required",
        shared_method="record_usdc_pair_snapshot_order_plan_live_readiness",
        parity_test=(
            "M58 backend-owned offline readiness preflight persists one-row "
            "evidence with submit_route_ready false and blocker "
            "m58_operator_workflow_unavailable; no Coinbase order submission, "
            "wallet allocation, or browser execution authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "POST /api/v1/automation/usdc-pair-snapshot-order-plans/"
            "{plan_id}/live-submit"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="not_applicable_source_disabled",
        approval="not_applicable_source_disabled",
        caps="not_applicable_source_disabled",
        audit="not_implemented_no_mutation",
        shared_method="submit_usdc_pair_snapshot_order_plan_live_order",
        parity_test=(
            "M58 exchange execution is source-parked with fixed typed 501 "
            "m58_operator_workflow_unavailable before idempotency, approval, "
            "cap, audit, or persistence; the installed dependency makes zero "
            "Coinbase executor calls and zero new submission-record writes; "
            "future restoration requires separate authorization"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "POST /api/v1/automation/usdc-pair-snapshot-allowlist-run-states/"
            "{run_state_id}/live-submit"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="not_applicable_source_disabled",
        approval="not_applicable_source_disabled",
        caps="not_applicable_source_disabled",
        audit="not_implemented_no_mutation",
        shared_method="submit_usdc_pair_snapshot_allowlist_run_state_live_order",
        parity_test=(
            "M58 exchange execution is source-parked with fixed typed 501 "
            "m58_operator_workflow_unavailable before idempotency, approval, "
            "cap, audit, or persistence; the installed dependency makes zero "
            "Coinbase executor calls and zero new submission-record writes; "
            "future restoration requires separate authorization"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "POST /api/v1/automation/usdc-pair-snapshot-allowlist-run-states/"
            "{run_state_id}/live-fanout-submit"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="not_applicable_source_disabled",
        approval="not_applicable_source_disabled",
        caps="not_applicable_source_disabled",
        audit="not_implemented_no_mutation",
        shared_method="submit_usdc_pair_snapshot_allowlist_run_state_live_fanout",
        parity_test=(
            "M58 fan-out exchange execution is source-parked with fixed typed "
            "501 m58_operator_workflow_unavailable before idempotency, approval, "
            "cap, audit, or persistence; no installed operator path can select "
            "the real fan-out executor; future restoration requires separate "
            "authorization"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation",
        surface=(
            "POST /api/v1/automation/usdc-pair-snapshot-order-plans/"
            "{plan_id}/proof-chain-refresh"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CAMPAIGN_EXECUTE,
        idempotency="required",
        approval=(
            "resolves exact approval snapshot evidence from backend lifecycle "
            "storage; does not grant live execution"
        ),
        caps=(
            "does not alter order sizing or allocate wallet balance; reads "
            "admission audit, cap/guard, reconciliation plan, and disabled "
            "live-service decision evidence"
        ),
        audit="required",
        shared_method="refresh_usdc_pair_snapshot_order_plan_proof_chain",
        parity_test=(
            "M58 backend-owned proof refresh links exact approval snapshot, "
            "admission audit, passed cap/guard, passed reconciliation plan, "
            "and disabled live-service decision evidence to durable no-live "
            "order-plan rows; no Coinbase order submission, no wallet "
            "allocation, and no browser execution authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/apply-executions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="execute_spot_recovery_apply",
        parity_test=(
            "spot recovery apply execution persists append-only local repair "
            "journal evidence only; no order/exchange-state mutation, Coinbase "
            "read, or Coinbase REST placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/rollback-executions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="execute_spot_recovery_rollback",
        parity_test=(
            "spot recovery rollback execution persists append-only local repair "
            "journal evidence only; no order/exchange-state mutation, Coinbase "
            "read, or Coinbase REST placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/exchange-state-proofs",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="record_spot_recovery_exchange_state_proof",
        parity_test=(
            "spot recovery exchange-state proof writing persists append-only "
            "local proof evidence only; no order/exchange-state mutation, "
            "Coinbase read, or Coinbase REST placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/exchange-state-snapshots",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="record_spot_recovery_exchange_state_snapshot",
        parity_test=(
            "spot recovery exchange-state snapshot writing persists append-only "
            "local snapshot evidence only; no order/exchange-state mutation, "
            "Coinbase read, or Coinbase REST placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/reconciliation-executions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="execute_spot_recovery_reconciliation",
        parity_test=(
            "spot recovery reconciliation execution is route-bound but "
            "fail-closed; no reconciliation execution, order/exchange-state "
            "mutation, Coinbase read, or Coinbase REST placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/reconciliation-proofs",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="record_spot_recovery_reconciliation_proof",
        parity_test=(
            "spot recovery reconciliation proof writing persists append-only "
            "local proof evidence only; no reconciliation execution, "
            "order/exchange-state mutation, Coinbase read, or Coinbase REST "
            "placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/pnl/checkpoints",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="list_spot_pnl_checkpoints",
        parity_test=(
            "read-only Spot P/L checkpoint evidence; no profitability authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/pnl/checkpoints/{checkpoint_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="get_spot_pnl_checkpoint",
        parity_test=(
            "read-only Spot P/L checkpoint detail; checkpoint is not sell authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/pnl/checkpoints",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_PNL_RECORD,
        idempotency="required",
        approval="not required for local P/L review evidence",
        caps="not applicable",
        audit="required",
        shared_method="record_spot_pnl_checkpoint",
        parity_test=(
            "append-only P/L checkpoint evidence only; no Coinbase call, "
            "sell authority, or tax accounting"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="legacy_dashboard_websocket",
        surface="cancel_order WebSocket",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission="compatibility policy",
        idempotency="enterprise-gated or compatibility-only",
        approval="not required unless policy adds approval",
        caps="required for rate/session controls",
        audit="required",
        shared_method="cancel_order_by_client_order_id",
        parity_test="WebSocket vs HTTP parity",
        compatibility_mode=AdminApiCompatibilityMode.COMPATIBILITY_ONLY.value,
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/bootstrap",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_admin_bootstrap",
        parity_test="backend association and live-disabled posture",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/approvals",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.APPROVAL_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="optional read audit",
        shared_method="list_approvals",
        parity_test="read-only approval lifecycle evidence; no command execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/approvals/requests/{approval_request_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.APPROVAL_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="optional read audit",
        shared_method="get_approval_request",
        parity_test="approval request identity only; no command execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/approvals/requests",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.APPROVAL_REQUEST,
        idempotency="required",
        approval="creates request only; not sufficient for live execution",
        caps="not applicable",
        audit="required",
        shared_method="create_approval_request",
        parity_test="request records are backend-owned and append-only",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/approvals/requests/{approval_request_id}/decisions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.APPROVAL_MANAGE,
        idempotency="required",
        approval="records backend decision; browser approval remains insufficient",
        caps="not applicable",
        audit="required",
        shared_method="decide_approval_request",
        parity_test="approved decisions link snapshots but do not execute commands",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/approvals/{approval_id}/revoke",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.APPROVAL_MANAGE,
        idempotency="required",
        approval="revokes backend approval snapshot",
        caps="not applicable",
        audit="required",
        shared_method="revoke_approval",
        parity_test="revoked snapshots fail closed in resolver",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/admission-audits",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ADMISSION_AUDIT_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only admission audit evidence",
        shared_method="list_admission_audits",
        parity_test="read-only admission audits; no command execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/admission-audits/{admission_audit_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ADMISSION_AUDIT_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only admission audit evidence",
        shared_method="get_admission_audit",
        parity_test="admission_audit_id identity only; no command execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/admission-audits",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ADMISSION_AUDIT_RECORD,
        idempotency="required",
        approval="required backend approval snapshot id link",
        caps="links expected cap/guard decision ref without evaluating guards",
        audit="required append-only admission audit proof",
        shared_method="record_admission_audit",
        parity_test="records are backend-owned and append-only; no browser audit writer",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/cap-guard/decisions",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.CAP_GUARD_READ,
        idempotency="not required",
        approval="not applicable",
        caps="read-only cap/guard decision evidence",
        audit="optional read audit",
        shared_method="list_cap_guard_decisions",
        parity_test="read-only cap/guard decisions; no guard evaluation or command execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/cap-guard/decisions/{decision_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.CAP_GUARD_READ,
        idempotency="not required",
        approval="not applicable",
        caps="read-only cap/guard decision evidence",
        audit="optional read audit",
        shared_method="get_cap_guard_decision",
        parity_test="decision_id identity only; no guard evaluation or command execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/cap-guard/decisions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CAP_GUARD_RECORD,
        idempotency="required",
        approval="required backend approval snapshot id link",
        caps="records passed or blocked backend cap/guard evidence",
        audit="required",
        shared_method="record_cap_guard_decision",
        parity_test="records are backend-owned and append-only; no browser guard evaluator",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/reconciliation/plans",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.RECONCILIATION_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only reconciliation plan evidence",
        shared_method="list_reconciliation_plans",
        parity_test="read-only reconciliation plans; no reconciliation execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/reconciliation/plans/{plan_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.RECONCILIATION_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only reconciliation plan evidence",
        shared_method="get_reconciliation_plan",
        parity_test="plan_id identity only; no reconciliation execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/reconciliation/plans",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.RECONCILIATION_RECORD,
        idempotency="required",
        approval="required backend approval snapshot id link",
        caps="requires cap/guard decision id link without evaluating guards",
        audit="required",
        shared_method="record_reconciliation_plan",
        parity_test=(
            "records are backend-owned and append-only; no reconciliation "
            "execution or order/exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/live-execution/admission-preview",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only command admission preview evidence",
        shared_method="preview_live_admission",
        parity_test=(
            "read-only exact-context command admission preview; no command "
            "execution, Coinbase call, audit append, or browser approval"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/live-execution/service-decisions",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only live-service decision evidence",
        shared_method="list_live_service_decisions",
        parity_test="read-only live-service decisions; no Coinbase execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/live-execution/service-decisions/{decision_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only live-service decision evidence",
        shared_method="get_live_service_decision",
        parity_test="decision_id identity and live-service decision readback only",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/live-execution/service-decisions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required",
        approval=(
            "records backend live-service decision; runtime opt-in and route "
            "admission still required"
        ),
        caps="not applicable",
        audit="required",
        shared_method="record_live_service_decision",
        parity_test=(
            "records are backend-owned and append-only; no adapter "
            "construction or Coinbase execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/live-execution/adapter-decisions",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only live-adapter decision evidence",
        shared_method="list_live_adapter_decisions",
        parity_test="read-only live-adapter decisions; no adapter construction",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/live-execution/adapter-decisions/{decision_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="read-only live-adapter decision evidence",
        shared_method="get_live_adapter_decision",
        parity_test="decision_id identity only; no live-adapter construction",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/live-execution/adapter-decisions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required",
        approval="records disabled backend adapter decision; not sufficient for live execution",
        caps="not applicable",
        audit="required",
        shared_method="record_live_adapter_decision",
        parity_test=(
            "records are backend-owned and append-only; no live-adapter "
            "construction, live-service enablement, or Coinbase execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/health",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_admin_health",
        parity_test="no Coinbase REST placement",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/session",
        action_class=AdminApiActionClass.READ_ONLY,
        permission="authenticated actor",
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_admin_session",
        parity_test="backend RBAC evidence only",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/oidc-readiness",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_oidc_jwt_readiness",
        parity_test="backend OIDC verifier readiness evidence only",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/capabilities",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_admin_capabilities",
        parity_test="route inventory derived registry with module_id evidence",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/csrf",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_csrf_contract",
        parity_test="does not disclose token value",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/live-enablement",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only cap evidence only",
        audit="optional read audit",
        shared_method="build_live_enablement",
        parity_test="read-only M8 live-enablement readiness; no Coinbase execution",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/enterprise-readiness",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only release evidence only",
        audit="optional read audit",
        shared_method="build_enterprise_readiness",
        parity_test=(
            "read-only M9/M20/M21 module support, registry, unsupported action, "
            "structured command-gap, security, and release evidence"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/release-gate",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_release_gate",
        parity_test="browser does not run pytest",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/recovery-gate",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_recovery_gate",
        parity_test="read-only recovery evidence",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/fill-ledger-health",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_fill_ledger_health",
        parity_test="no ledger repair mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/frontend-fixtures",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_frontend_fixtures",
        parity_test="backend-owned mock fixture examples",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/readiness",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_spot_readiness",
        parity_test="no Coinbase REST placement",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/command-suite",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only spot command-suite evidence",
        audit="optional read audit",
        shared_method="build_spot_command_suite",
        parity_test="M54 read-only spot command coverage; no Coinbase REST placement",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/recovery/preview",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only spot recovery preview evidence",
        audit="optional read audit",
        shared_method="build_spot_recovery_preview",
        parity_test=(
            "read-only spot recovery preview; no repair apply, rollback, "
            "reconciliation execution, Coinbase read, or Coinbase REST placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/recovery/apply-review",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only spot recovery apply-review evidence",
        audit="optional read audit",
        shared_method="build_spot_recovery_apply_review",
        parity_test=(
            "read-only spot recovery apply-review; no recovery apply, repair "
            "apply, rollback, reconciliation execution, Coinbase read, or "
            "Coinbase REST placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/recovery/rollback-plan",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only spot recovery rollback-plan evidence",
        audit="optional read audit",
        shared_method="build_spot_recovery_rollback_plan",
        parity_test=(
            "read-only spot recovery rollback-plan; no rollback execution, "
            "repair apply, reconciliation execution, Coinbase read, or Coinbase "
            "REST placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/recovery/reconciliation-proof",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only spot recovery reconciliation-proof evidence",
        audit="optional read audit",
        shared_method="build_spot_recovery_reconciliation_proof",
        parity_test=(
            "read-only spot recovery reconciliation-proof and execution "
            "boundary evidence; no proof writing, reconciliation execution, "
            "order/exchange-state mutation, Coinbase read, or Coinbase REST "
            "placement"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/sweep/status",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_spot_sweep_status",
        parity_test="no Coinbase REST placement",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/sweep/pnl",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_spot_sweep_pnl",
        parity_test="no Coinbase REST placement",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/cost-basis/status",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_spot_cost_basis_status",
        parity_test="no Coinbase REST placement",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/campaign/status",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.CAMPAIGN_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_spot_campaign_status",
        parity_test="no Coinbase REST placement",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/direct-orders/{client_order_id}/audit",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_spot_direct_order_audit",
        parity_test="no Coinbase REST placement",
    ),

    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/runtime",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="build_admin_runtime_status",
        parity_test="backend runtime lifecycle status only; no Coinbase call",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/runtime/pause",
        action_class=AdminApiActionClass.ADMIN_RUNTIME,
        permission=AdminApiPermission.RUNTIME_PAUSE,
        idempotency="required",
        approval="runtime permission required",
        caps="not applicable",
        audit="required",
        shared_method="pause_runtime",
        parity_test="pauses local runtime admission only; no Coinbase call",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/runtime/resume",
        action_class=AdminApiActionClass.ADMIN_RUNTIME,
        permission=AdminApiPermission.RUNTIME_RESUME,
        idempotency="required",
        approval="runtime permission required",
        caps="not applicable",
        audit="required",
        shared_method="resume_runtime",
        parity_test="resumes local runtime admission only; no Coinbase call",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/runtime/shutdown",
        action_class=AdminApiActionClass.ADMIN_RUNTIME,
        permission=AdminApiPermission.RUNTIME_SHUTDOWN,
        idempotency="required",
        approval="runtime permission required",
        caps="not applicable",
        audit="required",
        shared_method="request_runtime_shutdown",
        parity_test="requests local runtime shutdown only; no Coinbase call",
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface="GET /api/v1/admin/account-management",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="get_account_management",
        parity_test=(
            "local sanitized account reality only; zero Coinbase reads or "
            "writes; browser remains display-only"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface="GET /api/v1/admin/wallet",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="get_admin_wallet",
        parity_test=(
            "local unavailable wallet evidence only; zero Coinbase reads or "
            "writes and no admission authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface="GET /api/v1/admin/fees",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="get_admin_fees",
        parity_test=(
            "local unavailable fee evidence only; zero Coinbase reads, "
            "writes, or exchange mutations"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface="GET /api/v1/admin/products",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="get_admin_products",
        parity_test=(
            "local unavailable product evidence only; zero Coinbase reads "
            "or writes"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface="POST /api/v1/admin/products/refresh",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="not consumed; source-disabled before local mutation",
        approval="not required",
        caps="not applicable",
        audit="fixed response only; no durable audit while source-disabled",
        shared_method="refresh_admin_products",
        parity_test=(
            "source-disabled before Coinbase reads or products.json writes; "
            "no order execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/orders/{client_order_id}/fill-readback",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="read_spot_order_fill_readback",
        parity_test=(
            "client_order_id local durable sanitized fill-proof read only; zero "
            "Coinbase calls and writes; exchange order id remains evidence"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/orders/{client_order_id}/fill-readback",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="not applicable",
        audit="optional read audit",
        shared_method="read_futures_order_fill_readback",
        parity_test=(
            "fixed source-disabled local response; zero Coinbase order/fill "
            "reads, writes, or exchange mutations"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/manual-order/proof-chain",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_MANUAL_ORDER_PROOF_RECORD,
        idempotency="required",
        approval="required",
        caps="required",
        audit="required",
        shared_method="record_spot_manual_order_proof_chain",
        parity_test="records backend proof-chain evidence only; no Coinbase order submission",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/cancel-order/proof-chain",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_ORDER_CANCEL_PROOF_RECORD,
        idempotency="required",
        approval="proof evidence only",
        caps="proof evidence only",
        audit="required",
        shared_method="record_spot_cancel_order_proof_chain",
        parity_test="records backend cancel proof-chain evidence only; no Coinbase cancellation",
    ),
)
