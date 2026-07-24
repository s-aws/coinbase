"""Canonical manager adapter for the operator stealth reveal goal."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

from application.admin_api.command_service import (
    CoinbaseOrderReadbackError,
    exact_coinbase_order_readback,
)
from application.admin_api.operator_spot_automation_preview import (
    SpotAutomationPreviewOutcome,
    classify_spot_automation_preview_response,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC,
)
from application.admin_api.spot_portfolio_binding import (
    evaluate_spot_test_portfolio_binding,
)
from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
    COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
    COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW,
    canonical_coinbase_execution_scope,
    require_coinbase_execution_authority,
)
from core.enums import StealthOrderStatus
from core.enums import ActionGuardPhase
from core.models import RevealExecutionPlan
from core.stealth_order_manager import OperatorStealthMaterializationContext


_OPERATOR_STEALTH_PLAN_FIELDS = frozenset(
    {
        "product_id",
        "side",
        "base_size",
        "limit_price",
        "configured_limit_price",
        "submitted_limit_price",
        "reveal_pricing_policy",
        "reveal_price_source",
        "fallback_used",
        "market_source",
        "market_bid",
        "market_ask",
        "target_movement",
        "target_movement_type",
        "target_movement_source",
        "post_only",
    }
)


class OperatorStealthRevealRuntime:
    """Thin adapter; all placement and local lifecycle changes stay in manager."""

    def __init__(self, manager: Any, rest_client: Any) -> None:
        self.manager = manager
        self.rest_client = rest_client

    def condition_ready(self, definition: dict[str, Any]) -> bool:
        definition_id = str(definition["definition_id"])
        state = self.manager._get_stealth_order(definition_id)
        if not isinstance(state, Mapping):
            raise RuntimeError("operator_stealth_runtime_missing")
        if str(state.get("status") or "").upper() == "TRIGGERED":
            return True
        ready, _reason = self.manager.evaluate_conditions(definition_id)
        return bool(ready)

    def portfolio_binding_ready(
        self,
        *,
        expected_portfolio_id: str,
        expected_portfolio_label: str,
        before_permissions_call: Callable[[], None],
        before_catalog_call: Callable[[], None],
    ) -> dict[str, bool]:
        rest_client = self.rest_client
        call_results = {
            "permissions_returned": False,
            "catalog_returned": False,
        }

        class _ClaimedPortfolioClient:
            @staticmethod
            def get_api_key_permissions() -> Any:
                result = rest_client.get_api_key_permissions(
                    before_sdk_call=before_permissions_call
                )
                call_results["permissions_returned"] = True
                return result

            @staticmethod
            def list_portfolios() -> Any:
                result = rest_client.list_portfolios(
                    before_sdk_call=before_catalog_call
                )
                call_results["catalog_returned"] = True
                return result

        binding = evaluate_spot_test_portfolio_binding(
            rest_client=_ClaimedPortfolioClient(),
            expected_portfolio_id=expected_portfolio_id,
            expected_portfolio_label=expected_portfolio_label,
        )
        return {
            "ready": bool(binding.ready),
            **call_results,
        }

    def materialize(
        self,
        definition: dict[str, Any],
        *,
        portfolio_id: str,
        correlation_id: str,
        audit_id: str,
    ) -> None:
        definition_id = str(definition["definition_id"])
        existing = self.manager._get_stealth_order(definition_id)
        if isinstance(existing, Mapping):
            condition = existing.get("reveal_condition_json")
            sizing = existing.get("sizing_strategy_json")
            try:
                exact_terms = bool(
                    Decimal(str(existing.get("total_size")))
                    == Decimal(str(definition["total_size"]))
                    and Decimal(str(existing.get("limit_price")))
                    == Decimal(str(definition["limit_price"]))
                    and Decimal(
                        str(existing.get("revealed_size") or "0")
                    )
                    == 0
                    and Decimal(
                        str(existing.get("executed_size") or "0")
                    )
                    == 0
                )
            except (InvalidOperation, KeyError, TypeError, ValueError):
                exact_terms = False
            if (
                exact_terms
                and str(existing.get("stealth_order_id") or "")
                == definition_id
                and str(existing.get("product_id") or "")
                == str(definition["product_id"])
                and str(existing.get("side") or "").upper()
                == str(definition["side"]).upper()
                and str(existing.get("reveal_pricing_policy") or "").upper()
                == str(definition["reveal_pricing_policy"]).upper()
                and isinstance(condition, Mapping)
                and condition.get("operator_manual_reveal_required") is True
                and isinstance(sizing, Mapping)
                and str(sizing.get("type") or "").upper() == "FIXED"
                and existing.get("max_order_replacements") == 0
                and existing.get("allow_partial_fills") is False
                and existing.get("parent_order_id") is None
                and not list(existing.get("revealed_orders") or [])
            ):
                return
            raise RuntimeError("operator_stealth_runtime_identity_conflict")
        condition = self._condition(definition)
        self.manager.create_stealth_order(
            product_id=str(definition["product_id"]),
            side=str(definition["side"]).upper(),
            total_size=float(Decimal(str(definition["total_size"]))),
            limit_price=float(Decimal(str(definition["limit_price"]))),
            reveal_condition=condition,
            sizing_strategy={"type": "fixed"},
            parent_order_id=None,
            follow_up_reveal_direction=str(
                definition["follow_up_reveal_direction"]
            ).lower(),
            reason="operator_stealth_definition",
            notes="operator-stealth-reveal-goal-6",
            stealth_order_id=definition_id,
            max_order_replacements=int(
                definition["max_order_replacements"]
            ),
            target_movement=float(
                Decimal(str(definition["target_movement"]))
            ),
            target_movement_type=str(
                definition["target_movement_type"]
            ),
            reveal_pricing_policy=str(
                definition["reveal_pricing_policy"]
            ).lower(),
            allow_partial_fills=bool(
                definition["allow_partial_fills"]
            ),
            require_persistence=True,
            operator_materialization_context=(
                OperatorStealthMaterializationContext(
                    definition_revision=int(definition["revision"]),
                    definition_sha256=str(
                        definition["definition_sha256"]
                    ),
                    portfolio_id=portfolio_id,
                    correlation_id=correlation_id,
                    audit_id=audit_id,
                )
            ),
        )

    def build_plan(self, definition: dict[str, Any]) -> RevealExecutionPlan:
        plan = self.manager.build_reveal_execution_plan(
            str(definition["definition_id"])
        )
        if not isinstance(plan, RevealExecutionPlan):
            raise RuntimeError("operator_stealth_plan_unavailable")
        return plan

    def prepreview_admission(
        self,
        definition: dict[str, Any],
        *,
        plan: dict[str, Any],
        plan_sha256: str,
        portfolio_id: str,
        before_wallet_call: Callable[[], None],
    ) -> str:
        if not self._plan_matches_definition(
            definition=definition,
            plan=plan,
            plan_sha256=plan_sha256,
        ) or not self._plan_notional_is_admissible(plan):
            raise RuntimeError(
                "operator_stealth_prepreview_plan_mismatch"
            )
        wallets = self._read_single_page_wallets(
            portfolio_id=portfolio_id,
            before_call=before_wallet_call,
        )
        try:
            allowed, _failure = (
                self.manager._evaluate_action_condition_guard(
                    phase=ActionGuardPhase.REVEAL,
                    product_id=str(plan["product_id"]),
                    side=str(plan["side"]),
                    size=float(Decimal(str(plan["base_size"]))),
                    limit_price=float(
                        Decimal(str(plan["limit_price"]))
                    ),
                    stealth_order_id=str(definition["definition_id"]),
                    parent_order_id=None,
                    wallet_fetcher=lambda: wallets,
                )
            )
        except Exception:
            allowed = False
        if not allowed:
            raise RuntimeError(
                "operator_stealth_prepreview_admission_blocked"
            )
        return self.manager.operator_prepreview_admission_sha256(
            stealth_order_id=str(definition["definition_id"]),
            definition_revision=int(definition["revision"]),
            definition_sha256=str(definition["definition_sha256"]),
            portfolio_id=portfolio_id,
            plan_sha256=plan_sha256,
            product_id=str(plan["product_id"]),
            side=str(plan["side"]),
            base_size=str(plan["base_size"]),
            limit_price=str(plan["limit_price"]),
            post_only=bool(plan["post_only"]),
        )

    def preview(
        self,
        plan: dict[str, Any],
        *,
        before_call: Callable[[], None],
    ) -> str:
        try:
            expected_quote_size = (
                Decimal(str(plan["base_size"]))
                * Decimal(str(plan["limit_price"]))
            )
        except (InvalidOperation, KeyError, TypeError, ValueError):
            return "UNKNOWN"
        if (
            not expected_quote_size.is_finite()
            or expected_quote_size <= 0
        ):
            return "UNKNOWN"
        request = {
            "product_id": plan["product_id"],
            "side": plan["side"],
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": plan["base_size"],
                    "limit_price": plan["limit_price"],
                    "post_only": plan["post_only"],
                }
            },
        }
        with canonical_coinbase_execution_scope(
            COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW
        ):
            require_coinbase_execution_authority(
                expected_scope=COINBASE_EXECUTION_SCOPE_SPOT_PREVIEW
            )
            response = self.rest_client.preview_order(
                **request,
                before_sdk_call=before_call,
                require_spot_preview_authority=True,
            )
        classification = classify_spot_automation_preview_response(
            response,
            expected_base_size=plan["base_size"],
            expected_quote_size=str(expected_quote_size),
        )
        if classification.outcome is SpotAutomationPreviewOutcome.ACCEPTED:
            return "ACCEPTED"
        if classification.outcome is SpotAutomationPreviewOutcome.REJECTED:
            return "REJECTED"
        return "UNKNOWN"

    def reveal(
        self,
        definition: dict[str, Any],
        *,
        plan: dict[str, Any],
        plan_sha256: str,
        preview_claim_id: str,
        portfolio_id: str,
        prepreview_admission_sha256: str,
        before_create_call: Callable[[], None],
    ) -> dict[str, Any]:
        definition_id = str(definition["definition_id"])
        if not self._plan_matches_definition(
            definition=definition,
            plan=plan,
            plan_sha256=plan_sha256,
        ) or not self._plan_notional_is_admissible(plan):
            return {
                "outcome": "REJECTED",
                "placement_attempted": False,
                "client_order_id": definition_id,
                "exchange_order_id": None,
                "diagnostic_code": (
                    "operator_stealth_preview_binding_mismatch"
                ),
            }
        frozen_plan = RevealExecutionPlan(
            configured_limit_price=float(
                Decimal(str(plan["configured_limit_price"]))
            ),
            submitted_limit_price=float(
                Decimal(str(plan["submitted_limit_price"]))
            ),
            reveal_pricing_policy=str(plan["reveal_pricing_policy"]),
            reveal_price_source=str(plan["reveal_price_source"]),
            fallback_used=bool(plan["fallback_used"]),
            market_source=str(plan["market_source"]),
            market_bid=(
                None
                if plan["market_bid"] is None
                else float(Decimal(str(plan["market_bid"])))
            ),
            market_ask=(
                None
                if plan["market_ask"] is None
                else float(Decimal(str(plan["market_ask"])))
            ),
            target_movement=float(
                Decimal(str(plan["target_movement"]))
            ),
            target_movement_type=str(plan["target_movement_type"]),
            target_movement_source=str(plan["target_movement_source"]),
            post_only=bool(plan["post_only"]),
        )
        authority = self.manager.prepare_operator_stealth_reveal(
            stealth_order_id=definition_id,
            definition_revision=int(definition["revision"]),
            definition_sha256=str(definition["definition_sha256"]),
            portfolio_id=portfolio_id,
            preview_claim_id=preview_claim_id,
            plan_sha256=plan_sha256,
            prepreview_admission_sha256=(
                prepreview_admission_sha256
            ),
            plan=dict(plan),
            reveal_plan=frozen_plan,
        )
        with canonical_coinbase_execution_scope(
            COINBASE_EXECUTION_SCOPE_SPOT_PLACE
        ):
            require_coinbase_execution_authority(
                expected_scope=COINBASE_EXECUTION_SCOPE_SPOT_PLACE
            )
            placed_client_order_id = self.manager.reveal_order_slice(
                definition_id,
                operator_stealth_authority=authority,
                before_create_call=before_create_call,
            )
        state = self.manager._get_stealth_order(definition_id)
        state = state if isinstance(state, Mapping) else {}
        events = list(state.get("revealed_orders") or [])
        event = (
            events[-1]
            if events and isinstance(events[-1], Mapping)
            else {}
        )
        anchor = state.get("anchor_repricing_state_json")
        anchor = anchor if isinstance(anchor, Mapping) else {}
        exchange_order_id = str(
            anchor.get("active_exchange_order_id") or ""
        )
        accepted = bool(
            placed_client_order_id == definition_id
            and event.get("placement_success") is True
            and str(event.get("placed_order_id") or "") == definition_id
            and event.get("exchange_order_id") is None
            and exchange_order_id
            and str(state.get("status") or "").upper() == "REVEALED"
        )
        if accepted:
            return {
                "outcome": "ACCEPTED",
                "placement_attempted": True,
                "client_order_id": definition_id,
                "exchange_order_id": exchange_order_id,
                "diagnostic_code": "operator_stealth_create_accepted",
            }
        attempted = bool(
            event
            and str(event.get("placement_status") or "").lower()
            in {"placed", "failed"}
        )
        return {
            "outcome": "UNKNOWN" if attempted else "REJECTED",
            "placement_attempted": attempted,
            "client_order_id": definition_id,
            "exchange_order_id": None,
            "diagnostic_code": (
                "operator_stealth_create_unknown"
                if attempted
                else "operator_stealth_create_rejected"
            ),
        }

    @staticmethod
    def _plan_matches_definition(
        *,
        definition: dict[str, Any],
        plan: dict[str, Any],
        plan_sha256: str,
    ) -> bool:
        if set(plan) != _OPERATOR_STEALTH_PLAN_FIELDS:
            return False
        canonical = json.dumps(
            plan,
            sort_keys=True,
            separators=(",", ":"),
        )
        if (
            hashlib.sha256(canonical.encode()).hexdigest()
            != plan_sha256
            or str(plan.get("product_id") or "")
            != str(definition.get("product_id") or "")
            or str(plan.get("side") or "").upper()
            != str(definition.get("side") or "").upper()
            or plan.get("post_only") is not True
        ):
            return False
        try:
            expected_size = Decimal(str(definition["total_size"]))
            plan_size = Decimal(str(plan["base_size"]))
            limit_price = Decimal(str(plan["limit_price"]))
            configured_price = Decimal(
                str(plan["configured_limit_price"])
            )
            submitted_price = Decimal(
                str(plan["submitted_limit_price"])
            )
            definition_price = Decimal(str(definition["limit_price"]))
            target_movement = Decimal(str(plan["target_movement"]))
            definition_target = Decimal(
                str(definition["target_movement"])
            )
        except (InvalidOperation, KeyError, TypeError, ValueError):
            return False
        return bool(
            expected_size.is_finite()
            and expected_size > 0
            and plan_size == expected_size
            and limit_price.is_finite()
            and limit_price > 0
            and configured_price.is_finite()
            and configured_price == definition_price
            and submitted_price == limit_price
            and str(plan["reveal_pricing_policy"])
            == str(
                definition.get("reveal_pricing_policy") or ""
            ).lower()
            and bool(str(plan["reveal_price_source"]))
            and plan["fallback_used"] is False
            and bool(str(plan["market_source"]))
            and target_movement.is_finite()
            and target_movement > 0
            and target_movement == definition_target
            and str(plan["target_movement_type"]).upper()
            == str(
                definition.get("target_movement_type") or ""
            ).upper()
            and bool(str(plan["target_movement_source"]))
        )

    @staticmethod
    def _plan_notional_is_admissible(plan: dict[str, Any]) -> bool:
        try:
            base_size = Decimal(str(plan["base_size"]))
            limit_price = Decimal(str(plan["limit_price"]))
            submitted_notional = base_size * limit_price
        except (InvalidOperation, KeyError, TypeError, ValueError):
            return False
        return bool(
            base_size.is_finite()
            and base_size > 0
            and limit_price.is_finite()
            and limit_price > 0
            and submitted_notional.is_finite()
            and submitted_notional > 0
            and submitted_notional
            <= OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC
            and submitted_notional
            <= OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC
        )

    def _read_single_page_wallets(
        self,
        *,
        portfolio_id: str,
        before_call: Callable[[], None],
    ) -> dict[str, Any]:
        from external.coinbase_client import ACCOUNT_PAGE_LIMIT

        get_accounts = getattr(self.rest_client, "get_accounts", None)
        if not callable(get_accounts):
            raise RuntimeError(
                "operator_stealth_wallet_read_unavailable"
            )
        page = get_accounts(
            limit=ACCOUNT_PAGE_LIMIT,
            before_sdk_call=before_call,
        )
        page = dict(page) if isinstance(page, Mapping) else {}
        accounts = page.get("accounts")
        has_next = page.get("has_next")
        if not isinstance(accounts, list) or not isinstance(has_next, bool):
            raise RuntimeError(
                "operator_stealth_wallet_read_malformed"
            )
        if has_next:
            raise RuntimeError(
                "operator_stealth_wallet_read_incomplete"
            )
        wallets: dict[str, Any] = {}
        for raw in accounts:
            account = dict(raw) if isinstance(raw, Mapping) else {}
            currency = str(account.get("currency") or "").upper()
            if (
                not currency
                or str(account.get("retail_portfolio_id") or "")
                != portfolio_id
                or currency in wallets
            ):
                raise RuntimeError(
                    "operator_stealth_wallet_read_ambiguous"
                )
            if account.get("deleted_at") is None:
                wallets[currency] = account
        return wallets

    def exact_readback(
        self,
        *,
        client_order_id: str,
        product_id: str,
        expected_exchange_order_id_sha256: str,
        before_call: Callable[[], None],
    ) -> dict[str, Any]:
        state = self.manager._get_stealth_order(client_order_id)
        state = state if isinstance(state, Mapping) else {}
        anchor = state.get("anchor_repricing_state_json")
        anchor = anchor if isinstance(anchor, Mapping) else {}
        active_client_order_id = str(
            anchor.get("active_placement_client_order_id") or ""
        )
        exchange_order_id = str(
            anchor.get("active_exchange_order_id") or ""
        )
        if (
            active_client_order_id != client_order_id
            or not exchange_order_id
            or hashlib.sha256(exchange_order_id.encode()).hexdigest()
            != expected_exchange_order_id_sha256
        ):
            raise RuntimeError(
                "operator_stealth_exact_identity_unavailable"
            )
        rest_client = self.rest_client

        class _ClaimedExactReadClient:
            @staticmethod
            def get_order(order_id: str) -> Any:
                return rest_client.get_order(
                    order_id,
                    before_sdk_call=before_call,
                )

        try:
            result = exact_coinbase_order_readback(
                _ClaimedExactReadClient(),
                client_order_id=client_order_id,
                exchange_order_id=exchange_order_id,
                product_id=product_id,
                expected_retail_portfolio_id=str(
                    getattr(
                        self.manager,
                        "expected_retail_portfolio_id",
                        "",
                    )
                    or ""
                ),
            )
        except CoinbaseOrderReadbackError:
            raise RuntimeError(
                "operator_stealth_exact_readback_failed"
            ) from None
        exact = bool(
            result.get("authoritative") is True
            and result.get("pagination_complete") is True
            and result.get("exact_identity_match") is True
            and result.get("client_order_id") == client_order_id
            and result.get("exchange_order_id") == exchange_order_id
            and result.get(
                "retail_portfolio_id_matches_expected"
            )
            is True
        )
        return {
            "authoritative": exact,
            "client_order_id": client_order_id,
            "exchange_order_id": (
                exchange_order_id if exact else None
            ),
            "exchange_order_id_sha256": (
                expected_exchange_order_id_sha256 if exact else None
            ),
            "portfolio_matches": bool(
                exact
                and result.get(
                    "retail_portfolio_id_matches_expected"
                )
                is True
            ),
            "status": str(
                result.get("authoritative_status") or ""
            ).upper(),
        }

    def cancel_exchange_only(
        self,
        *,
        client_order_id: str,
        verified_exchange_order_id: str,
        before_cancel_call: Callable[[], None],
    ) -> bool:
        with canonical_coinbase_execution_scope(
            COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
        ):
            require_coinbase_execution_authority(
                expected_scope=COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
            )
            return bool(
                self.manager.cancel_stealth_order(
                    client_order_id,
                    reason="operator_goal6_exact_closeout",
                    cancel_exchange=True,
                    defer_local_terminal=True,
                    value_blind_diagnostics=True,
                    verified_exchange_order_id=(
                        verified_exchange_order_id
                    ),
                    before_cancel_call=before_cancel_call,
                )
            )

    def reconcile_terminal(
        self,
        *,
        client_order_id: str,
        status: str,
    ) -> None:
        normalized = str(status or "").upper()
        if normalized not in {"CANCELLED", "FILLED"}:
            raise RuntimeError("operator_stealth_terminal_status_invalid")
        if normalized == "FILLED":
            # Goal 6 records the authoritative terminal readback, while the
            # canonical fill reconciler remains the sole owner of filled-size
            # mutation. Never publish a stale cached quantity as exchange truth.
            return
        state = self.manager._get_stealth_order(client_order_id)
        state = state if isinstance(state, Mapping) else {}
        executed_size = Decimal(str(state.get("executed_size") or "0"))
        if not executed_size.is_finite() or executed_size < 0:
            raise RuntimeError("operator_stealth_executed_size_invalid")
        self.manager.update_execution(
            client_order_id,
            float(executed_size),
            StealthOrderStatus.CANCELLED.value,
        )

    @staticmethod
    def _condition(definition: dict[str, Any]) -> dict[str, Any]:
        condition_type = str(definition["reveal_condition_type"])
        if condition_type == "TIME_DELAY":
            condition = {
                "type": "time_delay",
                "delay_seconds": int(definition["delay_seconds"]),
            }
        elif condition_type == "PRICE":
            try:
                threshold = float(
                    Decimal(str(definition["reveal_price_threshold"]))
                )
            except (InvalidOperation, TypeError, ValueError):
                raise RuntimeError(
                    "operator_stealth_condition_invalid"
                ) from None
            condition = {
                "type": "price",
                "price_threshold": threshold,
                "direction": str(definition["reveal_direction"]).lower(),
                "hold_duration_seconds": int(
                    definition["hold_duration_seconds"]
                ),
            }
        else:
            raise RuntimeError("operator_stealth_condition_invalid")
        condition["operator_manual_reveal_required"] = True
        return condition


def get_operator_stealth_reveal_runtime() -> OperatorStealthRevealRuntime:
    try:
        import dashboard_server

        bridge = getattr(dashboard_server, "stealth_order_bridge", None)
        manager = getattr(bridge, "stealth_manager", None) if bridge else None
        if manager is None:
            raise RuntimeError("operator_stealth_manager_unavailable")
        from application.admin_api.command_runtime import (
            build_admin_api_command_service,
        )

        command_service = build_admin_api_command_service()
        dependencies = command_service.dependencies
        if not dependencies.rest_client_available:
            raise RuntimeError("operator_stealth_rest_client_unavailable")
        return OperatorStealthRevealRuntime(
            manager,
            dependencies.rest_client,
        )
    except Exception:
        raise RuntimeError("operator_stealth_runtime_unavailable") from None
