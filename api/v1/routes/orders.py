"""Order command route adapters for the Admin API skeleton."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Path, status
from fastapi.responses import JSONResponse

from application.admin_api.command_service import AdminApiCommandService
from application.admin_api.models import (
    AdminApiActor,
    AdminApiCommandEnvelope,
    AdminApiCommandResponse,
    CancelOrderCommand,
    CancelOrderRequest,
    ManualOrderCommand,
    ManualOrderRequest,
)
from core.enums import AdminApiCommandStatus


router = APIRouter()


def get_command_service() -> AdminApiCommandService:
    """Return the shared command service boundary."""

    return AdminApiCommandService()


def _build_envelope(
    *,
    idempotency_key: str,
    correlation_id: str,
    operator_intent: str,
    actor_id: str,
) -> AdminApiCommandEnvelope:
    return AdminApiCommandEnvelope(
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        operator_intent=operator_intent,
        actor=AdminApiActor(actor_id=actor_id, roles=[]),
    )


def _command_response(response: AdminApiCommandResponse) -> JSONResponse:
    http_status = (
        status.HTTP_501_NOT_IMPLEMENTED
        if response.status == AdminApiCommandStatus.NOT_IMPLEMENTED
        else status.HTTP_200_OK
    )
    return JSONResponse(
        status_code=http_status,
        content=response.model_dump(mode="json"),
        headers={"X-Correlation-Id": response.correlation_id or ""},
    )


@router.post(
    "/orders",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Create a manual order through the shared command service",
)
def create_manual_order(
    request: ManualOrderRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor_id: Annotated[str, Header(alias="X-Admin-Actor", min_length=1)],
) -> JSONResponse:
    """Contract endpoint for future manual placement.

    The current implementation returns ``not_implemented`` and does not call
    Coinbase. Live behavior must be extracted into
    ``AdminApiCommandService.place_manual_order`` first.
    """

    service = get_command_service()
    command = ManualOrderCommand(
        envelope=_build_envelope(
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
            actor_id=actor_id,
        ),
        request=request,
    )
    return _command_response(service.place_manual_order(command))


@router.post(
    "/orders/{client_order_id}/cancel",
    response_model=AdminApiCommandResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="Cancel an order by client_order_id through the shared command service",
)
def cancel_order_by_client_order_id(
    request: CancelOrderRequest,
    client_order_id: Annotated[str, Path(min_length=1)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    correlation_id: Annotated[str, Header(alias="X-Correlation-Id", min_length=1)],
    operator_intent: Annotated[str, Header(alias="X-Operator-Intent", min_length=1)],
    actor_id: Annotated[str, Header(alias="X-Admin-Actor", min_length=1)],
) -> JSONResponse:
    """Contract endpoint for future cancel-by-client-order-id."""

    service = get_command_service()
    command = CancelOrderCommand(
        envelope=_build_envelope(
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            operator_intent=operator_intent,
            actor_id=actor_id,
        ),
        client_order_id=client_order_id,
        request=request,
    )
    return _command_response(service.cancel_order_by_client_order_id(command))
