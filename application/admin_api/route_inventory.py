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
        approval="required for route-scoped configured live gate",
        caps="required for planning, guard, wallet, and lot authority",
        audit="required",
        shared_method="place_manual_order",
        parity_test=(
            "HTTP vs place_order guard/result parity; no-live by default, "
            "REST only after exact backend auth/RBAC, idempotency, approval, "
            "admission-audit, cap/guard, reconciliation, manual acknowledgement, "
            "live-service, REST-client, and event-stream gates"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/lifecycle/pause",
        action_class=AdminApiActionClass.ADMIN_RUNTIME,
        permission=AdminApiPermission.RUNTIME_PAUSE,
        idempotency="required",
        approval="not required for soft runtime pause",
        caps="not applicable",
        audit="required",
        shared_method="pause_runtime",
        parity_test=(
            "calls RuntimeController.request_pause through Admin API auth, "
            "idempotency, operator-intent, and audit; no dashboard WebSocket "
            "fallback and no Coinbase execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/lifecycle/resume",
        action_class=AdminApiActionClass.ADMIN_RUNTIME,
        permission=AdminApiPermission.RUNTIME_RESUME,
        idempotency="required",
        approval="not required for runtime resume",
        caps="not applicable",
        audit="required",
        shared_method="resume_runtime",
        parity_test=(
            "calls RuntimeController.resume through Admin API auth, "
            "idempotency, operator-intent, and audit; no dashboard WebSocket "
            "fallback and no Coinbase execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/lifecycle/drain",
        action_class=AdminApiActionClass.ADMIN_RUNTIME,
        permission=AdminApiPermission.RUNTIME_SHUTDOWN,
        idempotency="required",
        approval="not required for bounded runtime drain",
        caps="not applicable",
        audit="required",
        shared_method="drain_runtime",
        parity_test=(
            "calls RuntimeController.request_shutdown and wait_drain through "
            "Admin API auth, idempotency, operator-intent, timeout, and audit; "
            "does not invoke stop hooks, mark STOPPED, use dashboard WebSocket "
            "fallback, or run Coinbase execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/lifecycle/stop",
        action_class=AdminApiActionClass.ADMIN_RUNTIME,
        permission=AdminApiPermission.RUNTIME_SHUTDOWN,
        idempotency="required",
        approval="not required for bounded runtime stop",
        caps="not applicable",
        audit="required",
        shared_method="stop_runtime",
        parity_test=(
            "calls RuntimeController.drain_and_stop through Admin API auth, "
            "idempotency, operator-intent, timeout, and audit; marks the "
            "runtime STOPPED, invokes stop hooks, does not use dashboard "
            "WebSocket fallback, and does not run Coinbase execution"
        ),
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
        surface="GET /api/v1/stealth/operator-scope",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only stealth operator scope boundary evidence",
        audit="optional read audit",
        shared_method="build_stealth_operator_scope",
        parity_test=(
            "read-only stealth lifecycle operator scope; no browser/BFF "
            "trading authority, dashboard fallback, Coinbase call, mutation "
            "claim acquisition, or lifecycle mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/route-inventory",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only stealth route inventory evidence",
        audit="optional read audit",
        shared_method="build_stealth_route_inventory",
        parity_test=(
            "read-only stealth route inventory derived from "
            "ADMIN_API_ROUTE_INVENTORY; no browser/BFF route inference, "
            "dashboard fallback, Coinbase call, mutation claim acquisition, "
            "reconciliation execution, or lifecycle mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_orders",
        surface="GET /api/v1/stealth/exchange-reality-contract-map",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only stealth exchange-reality contract-map evidence",
        audit="optional read audit",
        shared_method="build_stealth_exchange_reality_contract_map",
        parity_test=(
            "read-only stealth exchange-reality contract map derived from "
            "ADMIN_API_ROUTE_INVENTORY and build_stealth_command_suite; no "
            "browser/BFF exchange-truth resolution, dashboard fallback, "
            "Coinbase read, Coinbase submit/cancel, active-placement "
            "cancel/replace, reconciliation execution, or lifecycle mutation"
        ),
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
            "read-only futures command contract matrix; exposes route-bound "
            "no-live command draft evidence, request payload contract refs, "
            "semantic guard summaries, and blocked request fields while "
            "execution remains false; no spot rules or live routes"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/orders",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for futures placement admission and margin/risk controls",
        audit="required",
        shared_method="place_futures_order",
        parity_test=(
            "product_id identity; route-bound draft only with no live adapter, "
            "Coinbase submission, reconciliation execution, state mutation, "
            "browser authority, BFF authority, or spot-rule authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/positions/{position_key}/close-reduce",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for futures close/reduce admission and position controls",
        audit="required",
        shared_method="close_or_reduce_futures_position",
        parity_test=(
            "position_key identity; route-bound draft only with no live adapter, "
            "Coinbase submission, reconciliation execution, state mutation, "
            "browser authority, BFF authority, or spot-rule authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/orders/{client_order_id}/cancel",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for futures cancel admission and exchange-reality controls",
        audit="required",
        shared_method="cancel_futures_order",
        parity_test=(
            "client_order_id identity; route-bound draft only with no live "
            "adapter, Coinbase cancellation, reconciliation execution, state "
            "mutation, browser authority, BFF authority, or spot-rule authority"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/positions/{position_key}/reconciliation",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.RECONCILIATION_RECORD,
        idempotency="required",
        approval="required by current HTTP live-disabled gate",
        caps="required for futures reconciliation admission controls",
        audit="required",
        shared_method="reconcile_futures_position",
        parity_test=(
            "position_key identity; route-bound draft only with no "
            "reconciliation execution, futures/order/exchange mutation, "
            "live adapter, Coinbase call, browser authority, BFF authority, "
            "or spot-rule authority"
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
        approval="required for route-scoped configured live gate",
        caps="required for rate/session controls and reconciliation proof",
        audit="required",
        shared_method="cancel_order_by_client_order_id",
        parity_test=(
            "HTTP vs cancel_order parity; no-live by default, calls only "
            "cancel_order(client_order_id) after exact backend auth/RBAC, "
            "idempotency, approval, admission-audit, cap/guard, reconciliation, "
            "manual acknowledgement, live-service, REST-client, and "
            "event-stream gates"
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
        parity_test=(
            "campaign dry-run review is accepted without invoking runners or "
            "Coinbase; live execution remains fail-closed"
        ),
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
            "sweep dry-run review is accepted without invoking scheduler, "
            "runner, or Coinbase; live execution remains fail-closed"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/sweep/automation-controls",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_SWEEP_EXECUTE,
        idempotency="required",
        approval="required for admission evidence",
        caps="required for command admission evidence",
        audit="required",
        shared_method="record_spot_sweep_automation_control",
        parity_test=(
            "pause/resume/retry control records append-only local evidence; "
            "no scheduler invocation, no sweep runner invocation, no browser/BFF "
            "automation authority, and no Coinbase REST placement"
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
        parity_test="decision_id identity only; no live-service enablement",
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="POST /api/v1/admin/live-execution/service-decisions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required",
        approval="records disabled backend decision; not sufficient for live execution",
        caps="not applicable",
        audit="required",
        shared_method="record_live_service_decision",
        parity_test=(
            "records are backend-owned and append-only; no live-service "
            "enablement, adapter construction, or Coinbase execution"
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
        surface="GET /api/v1/admin/settings-policy-map",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only settings/policy classification only",
        audit="optional read audit",
        shared_method="build_settings_policy_map",
        parity_test=(
            "safe settings map classifies editable, read-only, secret, "
            "unsupported, and not-modeled surfaces without exposing secrets "
            "or enabling Coinbase execution"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="admin_system_health",
        surface="GET /api/v1/admin/account-market-inventory",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only coverage evidence only",
        audit="optional read audit",
        shared_method="build_account_market_inventory",
        parity_test=(
            "read-only Release 0.1 account/market inventory coverage with "
            "bounded product/wallet/balance/fill rows when backend Coinbase "
            "reads are enabled; no browser fallback, BFF execution, or "
            "trading mutation"
        ),
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
        surface="GET /api/v1/spot/sweep/automation-service",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required",
        caps="read-only campaign/sweep automation service evidence",
        audit="optional read audit",
        shared_method="build_spot_sweep_automation_service_status",
        parity_test=(
            "read-only backend-owned automation status; no scheduler "
            "invocation, no sweep runner invocation, no browser/BFF "
            "automation authority, and no Coinbase REST placement"
        ),
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
)
