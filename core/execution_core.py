"""Transport-neutral application boundary for execution commands and queries.

The facade deliberately owns no lifecycle state. It exposes narrow typed
capabilities, atomically admits operator-originated work, and delegates to the
existing runtime and stealth lifecycle owners supplied by the composition root.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generic, Mapping, Optional, Protocol, TypeVar

from core.enums import (
    EngineState,
    FollowUpRevealDirection,
    OrderSide,
    RevealPricingPolicy,
    StealthMoveReason,
    StealthOrderStatus,
    TargetMovementType,
)
from core.models import StealthMovePlan, StealthMoveResult
from core.runtime_controller import (
    INFLIGHT_APPLICATION_COMMAND,
    EngineNotAdmittingError,
)


StealthOrderSnapshot = Dict[str, Dict[str, Any]]
T = TypeVar("T")


class RuntimeLifecyclePort(Protocol):
    """Runtime lifecycle capability used by the application boundary."""

    def lifecycle_snapshot(self) -> tuple[EngineState, bool, bool]:
        """Return coherent state, admission, and stopping values."""
        ...

    def request_pause(self) -> bool:
        """Request a soft pause and report whether it was accepted."""
        ...

    def resume(self) -> bool:
        """Resume a paused runtime and report whether it changed state."""
        ...

    def track_admitted_inflight(
        self,
        category: str,
    ) -> AbstractContextManager[None]:
        """Atomically admit and register one originating operation."""
        ...


class StealthOrderQueryPort(Protocol):
    """Detached active-state query capability owned by the stealth bridge."""

    def get_stealth_orders(
        self,
        status: Optional[StealthOrderStatus] = None,
    ) -> StealthOrderSnapshot:
        """Return caller-owned logical orders, optionally filtered by status."""
        ...


class StealthOrderCommandPort(Protocol):
    """Strategy mutation capabilities owned by the stealth bridge."""

    def create_stealth_order(
        self,
        stealth_order_id: Optional[str] = None,
        *,
        product_id: str,
        side: str,
        total_size: float,
        limit_price: float,
        reveal_condition: Dict[str, Any],
        reveal_pricing_policy: Optional[str],
        sizing_strategy: Dict[str, Any],
        parent_order_id: Optional[str],
        follow_up_reveal_direction: str,
        notes: str,
        max_order_replacements: Optional[int],
        target_movement: float,
        target_movement_type: str,
        allow_partial_fills: bool,
        anchor_repricing_policy: Optional[Dict[str, Any]],
        enable_hotpoint_replication: bool,
    ) -> str:
        """Create one managed logical order."""
        ...

    def create_stealth_order_span(
        self,
        span_request: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Create or resume one deterministic span."""
        ...

    def rehide_stealth_order(self, stealth_order_id: str) -> bool:
        """Request return of one revealed order to hidden state."""
        ...

    def reprice_stealth_order_now(self, stealth_order_id: str) -> int:
        """Run one operator-requested anchor reprice."""
        ...

    def move_revealed_stealth_order(
        self,
        stealth_order_id: str,
        new_limit_price: float,
        *,
        new_target_movement: Optional[float] = None,
        new_target_movement_type: Optional[str] = None,
        reason: Optional[StealthMoveReason] = None,
        notes: Optional[str] = None,
    ) -> tuple[StealthMovePlan, StealthMoveResult]:
        """Build and execute one manual revealed-order move."""
        ...


@dataclass(frozen=True, slots=True)
class RuntimeStatusSnapshot:
    """Immutable view of the runtime lifecycle boundary."""

    state: EngineState
    is_admitting: bool
    is_stopping: bool


@dataclass(frozen=True, slots=True)
class RuntimeTransitionResult:
    """Typed result for one pause or resume request."""

    accepted: bool
    runtime: RuntimeStatusSnapshot


@dataclass(frozen=True, slots=True)
class AdmissionRejection:
    """Expected refusal when a lifecycle transition wins admission."""

    state: EngineState
    category: str


@dataclass(frozen=True, slots=True)
class OriginatingCommandResult(Generic[T]):
    """Typed admission outcome for one originating application command."""

    value: Optional[T] = None
    rejection: Optional[AdmissionRejection] = None

    @property
    def admitted(self) -> bool:
        return self.rejection is None


@dataclass(frozen=True, slots=True)
class CreateStealthOrderRequest:
    """Transport-neutral inputs for one managed logical order."""

    product_id: str
    side: OrderSide
    total_size: float
    limit_price: float
    reveal_condition: Mapping[str, Any]
    client_order_id: Optional[str] = None
    reveal_pricing_policy: Optional[RevealPricingPolicy] = None
    sizing_strategy: Optional[Mapping[str, Any]] = None
    parent_client_order_id: Optional[str] = None
    follow_up_reveal_direction: FollowUpRevealDirection = (
        FollowUpRevealDirection.OPPOSITE
    )
    notes: str = ""
    max_order_replacements: Optional[int] = None
    target_movement: float = 0.002
    target_movement_type: TargetMovementType = TargetMovementType.PERCENTAGE
    allow_partial_fills: bool = True
    anchor_repricing_policy: Optional[Mapping[str, Any]] = None
    enable_hotpoint_replication: bool = False


@dataclass(frozen=True, slots=True)
class CreateStealthOrderSpanRequest:
    """Transport-neutral deterministic span request."""

    span: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RehideStealthOrderRequest:
    """Identity of one revealed order to return to hidden state."""

    client_order_id: str


@dataclass(frozen=True, slots=True)
class RepriceStealthOrderRequest:
    """Identity of one order requiring an immediate anchor reprice."""

    client_order_id: str


@dataclass(frozen=True, slots=True)
class MoveRevealedStealthOrderRequest:
    """Operator-selected replacement price and optional strategy overrides."""

    client_order_id: str
    new_limit_price: float
    new_target_movement: Optional[float] = None
    new_target_movement_type: Optional[TargetMovementType] = None
    reason: Optional[StealthMoveReason] = None
    notes: Optional[str] = None


@dataclass(frozen=True, slots=True)
class MoveRevealedStealthOrderResult:
    """Lifecycle plan evidence plus the completed replacement identifiers."""

    plan: StealthMovePlan
    result: StealthMoveResult


@dataclass(frozen=True, slots=True)
class ImportStealthOrdersRequest:
    """Validated root orders imported under one admission registration."""

    orders: tuple[CreateStealthOrderRequest, ...]


@dataclass(frozen=True, slots=True)
class ImportedStealthOrderResult:
    """Per-order outcome within an admitted import batch."""

    requested_client_order_id: Optional[str]
    client_order_id: Optional[str]
    product_id: str
    side: OrderSide
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.client_order_id is not None


@dataclass(frozen=True, slots=True)
class ImportStealthOrdersResult:
    """Ordered outcomes for one import batch."""

    orders: tuple[ImportedStealthOrderResult, ...]

    @property
    def imported_count(self) -> int:
        return sum(result.succeeded for result in self.orders)


class ExecutionCore:
    """Small in-process application facade over existing execution owners."""

    def __init__(
        self,
        *,
        runtime_controller: RuntimeLifecyclePort,
        stealth_commands: StealthOrderCommandPort,
        stealth_queries: StealthOrderQueryPort,
    ) -> None:
        self._runtime_controller = runtime_controller
        self._stealth_commands = stealth_commands
        self._stealth_queries = stealth_queries

    def runtime_status(self) -> RuntimeStatusSnapshot:
        """Return one coherent lifecycle snapshot from the runtime owner."""

        state, is_admitting, is_stopping = (
            self._runtime_controller.lifecycle_snapshot()
        )
        return RuntimeStatusSnapshot(
            state=state,
            is_admitting=is_admitting,
            is_stopping=is_stopping,
        )

    def pause_runtime(self) -> RuntimeTransitionResult:
        """Request a soft pause without originating trading work."""

        accepted = self._runtime_controller.request_pause()
        return RuntimeTransitionResult(
            accepted=accepted,
            runtime=self.runtime_status(),
        )

    def resume_runtime(self) -> RuntimeTransitionResult:
        """Request admission to reopen without originating trading work."""

        accepted = self._runtime_controller.resume()
        return RuntimeTransitionResult(
            accepted=accepted,
            runtime=self.runtime_status(),
        )

    def snapshot_stealth_orders(
        self,
        status: Optional[StealthOrderStatus] = None,
    ) -> StealthOrderSnapshot:
        """Return detached logical orders keyed by root ``client_order_id``.

        The managed stealth root ID is also the root client order ID. Exchange
        ``order_id`` values are supplemental evidence and never become keys at
        this application boundary.
        """

        if status is not None and not isinstance(status, StealthOrderStatus):
            raise TypeError("status must be a StealthOrderStatus or None")
        return self._stealth_queries.get_stealth_orders(status=status)

    def _run_originating(
        self,
        operation: Callable[[], T],
    ) -> OriginatingCommandResult[T]:
        """Cross the single atomic application admission boundary."""

        try:
            with self._runtime_controller.track_admitted_inflight(
                INFLIGHT_APPLICATION_COMMAND
            ):
                return OriginatingCommandResult(value=operation())
        except EngineNotAdmittingError as exc:
            return OriginatingCommandResult(
                rejection=AdmissionRejection(
                    state=exc.state,
                    category=exc.category,
                )
            )

    def _create_stealth_order(
        self,
        request: CreateStealthOrderRequest,
    ) -> str:
        return self._stealth_commands.create_stealth_order(
            stealth_order_id=request.client_order_id,
            product_id=request.product_id,
            side=request.side.value,
            total_size=request.total_size,
            limit_price=request.limit_price,
            reveal_condition=deepcopy(dict(request.reveal_condition)),
            reveal_pricing_policy=(
                request.reveal_pricing_policy.value
                if request.reveal_pricing_policy is not None
                else None
            ),
            sizing_strategy=deepcopy(dict(request.sizing_strategy or {})),
            parent_order_id=request.parent_client_order_id,
            follow_up_reveal_direction=request.follow_up_reveal_direction.value,
            notes=request.notes,
            max_order_replacements=request.max_order_replacements,
            target_movement=request.target_movement,
            target_movement_type=request.target_movement_type.value,
            allow_partial_fills=request.allow_partial_fills,
            anchor_repricing_policy=(
                deepcopy(dict(request.anchor_repricing_policy))
                if request.anchor_repricing_policy is not None
                else None
            ),
            enable_hotpoint_replication=request.enable_hotpoint_replication,
        )

    def create_stealth_order(
        self,
        request: CreateStealthOrderRequest,
    ) -> OriginatingCommandResult[str]:
        """Atomically admit and create one managed logical order."""

        return self._run_originating(lambda: self._create_stealth_order(request))

    def create_stealth_order_span(
        self,
        request: CreateStealthOrderSpanRequest,
    ) -> OriginatingCommandResult[Dict[str, Any]]:
        """Atomically admit one deterministic, resumable span operation."""

        return self._run_originating(
            lambda: self._stealth_commands.create_stealth_order_span(
                deepcopy(dict(request.span))
            )
        )

    def import_stealth_orders(
        self,
        request: ImportStealthOrdersRequest,
    ) -> OriginatingCommandResult[ImportStealthOrdersResult]:
        """Import validated roots under one admission/in-flight registration."""

        def import_orders() -> ImportStealthOrdersResult:
            results = []
            for order in request.orders:
                try:
                    client_order_id = self._create_stealth_order(order)
                    results.append(
                        ImportedStealthOrderResult(
                            requested_client_order_id=order.client_order_id,
                            client_order_id=str(client_order_id),
                            product_id=order.product_id,
                            side=order.side,
                        )
                    )
                except Exception as exc:
                    results.append(
                        ImportedStealthOrderResult(
                            requested_client_order_id=order.client_order_id,
                            client_order_id=None,
                            product_id=order.product_id,
                            side=order.side,
                            error=str(exc),
                        )
                    )
            return ImportStealthOrdersResult(orders=tuple(results))

        return self._run_originating(import_orders)

    def rehide_stealth_order(
        self,
        request: RehideStealthOrderRequest,
    ) -> OriginatingCommandResult[bool]:
        """Atomically admit a manual return-to-hidden request."""

        return self._run_originating(
            lambda: self._stealth_commands.rehide_stealth_order(
                request.client_order_id
            )
        )

    def reprice_stealth_order_now(
        self,
        request: RepriceStealthOrderRequest,
    ) -> OriginatingCommandResult[int]:
        """Atomically admit one manual anchor reprice."""

        return self._run_originating(
            lambda: self._stealth_commands.reprice_stealth_order_now(
                request.client_order_id
            )
        )

    def move_revealed_stealth_order(
        self,
        request: MoveRevealedStealthOrderRequest,
    ) -> OriginatingCommandResult[MoveRevealedStealthOrderResult]:
        """Atomically admit one cancel-and-replace move."""

        def move() -> MoveRevealedStealthOrderResult:
            plan, result = self._stealth_commands.move_revealed_stealth_order(
                request.client_order_id,
                request.new_limit_price,
                new_target_movement=request.new_target_movement,
                new_target_movement_type=(
                    request.new_target_movement_type.value
                    if request.new_target_movement_type is not None
                    else None
                ),
                reason=request.reason,
                notes=request.notes,
            )
            return MoveRevealedStealthOrderResult(plan=plan, result=result)

        return self._run_originating(move)
