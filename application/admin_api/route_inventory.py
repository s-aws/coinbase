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
        surface="GET /api/v1/spot/order-operations",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="returns durable Goal 12 audit binding",
        shared_method="list_orders",
        parity_test="PostgreSQL projection only; zero Coinbase calls",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "GET /api/v1/spot/order-operations/"
            "mutation-results/{request_correlation_id}"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="actor-bound immutable PostgreSQL result",
        shared_method="read_cycle_result",
        parity_test="PostgreSQL result only; zero Coinbase calls",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/order-operations/{client_order_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not applicable",
        caps="not applicable",
        audit="returns durable Goal 12 audit binding",
        shared_method="get_order",
        parity_test="canonical client_order_id PostgreSQL lookup only",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/order-operations/refresh",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required; one immutable goal-global cycle result",
        approval="explicit one-cycle acknowledgement; no live mutation",
        caps="one goal-global truth cycle",
        audit="required durable actor/correlation/category/page ledger",
        shared_method="refresh_catalog",
        parity_test="read-only Coinbase truth cycle; no Create or Cancel",
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/spot/order-operations/"
            "{client_order_id}/reconciliation"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required; one immutable goal-global cycle result",
        approval="explicit one-cycle acknowledgement; no live mutation",
        caps="one goal-global truth cycle",
        audit="required durable actor/correlation/category/page ledger",
        shared_method="reconcile_exact",
        parity_test="exact read-only Coinbase truth; no Create or Cancel",
    ),
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
        surface="GET /api/v1/follow-up-operations",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not applicable; local review navigation only",
        caps="not applicable; reports durable call accounting only",
        audit="returns durable correlation and audit identities",
        shared_method="list_follow_up_operations",
        parity_test=(
            "one backend-paginated local SQL snapshot with fixed sanitized "
            "classification; zero Coinbase client construction, reads, "
            "Create, or Cancel and zero local or exchange mutation; rows are "
            "review navigation only and never live eligibility"
        ),
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
        surface=(
            "GET /api/v1/orders/{source_client_order_id}/follow-up-intent/"
            "fill-triggered-activation"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not applicable; authoritative local control readback only",
        caps="reports no exchange authority and no child terms",
        audit="returns sanitized correlation and audit binding only",
        shared_method="read_fill_triggered_follow_up_activation",
        parity_test=(
            "PostgreSQL activation state only; withholds actor, roles, trigger "
            "claim, and evidence hash and makes zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/orders/{source_client_order_id}/follow-up-intent/"
            "fill-triggered-activation"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency=(
            "required revision-bound exact replay; changed action or revision "
            "conflicts"
        ),
        approval=(
            "required explicit enable, disable, pause, or drain confirmation; "
            "ENABLE delegates one future canonical Create authority"
        ),
        caps=(
            "required exact current 3.10 submitted and 1.00 possible-execution "
            "USDC caps; exactly one attached intent, full-fill claim, and "
            "backend-derived child"
        ),
        audit=(
            "required durable actor, roles, source, action, revision, "
            "correlation, and audit binding"
        ),
        shared_method="control_fill_triggered_follow_up_activation",
        parity_test=(
            "controls only one previously attached intent; backend owns the "
            "later full-fill trigger and exactly-once claim"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "GET /api/v1/orders/{source_client_order_id}/follow-up-intent/"
            "fill-triggered-activation/materialization"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not applicable; Goal 8 local evidence readback only",
        caps="reports Goal 8's one Create and one conditional Cancel allowance",
        audit="returns append-only Goal 8 operation and child evidence",
        shared_method="read_fill_triggered_follow_up_materialization",
        parity_test=(
            "reads the Goal 8 ledger and exact child locally without a "
            "Coinbase read or mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/orders/{source_client_order_id}/follow-up-intent/"
            "fill-triggered-activation/safe-closeout"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required Goal 8 exact-child one-use Cancel claim",
        approval="required explicit Goal 8 safe-closeout acknowledgement",
        caps="required at most one Cancel solely for Goal 8's exact child",
        audit="required append-only Goal 8 reconciliation and Cancel evidence",
        shared_method="safe_closeout_fill_triggered_follow_up",
        parity_test=(
            "authoritative exact-child read followed by at most one Cancel; "
            "zero retry, fallback, redirect, or alternate identity"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "GET /api/v1/orders/{source_client_order_id}/follow-up-intent/"
            "materialization"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not applicable; authoritative local readback only",
        caps="reports the fixed 3.10 submitted and 1.00 executed ceilings",
        audit="returns the immutable attempt and append-only state binding",
        shared_method="read_order_follow_up_materialization",
        parity_test=(
            "local intent, fill, lineage, exact-child, allowance, and durable "
            "attempt readback only; no Coinbase read or exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/orders/{source_client_order_id}/follow-up-intent/"
            "materialization"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency=(
            "required durable one-use claim; exact key replays and changed "
            "key or payload conflicts"
        ),
        approval=(
            "required fresh explicit materialization header and "
            "acknowledgements; the attachment acknowledgement is never live "
            "authority"
        ),
        caps=(
            "required backend fixed max submitted 3.10 USDC and max "
            "executed/effective 1.00 USDC, plus wallet and standing-price policy"
        ),
        audit=(
            "required immutable actor/source/root/intent/child/candidate binding "
            "and append-only invocation/result events"
        ),
        shared_method="materialize_order_follow_up_intent",
        parity_test=(
            "fresh exact full-fill, Test portfolio, Spot product, wallet, cap, "
            "market, and child-absence revalidation; persists only the exact "
            "preclaimed child before one Create with zero retry or fallback"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/orders/{source_client_order_id}/follow-up-intent/"
            "materialization/safe-closeout"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency=(
            "required separate durable Cancel key; exact replay only and no "
            "second boundary"
        ),
        approval=(
            "required fresh exact-child safe-closeout header and acknowledgements"
        ),
        caps=(
            "required one exact materialized child and at most one Cancel call"
        ),
        audit=(
            "required authoritative child-state read and append-only Cancel "
            "boundary/result evidence"
        ),
        shared_method="safe_closeout_materialized_follow_up_intent",
        parity_test=(
            "backend resolves the exact child and exchange evidence; terminal "
            "state is a no-op, active state permits one Cancel, and unknown "
            "consumes without retry, fallback, or alternate identity"
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
        module_id="stealth_definitions",
        surface="GET /api/v1/stealth/definitions",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; PostgreSQL definition readback only",
        caps="backend pagination up to 100 local definitions",
        audit="returns fixed lifecycle, runtime interlock, and command evidence",
        shared_method="list_operator_stealth_definitions",
        parity_test=(
            "call-free local definition readback; zero Coinbase calls and "
            "zero exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface="GET /api/v1/stealth/definitions/{definition_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; exact local definition readback only",
        caps="one exact definition and paginated fixed audit events",
        audit="returns runtime interlock, allowed actions, and fixed events",
        shared_method="get_operator_stealth_definition",
        parity_test=(
            "call-free exact definition projection; canonical runtime "
            "presence fails local mutations closed"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface=(
            "GET /api/v1/stealth/definitions/{definition_id}/execution"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; PostgreSQL goal-ledger readback only",
        caps="one exact Goal 6 definition and client_order_id",
        audit="fixed sanitized allowance, call-count, and terminal evidence",
        shared_method="get_operator_stealth_reveal_execution",
        parity_test=(
            "call-free reveal/closeout readback; raw Preview response and "
            "exchange order identity remain withheld"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface=(
            "POST /api/v1/stealth/definitions/{definition_id}/reveal"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required; exact revision/hash payload replay only",
        approval=(
            "required explicit exact-definition operator acknowledgement"
        ),
        caps=(
            "required one durable Preview claim and, only after accepted "
            "Preview, one identical Create"
        ),
        audit=(
            "required PostgreSQL definition/runtime/plan binding and fixed "
            "sanitized Preview/Create terminal evidence"
        ),
        shared_method="reveal_operator_stealth_definition",
        parity_test=(
            "canonical build_reveal_execution_plan and reveal_order_slice; "
            "one Create attempt, no retry, no automatic reveal"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface=(
            "POST /api/v1/stealth/definitions/{definition_id}/"
            "resume-accepted-create"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency=(
            "required; each interrupted pre-Create resume receives one "
            "bounded command cycle while Create remains unclaimed"
        ),
        approval=(
            "required explicit Preview-accepted Create resume acknowledgement"
        ),
        caps=(
            "required existing accepted Preview and still-unconsumed sole "
            "identical Create allowance"
        ),
        audit=(
            "required PostgreSQL resume correlation/idempotency binding, "
            "frozen plan, and exact Create claim evidence"
        ),
        shared_method="resume_operator_stealth_accepted_create",
        parity_test=(
            "restart-safe canonical reveal_order_slice continuation; no new "
            "Preview, alternate terms, retry, or second Create"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface=(
            "POST /api/v1/stealth/definitions/{definition_id}/closeout"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required; exact plan/client_order_id replay only",
        approval=(
            "required explicit exact-placement closeout acknowledgement"
        ),
        caps=(
            "required at most one Cancel after authoritative exact "
            "nonterminal readback"
        ),
        audit=(
            "required fixed pre/post readback classification, one-use cancel "
            "claim, and terminal manager reconciliation"
        ),
        shared_method="closeout_operator_stealth_placement",
        parity_test=(
            "canonical cancel_stealth_order exchange boundary with deferred "
            "local terminal state until exact readback"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface=(
            "GET /api/v1/stealth/definition-import-previews/{preview_id}"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; durable sanitized preview readback only",
        caps="one import preview of at most 100 definitions",
        audit="returns fixed per-item validation codes only",
        shared_method="get_operator_stealth_definition_import_preview",
        parity_test=(
            "readback cannot create a definition, activate a runtime order, "
            "or call Coinbase"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface="POST /api/v1/stealth/definitions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit local-definition create acknowledgement",
        caps="one DRAFT definition for one enabled Spot product",
        audit="required actor, hashed reason, revision, and correlation",
        shared_method="create_operator_stealth_definition",
        parity_test=(
            "PostgreSQL definition creation only; no manager, evaluator, "
            "order, Coinbase call, or exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface=(
            "POST /api/v1/stealth/definitions/{definition_id}/edit"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit exact-revision edit acknowledgement",
        caps="one DRAFT definition with immutable product and side",
        audit="required actor, hashed reason, revision, and correlation",
        shared_method="edit_operator_stealth_definition",
        parity_test=(
            "threshold, target movement, and allowlisted terms update only "
            "when no canonical stealth runtime row exists"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface=(
            "POST /api/v1/stealth/definitions/{definition_id}/cancel"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit exact-revision local cancellation acknowledgement",
        caps="one DRAFT, unmaterialized definition",
        audit="required durable terminal event and fixed blocker evidence",
        shared_method="cancel_operator_stealth_definition",
        parity_test=(
            "local DRAFT to CANCELLED transition only; active or revealed "
            "runtime rows fail closed without Coinbase cancellation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface="POST /api/v1/stealth/definitions/clear",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit exact-set clear acknowledgement",
        caps="atomic exact set of one to 100 DRAFT definitions",
        audit="required one fixed clear event per selected definition",
        shared_method="clear_operator_stealth_definitions",
        parity_test=(
            "atomic local DRAFT to CLEARED transitions; any runtime or "
            "revision conflict rolls back the entire set"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface="POST /api/v1/stealth/definition-exports",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit exact-set export acknowledgement",
        caps="one to 100 DRAFT unmaterialized definitions",
        audit="required one fixed export event per definition and manifest hash",
        shared_method="export_operator_stealth_definitions",
        parity_test=(
            "allowlisted definition fields only; runtime state, exchange ids, "
            "responses, and secrets are excluded"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface="POST /api/v1/stealth/definition-import-previews",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit schema-validation preview acknowledgement",
        caps="one manifest with one to 100 definitions",
        audit=(
            "required fixed per-item schema, identity, product, and increment "
            "codes"
        ),
        shared_method="preview_operator_stealth_definition_import",
        parity_test=(
            "preview stores no definition and invokes no runtime or Coinbase "
            "path"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="stealth_definitions",
        surface=(
            "POST /api/v1/stealth/definition-import-previews/"
            "{preview_id}/apply"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit exact-manifest apply acknowledgement",
        caps="atomic apply of one valid preview with at most 100 definitions",
        audit=(
            "required one imported event per definition and durable preview "
            "linkage"
        ),
        shared_method="apply_operator_stealth_definition_import",
        parity_test=(
            "atomic PostgreSQL import only; no manager, evaluator, Coinbase "
            "call, or exchange mutation"
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
        surface=(
            "GET /api/v1/movement-repricing/stealth/{stealth_order_id}/"
            "move-execution"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; PostgreSQL Goal 7 ledger readback only",
        caps="one exact zero-fill movement and fixed 3.10/1.00 USDC caps",
        audit="fixed hash-only plan, allowance, call, and terminal evidence",
        shared_method="get_operator_revealed_order_movement",
        parity_test=(
            "call-free exact movement readback; raw exchange identities, "
            "responses, and exception text remain withheld"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface=(
            "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/"
            "move-plans"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CANCEL,
        required_permissions=[
            AdminApiPermission.ORDER_CANCEL,
            AdminApiPermission.ORDER_CREATE,
        ],
        idempotency="required; exact reviewed payload replay only",
        approval="explicit operator plan acknowledgement; no live call",
        caps="required direct submitted and possible-execution cap proof",
        audit=(
            "required; durable immutable plan, actor hash, and correlation "
            "evidence"
        ),
        shared_method="prepare_operator_revealed_order_movement",
        parity_test=(
            "manager-owned call-free zero-fill, product, increment, target, "
            "and profitability validation; zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface=(
            "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/"
            "execute-move"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        required_permissions=[
            AdminApiPermission.ORDER_CANCEL,
            AdminApiPermission.ORDER_CREATE,
        ],
        idempotency="required; one exact plan-bound command cycle",
        approval="required explicit exact Cancel/Create acknowledgement",
        caps=(
            "required; one Cancel and, only after exact CANCELLED readback, one "
            "post-only replacement Create; zero retries"
        ),
        audit=(
            "required; PostgreSQL claims, exact read accounting, fixed "
            "diagnostics, hash-only exchange identity, and restart recovery"
        ),
        shared_method="execute_operator_revealed_order_movement",
        parity_test=(
            "canonical StealthOrderManager movement phases and flat linkage; "
            "unknown or unsuccessful Cancel prohibits Create"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface=(
            "GET /api/v1/movement-repricing/orders/{client_order_id}/"
            "parent-move"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; call-free PostgreSQL authority readback",
        caps=(
            "not applicable to the read; reports fixed 3.10 submitted and "
            "1.00 possible-execution USDC"
        ),
        audit="hash-only source, plan, cycle, allowance, and call evidence",
        shared_method="get_operator_parent_move_premark",
        parity_test=(
            "call-free exact direct-parent selection and Goal 14 ledger "
            "readback; zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface=(
            "POST /api/v1/movement-repricing/orders/{client_order_id}/"
            "parent-move-plans"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CANCEL,
        required_permissions=[
            AdminApiPermission.ORDER_CANCEL,
            AdminApiPermission.ORDER_CREATE,
        ],
        idempotency="required; exact immutable local plan replay only",
        approval="explicit PREMARK acknowledgement; no exchange authority",
        caps=(
            "required; fixed 3.10 submitted and 1.00 possible-execution USDC"
        ),
        audit=(
            "required; actor hash, correlation, payload hash, reserved "
            "successor, plan hash, and completed cycle evidence"
        ),
        shared_method="premark_operator_parent_move",
        parity_test=(
            "PostgreSQL-only exact direct-root premark; backend owns Test "
            "portfolio, BTC-USDC policy, increments, minimums, and zero fill"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface=(
            "POST /api/v1/movement-repricing/orders/{client_order_id}/"
            "execute-parent-move"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        required_permissions=[
            AdminApiPermission.ORDER_CANCEL,
            AdminApiPermission.ORDER_CREATE,
        ],
        idempotency="required by contract; no claim under current authority",
        approval=(
            "required by contract; source-disabled by incomplete Goal 14 "
            "live authority terms"
        ),
        caps=(
            "required; fixed 3.10 submitted and 1.00 possible-execution USDC"
        ),
        audit=(
            "required; fixed authority blocker before service, ledger, "
            "runtime, or Coinbase access"
        ),
        shared_method="execute_operator_parent_move",
        parity_test=(
            "visible future source Cancel/replacement Create contract fails "
            "closed; both allowances remain unconsumed"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface=(
            "POST /api/v1/movement-repricing/orders/{client_order_id}/"
            "parent-move-safe-closeout"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        required_permissions=[
            AdminApiPermission.ORDER_CANCEL,
            AdminApiPermission.ORDER_CREATE,
        ],
        idempotency="required by contract; no claim under current authority",
        approval=(
            "required by contract; source-disabled by incomplete Goal 14 "
            "live authority terms"
        ),
        caps=(
            "required; one exact reserved successor only; currently "
            "unavailable"
        ),
        audit=(
            "required; fixed authority blocker before service, ledger, "
            "runtime, or Coinbase access"
        ),
        shared_method="safe_closeout_operator_parent_move",
        parity_test=(
            "visible future exact-successor Cancel contract fails closed; "
            "closeout allowance remains unconsumed"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface=(
            "GET /api/v1/movement-repricing/stealth/{stealth_order_id}/"
            "placements/{client_order_id}/reprice-now"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; call-free canonical local source readback",
        caps=(
            "not bound; Goal 15 persists identity-only intent and reports "
            "cap_policy_bound=false"
        ),
        audit=(
            "sanitized exact source evidence; no exchange identifier or "
            "exchange-identifier hash"
        ),
        shared_method="get_single_order_reprice_now",
        parity_test=(
            "canonical Goal 7 local REVEALED zero-fill source resolver; zero "
            "Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface=(
            "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/"
            "placements/{client_order_id}/reprice-now-intents"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CANCEL,
        required_permissions=[
            AdminApiPermission.ORDER_CANCEL,
            AdminApiPermission.ORDER_CREATE,
        ],
        idempotency=(
            "required; actor/correlation/payload/source-evidence exact replay"
        ),
        approval=(
            "explicit prepare_single_order_reprice_now acknowledgement; "
            "no live authority"
        ),
        caps=(
            "not bound; browser supplies no product, portfolio, price, size, "
            "or cap term"
        ),
        audit=(
            "required; PostgreSQL intent, deterministic UUIDv5 successor, "
            "actor/key/payload hashes, completed cycle, and sanitized event"
        ),
        shared_method="prepare_reprice_now_intent",
        parity_test=(
            "one exact system-owned direct-parent REVEALED source; immutable "
            "non-market intent only"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="movement_repricing",
        surface=(
            "POST /api/v1/movement-repricing/stealth/{stealth_order_id}/"
            "placements/{client_order_id}/execute-reprice-now"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        required_permissions=[
            AdminApiPermission.ORDER_CANCEL,
            AdminApiPermission.ORDER_CREATE,
        ],
        idempotency="required by contract; no claim under current authority",
        approval=(
            "required by contract; fixed incomplete-live-terms blocker"
        ),
        caps="required but unbound under the conservative Goal 15 authority",
        audit=(
            "required by future contract; fixed blocker before service, "
            "PostgreSQL ledger, runtime, or Coinbase access"
        ),
        shared_method="execute_reprice_now",
        parity_test=(
            "visible future source Cancel/replacement Create remains disabled; "
            "both allowances remain unconsumed"
        ),
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
        surface=(
            "POST /api/v1/futures/order-operations/"
            "{client_order_id}/cancel"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency=(
            "required revision-bound cycle plus independent durable single-use "
            "exact Cancel claim"
        ),
        approval=(
            "required explicit exact client_order_id, one no-retry read cycle, "
            "and unknown-Cancel-consumption acknowledgement"
        ),
        caps="required one Default-profile Futures order and at most one Cancel",
        audit=(
            "required PostgreSQL category/page claims, ephemeral exchange-id "
            "resolution, hashed identity, and exact Cancel call accounting"
        ),
        shared_method="cancel_operator_futures_order",
        parity_test=(
            "one Default-profile product_type=FUTURE catalog read with no page "
            "retry, one exact client_order_id match, and at most one exchange-id "
            "Cancel with zero retry or fallback"
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
            "legacy client_order_id draft remains source-disabled with a fixed "
            "NOT_IMPLEMENTED response before replay, admission, audit, service, "
            "adapter, or Coinbase code"
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
            "controlled-live HTTP vs canonical cancel_order parity with full "
            "request admission and final execution-authority enforcement; an "
            "optional complete PostgreSQL recovery binding must atomically "
            "claim and close its sole allowance around the same wrapper; the "
            "mutually exclusive typed Goal 12 binding similarly claims only "
            "after admission and marks the exact existing SDK boundary"
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
        surface="GET /api/v1/spot/recovery/cases",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required; PostgreSQL case readback only",
        caps="reports per-case ten-cycle and one-Cancel accounting",
        audit="returns immutable sanitized recovery events",
        shared_method="list_operator_spot_recovery_cases",
        parity_test=(
            "backend-paginated PostgreSQL case list; zero Coinbase reads or "
            "exchange mutations"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/recovery/cases/{case_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required; exact case readback only",
        caps="reports per-case ten-cycle and one-Cancel accounting",
        audit="returns immutable sanitized recovery events",
        shared_method="get_operator_spot_recovery_case",
        parity_test=(
            "exact PostgreSQL case readback keyed by backend case identity; "
            "zero Coinbase reads or exchange mutations"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/cases",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_RECORD,
        idempotency="required; exact payload replay only",
        approval="explicit operator intent; no live authority",
        caps="one exact system-owned client_order_id per case",
        audit="required actor and hashed reason evidence",
        shared_method="create_operator_spot_recovery_case",
        parity_test=(
            "verifies durable system ownership and approved Test portfolio "
            "binding before one PostgreSQL case write; zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/cases/{case_id}/refresh",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        idempotency="required; exact payload replay only",
        approval="explicit manual live-read acknowledgement required",
        caps=(
            "maximum ten cycles; one logical exact-order read and one logical "
            "fill-catalog read per claimed cycle, with no page retry"
        ),
        audit="required fixed diagnostic and logical call accounting",
        shared_method="refresh_operator_spot_recovery_case",
        parity_test=(
            "canonical exact-order and fill readers produce a backend-owned "
            "immutable repair plan; no Coinbase mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/cases/{case_id}/apply",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        idempotency="required; exact payload replay only",
        approval="explicit reviewed-plan acknowledgement required",
        caps="one exact local status transition from immutable plan",
        audit="required actor and hashed reason evidence",
        shared_method="apply_operator_spot_recovery_case",
        parity_test=(
            "atomic PostgreSQL plan/revision/status precondition and local "
            "order repair; zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/recovery/cases/{case_id}/rollback",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_RECOVERY_EXECUTE,
        idempotency="required; exact payload replay only",
        approval="explicit safe-rollback acknowledgement required",
        caps="one exact terminal-to-terminal local rollback only",
        audit="required actor and hashed reason evidence",
        shared_method="rollback_operator_spot_recovery_case",
        parity_test=(
            "atomic PostgreSQL revision/status precondition blocks unsafe "
            "nonterminal restoration; zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface="GET /api/v1/product-catalog",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; PostgreSQL revision readback only",
        caps="backend pagination up to 100 immutable revisions",
        audit="returns fixed authority and goal-budget evidence",
        shared_method="list_operator_product_catalog",
        parity_test=(
            "call-free PostgreSQL revision list with zero trading authority "
            "and zero exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface="GET /api/v1/product-catalog/revisions/{revision_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; exact immutable revision readback only",
        caps="one exact revision, allowlisted metadata diff, and audit events",
        audit="fixed sanitized revision events only",
        shared_method="get_operator_product_catalog_revision",
        parity_test=(
            "call-free exact revision, per-product diff, and lifecycle "
            "readback; zero exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface="POST /api/v1/product-catalog/refresh",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit one-no-retry-read acknowledgement required",
        caps=(
            "maximum ten goal-global logical catalog reads; required cursor "
            "pages once each with no retry"
        ),
        audit=(
            "required durable page claims, call accounting, and fixed "
            "diagnostics"
        ),
        shared_method="refresh_operator_product_catalog",
        parity_test=(
            "one documented List Products read builds an immutable proposed "
            "metadata revision; zero exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface=(
            "POST /api/v1/product-catalog/revisions/"
            "{revision_id}/approve"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit exact revision and snapshot acknowledgement",
        caps="one proposed revision activation",
        audit="required actor, hashed reason, and snapshot binding",
        shared_method="approve_operator_product_catalog_revision",
        parity_test=(
            "atomic revision and parent preconditions activate only the "
            "reviewed administrative snapshot; no trading authority"
        ),
    ),
    *(
        AdminApiRouteInventoryItem(
            module_id="account_management",
            surface=(
                "POST /api/v1/product-catalog/products/{product_id}/"
                f"{action}"
            ),
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            permission=AdminApiPermission.CONFIG_UPDATE,
            idempotency="required; exact payload replay only",
            approval="explicit exact active-revision acknowledgement",
            caps="one exact administrative product lifecycle transition",
            audit="required actor, hashed reason, product, and lifecycle",
            shared_method="change_operator_product_catalog_lifecycle",
            parity_test=(
                "atomic active-revision clone changes one catalog lifecycle "
                "without modifying trading policy or calling Coinbase"
            ),
        )
        for action in ("enable", "disable", "retire")
    ),
    AdminApiRouteInventoryItem(
        module_id="account_management",
        surface=(
            "POST /api/v1/product-catalog/revisions/"
            "{target_revision_id}/rollback"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit active and target snapshot acknowledgement",
        caps="one exact prior administrative snapshot restored as a new revision",
        audit="required actor, hashed reason, and target revision linkage",
        shared_method="rollback_operator_product_catalog_revision",
        parity_test=(
            "atomic active and target snapshot preconditions restore one "
            "reviewed catalog; zero exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/parent-strategies",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; PostgreSQL definition readback only",
        caps="backend pagination up to 100 local parent strategies",
        audit="returns fixed lifecycle and dependency evidence",
        shared_method="list_operator_parent_strategies",
        parity_test=(
            "call-free parent strategy list; zero Coinbase calls and zero "
            "exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/parent-strategies/{strategy_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not required; exact local definition readback only",
        caps="one exact strategy and paginated fixed audit events",
        audit="returns backend deletion blockers and allowed actions",
        shared_method="get_operator_parent_strategy",
        parity_test=(
            "call-free exact parent strategy and dependency projection; "
            "zero exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/parent-strategies",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit parent-strategy creation acknowledgement",
        caps=(
            "one active definition for one enabled Spot product and hashed "
            "approved portfolio scope"
        ),
        audit="required actor, hashed reason, revision, and correlation",
        shared_method="create_operator_parent_strategy",
        parity_test=(
            "PostgreSQL definition creation only; no order, claim, Coinbase "
            "call, or exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/parent-strategies/{strategy_id}/edit",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit exact-revision edit acknowledgement",
        caps=(
            "allowlisted target movement, replacement, partial-fill, and "
            "fixed limit-child policy only"
        ),
        audit="required actor, hashed reason, revision, and correlation",
        shared_method="edit_operator_parent_strategy",
        parity_test=(
            "optimistic local policy edit only; immutable product, side, size, "
            "and price; zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/parent-strategies/{strategy_id}/deactivate"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit exact-revision deactivation acknowledgement",
        caps="one-way ACTIVE to DEACTIVATED local transition",
        audit="required actor, hashed reason, revision, and correlation",
        shared_method="deactivate_operator_parent_strategy",
        parity_test=(
            "local future-use deactivation only; no order or exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/parent-strategies/{strategy_id}/delete",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.CONFIG_UPDATE,
        idempotency="required; exact payload replay only",
        approval="explicit exact-revision deletion acknowledgement",
        caps=(
            "deactivated unused or terminal parent with zero active placement, "
            "child, unresolved claim, or reconciliation requirement"
        ),
        audit="required durable tombstone, actor, hashed reason, and blockers",
        shared_method="delete_operator_parent_strategy",
        parity_test=(
            "dependency-locked local tombstone only; zero Coinbase calls and "
            "zero exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/fill-inventory-repair/cases",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required; PostgreSQL case readback only",
        caps="reports the independent goal-global ten-cycle fill-read budget",
        audit="returns immutable sanitized import-batch events",
        shared_method="list_operator_fill_inventory_repair_cases",
        parity_test=(
            "backend-paginated repair cases and FIFO inventory projections; "
            "zero Coinbase reads or exchange mutations"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="GET /api/v1/spot/fill-inventory-repair/cases/{case_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUDIT_READ,
        idempotency="not required",
        approval="not required; exact case readback only",
        caps="one exact durable repair case",
        audit="returns immutable sanitized import-batch events",
        shared_method="get_operator_fill_inventory_repair_case",
        parity_test=(
            "exact PostgreSQL case and lot/P&L readback; zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface="POST /api/v1/spot/fill-inventory-repair/cases",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_FILL_INVENTORY_REPAIR_RECORD,
        idempotency="required; exact payload replay only",
        approval="explicit operator selector and reason required",
        caps=(
            "one exact system-owned order, approved BTC-USDC product, or "
            "bounded 24-hour BTC-USDC window"
        ),
        audit="required actor and hashed reason evidence",
        shared_method="create_operator_fill_inventory_repair_case",
        parity_test=(
            "binds one PostgreSQL case to the configured Test portfolio; "
            "zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/spot/fill-inventory-repair/cases/"
            "{case_id}/refresh"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_FILL_INVENTORY_REPAIR_EXECUTE,
        idempotency="required; exact payload replay only",
        approval="explicit manual live-read acknowledgement required",
        caps=(
            "maximum ten goal-global cycles across all repair cases; one "
            "logical fill-catalog read per claimed cycle, required cursor "
            "pages, and no page retry"
        ),
        audit=(
            "required actor audit, fixed diagnostics, and exact logical/page "
            "call accounting"
        ),
        shared_method="refresh_operator_fill_inventory_repair_case",
        parity_test=(
            "normalizes only allowlisted fill values, hashes all documented "
            "exchange identity aliases, and builds one scoped immutable "
            "import/projection plan; zero Coinbase order mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/spot/fill-inventory-repair/cases/{case_id}/apply"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_FILL_INVENTORY_REPAIR_EXECUTE,
        idempotency="required; exact payload replay only",
        approval="explicit immutable-plan acknowledgement required",
        caps="one exact missing-fill import batch and one BTC-USDC projection",
        audit="required actor, hashed reason, and inserted-row count",
        shared_method="apply_operator_fill_inventory_repair_case",
        parity_test=(
            "atomic PostgreSQL identity claims and reviewed-ledger baseline "
            "checks import only missing fills and rebuild FIFO lots, cost "
            "basis, fees, and operational P/L; zero Coinbase calls"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="spot_operations",
        surface=(
            "POST /api/v1/spot/fill-inventory-repair/cases/"
            "{case_id}/rollback"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.SPOT_FILL_INVENTORY_REPAIR_EXECUTE,
        idempotency="required; exact payload replay only",
        approval=(
            "explicit exact-batch rollback acknowledgement and applied-plan "
            "hash required"
        ),
        caps="deletes only rows linked to the selected import batch",
        audit="required actor, hashed reason, and deleted-row count",
        shared_method="rollback_operator_fill_inventory_repair_case",
        parity_test=(
            "atomic rollback verifies locked post-apply projection content/"
            "hash and exact fill/alias ownership, rejects superseded state, "
            "and restores the prior projection with its prior source "
            "provenance; zero Coinbase calls"
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
        surface="POST /api/v1/admin/runtime/drain",
        action_class=AdminApiActionClass.ADMIN_RUNTIME,
        permission=AdminApiPermission.RUNTIME_DRAIN,
        idempotency="required",
        approval="runtime permission required",
        caps="not applicable",
        audit="required",
        shared_method="drain_runtime",
        parity_test="drains local runtime admission and retains readback; no Coinbase call",
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
        shared_method="queue_runtime_shutdown",
        parity_test="queues response-safe local runtime shutdown only; no Coinbase call",
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
        module_id="account_management",
        surface="POST /api/v1/admin/account-reality/refresh",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ACCOUNT_REALITY_REFRESH,
        idempotency="required",
        approval="not required; explicit authenticated operator intent required",
        caps="not applicable; read-only Coinbase categories",
        audit="required durable claim and terminal sanitized evidence",
        shared_method="refresh_account_reality",
        parity_test=(
            "six approved read-only categories at most once each; strict "
            "pagination without retries; zero order or Futures risk calls"
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
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="GET /api/v1/automation/control-plane",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; local authority readback only",
        caps="not applicable; no domain invocation",
        audit="durable control-plane revision readback",
        shared_method="get_control_plane",
        parity_test="local PostgreSQL read only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="GET /api/v1/automation/control-plane/events",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; local posture audit readback only",
        caps="not applicable; no domain invocation",
        audit="durable posture transitions with audit and correlation identifiers",
        shared_method="list_control_events",
        parity_test="local PostgreSQL page only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="GET /api/v1/automation/definitions",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; local definition readback only",
        caps="not applicable; no domain invocation",
        audit="backend-owned filtering and pagination",
        shared_method="list_definitions",
        parity_test="local PostgreSQL page only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/definitions",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONFIGURE,
        idempotency="required; exact replay only",
        approval="explicit operator intent; never live authorization",
        caps="typed domain scope only; no domain invocation",
        audit="required durable actor, correlation, and revision binding",
        shared_method="create_definition",
        parity_test="local PostgreSQL definition only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/near-market-candidates",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ACCOUNT_REALITY_REFRESH,
        idempotency=(
            "required durable goal-global preparation claim; exact replay is "
            "call-free and changed payload, actor, or intent conflicts"
        ),
        approval=(
            "required explicit backend-derived BTC-USDC/Test-scope and unknown-consumes-cycle "
            "acknowledgements; also requires automation configure, trigger, and resume"
        ),
        caps=(
            "required one sequential V4-V6 proposal, one no-retry six-category preparation read, "
            "3.10 submitted and 1.00 possible-execution USDC ceilings"
        ),
        audit=(
            "required durable preparation cycle, fixed sanitized classification, atomic immutable "
            "definition linkage, and exact or unknown call accounting"
        ),
        shared_method="prepare_near_market_candidate",
        parity_test=(
            "bounded approved Coinbase calls for six read-only categories; zero Preview, "
            "Create, Cancel, retry, or other exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/minimum-size-candidates",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ACCOUNT_REALITY_REFRESH,
        idempotency=(
            "required durable goal-global V7-V9 preparation claim; exact replay is "
            "call-free and changed payload, actor, or intent conflicts"
        ),
        approval=(
            "required explicit backend-derived BTC-USDC/Test scope, dynamic-cap-below-3.10, "
            "and unknown-consumes-cycle acknowledgements; also requires automation "
            "configure, trigger, and resume"
        ),
        caps=(
            "required one sequential V7-V9 proposal, one no-retry six-category preparation "
            "read, submitted notional strictly below 3.10 USDC, and the smallest "
            "backend-derived fee-reserved execution cap strictly below 3.10 USDC"
        ),
        audit=(
            "required durable preparation cycle, fixed sanitized V4 boundary classification, "
            "atomic immutable definition linkage, and exact or unknown call accounting"
        ),
        shared_method="prepare_minimum_size_candidate",
        parity_test=(
            "bounded approved Coinbase calls for six read-only categories; zero Preview, "
            "Create, Cancel, retry, or other exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface=(
            "POST /api/v1/automation/"
            "atomic-market-snapshot-candidates/authorize"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency=(
            "required durable goal-global V13-V15 transport cycle and single-use "
            "Preview claim; terminal replay is call-free and changed request, "
            "actor, intent, or correlation identity conflicts"
        ),
        approval=(
            "required explicit atomic-snapshot, eight-category read, Preview, "
            "conditional identical Create, and unknown-consumption "
            "acknowledgements; also requires account reality refresh, "
            "automation configure, trigger, and resume"
        ),
        caps=(
            "required one sequential BTC-USDC V13-V15 candidate and one child; "
            "submitted and possible-execution notionals are each strictly below "
            "3.10 USDC"
        ),
        audit=(
            "required separate PostgreSQL value-blind no-HTTP DNS/TCP/TLS "
            "readiness record followed by atomic binding of one fresh market "
            "snapshot, final immutable terms, candidate identity, eight category "
            "attempts, single-use Preview claim, sanitized terminal "
            "classification, and exact or unknown call accounting"
        ),
        shared_method="authorize_atomic_market_snapshot_candidate",
        parity_test=(
            "Coinbase calls are limited to exactly eight approved no-retry read "
            "categories feeding one atomic "
            "final-market-snapshot binding immediately before at most one Preview; "
            "only an accepted error-free Preview permits one identical canonical "
            "Create, with zero route-local retry or alternate identity"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="GET /api/v1/automation/definitions/{definition_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; local definition readback only",
        caps="not applicable; no domain invocation",
        audit="durable definition revision readback",
        shared_method="get_definition",
        parity_test="local PostgreSQL read only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="GET /api/v1/automation/definitions/{definition_id}/events",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; local definition audit readback only",
        caps="not applicable; no domain invocation",
        audit="durable definition transitions with audit and correlation identifiers",
        shared_method="list_definition_events",
        parity_test="local PostgreSQL page only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/definitions/{definition_id}/enable",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONFIGURE,
        idempotency="required; exact replay only",
        approval="explicit local lifecycle intent; never live authorization",
        caps="not applicable; enabling does not invoke a domain",
        audit="required durable lifecycle transition",
        shared_method="transition_definition",
        parity_test="local lifecycle transition only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/definitions/{definition_id}/disable",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONFIGURE,
        idempotency="required; exact replay only",
        approval="explicit local lifecycle intent; never live authorization",
        caps="not applicable; disabling does not invoke a domain",
        audit="required durable lifecycle transition",
        shared_method="transition_definition",
        parity_test="local lifecycle transition only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/definitions/{definition_id}/pause",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONFIGURE,
        idempotency="required; exact replay only",
        approval="explicit local lifecycle intent; never live authorization",
        caps="not applicable; pausing does not invoke a domain",
        audit="required durable lifecycle transition",
        shared_method="transition_definition",
        parity_test="local lifecycle transition only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/definitions/{definition_id}/resume",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONFIGURE,
        idempotency="required; exact replay only",
        approval="explicit local lifecycle intent; never live authorization",
        caps="not applicable; resuming does not invoke a domain",
        audit="required durable lifecycle transition",
        shared_method="transition_definition",
        parity_test="local lifecycle transition only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/definitions/{definition_id}/drain",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONFIGURE,
        idempotency="required; exact replay only",
        approval="explicit local lifecycle intent; never live authorization",
        caps="not applicable; draining does not invoke a domain",
        audit="required durable lifecycle transition",
        shared_method="transition_definition",
        parity_test="local lifecycle transition only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/definitions/{definition_id}/schedule",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONFIGURE,
        idempotency="required; exact replay only",
        approval="explicit review-schedule intent; never live activation",
        caps="review timing only; no recurring live scheduler",
        audit="required durable schedule revision",
        shared_method="set_definition_schedule",
        parity_test="review metadata only; zero Coinbase call or worker start",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/definitions/{definition_id}/schedule/clear",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONFIGURE,
        idempotency="required; exact replay only",
        approval="explicit local schedule-clear intent",
        caps="manual-only review metadata; no domain invocation",
        audit="required durable schedule revision",
        shared_method="clear_definition_schedule",
        parity_test="review metadata only; zero Coinbase call or worker start",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/control-plane/pause",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONTROL,
        idempotency="required; exact replay only",
        approval="explicit local control-plane intent",
        caps="not applicable; blocks admission only",
        audit="required durable posture revision",
        shared_method="transition_control_posture",
        parity_test="local posture transition only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/control-plane/resume",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_RESUME,
        idempotency="required; exact replay only",
        approval="explicit local control-plane intent; no live authority",
        caps="not applicable; restores local admission only",
        audit="required durable posture revision",
        shared_method="transition_control_posture",
        parity_test="local posture transition only; zero Coinbase call or worker start",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/control-plane/drain",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONTROL,
        idempotency="required; exact replay only",
        approval="explicit local control-plane intent",
        caps="not applicable; blocks new local claims only",
        audit="required durable posture revision",
        shared_method="transition_control_posture",
        parity_test="local posture transition only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/control-plane/shutdown",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONTROL,
        idempotency="required; exact replay only",
        approval="explicit local control-plane intent",
        caps="not applicable; blocks local claims only",
        audit="required durable posture revision",
        shared_method="transition_control_posture",
        parity_test="local posture transition only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="POST /api/v1/automation/definitions/{definition_id}/runs",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_TRIGGER,
        idempotency="required one-shot claim; exact replay only",
        approval="explicit one-shot intent; never exchange authorization",
        caps="one definition, one run, and one immutable BTC-USDC child plan",
        audit="required durable claim, preparation, and fixed blocker event",
        shared_method="claim_one_shot_run",
        parity_test=(
            "single-child plan preparation is local; zero Coinbase call or "
            "exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface=(
            "POST /api/v1/automation/runs/{run_id}/eligibility-cycles"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ACCOUNT_REALITY_REFRESH,
        idempotency=(
            "required exact-run cycle claim; exact replay is call-free and "
            "changed payload, actor, or intent conflicts"
        ),
        approval=(
            "required approved-read and active-order-catalog and unknown-consumes-cycle "
            "acknowledgements; also requires automation:trigger and automation:resume"
        ),
        caps=(
            "required one goal-global cycle, at most ten cycles, exactly eight approved "
            "BTC-USDC read categories including one logical account-wide active Spot-order "
            "catalog read, and zero exchange mutations"
        ),
        audit=(
            "required PostgreSQL cycle/category claims with fixed sanitized "
            "terminal diagnostics and exact or unknown call accounting"
        ),
        shared_method="refresh_spot_eligibility",
        parity_test=(
            "eight approved read-only categories, including the account-wide active-order "
            "catalog, with no individual or page retry; bounded Coinbase call accounting "
            "and zero Create, Cancel, or other exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface=(
            "POST /api/v1/automation/runs/{run_id}/authorize-single-child"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required exact-run command; no alternate identity or retry",
        approval=(
            "required Create-only, final-eligibility-refresh, active-order-catalog, and "
            "unknown-consumption acknowledgements; also requires automation:trigger, "
            "automation:resume, and account_reality:refresh"
        ),
        caps=(
            "required BTC-USDC-only one-Test-portfolio-child cap guard; 3.10 "
            "submitted and 1.00 possible-execution USDC ceilings"
        ),
        audit=(
            "required revision-bound plan hash, PostgreSQL Create allowance, canonical "
            "admission, and operation-local read/Create accounting"
        ),
        shared_method="authorize_single_child",
        parity_test=(
            "one final eight-category eligibility refresh and canonical zero-active-order "
            "admission before at most one Coinbase call for Create; no Cancel or "
            "alternate placement path"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface=(
            "POST /api/v1/automation/runs/{run_id}/safe-closeout-child"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency=(
            "required separate exact-run safe-closeout command; no alternate child, "
            "identity, or retry"
        ),
        approval=(
            "required exact-child safe-closeout and unknown-consumption acknowledgements; "
            "also requires automation:trigger"
        ),
        caps=(
            "required exact backend-linked BTC-USDC child and at most one Cancel solely "
            "for safe closeout; zero Create authority"
        ),
        audit=(
            "required revision-bound plan hash, PostgreSQL Cancel allowance, exact-child "
            "reconciliation, and operation-local read/Cancel accounting"
        ),
        shared_method="safe_closeout_single_child",
        parity_test=(
            "separate exact-child terminal reconciliation with Coinbase call accounting; "
            "terminal is zero-Cancel and authoritatively nonterminal permits at most one "
            "canonical Cancel"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface=(
            "POST /api/v1/automation/runs/{run_id}/"
            "authorize-preview-gated-single-child"
        ),
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency=(
            "required distinct exact-run Preview and conditional Create claims; "
            "zero retries or alternate identity"
        ),
        approval=(
            "required separate one-use Preview, conditional Create, final eligibility, "
            "active-order-catalog, and both unknown-consumption acknowledgements; also "
            "requires automation:trigger, automation:resume, and account_reality:refresh"
        ),
        caps=(
            "required BTC-USDC-only one-Test-portfolio-child cap guard; 3.10 "
            "submitted and 1.00 possible-execution USDC ceilings"
        ),
        audit=(
            "required revision-bound plan hash, distinct PostgreSQL Preview/Create "
            "allowances, sanitized Preview classification, canonical admission, and "
            "operation-local Preview/read/Create accounting"
        ),
        shared_method="authorize_preview_gated_single_child",
        parity_test=(
            "one final eight-category eligibility refresh before exactly one Coinbase "
            "call for Preview; only an error-free accepted Preview permits at most one identical "
            "canonical Create"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="hotpoint_operations",
        surface="GET /api/v1/hotpoint",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; durable control readback only",
        caps="reports fixed 3.10 submitted and 1.00 execution ceilings",
        audit="returns durable revision, correlation, and call accounting",
        shared_method="read",
        parity_test="local PostgreSQL singleton read; zero Coinbase call",
    ),
    AdminApiRouteInventoryItem(
        module_id="hotpoint_operations",
        surface="GET /api/v1/hotpoint/eligible-parents",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; local candidate catalog only",
        caps="BTC-USDC approved-Test-portfolio roots only",
        audit="backend-owned filtering and pagination",
        shared_method="list_eligible_parents",
        parity_test="local PostgreSQL page; zero Coinbase call or mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="hotpoint_operations",
        surface="POST /api/v1/hotpoint/control",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.AUTOMATION_CONTROL,
        idempotency="required revision-bound exact replay",
        approval="required explicit enable, disable, arm, or disarm intent",
        caps="required one parent and one sixty-second trigger window",
        audit="required durable command and singleton revision",
        shared_method="control",
        parity_test="local PostgreSQL control only; zero Coinbase call",
    ),
    AdminApiRouteInventoryItem(
        module_id="hotpoint_operations",
        surface="POST /api/v1/hotpoint/run-once",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        required_permissions=[
            AdminApiPermission.AUTOMATION_TRIGGER,
            AdminApiPermission.ORDER_CREATE,
        ],
        idempotency="required durable single-use child claim",
        approval="required explicit bounded trigger and unknown-consumption acknowledgement",
        caps="required backend domain policy, one parent, one child, and fixed cap profile",
        audit="required claim before boundary with exact or unknown Create accounting",
        shared_method="run_once",
        parity_test=(
            "local trigger evaluation; only exact same-bucket evidence can "
            "dispatch one canonical post-only child with zero retry"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="hotpoint_operations",
        surface="POST /api/v1/hotpoint/safe-closeout",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
        permission=AdminApiPermission.ORDER_CANCEL,
        idempotency="required separate durable exact-child cancel claim",
        approval="required explicit exact-child and unknown-consumption acknowledgement",
        caps="required at most one Cancel for the accepted exact child",
        audit="required claim before boundary with exact or unknown Cancel accounting",
        shared_method="safe_closeout",
        parity_test=(
            "terminal child is call-free; only the exact linked nonterminal "
            "child can reach canonical Cancel with zero retry"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/order-operations",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable; local PostgreSQL projection read only",
        caps="reports Default-profile product_type=FUTURE orders only",
        audit=(
            "returns revision, cycle, hashed exchange identity, terminal state, "
            "filters, and local pagination with zero page-load Coinbase calls"
        ),
        shared_method="list_operator_futures_orders",
        parity_test=(
            "normal operator inventory keyed by client_order_id; page loading "
            "is call-free and exposes no raw exchange identifier"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface=(
            "GET /api/v1/futures/order-operations/{client_order_id}"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable; local PostgreSQL projection read only",
        caps="reports one exact Default-profile Futures order",
        audit=(
            "returns exact client_order_id projection, hashed exchange identity, "
            "status, timestamps, and current Goal 2 authority"
        ),
        shared_method="get_operator_futures_order",
        parity_test=(
            "exact detail is local and call-free; exchange order_id remains "
            "withheld and represented only by SHA-256 evidence"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface=(
            "GET /api/v1/futures/order-operations/"
            "mutation-results/{request_correlation_id}"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval=(
            "not applicable; actor-bound immutable PostgreSQL cycle-result "
            "read only"
        ),
        caps=(
            "reports at most one exact request correlation owned by the "
            "authenticated actor"
        ),
        audit=(
            "returns terminal/pending presence, exact request correlation, "
            "sanitized result snapshot, and zero Coinbase calls"
        ),
        shared_method="get_operator_futures_order_mutation_result",
        parity_test=(
            "frozen operator controls resolve only from the original immutable "
            "request result even after later singleton revisions"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface=(
            "GET /api/v1/futures/order-operations/"
            "{client_order_id}/follow-up-intent"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable; local PostgreSQL readback only",
        caps=(
            "reports one immutable attachment slot for one configured "
            "Default-profile, one-contract Futures source order"
        ),
        audit=(
            "returns source/root client_order_id, fixed eligibility, "
            "hash-bound source evidence, and durable audit identity"
        ),
        shared_method="get_operator_futures_follow_up_intent",
        parity_test=(
            "page loading reads only PostgreSQL; zero Coinbase calls, child "
            "creation, materialization, fill trigger, or exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface=(
            "POST /api/v1/futures/order-operations/"
            "{client_order_id}/follow-up-intent"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency=(
            "required payload-bound exact replay; changed payload or actor "
            "conflicts and each source has one immutable slot"
        ),
        approval=(
            "not live authority; two explicit local-only/future-authorization "
            "acknowledgements are required"
        ),
        caps=(
            "exactly one configured Default-profile Futures source, one "
            "opposite-side one-contract intent, zero Coinbase calls, and zero "
            "child orders"
        ),
        audit=(
            "required append-only PostgreSQL actor, roles, source/root, source "
            "evidence SHA-256, derived side, correlation, and audit event"
        ),
        shared_method="attach_operator_futures_follow_up_intent",
        parity_test=(
            "the backend revalidates an OPEN authoritative source projection, "
            "derives the opposite side, binds exact source evidence, and never "
            "invokes Coinbase or a child-order service"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface=(
            "GET /api/v1/futures/order-operations/{client_order_id}/"
            "follow-up-intent/fill-triggered-activation"
        ),
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable; local PostgreSQL authority read only",
        caps=(
            "reports one Default-profile, one-contract Futures activation "
            "and its exact single-use call outcomes"
        ),
        audit=(
            "returns sanitized control, trigger, source evidence hash, child "
            "client_order_id, correlation, and audit bindings"
        ),
        shared_method=(
            "get_operator_futures_fill_triggered_follow_up"
        ),
        parity_test=(
            "page loading is call-free and exposes no Coinbase response, "
            "exchange identifier, exception message, or browser-derived term"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface=(
            "POST /api/v1/futures/order-operations/{client_order_id}/"
            "follow-up-intent/fill-triggered-activation"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        required_permissions=[
            AdminApiPermission.ORDER_CREATE,
            AdminApiPermission.ORDER_CANCEL,
        ],
        idempotency=(
            "required revision-bound PostgreSQL command; exact replay only "
            "and changed payload conflicts"
        ),
        approval=(
            "required explicit ENABLE or RESUME approval for one Preview, "
            "identical Create, reconciliation, conditional exact-child "
            "Cancel, unknown consumption, and backend-derived-term "
            "acknowledgements"
        ),
        caps=(
            "required Default profile, configured Futures product, one "
            "source, one child, one contract, and strict "
            "<100 / <150 / <300 USDC caps"
        ),
        audit=(
            "required source/root/intent/full-fill hashes, actor, roles, "
            "control revision, call claims, terminal outcomes, and child "
            "client_order_id"
        ),
        shared_method=(
            "control_operator_futures_fill_triggered_follow_up"
        ),
        parity_test=(
            "authoritative exact reconciliation must persist FILLED with "
            "size=filled_size=1 before a backend-only opposite-side candidate "
            "may enter the canonical Default-profile Preview/Create path"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/order-operations/refresh",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required revision-bound no-retry catalog cycle",
        approval=(
            "required explicit one-cycle, goal-global ten-cycle, no-retry, "
            "and fail-closed acknowledgements"
        ),
        caps=(
            "required cap of at most ten goal-global cycles; each uses one permissions read, "
            "one portfolio read, and one logical paginated Futures order read"
        ),
        audit=(
            "required PostgreSQL category and per-page claims, fixed diagnostics, "
            "actor, correlation, and sanitized evidence SHA-256"
        ),
        shared_method="refresh_operator_futures_orders",
        parity_test=(
            "Default-profile binding precedes product_type=FUTURE pagination; "
            "no page retry and zero exchange mutation"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface=(
            "POST /api/v1/futures/order-operations/"
            "{client_order_id}/reconciliation"
        ),
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required revision-bound exact-order read cycle",
        approval=(
            "required explicit exact client_order_id, one no-retry cycle, and "
            "unknown-read fail-closed acknowledgement"
        ),
        caps=(
            "required cap of one target identity and one of ten goal-global "
            "cycles; no exchange mutation"
        ),
        audit=(
            "required exact client_order_id match, fresh projection, page claims, "
            "hash-only exchange evidence, actor, and correlation"
        ),
        shared_method="reconcile_operator_futures_order",
        parity_test=(
            "one scoped logical catalog read resolves the exact durable "
            "client_order_id with no fallback or direct raw-id input"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/product-ticket",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval=(
            "not applicable; durable configured-product policy and selected "
            "ticket authority readback only"
        ),
        caps=(
            "reports one selected one-contract candidate under strict <100, "
            "<150, and <300 USDC ceilings"
        ),
        audit=(
            "returns PostgreSQL policy/ticket revisions, fixed call outcomes, "
            "hashed identifiers, correlation, and audit evidence"
        ),
        shared_method="read_operator_futures_product_ticket",
        parity_test=(
            "local PostgreSQL read only; zero Coinbase call and no raw "
            "response or private identifier"
        ),
    ),
    *(
        AdminApiRouteInventoryItem(
            module_id="futures_perpetuals",
            surface=(
                "POST /api/v1/futures/product-ticket/products/"
                f"{{product_id}}/{action.lower()}"
            ),
            action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
            permission=AdminApiPermission.CONFIG_UPDATE,
            idempotency="required policy-revision-bound exact command replay",
            approval=(
                "required exact configured product, action, reason, and "
                "operator confirmation"
            ),
            caps=(
                "local policy only; configured AVP-20DEC30-CDE and "
                "BIP-20DEC30-CDE scope cannot expand"
            ),
            audit=(
                "required immutable PostgreSQL policy revision, actor, "
                "correlation, and reason SHA-256"
            ),
            shared_method=(
                f"{action.lower()}_operator_futures_product"
            ),
            parity_test=(
                "local product-policy mutation invalidates an unconsumed "
                "candidate atomically and makes zero Coinbase call"
            ),
        )
        for action in ("APPROVE", "ENABLE", "DISABLE", "RETIRE", "SELECT")
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/product-ticket/eligibility",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required ticket-revision-bound exact cycle replay",
        approval=(
            "required explicit one-cycle, goal-global, no-retry, and "
            "fail-closed acknowledgements"
        ),
        caps=(
            "required one backend-selected enabled configured product and one "
            "contract under strict <100, <150, and <300 USDC ceilings"
        ),
        audit=(
            "required PostgreSQL cycle and six category claims with policy "
            "revision/hash binding, fixed diagnostics, actor, and correlation"
        ),
        shared_method="refresh_operator_futures_product_ticket_eligibility",
        parity_test=(
            "each approved Default-profile Futures category is read at most "
            "once; zero Preview, Create, Cancel, retry, or fallback"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/product-ticket/execute",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        required_permissions=[
            AdminApiPermission.ORDER_CREATE,
            AdminApiPermission.ORDER_CANCEL,
        ],
        idempotency=(
            "required durable single-use Goal 3 claim binding current "
            "policy, candidate, client_order_id, Preview, Create, "
            "reconciliation, and conditional Cancel"
        ),
        approval=(
            "required explicit exact Preview/Create/safe-closeout and "
            "unknown-consumption acknowledgements"
        ),
        caps=(
            "required one selected configured Futures BUY contract under strict "
            "<100 opening, <150 exposure, and <300 turnover USDC ceilings"
        ),
        audit=(
            "required each call claimed before invocation with fixed "
            "outcomes, hashed identifiers, restart recovery, and zero "
            "persisted raw response"
        ),
        shared_method="execute_operator_futures_product_ticket",
        parity_test=(
            "one Preview, one identical Create only after accepted Preview, "
            "one exact reconciliation, and at most one exact nonterminal "
            "Cancel with zero retry or fallback"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/manual-lifecycle",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable; durable Goal 10 authority readback only",
        caps="reports exact V3 strict <100, <150, and <300 USDC ceilings",
        audit=(
            "returns PostgreSQL revision, cycle, fixed call outcomes, hashed "
            "identifiers, correlation, and audit evidence"
        ),
        shared_method="read",
        parity_test=(
            "local PostgreSQL singleton read only; zero Coinbase call and no "
            "raw response or private identifier"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/manual-lifecycle/eligibility",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required revision-bound exact cycle replay",
        approval=(
            "required explicit one-cycle, goal-global, no-retry, and "
            "fail-closed acknowledgements"
        ),
        caps=(
            "required fixed Default-profile AVP-20DEC30-CDE one-contract V3 policy "
            "with strict <100, <150, and <300 USDC ceilings"
        ),
        audit=(
            "required PostgreSQL cycle and six category claims with fixed "
            "diagnostics, SHA-256 evidence, actor, and correlation"
        ),
        shared_method="refresh_futures_manual_eligibility",
        parity_test=(
            "each of the six approved Futures categories is read at most once "
            "with zero Preview, Create, Cancel, Close, Reduce, retry, or fallback"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/manual-lifecycle/execute",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        required_permissions=[
            AdminApiPermission.ORDER_CREATE,
            AdminApiPermission.ORDER_CANCEL,
        ],
        idempotency=(
            "required durable single-use Goal 10 claim binding candidate, "
            "client_order_id, Preview, Create, reconciliation, and conditional Cancel"
        ),
        approval=(
            "required explicit exact Preview/Create/safe-closeout and "
            "unknown-consumption acknowledgements"
        ),
        caps=(
            "required one AVP-20DEC30-CDE BUY contract under strict <100 opening, "
            "<150 exposure, and <300 turnover USDC ceilings"
        ),
        audit=(
            "required each call claimed before invocation with fixed outcomes, hashed "
            "identifiers, restart recovery, and zero persisted raw response"
        ),
        shared_method="execute_futures_manual_lifecycle",
        parity_test=(
            "one Preview, one identical Create only after accepted Preview, "
            "one exact reconciliation, and at most one exact nonterminal "
            "Cancel with zero retry or fallback"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="GET /api/v1/futures/position-lifecycle",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.ANALYTICS_READ,
        idempotency="not required",
        approval="not applicable; durable Goal 11 authority readback only",
        caps="reports one selected authoritative Futures position and one action",
        audit=(
            "returns PostgreSQL revision, eligibility, exact action/call outcomes, "
            "hashed identifiers, correlation, and audit evidence"
        ),
        shared_method="read_operator_futures_position_lifecycle",
        parity_test=(
            "local PostgreSQL singleton read only; zero Coinbase call and no "
            "raw response or private identifier"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/position-lifecycle/eligibility",
        action_class=AdminApiActionClass.LOCAL_STATE_MUTATION,
        permission=AdminApiPermission.ORDER_CREATE,
        idempotency="required revision-bound exact cycle replay",
        approval=(
            "required explicit selected-position, one-cycle, no-retry, and "
            "fail-closed acknowledgements"
        ),
        caps=(
            "required one selected position with either full Close or bounded "
            "one-contract Reduce review"
        ),
        audit=(
            "required PostgreSQL cycle and six category claims with fixed "
            "diagnostics, actor, correlation, and selected public position key"
        ),
        shared_method="refresh_futures_position_eligibility",
        parity_test=(
            "each approved Futures category is read at most once with zero "
            "Close, Reduce, Cancel, retry, or fallback"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="futures_perpetuals",
        surface="POST /api/v1/futures/position-lifecycle/execute",
        action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
        permission=AdminApiPermission.ORDER_CREATE,
        required_permissions=[
            AdminApiPermission.ORDER_CREATE,
            AdminApiPermission.ORDER_CANCEL,
        ],
        idempotency=(
            "required durable mutually-exclusive Goal 11 action claim binding "
            "position, mode, client_order_id, reconciliation, and conditional Cancel"
        ),
        approval=(
            "required explicit exact Close-or-Reduce and unknown-consumption "
            "acknowledgements"
        ),
        caps=(
            "required exactly one selected position and either omitted-size full "
            "Close or exact one-contract Reduce"
        ),
        audit=(
            "required each call claimed before invocation with fixed outcomes, "
            "hashed identifiers, restart recovery, and zero persisted raw response"
        ),
        shared_method="execute_futures_position_lifecycle",
        parity_test=(
            "one mutually exclusive Close or Reduce, exact order and position "
            "reconciliation, and at most one exact nonterminal Cancel with zero retry"
        ),
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="GET /api/v1/automation/runs",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; local run history only",
        caps="not applicable; reports fixed call accounting",
        audit="backend-owned filtering and pagination",
        shared_method="list_runs",
        parity_test="local PostgreSQL page only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="GET /api/v1/automation/runs/{run_id}",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; local run history only",
        caps="not applicable; reports fixed call accounting",
        audit="durable run identity readback",
        shared_method="get_run",
        parity_test="local PostgreSQL read only; zero Coinbase call or exchange mutation",
    ),
    AdminApiRouteInventoryItem(
        module_id="automation_control_plane",
        surface="GET /api/v1/automation/runs/{run_id}/events",
        action_class=AdminApiActionClass.READ_ONLY,
        permission=AdminApiPermission.AUTOMATION_READ,
        idempotency="not required",
        approval="not applicable; append-only local audit readback",
        caps="not applicable; reports fixed call accounting",
        audit="backend-owned append-only event pagination",
        shared_method="list_run_events",
        parity_test="local PostgreSQL event page only; zero Coinbase call or exchange mutation",
    ),
)
