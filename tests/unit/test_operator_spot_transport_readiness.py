from __future__ import annotations

import socket
import ssl
from typing import Any

from application.admin_api.operator_spot_transport_readiness import (
    COINBASE_ADVANCED_API_HOSTNAME,
    SpotTransportReadinessFailureClass,
    SpotTransportReadinessStageStatus,
    probe_coinbase_transport_readiness,
)


class _Socket:
    def __init__(self, *, connect_error: Exception | None = None) -> None:
        self.connect_error = connect_error
        self.connected_to: Any = None
        self.timeout: float | None = None
        self.closed = False

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def connect(self, address: Any) -> None:
        self.connected_to = address
        if self.connect_error is not None:
            raise self.connect_error

    def close(self) -> None:
        self.closed = True


class _TlsSocket:
    def __init__(self, *, handshake_error: Exception | None = None) -> None:
        self.handshake_error = handshake_error
        self.handshake_count = 0
        self.closed = False

    def do_handshake(self) -> None:
        self.handshake_count += 1
        if self.handshake_error is not None:
            raise self.handshake_error

    def close(self) -> None:
        self.closed = True


class _Context:
    def __init__(self, tls_socket: _TlsSocket) -> None:
        self.tls_socket = tls_socket
        self.wrap_count = 0

    def wrap_socket(
        self,
        raw_socket: _Socket,
        *,
        server_hostname: str,
        do_handshake_on_connect: bool,
    ) -> _TlsSocket:
        assert server_hostname == COINBASE_ADVANCED_API_HOSTNAME
        assert do_handshake_on_connect is False
        self.wrap_count += 1
        return self.tls_socket


def _resolver(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
    assert args == (COINBASE_ADVANCED_API_HOSTNAME, 443)
    assert kwargs == {"type": socket.SOCK_STREAM}
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("192.0.2.10", 443),
        )
    ]


def test_readiness_probe_performs_one_dns_tcp_and_tls_step_without_http() -> None:
    raw_socket = _Socket()
    tls_socket = _TlsSocket()
    context = _Context(tls_socket)
    socket_factory_calls: list[tuple[int, int, int]] = []

    def socket_factory(family: int, socktype: int, proto: int) -> _Socket:
        socket_factory_calls.append((family, socktype, proto))
        return raw_socket

    result = probe_coinbase_transport_readiness(
        resolver=_resolver,
        socket_factory=socket_factory,
        ssl_context_factory=lambda: context,
        timeout_seconds=5,
    )

    assert result.ready is True
    assert result.failure_class is SpotTransportReadinessFailureClass.NONE
    assert result.dns_status is SpotTransportReadinessStageStatus.SUCCEEDED
    assert result.tcp_status is SpotTransportReadinessStageStatus.SUCCEEDED
    assert result.tls_status is SpotTransportReadinessStageStatus.SUCCEEDED
    assert (result.dns_probe_count, result.tcp_probe_count, result.tls_probe_count) == (
        1,
        1,
        1,
    )
    assert socket_factory_calls == [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    ]
    assert raw_socket.connected_to == ("192.0.2.10", 443)
    assert tls_socket.handshake_count == 1
    assert not hasattr(raw_socket, "send")


def test_readiness_dns_failure_stops_before_tcp_and_is_value_blind() -> None:
    calls = 0

    def resolver(*_args: Any, **_kwargs: Any) -> list[tuple[Any, ...]]:
        nonlocal calls
        calls += 1
        raise socket.gaierror("withheld-private-dns-detail")

    result = probe_coinbase_transport_readiness(
        resolver=resolver,
        socket_factory=lambda *_args: (_ for _ in ()).throw(
            AssertionError("tcp must not start")
        ),
        ssl_context_factory=lambda: (_ for _ in ()).throw(
            AssertionError("tls must not start")
        ),
    )

    assert calls == 1
    assert result.ready is False
    assert (
        result.failure_class
        is SpotTransportReadinessFailureClass.DNS_RESOLUTION_FAILURE
    )
    assert result.dns_status is SpotTransportReadinessStageStatus.FAILED
    assert result.tcp_status is SpotTransportReadinessStageStatus.NOT_ATTEMPTED
    assert result.tls_status is SpotTransportReadinessStageStatus.NOT_ATTEMPTED
    assert (result.dns_probe_count, result.tcp_probe_count, result.tls_probe_count) == (
        1,
        0,
        0,
    )
    assert "withheld" not in repr(result)


def test_readiness_connect_timeout_stops_before_tls_and_is_value_blind() -> None:
    raw_socket = _Socket(
        connect_error=socket.timeout("withheld-private-connect-detail")
    )

    result = probe_coinbase_transport_readiness(
        resolver=_resolver,
        socket_factory=lambda *_args: raw_socket,
        ssl_context_factory=lambda: (_ for _ in ()).throw(
            AssertionError("tls must not start")
        ),
    )

    assert result.ready is False
    assert result.failure_class is SpotTransportReadinessFailureClass.CONNECT_TIMEOUT
    assert result.dns_status is SpotTransportReadinessStageStatus.SUCCEEDED
    assert result.tcp_status is SpotTransportReadinessStageStatus.FAILED
    assert result.tls_status is SpotTransportReadinessStageStatus.NOT_ATTEMPTED
    assert (result.dns_probe_count, result.tcp_probe_count, result.tls_probe_count) == (
        1,
        1,
        0,
    )
    assert "withheld" not in repr(result)


def test_readiness_tls_certificate_failure_is_fixed_and_value_blind() -> None:
    raw_socket = _Socket()
    tls_socket = _TlsSocket(
        handshake_error=ssl.SSLCertVerificationError(
            "withheld-private-certificate-detail"
        )
    )

    result = probe_coinbase_transport_readiness(
        resolver=_resolver,
        socket_factory=lambda *_args: raw_socket,
        ssl_context_factory=lambda: _Context(tls_socket),
    )

    assert result.ready is False
    assert (
        result.failure_class
        is SpotTransportReadinessFailureClass.TLS_OR_CERTIFICATE_FAILURE
    )
    assert result.dns_status is SpotTransportReadinessStageStatus.SUCCEEDED
    assert result.tcp_status is SpotTransportReadinessStageStatus.SUCCEEDED
    assert result.tls_status is SpotTransportReadinessStageStatus.FAILED
    assert (result.dns_probe_count, result.tcp_probe_count, result.tls_probe_count) == (
        1,
        1,
        1,
    )
    assert "withheld" not in repr(result)
