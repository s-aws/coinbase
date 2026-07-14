"""Consume the single authorized Slice 2R3 Coinbase Preview attempt.

This backend-only tool has no product, profile, size, cap, actor, or artifact
path options.  It can call only the fixed producer, whose exclusive artifact
claim is created before any Coinbase SDK method is invoked.  It never creates,
cancels, closes, or reduces an exchange order.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.futures_order_preview import (  # noqa: E402
    DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
    validate_production_futures_order_preview_predecessor,
)
from external.coinbase_client import CoinbaseRestClient  # noqa: E402
from tools.coinbase_live_credentials import (  # noqa: E402
    ensure_live_coinbase_credentials,
)


COINBASE_PREVIEW_HTTP_TIMEOUT_SECONDS = 30
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


def production_artifact_path() -> Path:
    """Return the fixed one-attempt path; environment cannot redirect it."""

    return DEFAULT_FUTURES_PREVIEW_ARTIFACT_PATH


def validate_production_predecessor() -> dict[str, object]:
    """Validate the immutable consumed Slice 2R2 predecessor chain."""

    return validate_production_futures_order_preview_predecessor()


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
        help="Report fixed-path consumption state without credentials or Coinbase calls.",
    )
    mode.add_argument(
        "--confirm-one-r3-preview",
        action="store_true",
        help="Confirm consumption of the one authorized Slice 2R3 Preview attempt.",
    )
    return parser


def _controlled_default_credential_environment() -> dict[str, str]:
    """Return a copy that cannot inherit a Spot/Test credential selection."""

    controlled = dict(os.environ)
    for name in (*_DIRECT_CREDENTIAL_ENV_NAMES, *_SECRET_ID_ENV_NAMES):
        controlled.pop(name, None)
    controlled["COINBASE_SECRETS_MANAGER_SECRET_ID"] = (
        FUTURES_PREVIEW_CREDENTIAL_SECRET_ID
    )
    controlled["COINBASE_SECRETS_MANAGER_REGION"] = (
        FUTURES_PREVIEW_CREDENTIAL_REGION
    )
    return controlled


@contextmanager
def _suppress_coinbase_sdk_logging() -> Iterator[None]:
    """Prevent the Coinbase SDK from logging raw HTTP response bodies."""

    logger = logging.getLogger("coinbase.RESTClient")
    previously_disabled = logger.disabled
    logger.disabled = True
    try:
        yield
    finally:
        logger.disabled = previously_disabled


def build_rest_client() -> CoinbaseRestClient:
    """Hydrate the fixed Default credential and construct the wrapper."""

    credential_environment = _controlled_default_credential_environment()
    resolution = ensure_live_coinbase_credentials(credential_environment)
    if (
        resolution.source != "secrets_manager"
        or resolution.secret_id_env != "COINBASE_SECRETS_MANAGER_SECRET_ID"
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview credential source is not the fixed Default secret"
        )
    from coinbase.rest import RESTClient

    sdk_client = RESTClient(
        api_key=credential_environment["COINBASE_API_KEY"],
        api_secret=credential_environment["COINBASE_API_SECRET"],
        timeout=COINBASE_PREVIEW_HTTP_TIMEOUT_SECONDS,
        rate_limit_headers=True,
    )
    session = getattr(sdk_client, "session", None)
    adapters = getattr(session, "adapters", None)
    if not isinstance(adapters, dict) or not adapters:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview transport retry policy is unavailable"
        )
    if any(
        getattr(getattr(adapter, "max_retries", None), "total", None) != 0
        for adapter in adapters.values()
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview transport retry policy is not zero"
        )
    try:
        session.max_redirects = 0
    except Exception as exc:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview transport redirect policy is unavailable"
        ) from exc
    if getattr(session, "max_redirects", None) != 0:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview transport redirect policy is not zero"
        )
    return CoinbaseRestClient(sdk_client)


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

    store = FuturesOrderPreviewArtifactStore(path)
    producer = FuturesOrderPreviewProducer(
        rest_client=build_rest_client(),
        store=store,
        predecessor_binding=predecessor_binding,
        predecessor_validator=validate_production_predecessor,
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
