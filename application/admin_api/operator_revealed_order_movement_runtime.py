"""Canonical stealth-manager adapter for one reviewed cancel-and-replace."""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Callable, Mapping

from application.admin_api.command_service import (
    CoinbaseOrderReadbackError,
    coinbase_order_readback_zero_fill_classification,
    exact_coinbase_order_readback,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC,
)
from core.coinbase_execution_authority import (
    COINBASE_EXECUTION_SCOPE_SPOT_CANCEL,
    COINBASE_EXECUTION_SCOPE_SPOT_PLACE,
    canonical_coinbase_execution_scope,
    require_coinbase_execution_authority,
)
from core.stealth_order_manager import OperatorStealthMoveAuthority


def _text(value: Any) -> str:
    number = Decimal(str(value))
    if not number.is_finite():
        raise RuntimeError("operator_move_decimal_invalid")
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


class OperatorRevealedOrderMovementRuntime:
    """Bind durable operator evidence to the domain-owned stealth manager."""

    def __init__(
        self,
        *,
        manager: Any,
        rest_client: Any,
        product_catalog_repository: Any,
        configured_portfolio_id: str,
        replacement_client_order_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.manager = manager
        self.rest_client = rest_client
        self.product_catalog_repository = product_catalog_repository
        self.configured_portfolio_id = str(configured_portfolio_id or "").strip()
        self.replacement_client_order_id_factory = (
            replacement_client_order_id_factory
            or (lambda: str(uuid.uuid4()))
        )

    def build_plan(
        self,
        definition: Mapping[str, Any],
        *,
        requested_limit_price: str,
    ) -> dict[str, Any]:
        product = self._bound_product(definition)
        state = self._revealed_zero_fill_state(definition)
        try:
            increment = Decimal(str(product["price_increment"]))
            requested = Decimal(str(requested_limit_price))
            side = str(definition["side"]).upper()
            rounding = ROUND_FLOOR if side == "BUY" else ROUND_CEILING
            quantized = (
                requested / increment
            ).to_integral_value(rounding=rounding) * increment
            base_size = Decimal(
                str(state["_operator_move_source_placement"]["size"])
            )
        except (InvalidOperation, KeyError, TypeError, ValueError):
            raise RuntimeError("operator_move_product_increment_invalid") from None
        if (
            increment <= 0
            or not requested.is_finite()
            or requested <= 0
            or not quantized.is_finite()
            or quantized <= 0
            or not base_size.is_finite()
            or base_size <= 0
        ):
            raise RuntimeError("operator_move_product_increment_invalid")
        self._require_size_product_bounds(
            product=product,
            size=base_size,
            price=quantized,
        )
        move_plan = self.manager.build_operator_stealth_move_plan(
            str(definition["definition_id"]),
            float(quantized),
            notes="operator-goal7-reviewed-move",
        )
        reveal_plan = move_plan.reveal_plan
        reveal_plan.post_only = True
        if (
            str(move_plan.stealth_order_id)
            != str(definition["definition_id"])
            or str(move_plan.old_exchange_order_id)
            != str(
                state["anchor_repricing_state_json"][
                    "active_exchange_order_id"
                ]
            )
            or Decimal(str(move_plan.new_configured_limit_price)) != quantized
            or Decimal(str(reveal_plan.target_movement))
            != Decimal(str(definition["target_movement"]))
            or str(reveal_plan.target_movement_type).upper()
            != str(definition["target_movement_type"]).upper()
        ):
            raise RuntimeError("operator_move_manager_plan_binding_invalid")
        profitability = getattr(
            self.manager,
            "validate_operator_stealth_move_profitability",
            None,
        )
        if not callable(profitability) or not bool(
            profitability(
                stealth_order_id=str(definition["definition_id"]),
                replacement_limit_price=float(quantized),
                post_only=True,
            )
        ):
            raise RuntimeError("operator_move_profitability_not_proven")
        notional = base_size * quantized
        if (
            not notional.is_finite()
            or notional <= 0
            or notional > OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_USDC
            or notional > OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_USDC
        ):
            raise RuntimeError("operator_move_cap_exceeded")
        anchor = state["anchor_repricing_state_json"]
        source_exchange_id = str(anchor["active_exchange_order_id"])
        replacement_client_order_id = str(
            self.replacement_client_order_id_factory()
        )
        try:
            replacement_client_order_id = str(
                uuid.UUID(replacement_client_order_id)
            )
        except (TypeError, ValueError):
            raise RuntimeError(
                "operator_move_replacement_identity_invalid"
            ) from None
        plan = {
            "stealth_order_id": str(definition["definition_id"]),
            "definition_revision": int(definition["revision"]),
            "definition_sha256": str(definition["definition_sha256"]),
            "portfolio_scope_sha256": str(
                definition["portfolio_scope_sha256"]
            ),
            "source_client_order_id": str(
                anchor["active_placement_client_order_id"]
            ),
            "source_exchange_order_id_sha256": hashlib.sha256(
                source_exchange_id.encode()
            ).hexdigest(),
            "replacement_client_order_id": replacement_client_order_id,
            "root_client_order_id": str(
                move_plan.root_parent_client_order_id
            ),
            "product_id": str(definition["product_id"]),
            "side": str(definition["side"]).upper(),
            "base_size": _text(base_size),
            "old_limit_price": _text(move_plan.old_submitted_price),
            "requested_limit_price": _text(requested),
            "replacement_limit_price": _text(quantized),
            "price_increment": _text(increment),
            "target_movement": _text(definition["target_movement"]),
            "target_movement_type": str(
                definition["target_movement_type"]
            ).upper(),
            "post_only": True,
            "submitted_notional_usdc": _text(notional),
            "possible_execution_notional_usdc": _text(notional),
            "profitability_validated": True,
            "zero_fill_validated": True,
        }
        plan["plan_sha256"] = hashlib.sha256(
            json.dumps(
                plan,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return plan

    def revalidate_plan(
        self,
        definition: Mapping[str, Any],
        plan: Mapping[str, Any],
    ) -> None:
        product = self._bound_product(definition)
        state = self._revealed_zero_fill_state(definition)
        anchor = state["anchor_repricing_state_json"]
        source_exchange_id = str(anchor["active_exchange_order_id"])
        try:
            size = Decimal(str(plan["base_size"]))
            price = Decimal(str(plan["replacement_limit_price"]))
            increment = Decimal(str(product["price_increment"]))
        except (InvalidOperation, KeyError, TypeError, ValueError):
            raise RuntimeError("operator_move_revalidation_failed") from None
        exact = bool(
            str(plan["source_client_order_id"])
            == str(anchor["active_placement_client_order_id"])
            and str(plan["source_exchange_order_id_sha256"])
            == hashlib.sha256(source_exchange_id.encode()).hexdigest()
            and str(plan["portfolio_scope_sha256"])
            == hashlib.sha256(self.configured_portfolio_id.encode()).hexdigest()
            and str(plan["product_id"]) == str(definition["product_id"])
            and str(plan["side"]).upper()
            == str(definition["side"]).upper()
            and size
            == Decimal(
                str(state["_operator_move_source_placement"]["size"])
            )
            and price % increment == 0
            and plan.get("post_only") is True
            and plan.get("zero_fill_validated") is True
            and plan.get("profitability_validated") is True
        )
        if not exact:
            raise RuntimeError("operator_move_revalidation_failed")
        self._require_size_product_bounds(
            product=product,
            size=size,
            price=price,
        )
        profitability = getattr(
            self.manager,
            "validate_operator_stealth_move_profitability",
            None,
        )
        if not callable(profitability) or not bool(
            profitability(
                stealth_order_id=str(definition["definition_id"]),
                replacement_limit_price=float(price),
                post_only=True,
            )
        ):
            raise RuntimeError("operator_move_profitability_not_proven")

    def cancel_source(
        self,
        plan: Mapping[str, Any],
        *,
        before_pre_cancel_read: Callable[[], None],
        after_pre_cancel_read: Callable[[str], None],
        before_cancel_call: Callable[[], None],
        before_post_cancel_read: Callable[[], None],
        after_post_cancel_read: Callable[[str], None],
    ) -> str:
        authority = self._authority(plan)
        pre = self._read(
            authority=authority,
            client_order_id=str(plan["source_client_order_id"]),
            exchange_order_id=authority.source_exchange_order_id,
            before_call=before_pre_cancel_read,
            after_call=after_pre_cancel_read,
            require_zero_fill=True,
        )
        if pre == "FILLED":
            return "FILLED"
        if pre == "UNCLAIMED_UNKNOWN":
            return "PRE_CANCEL_UNKNOWN"
        if pre not in {"OPEN", "PENDING", "CANCEL_QUEUED"}:
            return "UNKNOWN"
        try:
            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
            ):
                require_coinbase_execution_authority(
                    expected_scope=COINBASE_EXECUTION_SCOPE_SPOT_CANCEL
                )
                cancelled = self.manager.cancel_operator_stealth_move(
                    authority=authority,
                    before_cancel_call=before_cancel_call,
                )
        except Exception:
            return "UNKNOWN"
        if not cancelled:
            return "REJECTED"
        post = self._read(
            authority=authority,
            client_order_id=str(plan["source_client_order_id"]),
            exchange_order_id=authority.source_exchange_order_id,
            before_call=before_post_cancel_read,
            after_call=after_post_cancel_read,
            require_zero_fill=True,
        )
        if post == "CANCELLED":
            return "CANCELLED"
        # Once the Cancel invocation boundary has been crossed, a later FILLED
        # read cannot prove whether the Cancel or a concurrent fill won the
        # race. The allowance is consumed and replacement Create must remain
        # prohibited.
        return "UNKNOWN"

    def create_replacement(
        self,
        plan: Mapping[str, Any],
        *,
        before_create_call: Callable[[], None],
        before_wallet_read: Callable[[], None],
        after_wallet_read: Callable[[str], None],
        before_post_create_read: Callable[[], None],
        after_post_create_read: Callable[[str], None],
    ) -> dict[str, Any]:
        authority = self._authority(plan)
        try:
            with canonical_coinbase_execution_scope(
                COINBASE_EXECUTION_SCOPE_SPOT_PLACE
            ):
                require_coinbase_execution_authority(
                    expected_scope=COINBASE_EXECUTION_SCOPE_SPOT_PLACE
                )
                result = self.manager.place_operator_stealth_move_replacement(
                    authority=authority,
                    before_create_call=before_create_call,
                    before_wallet_read=before_wallet_read,
                    after_wallet_read=after_wallet_read,
                )
        except Exception:
            return {
                "outcome": "UNKNOWN",
                "replacement_exchange_order_id_sha256": None,
            }
        result = dict(result) if isinstance(result, Mapping) else {}
        outcome = str(result.get("outcome") or "UNKNOWN").upper()
        exchange_order_id = str(result.get("exchange_order_id") or "")
        if outcome in {"WALLET_UNKNOWN", "WALLET_REJECTED"}:
            return {
                "outcome": outcome,
                "replacement_exchange_order_id_sha256": None,
            }
        if outcome != "ACCEPTED" or not exchange_order_id:
            return {
                "outcome": (
                    "REJECTED" if outcome == "REJECTED" else "UNKNOWN"
                ),
                "replacement_exchange_order_id_sha256": None,
            }
        post = self._read(
            authority=authority,
            client_order_id=str(plan["replacement_client_order_id"]),
            exchange_order_id=exchange_order_id,
            before_call=before_post_create_read,
            after_call=after_post_create_read,
            expected_terms={
                "side": authority.side,
                "base_size": authority.base_size,
                "limit_price": authority.replacement_limit_price,
                "post_only": True,
            },
        )
        if post not in {"OPEN", "PENDING", "FILLED"}:
            return {
                "outcome": "UNKNOWN",
                "replacement_exchange_order_id_sha256": None,
            }
        try:
            self.manager.complete_operator_stealth_move_reconciliation(
                authority=authority,
                replacement_exchange_order_id=exchange_order_id,
            )
        except Exception:
            return {
                "outcome": "UNKNOWN",
                "replacement_exchange_order_id_sha256": None,
            }
        return {
            "outcome": "ACCEPTED",
            "replacement_exchange_order_id_sha256": hashlib.sha256(
                exchange_order_id.encode()
            ).hexdigest(),
        }

    def _authority(
        self, plan: Mapping[str, Any]
    ) -> OperatorStealthMoveAuthority:
        state = self.manager._get_stealth_order(
            str(plan["stealth_order_id"])
        )
        state = state if isinstance(state, Mapping) else {}
        anchor = state.get("anchor_repricing_state_json")
        anchor = anchor if isinstance(anchor, Mapping) else {}
        source_exchange_id = str(
            anchor.get("active_exchange_order_id") or ""
        )
        if (
            not source_exchange_id
            or hashlib.sha256(source_exchange_id.encode()).hexdigest()
            != str(plan["source_exchange_order_id_sha256"])
            or str(anchor.get("active_placement_client_order_id") or "")
            != str(plan["source_client_order_id"])
        ):
            raise RuntimeError("operator_move_source_identity_unavailable")
        return OperatorStealthMoveAuthority(
            stealth_order_id=str(plan["stealth_order_id"]),
            definition_revision=int(plan["definition_revision"]),
            definition_sha256=str(plan["definition_sha256"]),
            portfolio_id=self.configured_portfolio_id,
            plan_sha256=str(plan["plan_sha256"]),
            source_client_order_id=str(plan["source_client_order_id"]),
            source_exchange_order_id=source_exchange_id,
            source_exchange_order_id_sha256=str(
                plan["source_exchange_order_id_sha256"]
            ),
            replacement_client_order_id=str(
                plan["replacement_client_order_id"]
            ),
            root_client_order_id=str(plan["root_client_order_id"]),
            product_id=str(plan["product_id"]),
            side=str(plan["side"]),
            base_size=str(plan["base_size"]),
            old_limit_price=str(plan["old_limit_price"]),
            replacement_limit_price=str(
                plan["replacement_limit_price"]
            ),
            target_movement=str(plan["target_movement"]),
            target_movement_type=str(plan["target_movement_type"]),
            post_only=bool(plan["post_only"]),
        )

    def _read(
        self,
        *,
        authority: OperatorStealthMoveAuthority,
        client_order_id: str,
        exchange_order_id: str,
        before_call: Callable[[], None],
        after_call: Callable[[str], None],
        require_zero_fill: bool = False,
        expected_terms: Mapping[str, Any] | None = None,
    ) -> str:
        claimed = False

        def claim_once() -> None:
            nonlocal claimed
            before_call()
            claimed = True

        try:
            result = _exact_readback(
                rest_client=self.rest_client,
                client_order_id=client_order_id,
                exchange_order_id=exchange_order_id,
                product_id=authority.product_id,
                portfolio_id=self.configured_portfolio_id,
                before_call=claim_once,
                expected_terms=expected_terms,
            )
            status = str(result.get("status") or "").upper()
            if result.get("authoritative") is not True:
                status = "UNKNOWN"
            elif require_zero_fill:
                fill = str(
                    result.get("zero_fill_classification") or "UNKNOWN"
                )
                if fill == "NONZERO":
                    status = "FILLED"
                elif fill != "ZERO":
                    status = "UNKNOWN"
            if (
                expected_terms is not None
                and result.get("terms_proven") is not True
            ):
                status = "UNKNOWN"
        except Exception:
            status = "UNKNOWN" if claimed else "UNCLAIMED_UNKNOWN"
        if claimed:
            after_call(status)
        return status

    def _bound_product(
        self, definition: Mapping[str, Any]
    ) -> dict[str, Any]:
        expected_portfolio_hash = hashlib.sha256(
            self.configured_portfolio_id.encode()
        ).hexdigest()
        revision_id = str(
            definition.get("admitted_product_catalog_revision_id") or ""
        )
        if (
            not self.configured_portfolio_id
            or str(
                getattr(
                    self.manager,
                    "expected_retail_portfolio_id",
                    "",
                )
                or ""
            )
            != self.configured_portfolio_id
            or str(definition.get("portfolio_scope_sha256") or "")
            != expected_portfolio_hash
            or self.product_catalog_repository.get_active_revision_id()
            != revision_id
        ):
            raise RuntimeError(
                "operator_move_product_catalog_binding_invalid"
            )
        revision = self.product_catalog_repository.get_revision(revision_id)
        if (
            revision.get("active") is not True
            or str(revision.get("snapshot_sha256") or "")
            != str(
                definition.get(
                    "admitted_product_catalog_snapshot_sha256"
                )
                or ""
            )
        ):
            raise RuntimeError(
                "operator_move_product_catalog_binding_invalid"
            )
        products = [
            dict(item)
            for item in self.product_catalog_repository.list_revision_products(
                revision_id
            )
            if str(item.get("product_id") or "")
            == str(definition.get("product_id") or "")
        ]
        if len(products) != 1:
            raise RuntimeError(
                "operator_move_product_catalog_binding_invalid"
            )
        product = products[0]
        if (
            str(product.get("product_type") or "").upper() != "SPOT"
            or str(product.get("lifecycle") or "").upper() != "ENABLED"
            or str(product.get("exchange_status") or "").upper() != "ONLINE"
            or product.get("exchange_disabled") is True
            or product.get("cancel_only") is True
            or product.get("view_only") is True
        ):
            raise RuntimeError(
                "operator_move_product_catalog_binding_invalid"
            )
        return product

    def _revealed_zero_fill_state(
        self, definition: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        state = self.manager._get_stealth_order(
            str(definition["definition_id"])
        )
        state = state if isinstance(state, Mapping) else {}
        anchor = state.get("anchor_repricing_state_json")
        anchor = anchor if isinstance(anchor, Mapping) else {}
        source_placement_reader = getattr(
            self.manager,
            "get_operator_stealth_move_source_placement",
            None,
        )
        try:
            executed = Decimal(str(state.get("executed_size") or "0"))
            remaining = Decimal(str(state["remaining_size"]))
            state_target = Decimal(
                str(state.get("target_movement") or "0")
            )
            definition_target = Decimal(
                str(definition.get("target_movement") or "0")
            )
        except (InvalidOperation, KeyError, TypeError, ValueError):
            raise RuntimeError("operator_move_zero_fill_not_proven") from None
        try:
            source_placement = (
                source_placement_reader(str(definition["definition_id"]))
                if callable(source_placement_reader)
                else None
            )
            source_placement = (
                source_placement
                if isinstance(source_placement, Mapping)
                else {}
            )
            source_size = Decimal(str(source_placement["size"]))
        except (
            InvalidOperation,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ):
            raise RuntimeError("operator_move_zero_fill_not_proven") from None
        if (
            str(state.get("status") or "").upper() != "REVEALED"
            or str(state.get("product_id") or "")
            != str(definition.get("product_id") or "")
            or str(state.get("side") or "").upper()
            != str(definition.get("side") or "").upper()
            or state.get("allow_partial_fills") is not False
            or state_target != definition_target
            or str(state.get("target_movement_type") or "P").upper()
            != str(definition.get("target_movement_type") or "P").upper()
            or not executed.is_finite()
            or executed != 0
            or not remaining.is_finite()
            or remaining != 0
            or not source_size.is_finite()
            or source_size <= 0
            or not str(anchor.get("active_placement_client_order_id") or "")
            or not str(anchor.get("active_exchange_order_id") or "")
            or str(source_placement.get("client_order_id") or "")
            != str(anchor.get("active_placement_client_order_id") or "")
            or (
                source_placement.get("exchange_order_id")
                and str(source_placement.get("exchange_order_id"))
                != str(anchor.get("active_exchange_order_id") or "")
            )
            or str(source_placement.get("product_id") or "")
            != str(definition.get("product_id") or "")
            or str(source_placement.get("side") or "").upper()
            != str(definition.get("side") or "").upper()
            or str(source_placement.get("status") or "").upper()
            not in {"PENDING", "SUBMITTED", "OPEN"}
            or source_placement.get("allow_partial_fills") is not False
            or str(source_placement.get("retail_portfolio_id") or "")
            != self.configured_portfolio_id
        ):
            raise RuntimeError("operator_move_zero_fill_not_proven")
        return {
            **state,
            "_operator_move_source_placement": dict(source_placement),
        }

    @staticmethod
    def _require_size_product_bounds(
        *,
        product: Mapping[str, Any],
        size: Decimal,
        price: Decimal,
    ) -> None:
        try:
            base_increment = Decimal(str(product["base_increment"]))
            base_min = Decimal(str(product["base_min_size"]))
            base_max = Decimal(str(product["base_max_size"]))
            quote_min = Decimal(str(product["quote_min_size"]))
            quote_max = Decimal(str(product["quote_max_size"]))
            quote = size * price
        except (InvalidOperation, KeyError, TypeError, ValueError):
            raise RuntimeError("operator_move_product_increment_invalid") from None
        if (
            base_increment <= 0
            or size < base_min
            or size > base_max
            or size % base_increment != 0
            or quote < quote_min
            or quote > quote_max
        ):
            raise RuntimeError("operator_move_product_increment_invalid")


def _exact_readback(
    *,
    rest_client: Any,
    client_order_id: str,
    exchange_order_id: str,
    product_id: str,
    portfolio_id: str,
    before_call: Callable[[], None],
    expected_terms: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    class _ClaimedClient:
        @staticmethod
        def get_order(order_id: str) -> Any:
            return rest_client.get_order(
                order_id,
                before_sdk_call=before_call,
            )

    try:
        result = exact_coinbase_order_readback(
            _ClaimedClient(),
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            product_id=product_id,
            expected_retail_portfolio_id=portfolio_id,
        )
    except CoinbaseOrderReadbackError:
        raise RuntimeError("operator_move_exact_readback_failed") from None
    exact = bool(
        result.get("authoritative") is True
        and result.get("pagination_complete") is True
        and result.get("exact_identity_match") is True
        and result.get("client_order_id") == client_order_id
        and result.get("exchange_order_id") == exchange_order_id
        and result.get("retail_portfolio_id_matches_expected") is True
    )
    terms_proven = (
        _replacement_terms_proven(
            result.get("matched_order"),
            expected_terms,
        )
        if expected_terms is not None
        else None
    )
    return {
        "authoritative": exact,
        "status": str(
            result.get("authoritative_status") or ""
        ).upper(),
        "zero_fill_classification": (
            coinbase_order_readback_zero_fill_classification(result)
        ),
        "terms_proven": terms_proven,
    }


def _replacement_terms_proven(
    matched_order: Any,
    expected_terms: Mapping[str, Any],
) -> bool:
    if not isinstance(matched_order, Mapping):
        return False
    configuration = matched_order.get("order_configuration")
    configuration = (
        configuration if isinstance(configuration, Mapping) else {}
    )
    limit_gtc = configuration.get("limit_limit_gtc")
    limit_gtc = limit_gtc if isinstance(limit_gtc, Mapping) else {}
    try:
        observed_size = Decimal(
            str(limit_gtc.get("base_size", matched_order.get("base_size")))
        )
        observed_price = Decimal(
            str(
                limit_gtc.get(
                    "limit_price",
                    matched_order.get("limit_price"),
                )
            )
        )
        expected_size = Decimal(str(expected_terms["base_size"]))
        expected_price = Decimal(str(expected_terms["limit_price"]))
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return False
    observed_post_only = limit_gtc.get(
        "post_only",
        matched_order.get("post_only"),
    )
    return bool(
        observed_size.is_finite()
        and observed_price.is_finite()
        and observed_size == expected_size
        and observed_price == expected_price
        and str(matched_order.get("side") or "").upper()
        == str(expected_terms["side"]).upper()
        and observed_post_only is expected_terms["post_only"]
    )


def get_operator_revealed_order_movement_runtime(
) -> OperatorRevealedOrderMovementRuntime:
    try:
        import dashboard_server

        bridge = getattr(dashboard_server, "stealth_order_bridge", None)
        manager = getattr(bridge, "stealth_manager", None) if bridge else None
        if manager is None:
            raise RuntimeError("operator_move_manager_unavailable")
        from application.admin_api.command_runtime import (
            build_admin_api_command_service,
        )
        from database.operator_product_catalog import (
            get_default_operator_product_catalog_repository,
        )

        dependencies = build_admin_api_command_service().dependencies
        if not dependencies.rest_client_available:
            raise RuntimeError("operator_move_rest_client_unavailable")
        import os

        return OperatorRevealedOrderMovementRuntime(
            manager=manager,
            rest_client=dependencies.rest_client,
            product_catalog_repository=(
                get_default_operator_product_catalog_repository()
            ),
            configured_portfolio_id=str(
                os.environ.get("COINBASE_ADMIN_API_SPOT_PORTFOLIO_ID")
                or ""
            ).strip(),
        )
    except Exception:
        raise RuntimeError("operator_move_runtime_unavailable") from None
