"""Consume the single authorized Slice 2R4 Coinbase Preview attempt.

This backend-only tool has no product, profile, size, cap, actor, or artifact
path options.  It can call only the fixed producer, whose exclusive artifact
claim is created before any Coinbase SDK method is invoked.  It never creates,
cancels, closes, or reduces an exchange order.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.futures_order_preview import (  # noqa: E402
    FUTURES_PREVIEW_PRODUCT_ID,
    FUTURES_PREVIEW_R4_ARTIFACT_PATH,
    FUTURES_PREVIEW_R4_ARTIFACT_TYPE,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
    validate_production_futures_order_preview_r3_predecessor,
)
from external.coinbase_client import CoinbaseRestClient  # noqa: E402
from tools.coinbase_live_credentials import (  # noqa: E402
    ensure_live_coinbase_credentials,
)


COINBASE_PREVIEW_HTTP_TIMEOUT_SECONDS = 30
COINBASE_API_BASE_URL = "api.coinbase.com"
COINBASE_CA_BUNDLE = (
    "/usr/local/lib/python3.13/site-packages/certifi/cacert.pem"
)
FUTURES_PREVIEW_CREDENTIAL_SECRET_ID = "coinbase"
FUTURES_PREVIEW_CREDENTIAL_REGION = "us-east-1"
_DIRECT_CREDENTIAL_ENV_NAMES = (
    "COINBASE_API_KEY",
    "COINBASE_API_SECRET",
)
_SECRET_ID_ENV_NAMES = (
    "COINBASE_SECRETS_MANAGER_SECRET_ID",
    "COINBASE_API_CREDENTIALS_SECRET_ID",
    "COINBASE_LIVE_CREDENTIALS_SECRET_ID",
)


class FuturesPreviewOnlyRestClient:
    """Expose only the fixed reads and one exact Preview used by Slice 2R4."""

    __slots__ = ("__delegate", "__preview_attempted")

    def __init__(self, delegate: Any) -> None:
        self.__delegate = delegate
        self.__preview_attempted = False

    def _uses_exact_delegate(self, delegate: object) -> bool:
        """Prove object identity without exposing the private delegate."""

        return self.__delegate is delegate

    def get_api_key_permissions(self) -> dict[str, Any]:
        return self.__delegate.get_api_key_permissions()

    def list_portfolios(self) -> list[dict[str, Any]]:
        return self.__delegate.list_portfolios()

    def get_product_dict(self, product_id: str) -> dict[str, Any] | None:
        if product_id != FUTURES_PREVIEW_PRODUCT_ID:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview product scope is invalid"
            )
        return self.__delegate.get_product_dict(product_id)

    def get_best_bid_ask(self, *, product_ids: list[str]) -> dict[str, Any]:
        if product_ids != [FUTURES_PREVIEW_PRODUCT_ID]:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview market scope is invalid"
            )
        return self.__delegate.get_best_bid_ask(product_ids=product_ids)

    def get_futures_positions(self) -> dict[str, Any]:
        return self.__delegate.get_futures_positions()

    def get_futures_margin_collateral_snapshot(self) -> dict[str, Any]:
        return self.__delegate.get_futures_margin_collateral_snapshot()

    def preview_order(
        self,
        *,
        product_id: str,
        side: str,
        order_configuration: dict[str, Any],
        leverage: str | None = None,
        margin_type: str | None = None,
    ) -> Any:
        if self.__preview_attempted:
            raise FuturesOrderPreviewArtifactError(
                "futures Preview was already attempted"
            )
        limit_configuration = (
            order_configuration.get("limit_limit_gtc")
            if isinstance(order_configuration, dict)
            and set(order_configuration) == {"limit_limit_gtc"}
            else None
        )
        if (
            product_id != FUTURES_PREVIEW_PRODUCT_ID
            or side != "BUY"
            or not isinstance(limit_configuration, dict)
            or set(limit_configuration) != {"base_size", "limit_price", "post_only"}
            or limit_configuration.get("base_size") != "1"
            or not isinstance(limit_configuration.get("limit_price"), str)
            or not str(limit_configuration["limit_price"]).strip()
            or limit_configuration.get("post_only") is not True
            or leverage is not None
            or margin_type is not None
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview request scope is invalid"
            )
        self.__preview_attempted = True
        return self.__delegate.preview_order(
            product_id=product_id,
            side=side,
            order_configuration=order_configuration,
        )


def production_artifact_path() -> Path:
    """Return the fixed one-attempt path; environment cannot redirect it."""

    return FUTURES_PREVIEW_R4_ARTIFACT_PATH


def validate_production_predecessor() -> dict[str, object]:
    """Validate immutable R3 plus its complete R2/R1/original chain."""

    return validate_production_futures_order_preview_r3_predecessor()


def build_parser() -> argparse.ArgumentParser:
    """Build the deliberately option-minimal producer CLI."""

    parser = argparse.ArgumentParser(
        description=(
            "Run exactly one fixed Default-profile AVAX Futures Preview; "
            "no exchange mutation is possible."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Report fixed-path consumption state without credentials or Coinbase calls."
        ),
    )
    mode.add_argument(
        "--confirm-one-r4-preview",
        action="store_true",
        help="Confirm consumption of the one authorized Slice 2R4 Preview attempt.",
    )
    return parser


def _controlled_default_credential_environment() -> dict[str, str]:
    """Return a copy that cannot inherit a Spot/Test credential selection."""

    controlled = dict(os.environ)
    for name in (*_DIRECT_CREDENTIAL_ENV_NAMES, *_SECRET_ID_ENV_NAMES):
        controlled.pop(name, None)
    for name in tuple(controlled):
        if name.startswith("AWS_") or name in {
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
        }:
            controlled.pop(name, None)
    controlled["COINBASE_SECRETS_MANAGER_SECRET_ID"] = (
        FUTURES_PREVIEW_CREDENTIAL_SECRET_ID
    )
    controlled["COINBASE_SECRETS_MANAGER_REGION"] = FUTURES_PREVIEW_CREDENTIAL_REGION
    controlled["AWS_CONFIG_FILE"] = "/home/developer/.aws/config"
    controlled["AWS_SHARED_CREDENTIALS_FILE"] = (
        "/home/developer/.aws/credentials"
    )
    controlled["PATH"] = "/home/developer/.local/bin:/usr/bin:/bin"
    return controlled


@contextmanager
def _suppress_coinbase_sdk_logging() -> Iterator[None]:
    """Prevent any Python logger from emitting network-scope private data."""

    logger = logging.getLogger("coinbase.RESTClient")
    previously_disabled = logger.disabled
    previous_global_threshold = logging.root.manager.disable
    logger.disabled = True
    logging.disable(sys.maxsize)
    try:
        yield
    finally:
        logging.disable(previous_global_threshold)
        logger.disabled = previously_disabled


def _build_canonical_default_rest_client(
    *,
    run_secret_lookup: Callable[[str, str | None], str] | None = None,
) -> CoinbaseRestClient:
    """Hydrate the one canonical zero-retry, zero-redirect Default client.

    This private constructor exists so the R8-only accepted handoff can retain
    the exact delegate already used through its Preview-only facade. Historical
    Preview tools still receive only :class:`FuturesPreviewOnlyRestClient` and
    have no delegate-release API.
    """

    credential_environment = _controlled_default_credential_environment()
    lookup_kwargs = (
        {}
        if run_secret_lookup is None
        else {"run_secret_lookup": run_secret_lookup}
    )
    resolution = ensure_live_coinbase_credentials(
        credential_environment,
        **lookup_kwargs,
    )
    if (
        resolution.source != "secrets_manager"
        or resolution.secret_id_env != "COINBASE_SECRETS_MANAGER_SECRET_ID"
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview credential source is not the fixed Default secret"
        )
    from coinbase.rest import RESTClient

    with _suppress_coinbase_sdk_logging():
        sdk_client = RESTClient(
            api_key=credential_environment["COINBASE_API_KEY"],
            api_secret=credential_environment["COINBASE_API_SECRET"],
            base_url=COINBASE_API_BASE_URL,
            timeout=COINBASE_PREVIEW_HTTP_TIMEOUT_SECONDS,
            rate_limit_headers=False,
        )
    session = getattr(sdk_client, "session", None)
    adapters = getattr(session, "adapters", None)
    if (
        getattr(sdk_client, "base_url", None) != COINBASE_API_BASE_URL
        or type(getattr(sdk_client, "timeout", None)) is not int
        or sdk_client.timeout != COINBASE_PREVIEW_HTTP_TIMEOUT_SECONDS
        or getattr(sdk_client, "rate_limit_headers", None) is not False
        or not isinstance(adapters, dict)
        or set(adapters) != {"http://", "https://"}
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview transport policy is unavailable"
        )
    if any(
        getattr(getattr(adapter, "max_retries", None), "total", None) != 0
        for adapter in adapters.values()
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview transport retry policy is not zero"
        )
    try:
        session.trust_env = False
        session.verify = COINBASE_CA_BUNDLE
        session.proxies = {}
        session.max_redirects = 0
    except Exception as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview transport policy is unavailable"
        ) from exc
    if (
        getattr(session, "trust_env", None) is not False
        or getattr(session, "verify", None) != COINBASE_CA_BUNDLE
        or getattr(session, "proxies", None) != {}
        or type(getattr(session, "max_redirects", None)) is not int
        or session.max_redirects != 0
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview transport policy is invalid"
        )
    try:
        with _suppress_coinbase_sdk_logging():
            headers = sdk_client.set_headers(
                "GET",
                "/api/v3/brokerage/key_permissions",
            )
        authorization = (
            headers.get("Authorization") if isinstance(headers, dict) else None
        )
        if (
            not isinstance(authorization, str)
            or not authorization.startswith("Bearer ")
            or len(authorization) <= len("Bearer ")
        ):
            raise ValueError("invalid_local_signing_probe")
    except Exception:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview credential signing probe failed"
        ) from None
    finally:
        headers = None
        authorization = None
    return CoinbaseRestClient(sdk_client)


def build_rest_client() -> FuturesPreviewOnlyRestClient:
    """Hydrate Default credentials and return a mutation-incapable facade."""

    return FuturesPreviewOnlyRestClient(_build_canonical_default_rest_client())


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fixed producer once and print only redacted summary evidence."""

    parser = build_parser()
    args = parser.parse_args(argv)
    path = production_artifact_path()
    consumed = path.exists() or path.is_symlink()
    if consumed:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "blocker": "futures_preview_attempt_already_consumed",
                    "artifact_path": str(path),
                    "artifact_created": False,
                    "coinbase_read_ran": False,
                    "preview_order_attempt_count": 0,
                    "exchange_submission_attempt_count": 0,
                    "live_coinbase_execution": "not_run",
                },
                sort_keys=True,
            ),
            file=sys.stderr if not args.preflight else sys.stdout,
        )
        return 2
    try:
        predecessor_binding = validate_production_predecessor()
    except FuturesOrderPreviewArtifactError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "blocker": str(exc),
                    "artifact_path": str(path),
                    "artifact_created": False,
                    "coinbase_read_ran": False,
                    "preview_order_attempt_count": 0,
                    "exchange_submission_attempt_count": 0,
                    "live_coinbase_execution": "not_run",
                },
                sort_keys=True,
            ),
            file=sys.stderr if not args.preflight else sys.stdout,
        )
        return 2
    if args.preflight:
        print(
            json.dumps(
                {
                    "status": "ready",
                    "blocker": None,
                    "artifact_path": str(path),
                    "artifact_created": False,
                    "predecessor_binding": predecessor_binding,
                    "coinbase_read_ran": False,
                    "preview_order_attempt_count": 0,
                    "exchange_submission_attempt_count": 0,
                    "live_coinbase_execution": "not_run",
                },
                sort_keys=True,
            )
        )
        return 0

    try:
        with _suppress_coinbase_sdk_logging():
            rest_client = build_rest_client()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "blocker": (
                        "futures_preview_client_preparation_blocked:"
                        f"{type(exc).__name__}"
                    ),
                    "artifact_path": str(path),
                    "artifact_created": path.exists() or path.is_symlink(),
                    "coinbase_read_ran": False,
                    "preview_order_attempt_count": 0,
                    "exchange_submission_attempt_count": 0,
                    "live_coinbase_execution": "not_run",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    store = FuturesOrderPreviewArtifactStore(path)
    producer = FuturesOrderPreviewProducer(
        rest_client=rest_client,
        store=store,
        predecessor_binding=predecessor_binding,
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R4_ARTIFACT_TYPE,
    )
    try:
        with _suppress_coinbase_sdk_logging():
            evidence = producer.run()
    except FuturesOrderPreviewArtifactError as exc:
        try:
            terminal = store.read_completed()
        except FuturesOrderPreviewArtifactError:
            terminal = None
        if terminal is not None:
            summary = {
                "status": terminal["status"],
                "outcome": terminal["outcome"],
                "blocker": terminal.get("blocker"),
                "artifact_path": str(path),
                "artifact_created": True,
                "attempt_counters": terminal["attempt_counters"],
                "exchange_submission_attempt_count": terminal[
                    "exchange_submission_attempt_count"
                ],
                "live_execution": terminal["live_execution"],
                "submitted_notional_usdc": terminal["submitted_notional_usdc"],
                "executed_notional_usdc": terminal["executed_notional_usdc"],
            }
        else:
            summary = {
                "status": "unknown",
                "outcome": "unknown",
                "blocker": (
                    "futures_preview_attempt_consumed_without_terminal_result:"
                    f"{type(exc).__name__}"
                ),
                "artifact_path": str(path),
                "artifact_created": path.exists(),
                "attempt_counters": None,
                "exchange_submission_attempt_count": 0,
                "live_execution": "not_run",
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
            }
        print(
            json.dumps(summary, sort_keys=True),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "status": evidence["status"],
                "artifact_path": str(path),
                "product_id": evidence["product_id"],
                "preview_id": evidence["preview_response"]["preview_id"],
                "seal_ready_plan_sha256": evidence["seal_ready_plan_sha256"],
                "evidence_sha256": evidence["evidence_sha256"],
                "attempt_counters": evidence["attempt_counters"],
                "live_execution": "not_run",
                "submitted_notional_usdc": "0",
                "executed_notional_usdc": "0",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
