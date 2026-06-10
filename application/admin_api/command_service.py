"""Shared Admin API command service skeleton.

FastAPI routes and legacy dashboard compatibility adapters must call this
service layer once live behavior is extracted. The skeleton deliberately does
not call Coinbase or duplicate dashboard order logic.
"""

from __future__ import annotations

from core.enums import AdminApiActionClass, AdminApiCommandStatus, AdminApiPermission

from .models import AdminApiCommandResponse, CancelOrderCommand, ManualOrderCommand


class AdminApiCommandService:
    """Shared command-service boundary for enterprise API work."""

    def place_manual_order(self, command: ManualOrderCommand) -> AdminApiCommandResponse:
        """Future manual placement entrypoint.

        Live placement remains unimplemented until dashboard behavior is
        extracted into this service and parity tests prove the shared path.
        """

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="place_manual_order",
            message="Manual order placement awaits shared-service extraction; no Coinbase call was made.",
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
        )

    def cancel_order_by_client_order_id(self, command: CancelOrderCommand) -> AdminApiCommandResponse:
        """Future cancel entrypoint keyed by ``client_order_id``.

        The eventual implementation must call the project Coinbase wrapper
        ``cancel_order(client_order_id)``. This skeleton does not call REST.
        """

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_CANCEL,
            required_permission=AdminApiPermission.ORDER_CANCEL,
            service_method="cancel_order_by_client_order_id",
            message="Cancel awaits shared-service extraction; no Coinbase call was made.",
            client_order_id=command.client_order_id,
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
        )

    def place_hotpoint_test_order(self, command: ManualOrderCommand) -> AdminApiCommandResponse:
        """Future hotpoint test placement entrypoint, if exposed over HTTP."""

        return AdminApiCommandResponse(
            status=AdminApiCommandStatus.NOT_IMPLEMENTED,
            action_class=AdminApiActionClass.LIVE_EXCHANGE_PLACE,
            required_permission=AdminApiPermission.ORDER_CREATE,
            service_method="place_hotpoint_test_order",
            message="Hotpoint test placement awaits shared-service extraction; no Coinbase call was made.",
            correlation_id=command.envelope.correlation_id,
            idempotency_key=command.envelope.idempotency_key,
        )

