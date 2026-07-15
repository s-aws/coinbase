"""Consume the single authorized Slice 2R5 Coinbase Preview attempt.

This backend-only tool has no product, profile, size, cap, actor, or artifact
path options. It reuses the mutation-incapable Preview facade while binding a
new fixed R5 path and the exact immutable R4 predecessor chain.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.admin_api.futures_order_preview import (  # noqa: E402
    FUTURES_PREVIEW_R5_ARTIFACT_PATH,
    FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
    FUTURES_PREVIEW_R4_PREDECESSOR_BINDING,
    FuturesOrderPreviewArtifactError,
    FuturesOrderPreviewArtifactStore,
    FuturesOrderPreviewProducer,
    validate_production_futures_order_preview_r4_predecessor,
)
from tools import run_admin_api_futures_no_live_preview as r4_tool  # noqa: E402


FuturesPreviewOnlyRestClient = r4_tool.FuturesPreviewOnlyRestClient
_suppress_coinbase_sdk_logging = r4_tool._suppress_coinbase_sdk_logging


class DeferredR5PreviewRestClient:
    """Hydrate the fixed client only after the producer has claimed R5."""

    __slots__ = ("__client",)

    def __init__(self) -> None:
        self.__client: FuturesPreviewOnlyRestClient | None = None

    def _get(self) -> FuturesPreviewOnlyRestClient:
        if self.__client is None:
            with _suppress_coinbase_sdk_logging():
                self.__client = build_rest_client()
        return self.__client

    def get_api_key_permissions(self):
        return self._get().get_api_key_permissions()

    def list_portfolios(self):
        return self._get().list_portfolios()

    def get_product_dict(self, product_id: str):
        return self._get().get_product_dict(product_id)

    def get_best_bid_ask(self, *, product_ids: list[str]):
        return self._get().get_best_bid_ask(product_ids=product_ids)

    def get_futures_positions(self):
        return self._get().get_futures_positions()

    def get_futures_margin_collateral_snapshot(self):
        return self._get().get_futures_margin_collateral_snapshot()

    def preview_order(self, **kwargs):
        return self._get().preview_order(**kwargs)


def production_artifact_path() -> Path:
    """Return the fixed R5 one-attempt path; environment cannot redirect it."""

    return FUTURES_PREVIEW_R5_ARTIFACT_PATH


def validate_production_predecessor() -> dict[str, object]:
    """Validate immutable R4 plus its complete predecessor chain."""

    return validate_production_futures_order_preview_r4_predecessor()


def build_parser() -> argparse.ArgumentParser:
    """Build the deliberately option-minimal R5 producer CLI."""

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
            "Report fixed-path consumption state without credentials or "
            "Coinbase calls."
        ),
    )
    mode.add_argument(
        "--confirm-one-r5-preview",
        action="store_true",
        help="Confirm consumption of the one authorized Slice 2R5 Preview attempt.",
    )
    return parser


def build_rest_client() -> FuturesPreviewOnlyRestClient:
    """Build the fixed Default client and reject SDK method fallback."""

    client = r4_tool.build_rest_client()
    delegate = getattr(
        client,
        "_FuturesPreviewOnlyRestClient__delegate",
        None,
    )
    sdk_client = getattr(delegate, "_client", None)
    required_sdk_methods = {
        "get_api_key_permissions",
        "get_portfolios",
        "get_product",
        "get_best_bid_ask",
        "list_futures_positions",
        "get_futures_balance_summary",
        "get_intraday_margin_setting",
        "get_current_margin_window",
        "list_futures_sweeps",
        "preview_order",
    }
    if sdk_client is None or any(
        not callable(getattr(sdk_client, method, None))
        for method in required_sdk_methods
    ):
        raise FuturesOrderPreviewArtifactError(
            "futures Preview fixed SDK read surface is unavailable"
        )
    session = getattr(sdk_client, "session", None)
    adapters = getattr(session, "adapters", None)
    if not isinstance(adapters, dict) or not adapters:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 transport policy is unavailable"
        )
    for adapter in adapters.values():
        policy = getattr(adapter, "max_retries", None)
        if (
            getattr(policy, "total", None) != 0
            or any(
                getattr(policy, dimension, None) not in {None, 0, False}
                for dimension in (
                    "connect",
                    "read",
                    "redirect",
                    "status",
                    "other",
                )
            )
        ):
            raise FuturesOrderPreviewArtifactError(
                "futures Preview R5 transport retry policy is not zero"
            )
    if getattr(session, "max_redirects", None) != 0:
        raise FuturesOrderPreviewArtifactError(
            "futures Preview R5 transport redirect policy is not zero"
        )
    return client


def _summary_before_attempt(
    *,
    status: str,
    blocker: str | None,
    path: Path,
    artifact_created: bool,
) -> dict[str, object]:
    return {
        "status": status,
        "blocker": blocker,
        "artifact_path": str(path),
        "artifact_created": artifact_created,
        "coinbase_read_ran": False,
        "preview_order_attempt_count": 0,
        "exchange_submission_attempt_count": 0,
        "live_coinbase_execution": "not_run",
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the fixed R5 producer once and print only redacted evidence."""

    parser = build_parser()
    args = parser.parse_args(argv)
    path = production_artifact_path()
    if path.exists() or path.is_symlink():
        print(
            json.dumps(
                _summary_before_attempt(
                    status="blocked",
                    blocker="futures_preview_attempt_already_consumed",
                    path=path,
                    artifact_created=False,
                ),
                sort_keys=True,
            ),
            file=sys.stderr if not args.preflight else sys.stdout,
        )
        return 2
    if args.preflight:
        try:
            predecessor_binding = validate_production_predecessor()
        except FuturesOrderPreviewArtifactError as exc:
            print(
                json.dumps(
                    _summary_before_attempt(
                        status="blocked",
                        blocker=str(exc),
                        path=path,
                        artifact_created=False,
                    ),
                    sort_keys=True,
                ),
                file=sys.stdout,
            )
            return 2
        summary = _summary_before_attempt(
            status="ready",
            blocker=None,
            path=path,
            artifact_created=False,
        )
        summary["predecessor_binding"] = predecessor_binding
        print(json.dumps(summary, sort_keys=True))
        return 0

    predecessor_binding = dict(FUTURES_PREVIEW_R4_PREDECESSOR_BINDING)

    store = FuturesOrderPreviewArtifactStore(path)
    producer = FuturesOrderPreviewProducer(
        rest_client=DeferredR5PreviewRestClient(),
        store=store,
        predecessor_binding=predecessor_binding,
        predecessor_validator=validate_production_predecessor,
        artifact_type=FUTURES_PREVIEW_R5_ARTIFACT_TYPE,
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
        print(json.dumps(summary, sort_keys=True), file=sys.stderr)
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
