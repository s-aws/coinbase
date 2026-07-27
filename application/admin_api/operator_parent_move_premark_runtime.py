"""Call-free installed adapter for the Goal 14 parent-move premark."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
import hashlib
import json
import os
from typing import Any, Callable, Mapping
import uuid

from application.admin_api.operator_parent_move_premark_models import (
    OperatorParentMovePlan,
    OperatorParentMovePremarkReadback,
    OperatorParentMoveSourceSelection,
)
from application.admin_api.operator_parent_move_premark_policy import (
    ParentMovePremarkPolicyError,
    ParentMovePremarkPolicyTerms,
    POLICY_REVISION,
    build_parent_move_premark_plan,
)
from application.admin_api.operator_parent_move_premark_service import (
    OperatorParentMovePremarkService,
    OperatorParentMoveServiceError,
    ParentMoveCommandContext,
    ParentMovePremarkRequest,
)
from application.admin_api.operator_mvp_policy import (
    OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT,
    OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT,
)
from application.admin_api.spot_portfolio_binding import (
    DEFAULT_SPOT_PORTFOLIO_LABEL,
    SPOT_PORTFOLIO_ID_ENV,
    SPOT_PORTFOLIO_LABEL_ENV,
)
from core.coinbase_execution_authority import (
    coinbase_execution_authority_enabled,
)
from database.operator_parent_move_premark import (
    OperatorParentMovePremarkRepository,
)


_APPROVED_PRODUCT_ID = "BTC-USDC"
_SHA256 = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class LocalParentMovePlanningTerms:
    policy_terms: ParentMovePremarkPolicyTerms
    complete: bool
    diagnostic_code: str


class Goal12ParentMoveOrderRepository:
    """Add the approved portfolio hash to the call-free Goal 12 projection."""

    def __init__(
        self,
        source_repository: Any,
        *,
        configured_portfolio_id: str,
    ) -> None:
        self.source_repository = source_repository
        self.configured_portfolio_id = configured_portfolio_id

    def get_order(self, client_order_id: str) -> Mapping[str, Any] | None:
        order = self.source_repository.get_order(client_order_id)
        if not isinstance(order, Mapping):
            return None
        goal = self.source_repository.read_goal()
        portfolio_hash = _field(goal, "portfolio_id_sha256")
        return {
            "client_order_id": order.get("client_order_id"),
            "parent_order_id": None,
            "ownership_provenance": order.get(
                "ownership_provenance"
            ),
            "portfolio_scope_sha256": portfolio_hash,
            "product_id": order.get("product_id"),
            "side": order.get("side"),
            "status": order.get("status"),
            "order_type": order.get("order_type"),
            "time_in_force": order.get("time_in_force"),
            "size": order.get("size"),
            "limit_price": order.get("limit_price"),
            "filled_size": order.get("filled_size"),
            "authoritatively_nonterminal": bool(
                order.get("authoritatively_nonterminal")
            ),
            "cancel_eligible": bool(order.get("cancel_eligible")),
            "post_only_compatible": bool(
                order.get("authoritatively_nonterminal")
                and order.get("cancel_eligible")
                and str(order.get("order_type") or "").upper() == "LIMIT"
                and str(order.get("time_in_force") or "").upper()
                == "GOOD_UNTIL_CANCELLED"
            ),
        }


class FailClosedParentMoveRuntime:
    """No wired exchange boundary exists under the Goal 14 addendum."""

    @staticmethod
    def _reject() -> None:
        raise OperatorParentMoveServiceError(
            "operator_parent_move_live_authority_terms_incomplete"
        )

    def cancel_source(self, _plan, *, before_exchange_call):
        _ = before_exchange_call
        self._reject()

    def create_successor(self, _plan, *, before_exchange_call):
        _ = before_exchange_call
        self._reject()

    def cancel_successor(self, _plan, *, before_exchange_call):
        _ = before_exchange_call
        self._reject()


class OperatorParentMovePremarkApiService:
    """Project the local policy, source, and ledger as one typed contract."""

    def __init__(
        self,
        *,
        service: OperatorParentMovePremarkService,
        order_repository: Goal12ParentMoveOrderRepository,
        planning_terms: LocalParentMovePlanningTerms,
        legacy_pending_move_checker: Callable[[str], bool],
        execution_authority_checker: Callable[[], bool],
    ) -> None:
        self.service = service
        self.order_repository = order_repository
        self.planning_terms = planning_terms
        self.legacy_pending_move_checker = legacy_pending_move_checker
        self.execution_authority_checker = execution_authority_checker

    def readback(
        self,
        source_client_order_id: str,
        *,
        allow_premark: bool,
    ) -> OperatorParentMovePremarkReadback:
        projection = self.service.get_execution(source_client_order_id)
        return self._project(
            source_client_order_id=source_client_order_id,
            projection=projection,
            allow_premark=allow_premark,
        )

    def premark(
        self,
        *,
        context: ParentMoveCommandContext,
        request: ParentMovePremarkRequest,
        allow_premark: bool = True,
    ) -> OperatorParentMovePremarkReadback:
        if not allow_premark:
            raise OperatorParentMoveServiceError(
                "operator_parent_move_permission_denied"
            )
        projection = self.service.premark(
            context=context,
            request=request,
        )
        return self._project(
            source_client_order_id=request.source_client_order_id,
            projection=projection,
            allow_premark=allow_premark,
        )

    def _project(
        self,
        *,
        source_client_order_id: str,
        projection: Mapping[str, Any] | None,
        allow_premark: bool,
    ) -> OperatorParentMovePremarkReadback:
        source = self._source_selection(source_client_order_id)
        plan: OperatorParentMovePlan | None = None
        plan_sha256: str | None = None
        reserved_successor_id: str | None = None
        if projection is not None:
            if (
                str(projection.get("source_client_order_id"))
                != source_client_order_id
                or not isinstance(projection.get("plan"), Mapping)
            ):
                raise OperatorParentMoveServiceError(
                    "operator_parent_move_readback_binding_invalid"
                )
            plan = OperatorParentMovePlan.model_validate(
                projection["plan"]
            )
            plan_sha256 = str(projection.get("plan_sha256") or "")
            if (
                _canonical_sha(plan.model_dump(mode="json"))
                != plan_sha256
                or plan.source_client_order_id != source_client_order_id
            ):
                raise OperatorParentMoveServiceError(
                    "operator_parent_move_readback_binding_invalid"
                )
            reserved_successor_id = (
                plan.reserved_successor_client_order_id
            )
        allowed_actions: list[str] = []
        if (
            projection is None
            and allow_premark
            and self.planning_terms.complete
            and source.eligible
        ):
            allowed_actions.append("PREMARK")
        diagnostic = (
            str(projection.get("diagnostic_code"))
            if projection is not None
            else source.diagnostic_code
        )
        try:
            execution_enabled = (
                self.execution_authority_checker() is True
            )
        except Exception:
            execution_enabled = False
        values = dict(projection or {})
        latest_correlation = _optional_text(
            values.get("latest_cycle_correlation_id")
        )
        return OperatorParentMovePremarkReadback(
            state=(
                str(values.get("state"))
                if projection is not None
                else "UNCONSUMED"
            ),
            diagnostic_code=diagnostic,
            source_client_order_id=source_client_order_id,
            source_client_order_id_sha256=_sha(source_client_order_id),
            reserved_successor_client_order_id=reserved_successor_id,
            reserved_successor_client_order_id_sha256=(
                _sha(reserved_successor_id)
                if reserved_successor_id is not None
                else None
            ),
            source_selection=source,
            plan=plan,
            plan_sha256=plan_sha256,
            allowed_actions=allowed_actions,
            planning_terms_complete=self.planning_terms.complete,
            execution_authority_enabled=execution_enabled,
            source_follow_up_suppressed=bool(
                values.get("source_follow_up_suppressed", False)
            ),
            source_cancel_allowance_consumed=bool(
                values.get(
                    "source_cancel_allowance_consumed",
                    False,
                )
            ),
            source_cancel_call_count=int(
                values.get("source_cancel_call_count") or 0
            ),
            replacement_create_allowance_consumed=bool(
                values.get(
                    "replacement_create_allowance_consumed",
                    False,
                )
            ),
            replacement_create_call_count=int(
                values.get("replacement_create_call_count") or 0
            ),
            successor_closeout_cancel_allowance_consumed=bool(
                values.get(
                    "successor_closeout_cancel_allowance_consumed",
                    False,
                )
            ),
            successor_closeout_cancel_call_count=int(
                values.get(
                    "successor_closeout_cancel_call_count"
                )
                or 0
            ),
            cycle_count=int(values.get("cycle_count") or 0),
            latest_cycle_number=values.get("latest_cycle_number"),
            latest_cycle_phase=values.get("latest_cycle_phase"),
            latest_cycle_status=values.get("latest_cycle_status"),
            latest_cycle_correlation_id=latest_correlation,
            latest_cycle_actor_id_sha256=values.get(
                "latest_cycle_actor_id_sha256"
            ),
            latest_cycle_idempotency_key_sha256=values.get(
                "latest_cycle_idempotency_key_sha256"
            ),
            latest_cycle_payload_sha256=values.get(
                "latest_cycle_payload_sha256"
            ),
            latest_cycle_evidence_sha256=values.get(
                "latest_cycle_evidence_sha256"
            ),
            active_cycle_number=values.get("active_cycle_number"),
            active_cycle_phase=values.get("active_cycle_phase"),
            active_cycle_status=values.get("active_cycle_status"),
            correlation_id=latest_correlation,
            command_replayed=bool(
                values.get("command_replayed", False)
            ),
            created_at=_optional_text(values.get("created_at")),
            updated_at=_optional_text(values.get("updated_at")),
        )

    def _source_selection(
        self,
        source_client_order_id: str,
    ) -> OperatorParentMoveSourceSelection:
        source = self.order_repository.get_order(source_client_order_id)
        if source is None:
            return _empty_source_selection(
                source_client_order_id,
                "operator_parent_move_source_not_found",
            )
        legacy_pending: bool | None
        try:
            legacy_pending = (
                self.legacy_pending_move_checker(
                    source_client_order_id
                )
                is True
            )
        except Exception:
            legacy_pending = None
        diagnostic = self.planning_terms.diagnostic_code
        source_evidence_sha256 = None
        eligible = False
        if not self.planning_terms.complete:
            pass
        elif legacy_pending is None:
            diagnostic = (
                "operator_parent_move_legacy_pending_check_unknown"
            )
        elif not bool(source.get("cancel_eligible")):
            diagnostic = (
                "operator_parent_move_source_not_cancel_eligible"
            )
        else:
            try:
                candidate = build_parent_move_premark_plan(
                    source=source,
                    requested_limit_price=str(
                        source.get("limit_price") or ""
                    ),
                    reserved_successor_client_order_id=(
                        _selection_successor_id(
                            source_client_order_id
                        )
                    ),
                    policy_terms=self.planning_terms.policy_terms,
                    legacy_pending_move=legacy_pending,
                )
                source_evidence_sha256 = (
                    candidate.source_evidence_sha256
                )
                diagnostic = "operator_parent_move_source_eligible"
                eligible = True
            except ParentMovePremarkPolicyError as exc:
                diagnostic = exc.code
        return OperatorParentMoveSourceSelection(
            client_order_id=source_client_order_id,
            found=True,
            eligible=eligible,
            diagnostic_code=diagnostic,
            product_id=_optional_text(source.get("product_id")),
            side=_optional_text(source.get("side")),
            status=_optional_text(source.get("status")),
            order_type=_optional_text(source.get("order_type")),
            time_in_force=_optional_text(source.get("time_in_force")),
            size=_optional_text(source.get("size")),
            limit_price=_optional_text(source.get("limit_price")),
            filled_size=_optional_text(source.get("filled_size")),
            ownership_provenance=_optional_text(
                source.get("ownership_provenance")
            ),
            authoritatively_nonterminal=bool(
                source.get("authoritatively_nonterminal")
            ),
            cancel_eligible=bool(source.get("cancel_eligible")),
            zero_fill_proven=_is_zero(source.get("filled_size")),
            system_owned=(
                str(source.get("ownership_provenance") or "")
                == "ADMIN_MANUAL_ROOT"
            ),
            direct_root=source.get("parent_order_id") in (None, ""),
            post_only_compatible=bool(
                source.get("post_only_compatible")
            ),
            legacy_pending_move=legacy_pending,
            portfolio_scope_sha256=(
                _valid_sha_or_none(
                    source.get("portfolio_scope_sha256")
                )
            ),
            source_evidence_sha256=source_evidence_sha256,
        )


def resolve_local_parent_move_planning_terms(
    *,
    product_catalog_repository: Any,
    configured_portfolio_id: str,
    configured_portfolio_label: str = DEFAULT_SPOT_PORTFOLIO_LABEL,
) -> LocalParentMovePlanningTerms:
    """Resolve only installed PostgreSQL/config evidence; never Coinbase."""

    if configured_portfolio_label != DEFAULT_SPOT_PORTFOLIO_LABEL:
        return _incomplete_terms(
            "operator_parent_move_test_portfolio_alias_invalid"
        )
    portfolio_id = _canonical_uuid_or_none(configured_portfolio_id)
    if portfolio_id is None:
        return _incomplete_terms(
            "operator_parent_move_test_portfolio_missing"
        )
    try:
        revision_id = (
            product_catalog_repository.get_active_revision_id()
        )
        products = (
            product_catalog_repository.list_revision_products(
                revision_id
            )
            if revision_id is not None
            else []
        )
    except Exception:
        return _incomplete_terms(
            "operator_parent_move_product_catalog_unavailable"
        )
    matches = [
        product
        for product in products
        if str(product.get("product_id") or "") == _APPROVED_PRODUCT_ID
    ]
    if len(matches) != 1:
        return _incomplete_terms(
            "operator_parent_move_btc_usdc_not_locally_approved"
        )
    product = matches[0]
    if (
        str(product.get("product_type") or "") != "SPOT"
        or str(product.get("lifecycle") or "") != "ENABLED"
        or str(product.get("exchange_status") or "") != "ONLINE"
        or bool(product.get("exchange_disabled"))
        or bool(product.get("cancel_only"))
        or bool(product.get("view_only"))
    ):
        return _incomplete_terms(
            "operator_parent_move_btc_usdc_not_locally_approved"
        )
    terms = ParentMovePremarkPolicyTerms(
        terms_complete=True,
        policy_revision=POLICY_REVISION,
        portfolio_scope_sha256=_sha(portfolio_id),
        approved_product_id=_APPROVED_PRODUCT_ID,
        price_increment=_optional_text(
            product.get("price_increment")
        ),
        base_increment=_optional_text(product.get("base_increment")),
        base_min_size=_optional_text(product.get("base_min_size")),
        quote_min_size=_optional_text(product.get("quote_min_size")),
        max_submitted_notional_usdc=(
            OPERATOR_MVP_MAX_SUBMITTED_NOTIONAL_TEXT
        ),
        max_possible_execution_notional_usdc=(
            OPERATOR_MVP_MAX_EXECUTED_NOTIONAL_TEXT
        ),
    )
    try:
        # The pure builder performs the same strict terms validation later.
        for value in (
            terms.price_increment,
            terms.base_increment,
            terms.base_min_size,
            terms.quote_min_size,
        ):
            if value is None or Decimal(value) <= 0:
                raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        return _incomplete_terms(
            "operator_parent_move_product_terms_invalid"
        )
    return LocalParentMovePlanningTerms(
        policy_terms=terms,
        complete=True,
        diagnostic_code="operator_parent_move_planning_terms_ready",
    )


def build_operator_parent_move_premark_api_service(
    *,
    goal_repository: Any,
    source_repository: Any,
    product_catalog_repository: Any,
    configured_portfolio_id: str,
    legacy_pending_move_checker: Callable[[str], bool],
    execution_authority_checker: Callable[[], bool],
    configured_portfolio_label: str = DEFAULT_SPOT_PORTFOLIO_LABEL,
) -> OperatorParentMovePremarkApiService:
    planning_terms = resolve_local_parent_move_planning_terms(
        product_catalog_repository=product_catalog_repository,
        configured_portfolio_id=configured_portfolio_id,
        configured_portfolio_label=configured_portfolio_label,
    )
    order_repository = Goal12ParentMoveOrderRepository(
        source_repository,
        configured_portfolio_id=configured_portfolio_id,
    )
    service = OperatorParentMovePremarkService(
        repository=goal_repository,
        order_repository=order_repository,
        runtime=FailClosedParentMoveRuntime(),
        policy_terms=planning_terms.policy_terms,
        legacy_pending_move_checker=legacy_pending_move_checker,
        live_authority_terms_complete=lambda: False,
        execution_authority_checker=execution_authority_checker,
    )
    return OperatorParentMovePremarkApiService(
        service=service,
        order_repository=order_repository,
        planning_terms=planning_terms,
        legacy_pending_move_checker=legacy_pending_move_checker,
        execution_authority_checker=execution_authority_checker,
    )


@lru_cache(maxsize=1)
def get_default_operator_parent_move_premark_goal_repository(
) -> OperatorParentMovePremarkRepository:
    from database.order import DB_CLIENT

    repository = OperatorParentMovePremarkRepository(DB_CLIENT)
    repository.ensure_schema()
    return repository


def get_default_operator_parent_move_premark_api_service(
) -> OperatorParentMovePremarkApiService:
    """Re-resolve mutable local Product Catalog policy on every request."""

    from database.operator_product_catalog import (
        get_default_operator_product_catalog_repository,
    )
    from database.operator_spot_order_truth import (
        get_default_operator_spot_order_truth_repository,
    )
    from database.order import has_pending_move

    return build_operator_parent_move_premark_api_service(
        goal_repository=(
            get_default_operator_parent_move_premark_goal_repository()
        ),
        source_repository=(
            get_default_operator_spot_order_truth_repository()
        ),
        product_catalog_repository=(
            get_default_operator_product_catalog_repository()
        ),
        configured_portfolio_id=os.environ.get(
            SPOT_PORTFOLIO_ID_ENV,
            "",
        ).strip(),
        configured_portfolio_label=os.environ.get(
            SPOT_PORTFOLIO_LABEL_ENV,
            DEFAULT_SPOT_PORTFOLIO_LABEL,
        ).strip(),
        legacy_pending_move_checker=has_pending_move,
        execution_authority_checker=(
            coinbase_execution_authority_enabled
        ),
    )


def reset_operator_parent_move_premark_runtime_for_tests() -> None:
    get_default_operator_parent_move_premark_goal_repository.cache_clear()


def _empty_source_selection(
    source_client_order_id: str,
    diagnostic_code: str,
) -> OperatorParentMoveSourceSelection:
    return OperatorParentMoveSourceSelection(
        client_order_id=source_client_order_id,
        found=False,
        eligible=False,
        diagnostic_code=diagnostic_code,
    )


def _incomplete_terms(code: str) -> LocalParentMovePlanningTerms:
    return LocalParentMovePlanningTerms(
        policy_terms=ParentMovePremarkPolicyTerms(),
        complete=False,
        diagnostic_code=code,
    )


def _field(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _valid_sha_or_none(value: Any) -> str | None:
    text = _optional_text(value)
    if (
        text is None
        or len(text) != 64
        or any(character not in _SHA256 for character in text)
    ):
        return None
    return text


def _canonical_uuid_or_none(value: Any) -> str | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed = uuid.UUID(text)
    except (ValueError, TypeError, AttributeError):
        return None
    return str(parsed) if str(parsed) == text else None


def _selection_successor_id(source_client_order_id: str) -> str:
    raw = bytearray(
        hashlib.sha256(
            f"parent-move-selection:{source_client_order_id}".encode()
        ).digest()[:16]
    )
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    candidate = str(uuid.UUID(bytes=bytes(raw)))
    if candidate == source_client_order_id:
        return "ffffffff-ffff-4fff-bfff-ffffffffffff"
    return candidate


def _is_zero(value: Any) -> bool:
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return _sha(
        json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


__all__ = [
    "FailClosedParentMoveRuntime",
    "Goal12ParentMoveOrderRepository",
    "LocalParentMovePlanningTerms",
    "OperatorParentMovePremarkApiService",
    "build_operator_parent_move_premark_api_service",
    "get_default_operator_parent_move_premark_api_service",
    "get_default_operator_parent_move_premark_goal_repository",
    "reset_operator_parent_move_premark_runtime_for_tests",
    "resolve_local_parent_move_planning_terms",
]
