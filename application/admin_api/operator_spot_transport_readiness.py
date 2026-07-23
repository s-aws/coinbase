"""Value-blind no-HTTP readiness proof for the official Coinbase API host."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import socket
import ssl
from typing import Any, Callable


COINBASE_ADVANCED_API_HOSTNAME = "api.coinbase.com"
COINBASE_ADVANCED_API_PORT = 443
DEFAULT_TRANSPORT_PROBE_TIMEOUT_SECONDS = 5.0


class SpotTransportReadinessStageStatus(str, Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class SpotTransportReadinessFailureClass(str, Enum):
    NONE = "NONE"
    DNS_RESOLUTION_FAILURE = "DNS_RESOLUTION_FAILURE"
    TCP_CONNECTION_FAILURE = "TCP_CONNECTION_FAILURE"
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"
    TLS_OR_CERTIFICATE_FAILURE = "TLS_OR_CERTIFICATE_FAILURE"
    UNKNOWN_TRANSPORT = "UNKNOWN_TRANSPORT"


@dataclass(frozen=True)
class SpotTransportReadinessResult:
    ready: bool
    failure_class: SpotTransportReadinessFailureClass
    dns_status: SpotTransportReadinessStageStatus
    tcp_status: SpotTransportReadinessStageStatus
    tls_status: SpotTransportReadinessStageStatus
    dns_probe_count: int
    tcp_probe_count: int
    tls_probe_count: int


def _result(
    *,
    failure_class: SpotTransportReadinessFailureClass,
    dns_status: SpotTransportReadinessStageStatus,
    tcp_status: SpotTransportReadinessStageStatus,
    tls_status: SpotTransportReadinessStageStatus,
    dns_probe_count: int,
    tcp_probe_count: int,
    tls_probe_count: int,
) -> SpotTransportReadinessResult:
    return SpotTransportReadinessResult(
        ready=failure_class is SpotTransportReadinessFailureClass.NONE,
        failure_class=failure_class,
        dns_status=dns_status,
        tcp_status=tcp_status,
        tls_status=tls_status,
        dns_probe_count=dns_probe_count,
        tcp_probe_count=tcp_probe_count,
        tls_probe_count=tls_probe_count,
    )


def probe_coinbase_transport_readiness(
    *,
    hostname: str = COINBASE_ADVANCED_API_HOSTNAME,
    port: int = COINBASE_ADVANCED_API_PORT,
    timeout_seconds: float = DEFAULT_TRANSPORT_PROBE_TIMEOUT_SECONDS,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
    socket_factory: Callable[[int, int, int], Any] = socket.socket,
    ssl_context_factory: Callable[[], Any] = ssl.create_default_context,
) -> SpotTransportReadinessResult:
    """Perform exactly one DNS lookup, one TCP connect, and one TLS handshake.

    The connected socket never sends application bytes.  Only fixed stage
    status and exception types influence the result; exception messages,
    addresses, and certificate values are neither retained nor returned.
    """

    if (
        hostname != COINBASE_ADVANCED_API_HOSTNAME
        or port != COINBASE_ADVANCED_API_PORT
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < float(timeout_seconds) <= 10
    ):
        raise ValueError("coinbase_transport_probe_scope_invalid")

    try:
        addresses = resolver(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return _result(
            failure_class=(
                SpotTransportReadinessFailureClass.DNS_RESOLUTION_FAILURE
            ),
            dns_status=SpotTransportReadinessStageStatus.FAILED,
            tcp_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            tls_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            dns_probe_count=1,
            tcp_probe_count=0,
            tls_probe_count=0,
        )
    except Exception:
        return _result(
            failure_class=SpotTransportReadinessFailureClass.UNKNOWN_TRANSPORT,
            dns_status=SpotTransportReadinessStageStatus.FAILED,
            tcp_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            tls_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            dns_probe_count=1,
            tcp_probe_count=0,
            tls_probe_count=0,
        )

    if not isinstance(addresses, list) or not addresses:
        return _result(
            failure_class=(
                SpotTransportReadinessFailureClass.DNS_RESOLUTION_FAILURE
            ),
            dns_status=SpotTransportReadinessStageStatus.FAILED,
            tcp_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            tls_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            dns_probe_count=1,
            tcp_probe_count=0,
            tls_probe_count=0,
        )
    first = addresses[0]
    if not isinstance(first, tuple) or len(first) != 5:
        return _result(
            failure_class=(
                SpotTransportReadinessFailureClass.DNS_RESOLUTION_FAILURE
            ),
            dns_status=SpotTransportReadinessStageStatus.FAILED,
            tcp_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            tls_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            dns_probe_count=1,
            tcp_probe_count=0,
            tls_probe_count=0,
        )
    family, socktype, proto, _canonical_name, address = first
    if (
        family not in {socket.AF_INET, socket.AF_INET6}
        or socktype != socket.SOCK_STREAM
        or not isinstance(proto, int)
    ):
        return _result(
            failure_class=(
                SpotTransportReadinessFailureClass.DNS_RESOLUTION_FAILURE
            ),
            dns_status=SpotTransportReadinessStageStatus.FAILED,
            tcp_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            tls_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            dns_probe_count=1,
            tcp_probe_count=0,
            tls_probe_count=0,
        )

    raw_socket = None
    tls_socket = None
    try:
        raw_socket = socket_factory(family, socktype, proto)
        raw_socket.settimeout(float(timeout_seconds))
        raw_socket.connect(address)
    except (socket.timeout, TimeoutError):
        if raw_socket is not None:
            raw_socket.close()
        return _result(
            failure_class=SpotTransportReadinessFailureClass.CONNECT_TIMEOUT,
            dns_status=SpotTransportReadinessStageStatus.SUCCEEDED,
            tcp_status=SpotTransportReadinessStageStatus.FAILED,
            tls_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            dns_probe_count=1,
            tcp_probe_count=1,
            tls_probe_count=0,
        )
    except (ConnectionError, OSError):
        if raw_socket is not None:
            raw_socket.close()
        return _result(
            failure_class=(
                SpotTransportReadinessFailureClass.TCP_CONNECTION_FAILURE
            ),
            dns_status=SpotTransportReadinessStageStatus.SUCCEEDED,
            tcp_status=SpotTransportReadinessStageStatus.FAILED,
            tls_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            dns_probe_count=1,
            tcp_probe_count=1,
            tls_probe_count=0,
        )
    except Exception:
        if raw_socket is not None:
            raw_socket.close()
        return _result(
            failure_class=SpotTransportReadinessFailureClass.UNKNOWN_TRANSPORT,
            dns_status=SpotTransportReadinessStageStatus.SUCCEEDED,
            tcp_status=SpotTransportReadinessStageStatus.FAILED,
            tls_status=SpotTransportReadinessStageStatus.NOT_ATTEMPTED,
            dns_probe_count=1,
            tcp_probe_count=1,
            tls_probe_count=0,
        )

    try:
        context = ssl_context_factory()
        tls_socket = context.wrap_socket(
            raw_socket,
            server_hostname=hostname,
            do_handshake_on_connect=False,
        )
        raw_socket = None
        tls_socket.do_handshake()
    except (ssl.SSLCertVerificationError, ssl.SSLError, socket.timeout):
        if tls_socket is not None:
            tls_socket.close()
        elif raw_socket is not None:
            raw_socket.close()
        return _result(
            failure_class=(
                SpotTransportReadinessFailureClass.TLS_OR_CERTIFICATE_FAILURE
            ),
            dns_status=SpotTransportReadinessStageStatus.SUCCEEDED,
            tcp_status=SpotTransportReadinessStageStatus.SUCCEEDED,
            tls_status=SpotTransportReadinessStageStatus.FAILED,
            dns_probe_count=1,
            tcp_probe_count=1,
            tls_probe_count=1,
        )
    except Exception:
        if tls_socket is not None:
            tls_socket.close()
        elif raw_socket is not None:
            raw_socket.close()
        return _result(
            failure_class=SpotTransportReadinessFailureClass.UNKNOWN_TRANSPORT,
            dns_status=SpotTransportReadinessStageStatus.SUCCEEDED,
            tcp_status=SpotTransportReadinessStageStatus.SUCCEEDED,
            tls_status=SpotTransportReadinessStageStatus.FAILED,
            dns_probe_count=1,
            tcp_probe_count=1,
            tls_probe_count=1,
        )

    tls_socket.close()
    return _result(
        failure_class=SpotTransportReadinessFailureClass.NONE,
        dns_status=SpotTransportReadinessStageStatus.SUCCEEDED,
        tcp_status=SpotTransportReadinessStageStatus.SUCCEEDED,
        tls_status=SpotTransportReadinessStageStatus.SUCCEEDED,
        dns_probe_count=1,
        tcp_probe_count=1,
        tls_probe_count=1,
    )


__all__ = [
    "COINBASE_ADVANCED_API_HOSTNAME",
    "COINBASE_ADVANCED_API_PORT",
    "SpotTransportReadinessFailureClass",
    "SpotTransportReadinessResult",
    "SpotTransportReadinessStageStatus",
    "probe_coinbase_transport_readiness",
]
